# pages/table_view.py

import re

import pandas as pd
import streamlit as st
from supabase import create_client, Client

st.set_page_config(page_title="Order Book Table", layout="wide")

REQUIRED_COLS = [
    "WO",
    "Quote",
    "PO Number",
    "Status",
    "Customer Name",
    "Model Description",
    "Scheduled Date",
    "Price",
]

SUPABASE_TABLE = "order_book"


# ---------------- Supabase ----------------

@st.cache_resource
def get_supabase() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def save_data(df: pd.DataFrame, last_uploaded_name: str):
    """Replace all rows in Supabase with the current DataFrame."""
    supabase = get_supabase()
    supabase.table(SUPABASE_TABLE).delete().neq("wo", "___never___").execute()

    if df.empty:
        return

    rows = []
    for _, r in df.iterrows():
        d = r.get("Scheduled Date", pd.NaT)
        price = r.get("Price", None)
        rows.append({
            "wo":                str(r.get("WO", "")).strip(),
            "quote":             str(r.get("Quote", "")),
            "po_number":         str(r.get("PO Number", "")),
            "status":            str(r.get("Status", "")),
            "customer_name":     str(r.get("Customer Name", "")),
            "model_description": str(r.get("Model Description", "")),
            "scheduled_date":    d.isoformat() if not pd.isna(d) else None,
            "price":             float(price) if price is not None and not pd.isna(price) else None,
            "uploaded_name":     last_uploaded_name or "",
        })

    for i in range(0, len(rows), 500):
        supabase.table(SUPABASE_TABLE).insert(rows[i : i + 500]).execute()


def load_data() -> tuple[pd.DataFrame, str | None]:
    """Fetch all rows from Supabase."""
    supabase = get_supabase()
    response = supabase.table(SUPABASE_TABLE).select("*").execute()
    rows = response.data

    if not rows:
        return pd.DataFrame(columns=REQUIRED_COLS), None

    df = pd.DataFrame(rows)
    last_name = df["uploaded_name"].iloc[0] if "uploaded_name" in df.columns else None

    df = df.rename(columns={
        "wo": "WO", "quote": "Quote", "po_number": "PO Number",
        "status": "Status", "customer_name": "Customer Name",
        "model_description": "Model Description",
        "scheduled_date": "Scheduled Date", "price": "Price",
    })
    df = df.drop(columns=[c for c in ["uploaded_name", "id"] if c in df.columns], errors="ignore")

    df["Scheduled Date"] = df["Scheduled Date"].apply(parse_date)
    df["Price"] = df["Price"].apply(lambda x: float(x) if x is not None else pd.NA)
    for c in ["Quote", "PO Number", "Status", "Customer Name", "Model Description"]:
        df[c] = df[c].fillna("").astype(str)

    present = [c for c in REQUIRED_COLS if c in df.columns]
    return df[present], last_name


# ---------------- Helpers ----------------

def parse_date(x):
    if x is None or str(x).strip() in ("", "None", "NaT"):
        return pd.NaT
    try:
        if pd.isna(x):
            return pd.NaT
    except Exception:
        pass
    return pd.to_datetime(x, errors="coerce").date()


def parse_price(x):
    if x is None or str(x).strip() == "":
        return pd.NA
    s = str(x).replace("$", "").replace(",", "")
    try:
        return float(s)
    except Exception:
        return pd.NA


def normalize_df(df):
    df = df.copy()
    df = df[REQUIRED_COLS]
    df["WO"] = df["WO"].astype(str).str.strip()
    df["Scheduled Date"] = df["Scheduled Date"].apply(parse_date)
    df["Price"] = df["Price"].apply(parse_price)
    for c in ["Quote", "PO Number", "Status", "Customer Name", "Model Description"]:
        df[c] = df[c].fillna("").astype(str)
    return df


# ---------------- Session Init ----------------
if "df" not in st.session_state:
    with st.spinner("Loading saved data..."):
        df_loaded, last_name = load_data()
    st.session_state.df = df_loaded
    st.session_state.last_uploaded_name = last_name
if "last_uploaded_name" not in st.session_state:
    st.session_state.last_uploaded_name = None
if "df_version" not in st.session_state:
    st.session_state.df_version = 0
if "has_unsaved_changes" not in st.session_state:
    st.session_state.has_unsaved_changes = False


# ---------------- Table Page ----------------
st.title("🧾 Table View")
st.caption("Edit rows here, then click **Apply Changes**. Calendar updates automatically.")

if st.session_state.last_uploaded_name:
    st.info(f"📂 Currently loaded: **{st.session_state.last_uploaded_name}**")
else:
    st.warning("No data loaded. Upload a file from the Calendar page.")

if st.session_state.has_unsaved_changes:
    st.warning("⚠️ You have unsaved changes. Save them below before they're lost.")

with st.form("table_form"):
    edited = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Scheduled Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "Price": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
    apply = st.form_submit_button("✅ Apply Changes")

if apply:
    df_new = normalize_df(edited)
    mask = (
        df_new["WO"].str.strip().ne("")
        | df_new["Customer Name"].str.strip().ne("")
        | df_new["Model Description"].str.strip().ne("")
    )
    df_new = df_new.loc[mask]

    st.session_state.df = df_new
    st.session_state.df_version += 1
    st.session_state.has_unsaved_changes = True
    st.success("Changes applied. Click 'Update Changes' below to save to database.")
    st.rerun()

# ---------------- Update Changes (Password Protected) ----------------
st.divider()
st.subheader("🔐 Save to Database")

with st.expander("Password Protected Update", expanded=st.session_state.has_unsaved_changes):
    st.write("Enter the password to save your changes to the Supabase database.")
    
    col_a, col_b = st.columns([2, 1])
    with col_a:
        password = st.text_input("Password", type="password", key="table_update_password")
    with col_b:
        update_btn = st.button("✅ Update Changes", type="primary", use_container_width=True)
    
    if update_btn:
        correct_password = st.secrets.get("UPDATE_PASSWORD", "admin123")
        
        if password == correct_password:
            with st.spinner("Saving to database..."):
                save_data(st.session_state.df, st.session_state.last_uploaded_name)
            st.session_state.has_unsaved_changes = False
            st.success("✅ Changes saved to database successfully!")
            st.rerun()
        else:
            st.error("❌ Incorrect password. Changes not saved.")
