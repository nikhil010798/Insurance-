from datetime import date, datetime, timedelta
from pathlib import Path
import re
import sqlite3
import urllib.parse
import numpy as np
import pandas as pd
import streamlit as st

try:
  from PIL import Image
except ImportError:
  Image = None

try:
  import pytesseract
except ImportError:
  pytesseract = None

st.set_page_config(
    page_title="Ultimate Insurance Sales CRM", page_icon="🛡️", layout="wide"
)

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "crm.db"
RATE_DIR = BASE / "rate_tables"
RATE_DIR.mkdir(exist_ok=True)

st.markdown(
    """
<style>
.block-container{padding-top:.7rem;padding-bottom:4rem}
.stButton>button{border-radius:12px;min-height:42px;font-weight:600}
div[data-testid="stMetric"]{border:1px solid #e5e7eb;border-radius:14px;padding:10px}
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# CONSTANTS
# ============================================================

INSURERS = [
    "Care Health",
    "Niva Bupa",
    "HDFC ERGO",
    "Star Health",
    "ICICI Lombard",
    "Other",
]

PLANS = {
    "Care Health": ["Ultimate Care", "Care Supreme", "Other"],
    "Niva Bupa": ["ReAssure 2.0", "ReAssure 3.0", "Health Companion", "Other"],
    "HDFC ERGO": ["my:Optima Secure", "Other"],
    "Star Health": ["Star Comprehensive", "Family Health Optima", "Other"],
    "ICICI Lombard": ["Complete Health Insurance", "Other"],
    "Other": ["Other"],
}

FEATURES = [
    "Room Rent",
    "ICU",
    "Modern Treatment",
    "Road Ambulance",
    "NCB / Bonus",
    "Restore / Refill",
    "Co-pay",
    "Disease Sub-limits",
    "PED Waiting",
    "Specific Waiting",
    "Maternity",
    "Day Care",
]

RATE_COLS = [
    "insurer",
    "plan",
    "zone",
    "policy_type",
    "sum_insured_lakh",
    "age_min",
    "age_max",
    "member_count",
    "base_premium",
    "gst_included",
    "discount_pct",
    "source",
    "source_date",
]


# ============================================================
# DATABASE
# ============================================================


def get_db():
  conn = sqlite3.connect(DB_PATH, check_same_thread=False)

  conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            mobile TEXT,
            city TEXT,
            insurer TEXT,
            plan TEXT,
            sum_insured REAL,
            renewal_date TEXT,
            premium REAL,
            members TEXT,
            ped TEXT,
            notes TEXT,
            score INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
    """)

  conn.execute("""
        CREATE TABLE IF NOT EXISTS followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            followup_date TEXT,
            status TEXT,
            note TEXT,
            created_at TEXT
        )
    """)

  conn.commit()
  return conn


DB = get_db()


# ============================================================
# HELPERS
# ============================================================


def normalize_mobile(value):
  value = re.sub(r"\D", "", str(value or ""))

  if value.startswith("91") and len(value) == 12:
    return value[2:]

  if len(value) >= 10:
    return value[-10:]

  return value


def money(value):
  try:
    return f"₹{float(value):,.0f}"
  except Exception:
    return "—"


def opportunity_score(
    renewal, sum_insured, premium, room=False, ped=False, age=0
):
  score = 0

  try:
    days = (renewal - date.today()).days

    if 0 <= days <= 30:
      score += 35
    elif 31 <= days <= 60:
      score += 25
    elif 61 <= days <= 90:
      score += 15
    elif days < 0:
      score += 15

  except Exception:
    pass

  try:
    si = float(sum_insured)

    if si <= 5:
      score += 20
    elif si <= 10:
      score += 12

  except Exception:
    pass

  if room:
    score += 15

  if ped:
    score += 10

  try:
    if int(age) >= 45:
      score += 10
  except Exception:
    pass

  if float(premium or 0) > 0:
    score += 5

  return min(score, 100)


# ============================================================
# RATE TABLE
# ============================================================


def normalize_rates(df):
  df = df.copy()

  df.columns = [
      str(c).strip().lower().replace(" ", "_") for c in df.columns
  ]

  aliases = {
      "sum_insured": "sum_insured_lakh",
      "si_lakh": "sum_insured_lakh",
      "premium": "base_premium",
      "members": "member_count",
      "age_from": "age_min",
      "age_to": "age_max",
  }

  for old, new in aliases.items():
    if old in df.columns and new not in df.columns:
      df.rename(columns={old: new}, inplace=True)

  for col in RATE_COLS:
    if col not in df.columns:
      df[col] = ""

  for col in [
      "sum_insured_lakh",
      "age_min",
      "age_max",
      "member_count",
      "base_premium",
      "discount_pct",
  ]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

  return df[RATE_COLS]


def load_rates():
  tables = []

  for file in RATE_DIR.glob("*.csv"):
    try:
      tables.append(normalize_rates(pd.read_csv(file)))
    except Exception:
      pass

  if not tables:
    return pd.DataFrame(columns=RATE_COLS)

  return pd.concat(tables, ignore_index=True)


rates = load_rates()


# ============================================================
# VERIFIED PREMIUM ENGINE
# ============================================================


def calculate_premium(
    rates_df, insurer, plan, zone, policy_type, sum_insured, ages
):
  if rates_df.empty:
    return None, "No verified rate table is loaded."

  df = rates_df[
      (rates_df["insurer"].astype(str).str.casefold() == insurer.casefold())
      & (rates_df["plan"].astype(str).str.casefold() == plan.casefold())
      & (rates_df["sum_insured_lakh"] == float(sum_insured))
  ]

  if zone:
    z = df[df["zone"].astype(str).str.casefold() == zone.casefold()]
    if not z.empty:
      df = z

  type_df = df[
      df["policy_type"].astype(str).str.casefold() == policy_type.casefold()
  ]

  if not type_df.empty:
    df = type_df

  if df.empty:
    return None, "No matching official rate row was found."

  if policy_type == "Individual":
    age = ages[0]
    match = df[(df["age_min"] <= age) & (df["age_max"] >= age)]

    if match.empty:
      return None, f"No verified rate found for age {age}."

    row = match.iloc[0]
    base = float(row["base_premium"])

  elif policy_type == "Family Floater":
    oldest = max(ages)
    match = df[
        (df["age_min"] <= oldest)
        & (df["age_max"] >= oldest)
        & (df["member_count"] == len(ages))
    ]

    if match.empty:
      return (
          None,
          "No explicit verified floater rate for this age/member combination.",
      )

    row = match.iloc[0]
    base = float(row["base_premium"])

  else:
    base = 0
    row = None

    for age in ages:
      match = df[(df["age_min"] <= age) & (df["age_max"] >= age)]
      if match.empty:
        return None, f"No verified rate found for age {age}."
      row = match.iloc[0]
      base += float(row["base_premium"])

  discount = float(row["discount_pct"] or 0)
  base = base * (1 - discount / 100)

  gst_included = str(row["gst_included"]).strip().lower()
  gst = 0 if gst_included in ["yes", "true", "1"] else base * 0.18

  total = base + gst

  return {
      "base": base,
      "gst": gst,
      "total": total,
      "source": str(row["source"]),
      "source_date": str(row["source_date"]),
  }, None


# ============================================================
# OCR
# ============================================================


def extract_ocr(file):
  if Image is None or pytesseract is None:
    return "", "OCR packages are unavailable."

  try:
    image = Image.open(file)
    text = pytesseract.image_to_string(image, config="--psm 6")
    return text, None
  except Exception as e:
    return "", str(e)


def extract_fields(text):
  patterns = {
      "mobile": r"(?:mobile|mob|phone)\D{0,10}([6-9]\d{9})",
      "premium": (
          r"(?:premium)\D{0,15}(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)"
      ),
      "renewal_date": (
          r"(?:renewal|expiry|policy end|valid till)\D{0,15}(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
      ),
  }

  result = {}
  for key, pattern in patterns.items():
    match = re.search(pattern, text or "", re.IGNORECASE)
    if match:
      result[key] = match.group(1)

  return result


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
  st.header("⚙️ Setup")
  st.write(f"Verified rate rows: **{len(rates)}**")

  rate_file = st.file_uploader(
      "Upload official rate table", type=["csv", "xlsx"]
  )

  if rate_file:
    try:
      if rate_file.name.lower().endswith(".xlsx"):
        raw = pd.read_excel(rate_file)
      else:
        raw = pd.read_csv(rate_file)

      normalized = normalize_rates(raw)
      output = RATE_DIR / f"{Path(rate_file.name).stem}.csv"
      normalized.to_csv(output, index=False)
      rates = load_rates()
      st.success(f"{len(normalized)} rate rows loaded.")
    except Exception as e:
      st.error(f"Rate table error: {e}")

  st.caption("Calculator uses verified rate rows only.")


# ============================================================
# HEADER
# ============================================================

st.title("🛡️ Insurance Sales CRM")
st.caption(
    "CRM • OCR • Opportunity Scanner • Policy Audit • Premium • Comparison •"
    " WhatsApp • Follow-ups"
)


# ============================================================
# TABS
# ============================================================

tabs = st.tabs([
    "🏠 Dashboard",
    "👤 CRM",
    "📷 Policy OCR",
    "🔥 Opportunity",
    "🧾 Audit",
    "💰 Premium",
    "⚖️ Compare",
    "💬 Sales",
    "📌 Follow-ups",
])


# ============================================================
# DASHBOARD
# ============================================================

with tabs[0]:
  leads = pd.read_sql_query("SELECT * FROM leads ORDER BY updated_at DESC", DB)

  if leads.empty:
    renewals = 0
    hot = 0
  else:
    renewal_dates = pd.to_datetime(
        leads["renewal_date"], errors="coerce"
    ).dt.date
    renewals = int(
        (
            (renewal_dates >= date.today())
            & (renewal_dates <= date.today() + timedelta(days=30))
        ).sum()
    )
    hot = int(
        (pd.to_numeric(leads["score"], errors="coerce").fillna(0) >= 70).sum()
    )

  c1, c2, c3, c4 = st.columns(4)
  c1.metric("Total Leads", len(leads))
  c2.metric("Renewals ≤30 Days", renewals)
  c3.metric("🔥 Hot Leads", hot)
  c4.metric("Verified Rate Rows", len(rates))

  st.subheader("🔥 Sales Opportunity Scanner")

  if leads.empty:
    st.info("Add customers from CRM.")
  else:
    display = leads[[
        "name",
        "mobile",
        "insurer",
        "plan",
        "sum_insured",
        "renewal_date",
        "score",
    ]].copy()

    display["Priority"] = np.where(
        display["score"] >= 80,
        "🔥 HOT",
        np.where(display["score"] >= 60, "🟠 WARM", "🟢 NURTURE"),
    )

    st.dataframe(
        display.sort_values("score", ascending=False),
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# CRM
# ============================================================

with tabs[1]:
  st.subheader("👤 Customer CRM")

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
    lead_score = opportunity_score(
        renewal, sum_insured, premium, ped=bool(ped.strip())
    )

    DB.execute(
        """
            INSERT INTO leads(
                name,mobile,city,insurer,plan,
                sum_insured,renewal_date,premium,
                members,ped,notes,score,
                created_at,updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
        (
            name.strip(),
            normalize_mobile(mob),
            city,
            insurer,
            plan,
            sum_insured,
            renewal.isoformat(),
            premium,
            members,
            ped,
            notes,
            lead_score,
            now,
            now,
        ),
    )
    DB.commit()
    st.success("Customer saved.")

  leads = pd.read_sql_query("SELECT * FROM leads ORDER BY id DESC", DB)
  if not leads.empty:
    st.dataframe(
        leads.drop(columns=["created_at", "updated_at"], errors="ignore"),
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# POLICY OCR
# ============================================================

with tabs[2]:
  st.subheader("📷 Policy Image Scanner")

  image_file = st.file_uploader(
      "Upload policy / renewal image",
      type=["jpg", "jpeg", "png", "webp"],
      key="policy_image",
  )

  if image_file:
    if Image:
      st.image(image_file, use_container_width=True)

    if st.button("🔍 Extract Policy Details", use_container_width=True):
      text, error = extract_ocr(image_file)
      if error:
        st.error(error)
      else:
        st.session_state["ocr_text"] = text
        st.session_state["ocr_fields"] = extract_fields(text)

  if st.session_state.get("ocr_text"):
    st.text_area("Extracted text", st.session_state["ocr_text"], height=220)
    st.subheader("Detected fields")
    st.json(st.session_state.get("ocr_fields", {}))
    st.warning(
        "OCR is a draft. Verify policy number, dates, premium, SI and medical"
        " details."
    )


# ============================================================
# OPPORTUNITY SCANNER
# ============================================================

with tabs[3]:
  st.subheader("🔥 Sales Opportunity Scanner")

  a, b = st.columns(2)
  customer = a.text_input("Customer")
  renewal_date = b.date_input("Renewal date", date.today() + timedelta(days=25))

  a, b = st.columns(2)
  current_si = a.number_input("Current SI ₹ lakh", min_value=0.0, value=5.0)
  age = b.number_input("Primary age", min_value=0, max_value=120, value=40)

  room_gap = st.checkbox("Room-rent restriction detected")
  ped_issue = st.checkbox("PED / waiting-period opportunity")
  current_premium = st.number_input(
      "Current annual premium", min_value=0.0, value=0.0
  )

  lead_score = opportunity_score(
      renewal_date, current_si, current_premium, room_gap, ped_issue, age
  )
  st.progress(lead_score / 100)
  st.metric("Opportunity Score", f"{lead_score}/100")

  if lead_score >= 80:
    st.error("🔥 HOT LEAD — contact immediately")
  elif lead_score >= 60:
    st.warning("🟠 WARM LEAD — follow up soon")
  else:
    st.success("🟢 NURTURE — keep in follow-up")


# ============================================================
# POLICY AUDIT
# ============================================================

with tabs[4]:
  st.subheader("🧾 Policy Audit")
  audit_values = {}

  for feature in FEATURES:
    audit_values[feature] = st.text_input(feature, key="audit_" + feature)

  if st.button("🔍 Run Policy Audit", use_container_width=True):
    missing = [key for key, value in audit_values.items() if not value]
    if missing:
      for item in missing:
        st.warning(f"{item}: information not entered.")
    else:
      st.success(
          "Audit fields populated. Verify against current official wording."
      )


# ============================================================
# PREMIUM CALCULATOR
# ============================================================

with tabs[5]:
  st.subheader("💰 Verified Premium Calculator")
  st.info(
      "This calculator uses loaded official rate-table rows only. It does not"
      " invent a premium using a generic formula."
  )

  if rates.empty:
    st.warning("Upload an official CSV/XLSX rate table from the sidebar.")
  else:
    insurer_options = sorted(rates["insurer"].dropna().astype(str).unique())
    selected_insurer = st.selectbox("Insurer", insurer_options)

    plan_options = sorted(
        rates[rates["insurer"].astype(str) == selected_insurer]["plan"]
        .dropna()
        .astype(str)
        .unique()
    )
    selected_plan = st.selectbox("Plan", plan_options)

    zone_options = sorted(
        rates[
            (rates["insurer"].astype(str) == selected_insurer)
            & (rates["plan"].astype(str) == selected_plan)
        ]["zone"]
        .dropna()
        .astype(str)
        .unique()
    )
    selected_zone = st.selectbox("Zone", [""] + zone_options)

    policy_type = st.selectbox(
        "Policy Type", ["Individual", "Family Floater", "Multi Member Individual"]
    )

    si_options = sorted(
        rates[
            (rates["insurer"].astype(str) == selected_insurer)
            & (rates["plan"].astype(str) == selected_plan)
        ]["sum_insured_lakh"]
        .dropna()
        .unique()
    )
    selected_si = st.selectbox("Sum Insured ₹ lakh", si_options)

    ages_text = st.text_input("Member ages", "35,32")
    try:
      ages = [int(x.strip()) for x in ages_text.split(",") if x.strip()]
    except Exception:
      ages = []

    if st.button("💰 Calculate Verified Premium", use_container_width=True):
      if not ages:
        st.error("Enter at least one age.")
      else:
        result, error = calculate_premium(
            rates,
            selected_insurer,
            selected_plan,
            selected_zone,
            policy_type,
            selected_si,
            ages,
        )
        if error:
          st.error(error)
        else:
          st.metric("Premium", money(result["total"]))
          a, b = st.columns(2)
          a.write(f"Base: {money(result['base'])}")
          b.write(f"GST: {money(result['gst'])}")
          st.success("Calculated from loaded rate table.")
          st.caption(
              f"Source: {result['source']} | Source date:"
              f" {result['source_date']}"
          )
          st.warning(
              "Not a binding insurer quote. Final premium remains subject to"
              " proposal, underwriting and insurer quotation."
          )


# ============================================================
# COMPARISON (FIXED UNIQUE COLUMN BUG)
# ============================================================

with tabs[6]:
  st.subheader("⚖️ Plan Comparison Builder")

  a, b = st.columns(2)
  current_insurer = a.selectbox(
      "Current insurer", list(PLANS.keys()), key="current_insurer"
  )
  current_plan = a.selectbox(
      "Current plan", PLANS[current_insurer], key="current_plan"
  )

  target_insurer = b.selectbox(
      "Target insurer", list(PLANS.keys()), key="target_insurer"
  )
  target_plan = b.selectbox(
      "Target plan", PLANS[target_insurer], key="target_plan"
  )

  comparison = []
  for feature in FEATURES:
    current_value = st.text_input(f"{feature} — Current", key="current_" + feature)
    target_value = st.text_input(f"{feature} — Target", key="target_" + feature)
    comparison.append([feature, current_value, target_value])

  # Unique columns safeguard to completely prevent duplicate column crashes
  col_curr_name = f"Current: {current_insurer} - {current_plan}"
  col_target_name = f"Target: {target_insurer} - {target_plan}"

  if col_curr_name == col_target_name:
    col_target_name = f"Target: {target_insurer} - {target_plan} (Alt)"

  comparison_df = pd.DataFrame(
      comparison, columns=["Feature", col_curr_name, col_target_name]
  )

  st.dataframe(comparison_df, use_container_width=True, hide_index=True)


# ============================================================
# SALES / WHATSAPP
# ============================================================

with tabs[7]:
  st.subheader("💬 WhatsApp Sales Message")

  a, b = st.columns(2)
  customer_name = a.text_input("Customer name")
  target_plan_name = b.text_input("Target plan", "Care Ultimate")

  tone = st.selectbox("Tone", ["Crisp", "Premium", "Hinglish"])
  comparison_point = st.text_area("Verified comparison point")

  if st.button("✍️ Generate Message", use_container_width=True):
    if tone == "Hinglish":
      message = (
          f"Hi {customer_name}, aapki policy ka renewal paas aa raha hai. Maine"
          f" current cover vs {target_plan_name} ka comparison dekha hai."
          f" {comparison_point} Ek baar comparison dekh lijiye. Agar suitable"
          " lage toh main next steps explain kar dunga."
      )
    elif tone == "Premium":
      message = (
          f"Hi {customer_name}, your renewal is approaching. I've prepared a"
          f" concise comparison with {target_plan_name}. Key point:"
          f" {comparison_point} Please review it once and let me know if you'd"
          " like me to walk you through it."
      )
    else:
      message = (
          f"Hi {customer_name}, your renewal is approaching. I've prepared a"
          f" quick comparison with {target_plan_name}. Key point:"
          f" {comparison_point} Please have a look and let me know if you'd"
          " like to explore the option."
      )

    st.text_area("Message", message, height=150)
    whatsapp_number = normalize_mobile(st.text_input("WhatsApp number"))

    if whatsapp_number:
      whatsapp_url = (
          "https://wa.me/91"
          + whatsapp_number
          + "?text="
          + urllib.parse.quote(message)
      )
      st.markdown(f"[📲 Open WhatsApp]({whatsapp_url})")


# ============================================================
# FOLLOW-UPS
# ============================================================

with tabs[8]:
  st.subheader("📌 Follow-up Tracker")

  leads = pd.read_sql_query(
      "SELECT id, name, mobile FROM leads ORDER BY score DESC", DB
  )

  if leads.empty:
    st.info("Add customers in CRM first.")
  else:
    options = {}
    for _, row in leads.iterrows():
      label = f"{row['id']} • {row['name']} • {row['mobile']}"
      options[label] = int(row["id"])

    selected_customer = st.selectbox("Customer", list(options.keys()))
    followup_date = st.date_input(
        "Follow-up date", date.today() + timedelta(days=2)
    )
    followup_note = st.text_input(
        "Follow-up note", "Send comparison / call"
    )

    if st.button("📌 Save Follow-up", use_container_width=True):
      DB.execute(
          """
                INSERT INTO followups(
                    lead_id,
                    followup_date,
                    status,
                    note,
                    created_at
                )
                VALUES(?,?,?,?,?)
                """,
          (
              options[selected_customer],
              followup_date.isoformat(),
              "Pending",
              followup_note,
              datetime.now().isoformat(timespec="seconds"),
          ),
      )
      DB.commit()
      st.success("Follow-up saved.")

  followups = pd.read_sql_query(
      """
        SELECT
            f.id,
            l.name,
            l.mobile,
            f.followup_date,
            f.status,
            f.note
        FROM followups f
        LEFT JOIN leads l
        ON l.id = f.lead_id
        ORDER BY f.followup_date
        """,
      DB,
  )

  if not followups.empty:
    st.dataframe(followups, use_container_width=True, hide_index=True)


# ============================================================
# FOOTER
# ============================================================

st.divider()
st.caption(
    "🛡️ Insurance Sales CRM | For sales workflow assistance only. Final policy"
    " terms, underwriting, premium and acceptance remain subject to the"
    " insurer's current official documents and quotation."
)
