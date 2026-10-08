import os
import re
import sqlite3
from urllib.parse import quote
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

DB_PATH = "insurance_crm.db"
RATE_PATH = "rate_table.csv"

st.set_page_config(
    page_title="Insurance Sales CRM",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)


# =========================================================
# DATABASE
# =========================================================

def db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()

    con.executescript("""
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        mobile TEXT,
        dob TEXT,
        age INTEGER,
        policy_no TEXT,
        sum_insured REAL,
        premium REAL,
        insurer TEXT,
        product TEXT,
        policy_date TEXT,
        renewal_date TEXT,
        status TEXT DEFAULT 'New Lead',
        notes TEXT DEFAULT '',
        objection TEXT DEFAULT '',
        interested_plan TEXT DEFAULT '',
        last_contact TEXT,
        next_followup TEXT,
        source TEXT DEFAULT '',
        opportunity_score INTEGER DEFAULT 0,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS interactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER,
        interaction_date TEXT,
        status TEXT,
        note TEXT,
        created_at TEXT
    );
    """)

    con.commit()
    con.close()


# =========================================================
# DATA CLEANING
# =========================================================

def clean_col(c):
    c = str(c).strip().lower()
    c = re.sub(r"[^a-z0-9]+", "_", c).strip("_")
    return c or "column"


def unique_columns(cols):
    seen = {}
    output = []

    for c in cols:
        base = clean_col(c)
        count = seen.get(base, 0)

        if count == 0:
            output.append(base)
        else:
            output.append(f"{base}_{count + 1}")

        seen[base] = count + 1

    return output


def safe_df(df):
    df = df.copy()
    df.columns = unique_columns(df.columns)

    for c in df.columns:
        if df[c].dtype == "object":
            df[c] = (
                df[c]
                .fillna("")
                .astype(str)
                .str.replace("\x00", "", regex=False)
            )

    return df


def norm_mobile(value):
    digits = re.sub(r"\D", "", str(value or ""))

    if len(digits) >= 12 and digits.startswith("91"):
        digits = digits[-10:]

    return digits[-10:] if len(digits) >= 10 else digits


def money(value):
    if value is None:
        return 0.0

    s = str(value).replace(",", "").replace("₹", "").strip()

    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)

    return float(m.group()) if m else 0.0


def parse_age(value):
    try:
        x = int(float(str(value).strip()))
        return x if 0 < x < 120 else None
    except Exception:
        return None


def age_from_dob(value):
    if not value:
        return None

    try:
        d = pd.to_datetime(
            value,
            errors="coerce",
            dayfirst=True
        )

        if pd.isna(d):
            return None

        today = date.today()

        return (
            today.year
            - d.date().year
            - ((today.month, today.day) < (d.date().month, d.date().day))
        )

    except Exception:
        return None


# =========================================================
# OPPORTUNITY SCORING
# =========================================================

def score_lead(row):

    score = 20

    age = row.get("age")
    si = float(row.get("sum_insured") or 0)
    premium = float(row.get("premium") or 0)
    renewal = row.get("renewal_date")

    if age and age >= 55:
        score += 20

    if si and si <= 500000:
        score += 20

    if premium and premium >= 25000:
        score += 10

    if renewal:

        try:
            rd = pd.to_datetime(
                renewal,
                errors="coerce"
            ).date()

            if rd and 0 <= (rd - date.today()).days <= 30:
                score += 30

        except Exception:
            pass

    return min(score, 100)


# =========================================================
# COLUMN MAPPING
# =========================================================

def infer_field(cols, aliases):

    for alias in aliases:

        for col in cols:

            if alias in col:
                return col

    return None


def map_columns(df):

    cols = list(df.columns)

    return {
        "name": infer_field(
            cols,
            ["customer_name", "name", "insured", "proposer"]
        ),

        "mobile": infer_field(
            cols,
            ["mobile", "phone", "contact", "mob"]
        ),

        "dob": infer_field(
            cols,
            ["dob", "date_of_birth", "birth"]
        ),

        "policy_no": infer_field(
            cols,
            ["policy_no", "policy", "policyno"]
        ),

        "sum_insured": infer_field(
            cols,
            ["sum_insured", "si", "suminsured", "cover"]
        ),

        "premium": infer_field(
            cols,
            ["premium", "prem"]
        ),

        "insurer": infer_field(
            cols,
            ["insurer", "company"]
        ),

        "product": infer_field(
            cols,
            ["product", "plan"]
        ),

        "policy_date": infer_field(
            cols,
            [
                "policy_date",
                "app_date",
                "application_date",
                "start"
            ]
        ),

        "renewal_date": infer_field(
            cols,
            [
                "renewal",
                "renewal_date",
                "expiry",
                "expiry_date"
            ]
        ),
    }


# =========================================================
# IMPORT INTO CRM
# =========================================================

def import_df(df, source="Import"):

    df = safe_df(df)
    mapping = map_columns(df)

    con = db()

    added = 0
    updated = 0

    now = datetime.now().isoformat(timespec="seconds")

    for _, r in df.iterrows():

        name = str(
            r.get(mapping["name"], "")
            if mapping["name"]
            else ""
        ).strip()

        mobile = norm_mobile(
            r.get(mapping["mobile"], "")
            if mapping["mobile"]
            else ""
        )

        if not name and not mobile:
            continue

        dob = str(
            r.get(mapping["dob"], "")
            if mapping["dob"]
            else ""
        ).strip()

        age = (
            age_from_dob(dob)
            or parse_age(r.get("age", ""))
        )

        policy_no = str(
            r.get(mapping["policy_no"], "")
            if mapping["policy_no"]
            else ""
        ).strip()

        si = money(
            r.get(mapping["sum_insured"], 0)
            if mapping["sum_insured"]
            else 0
        )

        premium = money(
            r.get(mapping["premium"], 0)
            if mapping["premium"]
            else 0
        )

        insurer = str(
            r.get(mapping["insurer"], "")
            if mapping["insurer"]
            else ""
        ).strip()

        product = str(
            r.get(mapping["product"], "")
            if mapping["product"]
            else ""
        ).strip()

        policy_date = str(
            r.get(mapping["policy_date"], "")
            if mapping["policy_date"]
            else ""
        ).strip()

        renewal = str(
            r.get(mapping["renewal_date"], "")
            if mapping["renewal_date"]
            else ""
        ).strip()

        score = score_lead({
            "age": age,
            "sum_insured": si,
            "premium": premium,
            "renewal_date": renewal
        })

        existing = None

        if mobile:

            existing = con.execute(
                "SELECT id FROM leads WHERE mobile=? LIMIT 1",
                (mobile,)
            ).fetchone()

        if not existing and policy_no:

            existing = con.execute(
                "SELECT id FROM leads WHERE policy_no=? LIMIT 1",
                (policy_no,)
            ).fetchone()

        if existing:

            con.execute(
                """
                UPDATE leads
                SET
                    name=?,
                    dob=?,
                    age=?,
                    policy_no=?,
                    sum_insured=?,
                    premium=?,
                    insurer=?,
                    product=?,
                    policy_date=?,
                    renewal_date=?,
                    opportunity_score=?,
                    source=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    name,
                    dob,
                    age,
                    policy_no,
                    si,
                    premium,
                    insurer,
                    product,
                    policy_date,
                    renewal,
                    score,
                    source,
                    now,
                    existing["id"]
                )
            )

            updated += 1

        else:

            con.execute(
                """
                INSERT INTO leads
                (
                    name,
                    mobile,
                    dob,
                    age,
                    policy_no,
                    sum_insured,
                    premium,
                    insurer,
                    product,
                    policy_date,
                    renewal_date,
                    opportunity_score,
                    source,
                    updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    name,
                    mobile,
                    dob,
                    age,
                    policy_no,
                    si,
                    premium,
                    insurer,
                    product,
                    policy_date,
                    renewal,
                    score,
                    source,
                    now
                )
            )

            added += 1

    con.commit()
    con.close()

    return added, updated


# =========================================================
# SUM INSURED OCR PARSER
# =========================================================

def parse_si(value):

    s = (
        str(value or "")
        .strip()
        .upper()
        .replace("₹", "")
        .replace(",", "")
    )

    m = re.search(
        r"([0-9]+(?:\.[0-9]+)?)\s*(CR|CRORE|L|LAKH|K)?",
        s
    )

    if not m:
        return 0.0

    n = float(m.group(1))
    unit = m.group(2) or ""

    if unit in ("CR", "CRORE"):
        return n * 10000000

    if unit in ("L", "LAKH"):
        return n * 100000

    if unit == "K":
        return n * 1000

    # OCR often reads:
    # 5L  -> 51
    # 15L -> 151
    # 25L -> 251

    if (
        not unit
        and 11 <= n <= 1001
        and int(n) % 10 == 1
    ):

        implied_lakh = int(n) // 10

        if implied_lakh in {
            1, 2, 3, 5, 7,
            10, 15, 20, 25,
            30, 50, 75, 100
        }:
            return implied_lakh * 100000

    return n


# =========================================================
# OCR
# =========================================================

def _ocr_tokens(img):

    from PIL import ImageOps, ImageEnhance, ImageFilter
    import pytesseract

    gray = ImageOps.grayscale(img)

    gray = ImageEnhance.Contrast(gray).enhance(1.8)

    gray = gray.filter(ImageFilter.SHARPEN)

    data = pytesseract.image_to_data(
        gray,
        config="--psm 11",
        output_type=pytesseract.Output.DATAFRAME
    )

    data = data.dropna(subset=["text"])

    data["text"] = (
        data["text"]
        .astype(str)
        .str.strip()
    )

    return data[data["text"] != ""].copy()


def _extract_rows_from_tokens(data, image_width):

    digits = data["text"].str.replace(
        r"\D",
        "",
        regex=True
    )

    phones = data[
        digits.str.match(
            r"^[6-9]\d{9}$",
            na=False
        )
    ].copy()

    records = []

    used_y = []

    for _, phone in phones.sort_values("top").iterrows():

        cy = float(
            phone.top + phone.height / 2
        )

        if any(abs(cy - y) < 18 for y in used_y):
            continue

        used_y.append(cy)

        row = data[
            (
                data.top
                + data.height / 2
                - cy
            ).abs() <= 22
        ].copy()

        row["cx"] = (
            row.left + row.width / 2
        ) / max(image_width, 1)

        row = row.sort_values("left")

        record = {
            "mobile": norm_mobile(phone.text)
        }

        # Typical column positions in the user's sheet.
        bands = {

            "policy": row[
                (row.cx < .15)
                &
                row.text
                .str.replace(r"\D", "", regex=True)
                .str.match(
                    r"^\d{7,15}$",
                    na=False
                )
            ],

            "dob": row[
                (row.cx >= .25)
                &
                (row.cx < .34)
            ],

            "si": row[
                (row.cx >= .34)
                &
                (row.cx < .41)
            ],

            "name": row[
                (row.cx >= .40)
                &
                (row.cx < .65)
            ],

            "product": row[
                (row.cx >= .64)
                &
                (row.cx < .81)
            ],

            "premium": row[
                (row.cx >= .81)
                &
                (row.cx < .91)
            ],

            "app_date": row[
                row.cx >= .91
            ],
        }

        # POLICY NUMBER
        if not bands["policy"].empty:

            values = [
                str(x)
                for x in bands["policy"].text.tolist()
                if len(
                    re.sub(
                        r"\D",
                        "",
                        str(x)
                    )
                ) >= 7
            ]

            if values:

                record["policy_no"] = max(
                    values,
                    key=lambda x: len(
                        re.sub(
                            r"\D",
                            "",
                            x
                        )
                    )
                )

        # DOB
        dob_match = None

        for text in bands["dob"].text.tolist():

            match = re.search(
                r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b",
                str(text)
            )

            if match:
                dob_match = match.group()
                break

        if dob_match:

            record["dob"] = (
                dob_match
                .replace(".", "-")
                .replace("/", "-")
            )

        # SUM INSURED
        si_text = " ".join(
            bands["si"].text.astype(str).tolist()
        )

        if re.search(r"\d", si_text):

            record["sum_insured"] = parse_si(
                si_text
            )

        # NAME
        name = " ".join(
            bands["name"].text.astype(str).tolist()
        )

        name = re.sub(
            r"[^A-Za-z .'-]",
            " ",
            name
        )

        name = re.sub(
            r"\s+",
            " ",
            name
        ).strip()

        if (
            name
            and len(name) > 2
            and "name" not in name.lower()
            and "product" not in name.lower()
        ):
            record["name"] = name

        # PRODUCT
        product = " ".join(
            bands["product"].text.astype(str).tolist()
        )

        product = re.sub(
            r"\s+",
            " ",
            product
        ).strip()

        if (
            product
            and "product" not in product.lower()
        ):
            record["product"] = product

        # PREMIUM
        premium_numbers = []

        for text in bands["premium"].text.astype(str).tolist():

            match = re.search(
                r"\d[\d,]{3,8}",
                text.replace("$", "")
            )

            if match:

                premium_numbers.append(
                    match.group().replace(",", "")
                )

        if premium_numbers:

            record["premium"] = float(
                max(
                    premium_numbers,
                    key=lambda x: float(x)
                )
            )

        # APPLICATION DATE
        for text in bands["app_date"].text.astype(str).tolist():

            match = re.search(
                r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b",
                text
            )

            if match:

                record["policy_date"] = (
                    match.group()
                    .replace(".", "-")
                    .replace("/", "-")
                )

                break

        if (
            record.get("mobile")
            or record.get("policy_no")
        ):
            records.append(record)

    return safe_df(
        pd.DataFrame(records)
    )


def ocr_image(uploaded):

    try:

        from PIL import Image
        import pytesseract

        image = Image.open(uploaded).convert("RGB")

        # First attempt: complete image
        data = _ocr_tokens(image)

        used_image = image

        # If uploaded image is actually a gallery/phone screenshot,
        # automatically focus on the table area.
        if len(data) < 50:

            w, h = image.size

            used_image = image.crop(
                (
                    0,
                    int(h * .30),
                    w,
                    int(h * .68)
                )
            )

            used_image = used_image.resize(
                (
                    w * 3,
                    int(h * .38) * 3
                )
            )

            data = _ocr_tokens(
                used_image
            )

        rows = _extract_rows_from_tokens(
            data,
            used_image.size[0]
        )

        raw = pytesseract.image_to_string(
            used_image,
            config="--psm 11"
        )

        return rows, raw

    except Exception as e:

        return (
            pd.DataFrame(),
            f"OCR unavailable/error: {e}"
        )


# =========================================================
# START
# =========================================================

init_db()

st.markdown(
    "# 🛡️ Insurance Sales CRM"
)

st.caption(
    "JPG/JPEG Sheet OCR • Customer Profiling • "
    "CRM • Opportunity Scanner • Follow-ups • "
    "Portability Review • Sales Tools • Premium Calculator"
)


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:

    st.subheader("⚙️ System")

    st.write(
        "📸 JPG/JPEG/PNG OCR: Enabled"
    )

    st.write(
        "📊 Excel/CSV: Enabled"
    )

    st.write(
        "👥 CRM: SQLite"
    )

    st.write(
        "🔥 Opportunity Scanner: Enabled"
    )

    st.info(
        "Premium is shown as verified only when "
        "an official/current rate table is loaded."
    )


# =========================================================
# LOAD LEADS
# =========================================================

con = db()

leads = pd.read_sql_query(
    """
    SELECT *
    FROM leads
    ORDER BY
        opportunity_score DESC,
        updated_at DESC
    """,
    con
)

con.close()


TABS = st.tabs(
    [
        "🏠 Dashboard",
        "📸 Import",
        "👥 CRM",
        "🔥 Opportunities",
        "👤 Customer",
        "💰 Calculator",
        "📅 Follow-ups",
        "💬 Sales Tools"
    ]
)


# =========================================================
# DASHBOARD
# =========================================================

with TABS[0]:

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Total Leads",
        len(leads)
    )

    c2.metric(
        "🔥 Hot Leads",
        int(
            (
                leads.opportunity_score >= 70
            ).sum()
        )
        if not leads.empty
        else 0
    )

    followup_dates = pd.to_datetime(
        leads.next_followup,
        errors="coerce"
    ).dt.date if not leads.empty else pd.Series(dtype="object")

    renewal_dates = pd.to_datetime(
        leads.renewal_date,
        errors="coerce"
    ).dt.date if not leads.empty else pd.Series(dtype="object")

    c3.metric(
        "Follow-ups Due",
        int(
            (followup_dates <= date.today()).sum()
        )
        if not leads.empty
        else 0
    )

    c4.metric(
        "Renewal ≤30 Days",
        int(
            (
                (renewal_dates >= date.today())
                &
                (
                    renewal_dates
                    <= date.today()
                    + timedelta(days=30)
                )
            ).sum()
        )
        if not leads.empty
        else 0
    )

    st.subheader(
        "🔥 Sales Opportunity Scanner"
    )

    if leads.empty:

        st.info(
            "Import your JPG/JPEG sheet or Excel/CSV first."
        )

    else:

        show = leads[
            [
                "name",
                "mobile",
                "age",
                "sum_insured",
                "premium",
                "product",
                "status",
                "opportunity_score"
            ]
        ].copy()

        show["sum_insured"] = show[
            "sum_insured"
        ].map(
            lambda x: f"₹{x:,.0f}"
        )

        show["premium"] = show[
            "premium"
        ].map(
            lambda x: f"₹{x:,.0f}"
        )

        st.dataframe(
            safe_df(show),
            use_container_width=True,
            hide_index=True
        )


# =========================================================
# IMPORT
# =========================================================

with TABS[1]:

    st.subheader(
        "📸 JPG / JPEG / PNG Sheet Import"
    )

    uploaded = st.file_uploader(
        "Upload customer sheet / screenshot",
        type=[
            "jpg",
            "jpeg",
            "png",
            "webp",
            "xlsx",
            "xls",
            "csv"
        ],
        key="main_import"
    )

    if uploaded:

        is_image = uploaded.name.lower().endswith(
            (
                ".jpg",
                ".jpeg",
                ".png",
                ".webp"
            )
        )

        if is_image:

            st.image(
                uploaded,
                caption=uploaded.name,
                use_container_width=True
            )

            with st.spinner(
                "Reading sheet and profiling customers..."
            ):

                ocr_df, raw = ocr_image(
                    uploaded
                )

            if raw.startswith(
                "OCR unavailable"
            ):

                st.error(raw)

                st.warning(
                    "Make sure packages.txt contains "
                    "tesseract-ocr and tesseract-ocr-eng."
                )

            elif ocr_df.empty:

                st.warning(
                    "No reliable customer rows detected. "
                    "Try a clearer/full-resolution image."
                )

                with st.expander(
                    "Raw OCR"
                ):
                    st.text(
                        raw[:20000]
                    )

            else:

                st.success(
                    f"OCR detected {len(ocr_df)} candidate customer rows."
                )

                st.info(
                    "Please quickly verify OCR values before importing. "
                    "OCR is extraction assistance, not a source of truth."
                )

                st.dataframe(
                    ocr_df,
                    use_container_width=True,
                    hide_index=True
                )

                if st.button(
                    "✅ Import Customers",
                    type="primary"
                ):

                    added, updated = import_df(
                        ocr_df,
                        source=uploaded.name
                    )

                    st.success(
                        f"Imported {added} new customers • "
                        f"Updated {updated} existing customers."
                    )

                    st.rerun()

                with st.expander(
                    "Raw OCR Text"
                ):
                    st.text(
                        raw[:20000]
                    )

        else:

            try:

                if uploaded.name.lower().endswith(
                    ".csv"
                ):

                    df = pd.read_csv(
                        uploaded
                    )

                else:

                    df = pd.read_excel(
                        uploaded
                    )

                df = safe_df(df)

                st.write(
                    "Detected columns:",
                    list(df.columns)
                )

                st.dataframe(
                    df.head(100),
                    use_container_width=True,
                    hide_index=True
                )

                if st.button(
                    "✅ Import Spreadsheet",
                    type="primary"
                ):

                    added, updated = import_df(
                        df,
                        source=uploaded.name
                    )

                    st.success(
                        f"Imported {added} new customers • "
                        f"Updated {updated} existing customers."
                    )

                    st.rerun()

            except Exception as e:

                st.error(
                    f"Could not read file: {e}"
                )


# =========================================================
# CRM
# =========================================================

with TABS[2]:

    st.subheader(
        "👥 Customer CRM"
    )

    con = db()

    crm = pd.read_sql_query(
        """
        SELECT *
        FROM leads
        ORDER BY updated_at DESC
        """,
        con
    )

    con.close()

    search = st.text_input(
        "Search name / mobile / policy"
    )

    if search:

        mask = (
            crm.astype(str)
            .apply(
                lambda col:
                col.str.contains(
                    search,
                    case=False,
                    na=False
                )
            )
            .any(axis=1)
        )

        crm = crm[mask]

    if crm.empty:

        st.info(
            "No customers yet."
        )

    else:

        display_cols = [
            "id",
            "name",
            "mobile",
            "age",
            "policy_no",
            "sum_insured",
            "premium",
            "product",
            "status",
            "next_followup",
            "opportunity_score"
        ]

        st.dataframe(
            safe_df(
                crm[display_cols]
            ),
            use_container_width=True,
            hide_index=True
        )


# =========================================================
# OPPORTUNITIES
# =========================================================

with TABS[3]:

    st.subheader(
        "🔥 Sales Opportunity Scanner"
    )

    if leads.empty:

        st.info(
            "Import customers first."
        )

    else:

        minimum_score = st.slider(
            "Minimum opportunity score",
            0,
            100,
            50
        )

        opportunities = leads[
            leads.opportunity_score
            >= minimum_score
        ].copy()

        st.dataframe(
            safe_df(
                opportunities[
                    [
                        "name",
                        "mobile",
                        "age",
                        "sum_insured",
                        "premium",
                        "product",
                        "renewal_date",
                        "status",
                        "opportunity_score"
                    ]
                ]
            ),
            use_container_width=True,
            hide_index=True
        )

        st.caption(
            "Opportunity score is a lead-prioritisation "
            "heuristic, not an underwriting or savings guarantee."
        )


# =========================================================
# CUSTOMER PROFILE
# =========================================================

with TABS[4]:

    st.subheader(
        "👤 Customer Profile + Conversation Tracking"
    )

    con = db()

    all_leads = pd.read_sql_query(
        """
        SELECT *
        FROM leads
        ORDER BY name
        """,
        con
    )

    con.close()

    if all_leads.empty:

        st.info(
            "Import customers first."
        )

    else:

        options = {
            f"{r['name']} | "
            f"{r['mobile'] or r['policy_no'] or r['id']}":
            int(r["id"])
            for _, r in all_leads.iterrows()
        }

        selected = st.selectbox(
            "Select customer",
            list(options.keys()),
            key="profile_customer"
        )

        lead_id = options[selected]

        row = (
            all_leads[
                all_leads.id == lead_id
            ]
            .iloc[0]
            .to_dict()
        )

        a, b, c = st.columns(3)

        a.metric(
            "Age",
            row.get("age") or "—"
        )

        b.metric(
            "Cover",
            f"₹{float(row.get('sum_insured') or 0):,.0f}"
        )

        c.metric(
            "Opportunity",
            f"{int(row.get('opportunity_score') or 0)}/100"
        )

        st.write(
            {
                k: v
                for k, v in row.items()
                if k not in {
                    "id",
                    "updated_at"
                }
            }
        )

        statuses = [
            "New Lead",
            "Contacted",
            "Comparison Sent",
            "Discussed",
            "Customer Thinking",
            "Documents Pending",
            "Portability Interested",
            "Premium Discussed",
            "Converted",
            "Not Interested",
            "Follow-up Required"
        ]

        current_status = (
            row.get("status")
            or "New Lead"
        )

        if current_status not in statuses:
            current_status = "New Lead"

        with st.form(
            "customer_update"
        ):

            status = st.selectbox(
                "Conversation status",
                statuses,
                index=statuses.index(
                    current_status
                )
            )

            note = st.text_area(
                "Where did the conversation reach?",
                value=row.get("notes") or ""
            )

            objection = st.text_input(
                "Customer objection",
                value=row.get("objection") or ""
            )

            interested = st.text_input(
                "Interested plan",
                value=row.get("interested_plan") or ""
            )

            existing_followup = pd.to_datetime(
                row.get("next_followup"),
                errors="coerce"
            )

            if pd.notna(
                existing_followup
            ):

                default_followup = (
                    existing_followup.date()
                )

            else:

                default_followup = (
                    date.today()
                    + timedelta(days=2)
                )

            next_followup = st.date_input(
                "Next follow-up",
                value=default_followup
            )

            if st.form_submit_button(
                "💾 Save Profile"
            ):

                con = db()

                now = datetime.now().isoformat(
                    timespec="seconds"
                )

                con.execute(
                    """
                    UPDATE leads
                    SET
                        status=?,
                        notes=?,
                        objection=?,
                        interested_plan=?,
                        last_contact=?,
                        next_followup=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        status,
                        note,
                        objection,
                        interested,
                        date.today().isoformat(),
                        next_followup.isoformat(),
                        now,
                        lead_id
                    )
                )

                con.execute(
                    """
                    INSERT INTO interactions
                    (
                        lead_id,
                        interaction_date,
                        status,
                        note,
                        created_at
                    )
                    VALUES(?,?,?,?,?)
                    """,
                    (
                        lead_id,
                        date.today().isoformat(),
                        status,
                        note,
                        now
                    )
                )

                con.commit()
                con.close()

                st.success(
                    "Customer profile saved."
                )

                st.rerun()

        con = db()

        history = pd.read_sql_query(
            """
            SELECT
                interaction_date,
                status,
                note
            FROM interactions
            WHERE lead_id=?
            ORDER BY id DESC
            """,
            con,
            params=(lead_id,)
        )

        con.close()

        if not history.empty:

            st.subheader(
                "📝 Conversation History"
            )

            st.dataframe(
                safe_df(history),
                use_container_width=True,
                hide_index=True
            )


# =========================================================
# PREMIUM CALCULATOR
# =========================================================

with TABS[5]:

    st.subheader(
        "💰 Premium Calculator"
    )

    st.caption(
        "Verified mode uses an official/current rate table. "
        "The app will not invent an insurer premium."
    )

    rate_upload = st.file_uploader(
        "Upload official/current insurer rate table",
        type=[
            "csv",
            "xlsx",
            "xls"
        ],
        key="rate_upload"
    )

    rates = pd.DataFrame()

    if rate_upload:

        try:

            if rate_upload.name.lower().endswith(
                ".csv"
            ):

                rates = pd.read_csv(
                    rate_upload
                )

            else:

                rates = pd.read_excel(
                    rate_upload
                )

            rates = safe_df(
                rates
            )

            st.success(
                f"Loaded {len(rates)} rate rows."
            )

        except Exception as e:

            st.error(
                str(e)
            )

    elif os.path.exists(
        RATE_PATH
    ):

        try:

            rates = safe_df(
                pd.read_csv(
                    RATE_PATH
                )
            )

        except Exception:

            rates = pd.DataFrame()

    if rates.empty:

        st.warning(
            "No verified rate table loaded. "
            "Upload an official rate table to calculate "
            "an exact table-based premium."
        )

        st.code(
            "insurer,plan,zone,age_min,age_max,sum_insured,base_premium"
        )

    else:

        required = {
            "insurer",
            "plan",
            "zone",
            "age_min",
            "age_max",
            "sum_insured",
            "base_premium"
        }

        missing = (
            required
            - set(rates.columns)
        )

        if missing:

            st.error(
                "Rate table is missing: "
                + ", ".join(
                    sorted(missing)
                )
            )

        else:

            c1, c2 = st.columns(2)

            insurer = c1.selectbox(
                "Insurer",
                sorted(
                    rates.insurer
                    .astype(str)
                    .unique()
                )
            )

            insurer_rates = rates[
                rates.insurer.astype(str)
                == insurer
            ]

            plan = c2.selectbox(
                "Plan",
                sorted(
                    insurer_rates.plan
                    .astype(str)
                    .unique()
                )
            )

            c3, c4, c5 = st.columns(3)

            age = c3.number_input(
                "Age",
                1,
                100,
                35
            )

            zone = c4.text_input(
                "Zone",
                "Zone 1"
            )

            sum_insured = c5.number_input(
                "Sum insured",
                min_value=0,
                value=1000000,
                step=100000
            )

            matches = rates[
                (rates.insurer.astype(str) == insurer)
                &
                (rates.plan.astype(str) == plan)
            ]

            matches = matches[
                (
                    matches.zone
                    .astype(str)
                    .str.lower()
                    == zone.lower()
                )
                &
                (
                    pd.to_numeric(
                        matches.age_min,
                        errors="coerce"
                    ) <= age
                )
                &
                (
                    pd.to_numeric(
                        matches.age_max,
                        errors="coerce"
                    ) >= age
                )
                &
                (
                    pd.to_numeric(
                        matches.sum_insured,
                        errors="coerce"
                    ) == sum_insured
                )
            ]

            if not matches.empty:

                base_premium = float(
                    matches.iloc[0].base_premium
                )

                st.metric(
                    "Verified Base Premium",
                    f"₹{base_premium:,.0f}"
                )

                st.success(
                    "Matched directly to the uploaded rate table."
                )

            else:

                st.warning(
                    "No exact rate-table row matched. "
                    "No premium shown to avoid a false quote."
                )


# =========================================================
# SALES TOOLS
# =========================================================

with TABS[7]:

    st.subheader(
        "💬 Sales Tools"
    )

    if leads.empty:

        st.info(
            "Import customers first."
        )

    else:

        options = {
            f"{r['name']} | "
            f"{r['mobile'] or r['policy_no'] or r['id']}":
            int(r["id"])
            for _, r in leads.iterrows()
        }

        selected = st.selectbox(
            "Customer",
            list(options.keys()),
            key="sales_customer"
        )

        lead_id = options[selected]

        row = (
            leads[
                leads.id == lead_id
            ]
            .iloc[0]
            .to_dict()
        )

        c1, c2 = st.columns(2)

        language = c1.selectbox(
            "Message language",
            [
                "English",
                "Hinglish",
                "Hindi"
            ]
        )

        objective = c2.selectbox(
            "Objective",
            [
                "Portability",
                "Coverage Upgrade",
                "Renewal Follow-up",
                "Premium Discussion"
            ]
        )

        recommended_plan = st.text_input(
            "Recommended plan",
            value=(
                row.get("interested_plan")
                or "Care Ultimate"
            )
        )

        if language == "English":

            pitch = (
                f"Hi {row.get('name') or 'Sir/Ma’am'}, "
                f"based on our discussion, I’d suggest we "
                f"review your current "
                f"{row.get('product') or 'health policy'} "
                f"against {recommended_plan}. "
                f"I can share a concise comparison covering "
                f"coverage, limits, waiting periods and premium. "
                f"Final eligibility/premium will depend on "
                f"the insurer’s current terms and underwriting."
            )

        elif language == "Hindi":

            pitch = (
                f"Namaste {row.get('name') or 'Sir/Ma’am'}, "
                f"aapki current "
                f"{row.get('product') or 'health policy'} "
                f"ko {recommended_plan} ke saath compare "
                f"karke dekh lete hain. "
                f"Main coverage, limits, waiting periods aur "
                f"premium ka short comparison bhej deta hoon. "
                f"Final eligibility/premium insurer ke current "
                f"terms aur underwriting par depend karega."
            )

        else:

            pitch = (
                f"Hi {row.get('name') or 'Sir/Ma’am'}, "
                f"aapki current "
                f"{row.get('product') or 'policy'} "
                f"ko {recommended_plan} se ek baar compare "
                f"kar lete hain. "
                f"Main coverage, limits, waiting periods aur "
                f"premium ka crisp comparison bhej deta hoon. "
                f"Final eligibility/premium insurer ke current "
                f"terms aur underwriting par depend karega."
            )

        st.text_area(
            "Ready-to-send message",
            pitch,
            height=130
        )

        mobile = norm_mobile(
            row.get("mobile")
        )

        if mobile:

            whatsapp_url = (
                "https://wa.me/91"
                + mobile
                + "?text="
                + quote(pitch)
            )

            st.markdown(
                f"[📱 Open WhatsApp Chat]({whatsapp_url})"
            )

        st.divider()

        # PORTABILITY REVIEW

        st.subheader(
            "🔄 Portability Review"
        )

        st.write(
            "Review checklist only — not a guarantee of "
            "acceptance or waiting-period transfer."
        )

        checks = [
            "Current policy details verified",
            "Renewal date checked",
            "Waiting periods / PED disclosed",
            "Requested sum insured and members verified",
            "New insurer underwriting / portability rules checked",
            "Final quote and policy wording reviewed"
        ]

        completed = st.multiselect(
            "Completed checks",
            checks
        )

        st.progress(
            len(completed) / len(checks)
        )

        if len(completed) == len(checks):

            st.success(
                "Review checklist complete — "
                "final insurer confirmation still required."
            )

        st.divider()

        # COMPARISON

        st.subheader(
            "🆚 Quick Comparison Card"
        )

        feature = st.text_input(
            "Feature",
            "Room Rent"
        )

        current_policy = st.text_input(
            "Current policy",
            "Add current policy wording"
        )

        recommended = st.text_input(
            "Recommended plan",
            "Add recommended plan wording"
        )

        comparison = pd.DataFrame(
            {
                "Feature": [feature],
                "Current": [current_policy],
                "Recommended": [recommended]
            }
        )

        st.table(
            comparison
        )

        # OBJECTION HANDLER

        st.subheader(
            "🧠 Objection Handler"
        )

        objection = st.selectbox(
            "Customer says",
            [
                "Premium is high",
                "I need time",
                "My current policy is already good",
                "I am worried about medical history",
                "I only want renewal"
            ]
        )

        responses = {

            "Premium is high":
                "I understand. Let’s first compare the actual "
                "coverage and limitations, then we can see "
                "whether the difference in premium is justified "
                "for your needs.",

            "I need time":
                "Sure. I’ll keep it simple — I’ll send the "
                "comparison so you can review the key differences "
                "and we can discuss only the points that matter.",

            "My current policy is already good":
                "That’s fair. I’m not asking you to change it "
                "blindly; let’s compare the wording, limits, "
                "waiting periods and premium side-by-side.",

            "I am worried about medical history":
                "That’s important. We should disclose it correctly "
                "and let the insurer assess it. I won’t promise "
                "acceptance or a zero-waiting outcome.",

            "I only want renewal":
                "No problem. Before renewal, a quick review can "
                "help confirm whether the existing cover still "
                "matches your current requirements. You can then decide."
        }

        st.info(
            responses[objection]
        )


# =========================================================
# FOLLOW UPS
# =========================================================

with TABS[6]:

    st.subheader(
        "📅 Follow-up Tracker"
    )

    con = db()

    followups = pd.read_sql_query(
        """
        SELECT *
        FROM leads
        WHERE next_followup IS NOT NULL
        ORDER BY next_followup
        """,
        con
    )

    con.close()

    if followups.empty:

        st.info(
            "No follow-ups scheduled."
        )

    else:

        followups["days"] = (
            pd.to_datetime(
                followups.next_followup,
                errors="coerce"
            )
            .dt.date
            - date.today()
        ).apply(
            lambda x:
            x.days
            if pd.notna(x)
            else None
        )

        due = followups[
            followups.days <= 0
        ]

        st.metric(
            "Due / Overdue",
            len(due)
        )

        st.dataframe(
            safe_df(
                followups[
                    [
                        "name",
                        "mobile",
                        "status",
                        "next_followup",
                        "days",
                        "notes",
                        "opportunity_score"
                    ]
                ]
            ),
            use_container_width=True,
            hide_index=True
      )
