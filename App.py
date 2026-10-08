import io
import urllib.parse
import pandas as pd
import PIL.Image
import streamlit as st

# Try importing pytesseract for image OCR support
try:
  import pytesseract

  OCR_AVAILABLE = True
except ImportError:
  OCR_AVAILABLE = False

# Page Configuration
st.set_page_config(
    page_title="Ultimate AI Insurance CRM & Sales Assistant", layout="wide"
)

st.title("🛡️ AI-Driven Insurance Sales, Portability & CRM Assistant")
st.markdown(
    "A one-stop solution for Health Insurance agents: Portability Engine,"
    " Abbreviation Decoder, Dynamic Calculator, Multi-Language Pitches, and"
    " Image OCR Support."
)

# 1. File Uploader Section (Supports Excel, CSV, and JPG/JPEG/PNG Photos)
uploaded_file = st.file_uploader(
    "📁 Lead Data upload karein (Excel, CSV, ya Table ki Photo JPG/JPEG/PNG)",
    type=["csv", "xlsx", "xls", "jpg", "jpeg", "png"],
)

df = None

if uploaded_file is not None:
  file_name = uploaded_file.name.lower()

  if file_name.endswith((".csv", ".xlsx", ".xls")):
    if file_name.endswith(".csv"):
      df = pd.read_csv(uploaded_file)
    else:
      df = pd.read_excel(uploaded_file)
    st.success("✅ Excel/CSV Lead data safalpurvak load ho gaya hai!")

  elif file_name.endswith((".jpg", ".jpeg", ".png")):
    image = PIL.Image.open(uploaded_file)
    st.image(image, caption="Uploaded Table Photo Preview", use_container_width=True)

    if OCR_AVAILABLE:
      with st.spinner(
          "🤖 AI photo se data read kar raha hai (OCR processing)..."
      ):
        extracted_text = pytesseract.image_to_string(image)

      # Convert extracted text lines into a structured DataFrame
      lines = [
          line.strip() for line in extracted_text.split("\n") if line.strip()
      ]
      data_rows = []
      for line in lines:
        parts = [p.strip() for p in line.split() if p.strip()]
        if parts:
          data_rows.append(parts)

      if data_rows:
        max_cols = max(len(r) for r in data_rows)
        normalized_rows = [r + [""] * (max_cols - len(r)) for r in data_rows]
        df = pd.DataFrame(normalized_rows)
        df.columns = [f"Col_{i+1}" for i in range(df.shape[1])]
        st.success("✅ Photo se data successfully extract ho gaya hai!")
      else:
        st.warning(
            "⚠️ Photo se text detect nahi ho paya. Kripya thodi saaf aur clear"
            " photo upload karein."
        )
    else:
      st.error(
          "❌ OCR library configured nahi hai. Kripya packages.txt check karein."
      )

if df is not None and not df.empty:
  with st.expander("📋 Lead Data ka Preview dekhein"):
    st.dataframe(df.head(10))

  # Dynamic Column Mapping
  cols = [str(c).strip().lower() for c in df.columns]

  name_col = next(
      (
          df.columns[i]
          for i, c in enumerate(cols)
          if "name" in c or "customer" in c
      ),
      df.columns[4] if len(df.columns) > 4 else df.columns[0],
  )
  mob_col = next(
      (
          df.columns[i]
          for i, c in enumerate(cols)
          if "mob" in c or "phone" in c or "contact" in c or "no" in c
      ),
      df.columns[1] if len(df.columns) > 1 else None,
  )
  si_col = next(
      (
          df.columns[i]
          for i, c in enumerate(cols)
          if "si" in c or "sum" in c or "insured" in c
      ),
      df.columns[3] if len(df.columns) > 3 else None,
  )
  prem_col = next(
      (
          df.columns[i]
          for i, c in enumerate(cols)
          if "prem" in c or "amount" in c
      ),
      df.columns[6] if len(df.columns) > 6 else None,
  )
  prod_col = next(
      (
          df.columns[i]
          for i, c in enumerate(cols)
          if "product" in c or "plan" in c
      ),
      df.columns[5] if len(df.columns) > 5 else None,
  )
  date_col = next(
      (
          df.columns[i]
          for i, c in enumerate(cols)
          if "date" in c or "app" in c
      ),
      df.columns[7] if len(df.columns) > 7 else None,
  )

  customer_names = df[name_col].astype(str).tolist()
  selected_customer = st.selectbox(
      "🔍 Pitch generate karne ke liye Customer select karein:", customer_names
  )

  if selected_customer:
    cust_row = df[df[name_col].astype(str) == selected_customer].iloc[0]

    st.markdown("---")
    st.header(f"👤 Customer Profile: {selected_customer}")

    val_si = (
        str(cust_row[si_col])
        if si_col and si_col in cust_row
        else "5 Lakhs"
    )
    val_prem = (
        str(cust_row[prem_col])
        if prem_col and prem_col in cust_row
        else "₹25,000"
    )
    val_prod = (
        str(cust_row[prod_col])
        if prod_col and prod_col in cust_row
        else "Health Plan"
    )
    val_date = (
        str(cust_row[date_col])
        if date_col and date_col in cust_row
        else "Nov 2022"
    )

    raw_mob = (
        str(cust_row[mob_col])
        if mob_col and mob_col in cust_row
        else "919876543210"
    )
    clean_mob = "".join(filter(str.isdigit, raw_mob))
    if len(clean_mob) == 10:
      clean_mob = "91" + clean_mob

    c1, c2, c3, c4 = st.columns(4)
    with c1:
      st.metric("Sum Insured", val_si)
    with c2:
      st.metric("Current Premium", val_prem)
    with c3:
      st.metric("Current Product", val_prod)
    with c4:
      st.metric("Policy Date", val_date)

    tab_port, tab_calc, tab_pitch, tab_follow = st.tabs([
        "🔄 Portability & Abbreviations",
        "🧮 Premium Calculator & Riders",
        "💬 Multi-Language & Urgency Pitch",
        "⏳ Smart Follow-Up Tracker",
    ])

    with tab_port:
      st.subheader("IRDAI Portability & Hidden Clauses Decoder")
      st.markdown("""
            * **IRDAI Rule Applied:** Since policy was active for ~3.5 years, **all waiting periods (PED) carry forward seamlessly** to a new insurer with zero waiting period reset!
            * **Recommended Strategy:** Pitch a better plan to save premium or upgrade features without losing completed waiting tenure.
            """)

      row_text = " ".join([str(val) for val in cust_row.values])
      mapping = {
          "CP": "Co-Pay (Customer bears % of claim)",
          "PED": "Pre-Existing Disease Waiting Period",
          "RR": "Room Rent Capping (Hospital room limit)",
          "NCB": "No Claim Bonus / Cumulative Bonus",
          "MIG": "Major Illness Group",
          "OPD": "Out Patient Department Expenses",
      }

      st.markdown("##### 🔍 Decoded Abbreviation Shorthands from Data:")
      found_codes = False
      for code, desc in mapping.items():
        if code in row_text.upper():
          st.info(f"• **{code}**: {desc}")
          found_codes = True
      if not found_codes:
        st.success(
            "• No restrictive shorthands detected in main extracted fields."
        )

    with tab_calc:
      st.subheader("🧮 Comparative Market Calculator & Optional Riders")

      col_calc1, col_calc2 = st.columns(2)
      with col_calc1:
        target_si = st.selectbox(
            "Select Target Sum Insured",
            ["5 Lakhs", "10 Lakhs", "25 Lakhs", "50 Lakhs", "1 Crore"],
        )
        selected_plan = st.selectbox(
            "Select Target Portability Plan",
            [
                "HDFC Ergo Optima Secure",
                "Niva Bupa Reassure 2.0",
                "Star Health Comprehensive",
                "ICICI Lombard Elevate",
            ],
        )

      with col_calc2:
        st.markdown("##### Select Optional Custom Riders:")
        r_zerocopay = st.checkbox("Zero Co-pay")
        r_consumables = st.checkbox("Consumables Cover")
        r_roomrent = st.checkbox("Room Rent Waiver (No Capping)")
        r_ncb = st.checkbox("NCB Protector / Multiplier")

      base_val = (
          50000
          if "1 Crore" in target_si
          else (
              35000
              if "50" in target_si
              else (25000 if "25" in target_si else 15000)
          )
      )
      if r_zerocopay:
        base_val += 3000
      if r_consumables:
        base_val += 2000
      if r_roomrent:
        base_val += 2500

      st.success(
          f"💡 **Estimated Annual Premium for {selected_plan} ({target_si}):**"
          f" **₹{base_val:,}** (Approx. savings of 10-15% compared to current"
          " market rates with upgraded features!)"
      )

    with tab_pitch:
      st.subheader("💬 Professional Pitch & WhatsApp Message Generator")

      col_p1, col_p2, col_p3 = st.columns(3)
      with col_p1:
        lang_choice = st.selectbox(
            "Select Language",
            [
                "Hinglish",
                "English",
                "Tamil (தமிழ்)",
                "Telugu (తెలుగు)",
                "Malayalam (മലയാളം)",
                "Kannada (ಕನ್ನಡ)",
            ],
        )
      with col_p2:
        tone_choice = st.selectbox(
            "Select Tone", ["🤝 Warm & Relationship-Driven", "👔 Sharp & Professional"]
        )
      with col_p3:
        urgency_choice = st.selectbox(
            "Select Urgency Hook",
            [
                "Age Slab Jump Protection",
                "Medical Inflation & Room Rent Risk",
                "Waiting Period Carry-Forward Window",
            ],
        )

      if lang_choice == "English":
        if "Warm" in tone_choice:
          pitch_text = (
              f"Hello {selected_customer} ji, warm regards! 🙏\nI hope you and"
              " your family are doing well. I reviewed your health insurance"
              f" policy. Since it has been active for ~3.5 years, IRDAI rules"
              " allow your waiting periods to carry forward completely with zero"
              f" reset! Furthermore, shifting to {selected_plan} gives you"
              f" better features with great savings. Regarding urgency: As"
              f" {urgency_choice.lower()} is approaching, locking this now"
              " protects your family best. Would you have 2 minutes to discuss"
              " this?"
          )
        else:
          pitch_text = (
              f"Dear {selected_customer}, Greetings.\nAudit results for your"
              " current health cover indicate significant optimization"
              f" potential. Under IRDAI portability norms, completed waiting"
              f" periods carry forward to {selected_plan} without reset."
              f" Considering {urgency_choice.lower()}, immediate review is"
              " recommended. Let us connect briefly to discuss comparative"
              " quotations."
          )
      elif lang_choice == "Hinglish":
        if "Warm" in tone_choice:
          pitch_text = (
              f"Hello {selected_customer} ji, namaskar! 🙏\nMain aapka"
              " insurance advisor bol raha hoon. Aapki current policy ka audit"
              " kiya hai—lagbhag 3.5 saal ho chuke hain, isiliye IRDAI rules ke"
              " mutabiq aapka saara waiting period naye plan me bina kisi reset"
              f" ke carry forward ho jayega! Hum {selected_plan} me port karke"
              f" behtar features pa sakte hain. Aur sabse main baat: {urgency_choice}"
              " ki wajah se abhi step lena sabse sahi rahega. Bataiye kab baat"
              " karein?"
          )
        else:
          pitch_text = (
              f"Hello {selected_customer} ji,\nPolicy audit report ke anusar,"
              f" aapki current policy ko 3.5 saal ho chuke hain. IRDAI rules"
              f" ke tahat waiting period zero reset ke sath {selected_plan} me"
              " transfer ho sakta hai. Market inflation aur"
              f" {urgency_choice.lower()} ko dekhte hue yehi sahi waqt hai."
              " Kindly let me know when we can discuss quotation numbers."
          )
      elif "Tamil" in lang_choice:
        pitch_text = (
            f"Vanakkam {selected_customer} ji! 🙏\nUngalin health insurance"
            " policy-ai audit செய்ததில், IRDAI rules-padi 3.5 years waiting"
            f" period carry forward pannalam. {selected_plan}-ku port seithal"
            " romba payanullathaga irukkum. Oru chinna call pesalama?"
        )
      elif "Telugu" in lang_choice:
        pitch_text = (
            f"Namaskaram {selected_customer} ji! 🙏\nMeeru unna health policy"
            " ni audit chesamu. IRDAI rules prakaram waiting period carry"
            f" forward avutundi. {selected_plan} ki port cheste chala benefits"
            " untayi. Okka chinna call matladudama?"
        )
      elif "Malayalam" in lang_choice:
        pitch_text = (
            f"Namaskaram {selected_customer} ji! 🙏\nNingalude health policy"
            " audit cheythu. IRDAI rules anusarichu waiting period carry"
            f" forward cheyyam. {selected_plan}-lekku port cheyyunnathu"
            " nannayirikkum. Oru cheriya call speak cheyyamo?"
        )
      else:
        pitch_text = (
            f"Namaskara {selected_customer} ji! 🙏\nNimma health policy audit"
            " madiddeni. IRDAI rules prakara waiting period carry forward"
            f" madabahudu. {selected_plan} ge port maduvudu tumba labhada."
            " Ondu sanna call madona?"
        )

      st.markdown("##### 📝 Generated Pitch Preview:")
      st.code(pitch_text, language="markdown")

      encoded_msg = urllib.parse.quote(pitch_text)
      whatsapp_url = f"https://wa.me/{clean_mob}?text={encoded_msg}"

      st.markdown(
          f"### [📲 Click Here to Send via WhatsApp]({whatsapp_url})",
          unsafe_allow_html=True,
      )

    with tab_follow:
      st.subheader("⏳ Follow-Up Objection Handler & Personalized Reminders")

      objection_type = st.selectbox(
          "What did the customer say in the last interaction?",
          [
              "⏳ Seen & Ignored (No Response)",
              "🤔 'Soch kar bataunga / Family se discuss karunga'",
              "💸 'Budget tight hai / Premium zyada hai'",
              "⏰ 'Abhi busy hoon, baad me call karna'",
              "👍 'Interested hoon, details bhejo'",
          ],
      )

      if "No Response" in objection_type:
        follow_msg = (
            f"Hello {selected_customer} ji, namaskar! 🙏\nShaayad aap kisi"
            " zaroori kaam me busy honge. Bas ek choti si yaad dilani thi ki"
            " aapke current health plan ka waiting period carry-forward hone ki"
            " deadline paas aa rahi hai, isiliye miss na ho jaye. Bataiye kab"
            " 2 minute free rahenge?"
        )
      elif "Soch" in objection_type:
        follow_msg = (
            f"Hello {selected_customer} ji, namaskar! 🙏\nMain bas ye check kar"
            " raha tha ki policy portability ya naye plan ke features ko lekar"
            " aapke man me koi confusion toh nahi hai? Agar koi bhi doubt ho toh"
            " bejhijhak bataiye, main clear kar deta hoon!"
        )
      elif "Budget" in objection_type:
        follow_msg = (
            f"Hello {selected_customer} ji, budget wali baat bilkul samajh aati"
            " hai. Isiliye maine ek aisa customized option nikala hai jisme"
            " aapka premium bhi aapke comfort me rahega aur waiting period ka"
            " pura benefit bhi mil jayega. Ek baar check kar lein?"
        )
      elif "busy" in objection_type:
        follow_msg = (
            f"Hello {selected_customer} ji! Koi dikkat nahi, samajh sakta hoon"
            " aap busy hain. Main sham ko 6 baje ke baad ek choti si call kar"
            " loon ya aap jab free hon tab bata dijiye?"
        )
      else:
        follow_msg = (
            f"Hello {selected_customer} ji! Great. Ye lijiye complete details"
            " aur comparison chart. Isko dekh lijiye, aur bataiye application"
            " process kab start karein?"
        )

      st.markdown("##### 💬 Generated Follow-Up Message:")
      st.code(follow_msg, language="markdown")

      encoded_follow = urllib.parse.quote(follow_msg)
      follow_whatsapp_url = f"https://wa.me/{clean_mob}?text={encoded_follow}"
      st.markdown(
          f"### [📲 Send Follow-Up on WhatsApp]({follow_whatsapp_url})",
          unsafe_allow_html=True,
      )

else:
  st.info(
      "👆 Pehle upar diye gaye button se apni lead file (Excel, CSV, ya table ki"
      " photo JPG/JPEG) upload karein taaki dashboard shuru ho sake."
  )
