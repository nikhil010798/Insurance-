import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import re
import urllib.parse
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


# ============================================================
# APP CONFIG
# ============================================================

st.set_page_config(
    page_title="Insurance Sales CRM",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

APP_DIR = Path(__file__).parent
DB_FILE = APP_DIR / "crm.db"
RATE_DIR = APP_DIR / "rate_tables"
RATE_DIR.mkdir(exist_ok=True)


# ============================================================
# CUSTOM CSS - MOBILE FRIENDLY
# ============================================================

st.markdown("""
<style>

.block-container {
    padding-top: 0.7rem;
    padding-bottom: 4rem;
    max-width: 1250px;
}

h1, h2, h3 {
    letter-spacing: -0.3px;
}

div[data-testid="stMetric"] {
    border: 1px solid #e5e5e5;
    border-radius: 14px;
    padding: 10px;
}

.stButton > button {
    border-radius: 12px;
    font-weight: 600;
    min-height: 42px;
}

.stTextInput input,
.stNumberInput input,
.stSelectbox,
.stTextArea textarea {
    border-radius: 10px;
}

div[data-testid="stFileUploader"] {
    border-radius: 14px;
}

.small-text {
    font-size: 0.85rem;
    color: #666;
}

</style>
""", unsafe_allow_html=True)


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

PLAN_LIBRARY = {
    "Care Health": [
        "Ultimate Care",
        "Care Supreme"
    ],
    "Niva Bupa": [
        "ReAssure 2.0",
        "ReAssure 3.0",
        "Health Companion"
    ],
    "HDFC ERGO": [
        "my:Optima Secure"
    ],
    "Star Health": [
        "Star Comprehensive",
        "Family Health Optima"
    ],
    "ICICI Lombard": [
        "Complete Health Insurance"
    ],
    "Other": [
        "Other"
    ]
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
    "Day Care"
]

RATE_COLUMNS = [
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
    "source_date"
]


# ============================================================
# DATABASE
# ============================================================

def get_db():

    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )

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
            score INTEGER DEFAULT 0,
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
        value = value[2:]

    if len(value) > 10:
        value = value[-10:]

    return value


def money(value):

    try:
        return f"₹{float(value):,.0f}"
    except Exception:
        return "—"


def parse_date(value):

    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def opportunity_score(
    renewal_date,
    sum_insured,
    premium,
    room_gap,
    ped_issue,
    age
):

    score = 0

    rd = parse_date(renewal_date)

    if rd:

        days = (rd - date.today()).days

        if 0 <= days <= 30:
            score += 35

        elif 31 <= days <= 60:
            score += 25

        elif 61 <= days <= 90:
            score += 15

        elif days < 0:
            score += 15

    try:

        if float(sum_insured) <= 5:
            score += 20

        elif float(sum_insured) <= 10:
            score += 12

    except Exception:
        pass

    if room_gap:
        score += 15

    if ped_issue:
        score += 10

    try:

        if int(age) >= 45:
            score += 10

    except Exception:
        pass

    if premium and float(premium) > 0:
        score += 5

    return min(score, 100)


# ============================================================
# RATE TABLE ENGINE
# ============================================================

def normalize_rate_table(df):

    df = df.copy()

    df.columns = [
        str(c).strip().lower().replace(" ", "_")
        for c in df.columns
    ]

    aliases = {
        "sum_insured": "sum_insured_lakh",
        "si_lakh": "sum_insured_lakh",
        "premium": "base_premium",
        "members": "member_count",
        "age_from": "age_min",
        "age_to": "age_max"
    }

    for old, new in aliases.items():

        if old in df.columns and new not in df.columns:
            df.rename(
                columns={old: new},
                inplace=True
            )

    for col in RATE_COLUMNS:

        if col not in df.columns:
            df[col] = ""

    numeric_columns = [
        "sum_insured_lakh",
        "age_min",
        "age_max",
        "member_count",
        "base_premium",
        "discount_pct"
    ]

    for col in numeric_columns:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    return df[RATE_COLUMNS]


def load_rate_tables():

    frames = []

    for file in RATE_DIR.glob("*.csv"):

        try:

            df = pd.read_csv(file)

            df = normalize_rate_table(df)

            frames.append(df)

        except Exception:
            pass

    if not frames:

        return pd.DataFrame(
            columns=RATE_COLUMNS
        )

    return pd.concat(
        frames,
        ignore_index=True
    )


def calculate_verified_premium(
    rates,
    insurer,
    plan,
    zone,
    policy_type,
    sum_insured,
    ages
):

    if rates.empty:

        return None, "No verified rate table is loaded."

    df = rates.copy()

    df = df[
        df["insurer"]
        .astype(str)
        .str.casefold()
        ==
        str(insurer).casefold()
    ]

    df = df[
        df["plan"]
        .astype(str)
        .str.casefold()
        ==
        str(plan).casefold()
    ]

    if zone:

        zone_df = df[
            df["zone"]
            .astype(str)
            .str.casefold()
            ==
            str(zone).casefold()
        ]

        if not zone_df.empty:
            df = zone_df

    type_df = df[
        df["policy_type"]
        .astype(str)
        .str.casefold()
        ==
        str(policy_type).casefold()
    ]

    if not type_df.empty:
        df = type_df

    df = df[
        df["sum_insured_lakh"]
        ==
        float(sum_insured)
    ]

    if df.empty:

        return None, (
            "No matching official rate row "
            "was found."
        )

    premiums = []

    for age in ages:

        match = df[
            (df["age_min"] <= age)
            &
            (df["age_max"] >= age)
        ]

        if match.empty:

            return None, (
                f"No verified rate row found "
                f"for age {age}."
            )

        row = match.iloc[0]

        premiums.append(
            float(row["base_premium"])
        )

    # IMPORTANT:
    # Do not invent insurer-specific floater formulas.
    if policy_type == "Family Floater":

        member_rows = df[
            df["member_count"] == len(ages)
        ]

        if not member_rows.empty:

            # If an explicit member-count rate exists,
            # use it.

            oldest = max(ages)

            match = member_rows[
                (member_rows["age_min"] <= oldest)
                &
                (member_rows["age_max"] >= oldest)
            ]

            if not match.empty:

                premiums = [
                    float(match.iloc[0]["base_premium"])
                ]

            else:

                return None, (
                    "Explicit floater rate for "
                    "these members is unavailable."
                )

        else:

            return None, (
                "Floater calculation rule is not "
                "present in the official rate table."
            )

    total_base = sum(premiums)

    discount = 0

    if not df["discount_pct"].dropna().empty:

        discount = float(
            df["discount_pct"]
            .dropna()
            .iloc[0]
        )

    discounted = (
        total_base *
        (1 - discount / 100)
    )

    gst_included = (
        str(df["gst_included"].iloc[0])
        .lower()
        in ["yes", "true", "1"]
    )

    if gst_included:

        gst = 0
        final = discounted

    else:

        gst = discounted * 0.18
        final = discounted + gst

    source = str(
        df["source"].iloc[0]
    )

    source_date = str(
        df["source_date"].iloc[0]
    )

    return {
        "base": discounted,
        "gst": gst,
        "total": final,
        "source": source,
        "source_date": source_date
    }, None


# ============================================================
# OCR
# ============================================================

def extract_ocr(uploaded_file):

    if Image is None:

        return "", (
            "Pillow is not installed."
        )

    if pytesseract is None:

        return "", (
            "pytesseract is not installed."
        )

    try:

        image = Image.open(
            uploaded_file
        )

        text = pytesseract.image_to_string(
            image,
            config="--psm 6"
        )

        return text, None

    except Exception as e:

        return "", str(e)


def parse_policy_text(text):

    result = {}

    patterns = {

        "mobile":
        r"(?:mobile|mob|phone)"
        r"\D{0,10}"
        r"([6-9]\d{9})",

        "sum_insured":
        r"(?:sum insured|sum assured|coverage)"
        r"\D{0,20}"
        r"(?:₹|rs\.?|inr)?"
        r"\s*([\d,]+(?:\.\d+)?)"
        r"\s*(?:lakh|lac|l)?",

        "premium":
        r"(?:premium)"
        r"\D{0,15}"
        r"(?:₹|rs\.?|inr)?"
        r"\s*([\d,]+(?:\.\d+)?)",

        "renewal_date":
        r"(?:renewal|expiry|policy end|valid till)"
        r"\D{0,15}"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
    }

    for key, pattern in patterns.items():

        match = re.search(
            pattern,
            text or "",
            re.IGNORECASE
        )

        if match:
            result[key] = match.group(1)

    return result


# ============================================================
# SIDEBAR
# ============================================================

rates = load_rate_tables()

with st.sidebar:

    st.header("⚙️ Setup")

    st.write(
        f"Verified rate rows: "
        f"**{len(rates)}**"
    )

    uploaded_rate = st.file_uploader(
        "Upload official rate table",
        type=["csv", "xlsx"],
        key="rate_upload"
    )

    if uploaded_rate:

        try:

            if uploaded_rate.name.lower().endswith(
                ".xlsx"
            ):

                raw = pd.read_excel(
                    uploaded_rate
                )

            else:

                raw = pd.read_csv(
                    uploaded_rate
                )

            normalized = normalize_rate_table(
                raw
            )

            filename = (
                RATE_DIR /
                f"{Path(uploaded_rate.name).stem}.csv"
            )

            normalized.to_csv(
                filename,
                index=False
            )

            rates = load_rate_tables()

            st.success(
                f"{len(normalized)} rate rows loaded."
            )

        except Exception as e:

            st.error(
                f"Rate table error: {e}"
            )

    st.divider()

    st.caption(
        "The calculator never invents a "
        "premium when an official rate row "
        "is unavailable."
    )


# ============================================================
# HEADER
# ============================================================

st.title("🛡️ Insurance Sales CRM")

st.caption(
    "CRM • Policy OCR • Portability Opportunity "
    "• Policy Audit • Premium • Comparison "
    "• WhatsApp • Follow-ups"
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
    "📌 Follow-ups"
])


# ============================================================
# DASHBOARD
# ============================================================

with tabs[0]:

    leads = pd.read_sql_query(
        "SELECT * FROM leads ORDER BY updated_at DESC",
        DB
    )

    if leads.empty:

        renewals_30 = 0
        hot = 0

    else:

        leads["renewal_dt"] = pd.to_datetime(
            leads["renewal_date"],
            errors="coerce"
        ).dt.date

        renewals_30 = (
            (leads["renewal_dt"] >= date.today())
            &
            (
                leads["renewal_dt"]
                <= date.today()
                + timedelta(days=30)
            )
        ).sum()

        hot = (
            pd.to_numeric(
                leads["score"],
                errors="coerce"
            )
            .fillna(0)
            >= 70
        ).sum()

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Total Leads",
        len(leads)
    )

    c2.metric(
        "Renewals ≤30 Days",
        int(renewals_30)
    )

    c3.metric(
        "🔥 Hot Leads",
        int(hot)
    )

    c4.metric(
        "Verified Rate Rows",
        len(rates)
    )

    st.subheader(
        "🔥 Sales Opportunity Scanner"
    )

    if leads.empty:import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import re
import urllib.parse
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


# ============================================================
# APP CONFIG
# ============================================================

st.set_page_config(
    page_title="Insurance Sales CRM",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

APP_DIR = Path(__file__).parent
DB_FILE = APP_DIR / "crm.db"
RATE_DIR = APP_DIR / "rate_tables"
RATE_DIR.mkdir(exist_ok=True)


# ============================================================
# CUSTOM CSS - MOBILE FRIENDLY
# ============================================================

st.markdown("""
<style>

.block-container {
    padding-top: 0.7rem;
    padding-bottom: 4rem;
    max-width: 1250px;
}

h1, h2, h3 {
    letter-spacing: -0.3px;
}

div[data-testid="stMetric"] {
    border: 1px solid #e5e5e5;
    border-radius: 14px;
    padding: 10px;
}

.stButton > button {
    border-radius: 12px;
    font-weight: 600;
    min-height: 42px;
}

.stTextInput input,
.stNumberInput input,
.stSelectbox,
.stTextArea textarea {
    border-radius: 10px;
}

div[data-testid="stFileUploader"] {
    border-radius: 14px;
}

.small-text {
    font-size: 0.85rem;
    color: #666;
}

</style>
""", unsafe_allow_html=True)


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

PLAN_LIBRARY = {
    "Care Health": [
        "Ultimate Care",
        "Care Supreme"
    ],
    "Niva Bupa": [
        "ReAssure 2.0",
        "ReAssure 3.0",
        "Health Companion"
    ],
    "HDFC ERGO": [
        "my:Optima Secure"
    ],
    "Star Health": [
        "Star Comprehensive",
        "Family Health Optima"
    ],
    "ICICI Lombard": [
        "Complete Health Insurance"
    ],
    "Other": [
        "Other"
    ]
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
    "Day Care"
]

RATE_COLUMNS = [
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
    "source_date"
]


# ============================================================
# DATABASE
# ============================================================

def get_db():

    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )

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
            score INTEGER DEFAULT 0,
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
        value = value[2:]

    if len(value) > 10:
        value = value[-10:]

    return value


def money(value):

    try:
        return f"₹{float(value):,.0f}"
    except Exception:
        return "—"


def parse_date(value):

    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def opportunity_score(
    renewal_date,
    sum_insured,
    premium,
    room_gap,
    ped_issue,
    age
):

    score = 0

    rd = parse_date(renewal_date)

    if rd:

        days = (rd - date.today()).days

        if 0 <= days <= 30:
            score += 35

        elif 31 <= days <= 60:
            score += 25

        elif 61 <= days <= 90:
            score += 15

        elif days < 0:
            score += 15

    try:

        if float(sum_insured) <= 5:
            score += 20

        elif float(sum_insured) <= 10:
            score += 12

    except Exception:
        pass

    if room_gap:
        score += 15

    if ped_issue:
        score += 10

    try:

        if int(age) >= 45:
            score += 10

    except Exception:
        pass

    if premium and float(premium) > 0:
        score += 5

    return min(score, 100)


# ============================================================
# RATE TABLE ENGINE
# ============================================================

def normalize_rate_table(df):

    df = df.copy()

    df.columns = [
        str(c).strip().lower().replace(" ", "_")
        for c in df.columns
    ]

    aliases = {
        "sum_insured": "sum_insured_lakh",
        "si_lakh": "sum_insured_lakh",
        "premium": "base_premium",
        "members": "member_count",
        "age_from": "age_min",
        "age_to": "age_max"
    }

    for old, new in aliases.items():

        if old in df.columns and new not in df.columns:
            df.rename(
                columns={old: new},
                inplace=True
            )

    for col in RATE_COLUMNS:

        if col not in df.columns:
            df[col] = ""

    numeric_columns = [
        "sum_insured_lakh",
        "age_min",
        "age_max",
        "member_count",
        "base_premium",
        "discount_pct"
    ]

    for col in numeric_columns:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    return df[RATE_COLUMNS]


def load_rate_tables():

    frames = []

    for file in RATE_DIR.glob("*.csv"):

        try:

            df = pd.read_csv(file)

            df = normalize_rate_table(df)

            frames.append(df)

        except Exception:
            pass

    if not frames:

        return pd.DataFrame(
            columns=RATE_COLUMNS
        )

    return pd.concat(
        frames,
        ignore_index=True
    )


def calculate_verified_premium(
    rates,
    insurer,
    plan,
    zone,
    policy_type,
    sum_insured,
    ages
):

    if rates.empty:

        return None, "No verified rate table is loaded."

    df = rates.copy()

    df = df[
        df["insurer"]
        .astype(str)
        .str.casefold()
        ==
        str(insurer).casefold()
    ]

    df = df[
        df["plan"]
        .astype(str)
        .str.casefold()
        ==
        str(plan).casefold()
    ]

    if zone:

        zone_df = df[
            df["zone"]
            .astype(str)
            .str.casefold()
            ==
            str(zone).casefold()
        ]

        if not zone_df.empty:
            df = zone_df

    type_df = df[
        df["policy_type"]
        .astype(str)
        .str.casefold()
        ==
        str(policy_type).casefold()
    ]

    if not type_df.empty:
        df = type_df

    df = df[
        df["sum_insured_lakh"]
        ==
        float(sum_insured)
    ]

    if df.empty:

        return None, (
            "No matching official rate row "
            "was found."
        )

    premiums = []

    for age in ages:

        match = df[
            (df["age_min"] <= age)
            &
            (df["age_max"] >= age)
        ]

        if match.empty:

            return None, (
                f"No verified rate row found "
                f"for age {age}."
            )

        row = match.iloc[0]

        premiums.append(
            float(row["base_premium"])
        )

    # IMPORTANT:
    # Do not invent insurer-specific floater formulas.
    if policy_type == "Family Floater":

        member_rows = df[
            df["member_count"] == len(ages)
        ]

        if not member_rows.empty:

            # If an explicit member-count rate exists,
            # use it.

            oldest = max(ages)

            match = member_rows[
                (member_rows["age_min"] <= oldest)
                &
                (member_rows["age_max"] >= oldest)
            ]

            if not match.empty:

                premiums = [
                    float(match.iloc[0]["base_premium"])
                ]

            else:

                return None, (
                    "Explicit floater rate for "
                    "these members is unavailable."
                )

        else:

            return None, (
                "Floater calculation rule is not "
                "present in the official rate table."
            )

    total_base = sum(premiums)

    discount = 0

    if not df["discount_pct"].dropna().empty:

        discount = float(
            df["discount_pct"]
            .dropna()
            .iloc[0]
        )

    discounted = (
        total_base *
        (1 - discount / 100)
    )

    gst_included = (
        str(df["gst_included"].iloc[0])
        .lower()
        in ["yes", "true", "1"]
    )

    if gst_included:

        gst = 0
        final = discounted

    else:

        gst = discounted * 0.18
        final = discounted + gst

    source = str(
        df["source"].iloc[0]
    )

    source_date = str(
        df["source_date"].iloc[0]
    )

    return {
        "base": discounted,
        "gst": gst,
        "total": final,
        "source": source,
        "source_date": source_date
    }, None


# ============================================================
# OCR
# ============================================================

def extract_ocr(uploaded_file):

    if Image is None:

        return "", (
            "Pillow is not installed."
        )

    if pytesseract is None:

        return "", (
            "pytesseract is not installed."
        )

    try:

        image = Image.open(
            uploaded_file
        )

        text = pytesseract.image_to_string(
            image,
            config="--psm 6"
        )

        return text, None

    except Exception as e:

        return "", str(e)


def parse_policy_text(text):

    result = {}

    patterns = {

        "mobile":
        r"(?:mobile|mob|phone)"
        r"\D{0,10}"
        r"([6-9]\d{9})",

        "sum_insured":
        r"(?:sum insured|sum assured|coverage)"
        r"\D{0,20}"
        r"(?:₹|rs\.?|inr)?"
        r"\s*([\d,]+(?:\.\d+)?)"
        r"\s*(?:lakh|lac|l)?",

        "premium":
        r"(?:premium)"
        r"\D{0,15}"
        r"(?:₹|rs\.?|inr)?"
        r"\s*([\d,]+(?:\.\d+)?)",

        "renewal_date":
        r"(?:renewal|expiry|policy end|valid till)"
        r"\D{0,15}"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
    }

    for key, pattern in patterns.items():

        match = re.search(
            pattern,
            text or "",
            re.IGNORECASE
        )

        if match:
            result[key] = match.group(1)

    return result


# ============================================================
# SIDEBAR
# ============================================================

rates = load_rate_tables()

with st.sidebar:

    st.header("⚙️ Setup")

    st.write(
        f"Verified rate rows: "
        f"**{len(rates)}**"
    )

    uploaded_rate = st.file_uploader(
        "Upload official rate table",
        type=["csv", "xlsx"],
        key="rate_upload"
    )

    if uploaded_rate:

        try:

            if uploaded_rate.name.lower().endswith(
                ".xlsx"
            ):

                raw = pd.read_excel(
                    uploaded_rate
                )

            else:

                raw = pd.read_csv(
                    uploaded_rate
                )

            normalized = normalize_rate_table(
                raw
            )

            filename = (
                RATE_DIR /
                f"{Path(uploaded_rate.name).stem}.csv"
            )

            normalized.to_csv(
                filename,
                index=False
            )

            rates = load_rate_tables()

            st.success(
                f"{len(normalized)} rate rows loaded."
            )

        except Exception as e:

            st.error(
                f"Rate table error: {e}"
            )

    st.divider()

    st.caption(
        "The calculator never invents a "
        "premium when an official rate row "
        "is unavailable."
    )


# ============================================================
# HEADER
# ============================================================

st.title("🛡️ Insurance Sales CRM")

st.caption(
    "CRM • Policy OCR • Portability Opportunity "
    "• Policy Audit • Premium • Comparison "
    "• WhatsApp • Follow-ups"
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
    "📌 Follow-ups"
])


# ============================================================
# DASHBOARD
# ============================================================

with tabs[0]:

    leads = pd.read_sql_query(
        "SELECT * FROM leads ORDER BY updated_at DESC",
        DB
    )

    if leads.empty:

        renewals_30 = 0
        hot = 0

    else:

        leads["renewal_dt"] = pd.to_datetime(
            leads["renewal_date"],
            errors="coerce"
        ).dt.date

        renewals_30 = (
            (leads["renewal_dt"] >= date.today())
            &
            (
                leads["renewal_dt"]
                <= date.today()
                + timedelta(days=30)
            )
        ).sum()

        hot = (
            pd.to_numeric(
                leads["score"],
                errors="coerce"
            )
            .fillna(0)
            >= 70
        ).sum()

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Total Leads",
        len(leads)
    )

    c2.metric(
        "Renewals ≤30 Days",
        int(renewals_30)
    )

    c3.metric(
        "🔥 Hot Leads",
        int(hot)
    )

    c4.metric(
        "Verified Rate Rows",
        len(rates)
    )

    st.subheader(
        "🔥 Sales Opportunity Scanner"
    )

    if leads.empty:
