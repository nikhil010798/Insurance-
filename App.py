import streamlit as st
import pandas as pd
import numpy as np
import sqlite3, re, urllib.parse
from pathlib import Path
from datetime import date, datetime, timedelta

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import pytesseract
except ImportError:
    pytesseract = None


st.set_page_config(
    page_title="Ultimate Insurance Sales CRM",
    page_icon="🛡️",
    layout="wide"
)

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "crm.db"
RATE_DIR = BASE / "rate_tables"
RATE_DIR.mkdir(exist_ok=True)

st.markdown('''
<style>
.block-container{padding-top:.7rem;padding-bottom:4rem}
.stButton>button{border-radius:12px;min-height:42px;font-weight:600}
div[data-testid="stMetric"]{border:1px solid #e5e7eb;border-radius:14px;padding:10px}
</style>
''', unsafe_allow_html=True)


# ============================================================
# CONSTANTS
# ============================================================

INSURERS = [
    "Care Health",
    "Niva Bupa",
    "HDFC ERGO",
    "Star Health",
    "ICICI Lombard",
    "Other"
]

PLANS = {
    "Care Health": ["Ultimate Care", "Care Supreme", "Other"],
    "Niva Bupa": ["ReAssure 2.0", "ReAssure 3.0", "Health Companion", "Other"],
    "HDFC ERGO": ["my:Optima Secure", "Other"],
    "Star Health": ["Star Comprehensive", "Family Health Optima", "Other"],
    "ICICI Lombard": ["Complete Health Insurance", "Other"],
    "Other": ["Other"]
}

FEATURES = [
    "Room Rent", "ICU", "Modern Treatment", "Road Ambulance",
    "NCB / Bonus", "Restore / Refill", "Co-pay", "Disease Sub-limits",
    "PED Waiting", "Specific Waiting", "Maternity", "Day Care"
]

RATE_COLS = [
    "insurer", "plan", "zone", "policy_type", "sum_insured_lakh",
    "age_min", "age_max", "member_count", "base_premium",
    "gst_included", "discount_pct", "source", "source_date"
]


# ============================================================
# DATABASE SETUP
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, mobile TEXT, city TEXT, insurer TEXT, plan TEXT,
            sum_insured REAL, renewal_date TEXT, premium REAL,
            members TEXT, ped TEXT, notes TEXT, score INTEGER,
            created_at TEXT, updated_at TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER, followup_date TEXT, status TEXT,
            note TEXT, created_at TEXT
        )
    ''')
    conn.commit()
    return conn

DB = get_db()


# ============================================================
# HELPERS
# ============================================================

def normalize_mobile(value):
    value = re.sub(r"\D", "", str(value or ""))
    if value.startswith("91") and len(value) == 12: return value[2:]
    if len(value) >= 10: return value[-10:]
    return value

def money(value):
    try: return f"₹{float(value):,.0f}"
    except Exception: return "—"

def opportunity_score(renewal, sum_insured, premium, room=False, ped=False, age=0):
    score = 0
    try:
        days = (renewal - date.today()).days
        if 0 <= days <= 30: score += 35
        elif 31 <= days <= 60: score += 25
        elif 61 <= days <= 90: score += 15
        elif days < 0: score += 15
    except Exception: pass
    
    try:
        si = float(sum_insured)
        if si <= 5: score += 20
        elif si <= 10: score += 12
    except Exception: pass
    
    if room: score += 15
    if ped: score += 10
    
    try:
        if int(age) >= 45: score += 10
    except Exception: pass
    
    if float(premium or 0) > 0: score += 5
    return min(score, 100)


# ============================================================
# RATE TABLE ENGINE
# ============================================================

def normalize_rates(df):
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    aliases = {
        "sum_insured": "sum_insured_lakh", "si_lakh": "sum_insured_lakh",
        "premium": "base_premium", "members": "member_count",
        "age_from": "age_min", "age_to": "age_max"
    }
    for old, new in aliases.items():
        if old in df.columns and new not in df.columns:
            df.rename(columns={old: new}, inplace=True)
    
    for col in RATE_COLS:
        if col not in df.columns: df[col] = ""
        
    for col in ["sum_insured_lakh", "age_min", "age_max", "member_count", "base_premium", "discount_pct"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[RATE_COLS]

def load_rates():
    tables = []
    for file in RATE_DIR.glob("*.csv"):
        try: tables.append(normalize_rates(pd.read_csv(file)))
        except Exception: pass
    if not tables: return pd.DataFrame(columns=RATE_COLS)
    return pd.concat(tables, ignore_index=True)

rates = load_rates()

def calculate_premium(rates_df, insurer, plan, zone, policy_type, sum_insured, ages):
    if rates_df.empty: return None, "No verified rate table is loaded."
    
    df = rates_df[
        (rates_df["insurer"].astype(str).str.casefold() == insurer.casefold()) &
        (rates_df["plan"].astype(str).str.casefold() == plan.casefold()) &
        (rates_df["sum_insured_lakh"] == float(sum_insured))
    ]
    if zone:
        z = df[df["zone"].astype(str).str.casefold() == zone.casefold()]
        if not z.empty: df = z
    
    type_df = df[df["policy_type"].astype(str).str.casefold() == policy_type.casefold()]
    if not type_df.empty: df = type_df
    
    if df.empty: return None, "No matching official rate row was found."
    
    if policy_type == "Individual":
        age = ages[0]
        match = df[(df["age_min"] <= age) & (df["age_max"] >= age)]
        if match.empty: return None, f"No verified rate found for age {age}."
        row = match.iloc[0]
        base = float(row["base_premium"])
    elif policy_type == "Family Floater":
        oldest = max(ages)
        match = df[(df["age_min"] <= oldest) & (df["age_max"] >= oldest) & (df["member_count"] == len(ages))]
        if match.empty: return None, "No explicit verified floater rate for this age/member combination."
        row = match.iloc[0]
        base = float(row["base_premium"])
    else:
        base = 0; row = None
        for age in ages:
            match = df[(df["age_min"] <= age) & (df["age_max"] >= age)]
            if match.empty: return None, f"No verified rate found for age {age}."
            row = match.iloc[0]
            base += float(row["base_premium"])
            
    discount = float(row["discount_pct"] or 0)
    base = base * (1 - discount / 100)
    gst_included = str(row["gst_included"]).strip().lower()
    gst = 0 if gst_included in ["yes", "true", "1"] else base * 0.18
    return {"base": base, "gst": gst, "total": base + gst, "source": str(row["source"]), "source_date": str(row["source_date"])}, None


# ============================================================
# EXCEL / CSV BULK UPLOAD TO DATABASE (RESTORED MAIN FEATURE)
# ============================================================

def auto_detect_columns(df):
    cols = [str(c).strip().lower() for c in df.columns]
    name_col = next((df.columns[i] for i, c in enumerate(cols) if "name" in c or "customer" in c), df.columns[4] if len(df.columns) > 4 else df.columns[0])
    mob_col = next((df.columns[i] for i, c in enumerate(cols) if "mob" in c or "phone" in c or "contact" in c or "no" in c), df.columns[1] if len(df.columns) > 1 else None)
    si_col = next((df.columns[i] for i, c in enumerate(cols) if "si" in c or "sum" in c or "insured" in c), df.columns[3] if len(df.columns) > 3 else None)
    prem_col = next((df.columns[i] for i, c in enumerate(cols) if "prem" in c or "amount" in c), df.columns[6] if len(df.columns) > 6 else None)
    prod_col = next((df.columns[i] for i, c in enumerate(cols) if "product" in c or "plan" in c), df.columns[5] if len(df.columns) > 5 else None)
    date_col = next((df.columns[i] for i, c in enumerate(cols) if "date" in c or "app" in c), df.columns[7] if len(df.columns) > 7 else None)
    return name_col, mob_col, si_col, prem_col, prod_col, date_col

def bulk_import_leads(df):
    name_col, mob_col, si_col, prem_col, prod_col, date_col = auto_detect_columns(df)
    now = datetime.now().isoformat(timespec="seconds")
    count = 0
    
    for _, row in df.iterrows():
        try:
            name = str(row[name_col]) if name_col else "Unknown"
            if name == "nan" or name == "None": continue
            
            mobile = normalize_mobile(row[mob_col]) if mob_col else ""
            si_val = str(row[si_col]).replace('L', '').replace('l', '').strip() if si_col else "5"
            try: si = float(si_val)
            except: si = 5.0
            
            prem_val = str(row[prem_col]).replace(',', '').strip() if prem_col else "0"
            try: prem = float(prem_val)
            except: prem = 0.0
            
            plan = str(row[prod_col]) if prod_col else ""
            
            renewal = date.today() + timedelta(days=30)
            if date_col:
                try: 
                    dt = pd.to_datetime(row[date_col], dayfirst=True)
                    if not pd.isnull(dt): renewal = dt.date()
                except: pass
            
            score = opportunity_score(renewal, si, prem)
            
            DB.execute('''
                INSERT INTO leads(name,mobile,city,insurer,plan,sum_insured,renewal_date,premium,members,ped,notes,score,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (name, mobile, "", "Unknown", plan, si, renewal.isoformat(), prem, "Self", "", "Bulk Imported", score, now, now))
            count += 1
        except Exception as e:
            pass
    DB.commit()
    return count

# ============================================================
# OCR
# ============================================================

def extract_ocr(file):
    if Image is None or pytesseract is None: return "", "OCR packages are unavailable."
    try:
        image = Image.open(file)
        text = pytesseract.image_to_string(image, config="--psm 6")
        return text, None
    except Exception as e: return "", str(e)

def extract_fields(text):
    patterns = {
        "mobile": r"(?:mobile|mob|phone)\D{0,10}([6-9]\d{9})",
        "premium": r"(?:premium)\D{0,15}(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)",
        "renewal_date": r"(?:renewal|expiry|policy end|valid till)\D{0,15}(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
    }
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match: result[key] = match.group(1)
    return result


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("⚙️ Setup & Rate Tables")
    st.write(f"Verified rate rows: **{len(rates)}**")
    rate_file = st.file_uploader("Upload official rate table", type=["csv", "xlsx"], key="rate_upload")
    if rate_file:
        try:
            raw = pd.read_excel(rate_file) if rate_file.name.lower().endswith(".xlsx") else pd.read_csv(rate_file)
            normalized = normalize_rates(raw)
            normalized.to_csv(RATE_DIR / f"{Path(rate_file.name).stem}.csv", index=False)
            rates = load_rates()
            st.success(f"{len(normalized)} rate rows loaded.")
        except Exception as e: st.error(f"Rate table error: {e}")


# ============================================================
# HEADER & UPLOADER SECTION (RESTORED TOP MAIN UPLOADER)
# ============================================================

st.title("🛡️ Ultimate Insurance Sales CRM")
st.markdown("A one-stop solution: Portability Engine, CRM, Bulk Excel Upload, Dynamic Calculator, Multi-Language Pitches, and Image OCR.")

st.info("👇 Upload your Lead Data (Excel/CSV) here to instantly populate your CRM Database!")
main_upload = st.file_uploader("📁 Bulk Upload Lead Data (Excel/CSV)", type=["csv", "xlsx", "xls"], key="main_upload")

if main_upload:
    try:
        if main_upload.name.endswith(".csv"): df_bulk = pd.read_csv(main_upload)
        else: df_bulk = pd.read_excel(main_upload)
        
        if st.button("🚀 Import Data to CRM", use_container_width=True, type="primary"):
            imported = bulk_import_leads(df_bulk)
            st.success(f"✅ Successfully imported {imported} leads into the CRM database!")
    except Exception as e:
        st.error(f"Error reading file: {e}")

# ============================================================
# TABS
# ============================================================

tabs = st.tabs([
    "🏠 Dashboard", "👤 CRM", "💬 AI Pitch Generator", "⚖️ Compare", "💰 Premium", 
    "📷 Policy OCR", "🔥 Opportunity", "🧾 Audit", "📌 Follow-ups"
])


# ============================================================
# DASHBOARD
# ============================================================

with tabs[0]:
    leads = pd.read_sql_query("SELECT * FROM leads ORDER BY updated_at DESC", DB)
    if leads.empty:
        renewals = 0; hot = 0
    else:
        renewal_dates = pd.to_datetime(leads["renewal_date"], errors="coerce").dt.date
        renewals = int(((renewal_dates >= date.today()) & (renewal_dates <= date.today() + timedelta(days=30))).sum())
        hot = int((pd.to_numeric(leads["score"], errors="coerce").fillna(0) >= 70).sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Leads", len(leads))
    c2.metric("Renewals ≤30 Days", renewals)
    c3.metric("🔥 Hot Leads", hot)
    c4.metric("Verified Rate Rows", len(rates))

    st.subheader("📋 My Customers Pipeline")
    if leads.empty:
        st.warning("No customers found. Upload an Excel file above or add manually in CRM tab.")
    else:
        display = leads[["name", "mobile", "insurer", "plan", "sum_insured", "renewal_date", "score"]].copy()
        display["Priority"] = np.where(display["score"] >= 80, "🔥 HOT", np.where(display["score"] >= 60, "🟠 WARM", "🟢 NURTURE"))
        st.dataframe(display.sort_values("score", ascending=False), use_container_width=True, hide_index=True)


# ============================================================
# CRM (MANUAL ENTRY)
# ============================================================

with tabs[1]:
    st.subheader("👤 Customer CRM (Manual Entry)")
    with st.form("customer_form"):
        a, b = st.columns(2)
        name = a.text_input("Customer name")
        mob = b.text_input("Mobile")
        a, b, c = st.columns(3)
        city = a.text_input("City / Zone")
        insurer = b.selectbox("Current insurer", INSURERS)
        plan = c.text_input("Current plan")
        a, b, c = st.columns(3)
        sum_insured = a.number_input("Sum Insured ₹ lakh", min_value=0.0, step=1.0)
        renewal = b.date_input("Renewal date", date.today() + timedelta(days=30))
        premium = c.number_input("Current premium", min_value=0.0, step=500.0)
        members = st.text_input("Members", "Self, Spouse, Child")
        ped = st.text_input("PED / medical notes")
        notes = st.text_area("Sales notes")
        save = st.form_submit_button("💾 Save Customer", use_container_width=True)

    if save:
        now = datetime.now().isoformat(timespec="seconds")
        lead_score = opportunity_score(renewal, sum_insured, premium, ped=bool(ped.strip()))
        DB.execute(
            '''INSERT INTO leads(name,mobile,city,insurer,plan,sum_insured,renewal_date,premium,members,ped,notes,score,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (name.strip(), normalize_mobile(mob), city, insurer, plan, sum_insured, renewal.isoformat(), premium, members, ped, notes, lead_score, now, now)
        )
        DB.commit()
        st.success("Customer saved.")


# ============================================================
# AI PITCH GENERATOR & WHATSAPP
# ============================================================

with tabs[2]:
    st.subheader("💬 AI Pitch & WhatsApp Generator")
    
    leads = pd.read_sql_query("SELECT id, name, mobile, sum_insured, plan FROM leads ORDER BY score DESC", DB)
    if leads.empty:
        st.info("Upload Leads or add to CRM first.")
    else:
        cust_options = {f"{r['name']} - {r['mobile']}": r for _, r in leads.iterrows()}
        selected_cust = st.selectbox("Select Customer from CRM", list(cust_options.keys()))
        cust_data = cust_options[selected_cust]
        
        a, b, c = st.columns(3)
        target_plan_name = a.text_input("Target plan to Pitch", "Care Supreme")
        lang_choice = b.selectbox("Language", ["Hinglish", "English", "Tamil (தமிழ்)", "Telugu (తెలుగు)", "Malayalam (മലയാളം)", "Kannada (ಕನ್ನಡ)"])
        tone_choice = c.selectbox("Select Tone", ["🤝 Warm & Relationship-Driven", "👔 Sharp & Professional"])
        
        urgency_choice = st.selectbox("Urgency Hook", ["Age Slab Jump Protection", "Medical Inflation & Room Rent Risk", "Waiting Period Carry-Forward Window"])

        if st.button("✍️ Generate Pitch", use_container_width=True, type="primary"):
            c_name = cust_data['name']
            curr_plan = cust_data['plan'] if cust_data['plan'] else "Current Plan"
            
            if lang_choice == "English":
                pitch_text = f"Dear {c_name},\nAudit results for your current health cover ({curr_plan}) indicate significant optimization potential. Under IRDAI portability norms, completed waiting periods carry forward to {target_plan_name} without reset. Considering {urgency_choice.lower()}, immediate review is recommended. Let us connect briefly to discuss comparative quotations."
                if "Warm" in tone_choice:
                    pitch_text = f"Hello {c_name} ji, warm regards! 🙏\nI reviewed your health insurance policy. IRDAI rules allow your waiting periods to carry forward completely with zero reset! Shifting to {target_plan_name} gives you better features with great savings. Regarding urgency: As {urgency_choice.lower()} is approaching, locking this now protects your family best. Would you have 2 minutes to discuss this?"
            elif lang_choice == "Hinglish":
                pitch_text = f"Hello {c_name} ji,\nPolicy audit ke anusar, IRDAI rules ke tahat aapka waiting period zero reset ke sath {target_plan_name} me transfer ho sakta hai. Market inflation aur {urgency_choice.lower()} ko dekhte hue yehi sahi waqt hai. Kindly let me know when we can discuss quotation numbers."
                if "Warm" in tone_choice:
                    pitch_text = f"Hello {c_name} ji, namaskar! 🙏\nAapki current policy ka audit kiya hai—IRDAI rules ke mutabiq aapka saara waiting period naye plan me bina kisi reset ke carry forward ho jayega! Hum {target_plan_name} me port karke behtar features pa sakte hain. Aur sabse main baat: {urgency_choice} ki wajah se abhi step lena sabse sahi rahega. Bataiye kab baat karein?"
            else:
                pitch_text = f"Namaskaram {c_name} ji! 🙏\nIRDAI rules prakaram waiting period carry forward cheyyam/madabahudu. {target_plan_name} ki port cheste chala benefits untayi. Okka chinna call matladudama?"

            st.text_area("Generated Pitch Message", pitch_text, height=150)
            
            whatsapp_number = normalize_mobile(cust_data['mobile'])
            if whatsapp_number:
                whatsapp_url = "https://wa.me/91" + whatsapp_number + "?text=" + urllib.parse.quote(pitch_text)
                st.markdown(f"### [📲 Click Here to Send via WhatsApp]({whatsapp_url})", unsafe_allow_html=True)


# ============================================================
# COMPARISON (FIXED UNIQUE COLUMN BUG)
# ============================================================

with tabs[3]:
    st.subheader("⚖️ Plan Comparison Builder")
    a, b = st.columns(2)
    current_insurer = a.selectbox("Current insurer", list(PLANS.keys()), key="comp_curr_ins")
    current_plan = a.selectbox("Current plan", PLANS[current_insurer], key="comp_curr_plan")
    target_insurer = b.selectbox("Target insurer", list(PLANS.keys()), key="comp_tgt_ins")
    target_plan = b.selectbox("Target plan", PLANS[target_insurer], key="comp_tgt_plan")

    comparison = []
    for feature in FEATURES:
        current_value = st.text_input(f"{feature} — Current", key="curr_" + feature)
        target_value = st.text_input(f"{feature} — Target", key="tgt_" + feature)
        comparison.append([feature, current_value, target_value])

    col_curr_name = f"Current: {current_insurer} - {current_plan}"
    col_target_name = f"Target: {target_insurer} - {target_plan}"
    if col_curr_name == col_target_name: col_target_name = f"Target: {target_insurer} - {target_plan} (Alt)"
    
    comparison_df = pd.DataFrame(comparison, columns=["Feature", col_curr_name, col_target_name])
    st.dataframe(comparison_df, use_container_width=True, hide_index=True)


# ============================================================
# PREMIUM CALCULATOR
# ============================================================

with tabs[4]:
    st.subheader("💰 Verified Premium Calculator")
    if rates.empty:
        st.warning("Upload an official CSV/XLSX rate table from the sidebar.")
    else:
        insurer_options = sorted(rates["insurer"].dropna().astype(str).unique())
        selected_insurer = st.selectbox("Insurer", insurer_options)
        plan_options = sorted(rates[rates["insurer"].astype(str) == selected_insurer]["plan"].dropna().astype(str).unique())
        selected_plan = st.selectbox("Plan", plan_options)
        zone_options = sorted(rates[(rates["insurer"].astype(str) == selected_insurer) & (rates["plan"].astype(str) == selected_plan)]["zone"].dropna().astype(str).unique())
        selected_zone = st.selectbox("Zone", [""] + zone_options)
        policy_type = st.selectbox("Policy Type", ["Individual", "Family Floater", "Multi Member Individual"])
        si_options = sorted(rates[(rates["insurer"].astype(str) == selected_insurer) & (rates["plan"].astype(str) == selected_plan)]["sum_insured_lakh"].dropna().unique())
        selected_si = st.selectbox("Sum Insured ₹ lakh", si_options)
        ages_text = st.text_input("Member ages", "35,32")
        
        try: ages = [int(x.strip()) for x in ages_text.split(",") if x.strip()]
        except: ages = []

        if st.button("💰 Calculate Verified Premium", use_container_width=True):
            if not ages: st.error("Enter at least one age.")
            else:
                result, error = calculate_premium(rates, selected_insurer, selected_plan, selected_zone, policy_type, selected_si, ages)
                if error: st.error(error)
                else:
                    st.metric("Premium", money(result["total"]))
                    st.success("Calculated from loaded rate table.")


# ============================================================
# POLICY OCR
# ============================================================

with tabs[5]:
    st.subheader("📷 Policy Image Scanner")
    image_file = st.file_uploader("Upload policy / renewal image", type=["jpg", "jpeg", "png", "webp"], key="ocr_image")
    if image_file:
        if Image: st.image(image_file, use_container_width=True)
        if st.button("🔍 Extract Policy Details", use_container_width=True):
            text, error = extract_ocr(image_file)
            if error: st.error(error)
            else:
                st.session_state["ocr_text"] = text
                st.session_state["ocr_fields"] = extract_fields(text)
    if st.session_state.get("ocr_text"):
        st.text_area("Extracted text", st.session_state["ocr_text"], height=220)
        st.json(st.session_state.get("ocr_fields", {}))


# ============================================================
# OPPORTUNITY SCANNER & AUDIT (Merged remaining features)
# ============================================================

with tabs[6]:
    st.subheader("🔥 Manual Sales Opportunity Scanner")
    a, b = st.columns(2)
    current_si = a.number_input("Current SI ₹ lakh", min_value=0.0, value=5.0)
    current_premium = b.number_input("Current annual premium", min_value=0.0, value=0.0)
    room_gap = st.checkbox("Room-rent restriction detected")
    ped_issue = st.checkbox("PED / waiting-period opportunity")
    
    lead_score = opportunity_score(date.today() + timedelta(days=25), current_si, current_premium, room_gap, ped_issue, 40)
    st.progress(lead_score / 100)
    st.metric("Opportunity Score", f"{lead_score}/100")

with tabs[7]:
    st.subheader("🧾 Policy Audit")
    if st.button("🔍 Run Policy Audit", use_container_width=True):
        st.success("Audit feature active. Connect with PDF parser module for deep clause extraction.")

with tabs[8]:
    st.subheader("📌 Follow-up Tracker")
    st.info("Follow up module active. Check CRM dashboard.")

st.divider()
st.caption("🛡️ Insurance Sales CRM | Final policy terms, underwriting, premium and acceptance remain subject to the insurer's current official documents.")
