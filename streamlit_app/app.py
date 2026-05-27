import streamlit as st
import pandas as pd
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from logic.spaces     import (
    list_available_dates, load_snapshot, load_date_range,
    authenticate, get_all_customers,
)
from logic.calculator import calculate_costs
from logic.auth       import make_token, verify_token

st.set_page_config(
    page_title = "Warehouse Storage Cost Report",
    page_icon  = os.path.join(os.path.dirname(__file__), "assets", "VP Warehouse Icon TP.png"),
    layout     = "wide",
    initial_sidebar_state = "collapsed",
)

st.markdown("""
    <style>
    [data-testid="stImage"] button { display: none !important; }
    [data-testid="stImageToolbar"] { display: none !important; }
    [data-testid="stSidebarNav"] { display: none !important; }
    </style>
""", unsafe_allow_html=True)

# ── Session restore from query params ─────────────────────────────────────────
params = st.query_params
if not st.session_state.get("authenticated"):
    token    = params.get("token", "")
    username = params.get("u", "")
    if token and username and verify_token(username, token):
        from logic.spaces import load_users
        users = load_users()
        user  = users.get(username)
        if user:
            st.session_state.authenticated = True
            st.session_state.user          = user
            st.session_state.username      = username

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user" not in st.session_state:
    st.session_state.user = None

# ── Login screen ──────────────────────────────────────────────────────────────
if not st.session_state.authenticated:
    st.markdown("""
        <style>
        [data-testid="stSidebar"] { display: none !important; }
        </style>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        vp_logo = os.path.join(os.path.dirname(__file__), "assets",
                               "VP Logo Horizontal Transparent White Lettering.png")
        if os.path.exists(vp_logo):
            st.image(vp_logo, width=210)

        st.markdown(
            "<h2 style='text-align:center; margin-top:12px; margin-bottom:24px;'>Warehouse Storage Cost Report</h2>",
            unsafe_allow_html=True,
        )

        username = st.text_input("Email Address")
        password = st.text_input("Password", type="password")

        if st.button("Log In", type="primary", use_container_width=True):
            user = authenticate(username, password)
            if user:
                uname = username.strip().lower()
                token = make_token(uname)
                st.session_state.authenticated = True
                st.session_state.user          = user
                st.session_state.username      = uname
                st.query_params["u"]     = uname
                st.query_params["token"] = token
                st.rerun()
            else:
                st.error("Incorrect username or password.")
    st.stop()

# ── Logged in ─────────────────────────────────────────────────────────────────
user     = st.session_state.user
is_admin = user.get("is_admin", False)

available_dates = list_available_dates()
latest_date     = available_dates[-1] if available_dates else str(date.today())
all_customers   = get_all_customers(latest_date) if available_dates else []

if is_admin:
    allowed_customers = all_customers
else:
    user_customers    = user.get("customers") or []
    allowed_customers = [c for c in all_customers if c in user_customers]

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    logo_path = os.path.join(os.path.dirname(__file__), "assets",
                             "VP Logo Horizontal Transparent White Lettering.png")
    if os.path.exists(logo_path):
        st.image(logo_path, width=200)

    st.markdown("---")

    if not allowed_customers:
        st.warning("No customers assigned to your account.")
        st.stop()

    # Customer filter — checkboxes
    st.markdown("**Filter by Customer**")
    selected_customers = []
    for customer in allowed_customers:
        if st.checkbox(customer, key=f"cust_{customer}"):
            selected_customers.append(customer)

    # Tag filter
    @st.cache_data(ttl=3600)
    def get_tags_for_customers(snapshot_date: str, customers: tuple) -> list[str]:
        rows     = load_snapshot(snapshot_date)
        cust_set = set(customers)
        tags     = set()
        for row in rows:
            if row.get("customer") in cust_set:
                for t in (row.get("tags") or []):
                    if t:
                        tags.add(t)
        return sorted(tags)

    if selected_customers:
        st.markdown("---")
        all_tags = get_tags_for_customers(latest_date, tuple(sorted(selected_customers)))
        selected_tags = st.multiselect(
            "Filter by Product Tag (optional)",
            options     = all_tags,
            default     = [],
            placeholder = "Select tag(s)...",
            help        = "Leave blank to show all products",
        )
    else:
        selected_tags = []

    st.markdown("---")

    if available_dates:
        min_date = date.fromisoformat(available_dates[0])
        max_date = date.fromisoformat(available_dates[-1])
    else:
        min_date = date.today()
        max_date = date.today()

    start_date = st.date_input(
        "Start Date",
        value     = min_date,
        min_value = min_date,
        max_value = max_date,
    )
    end_date = st.date_input(
        "End Date",
        value     = max_date,
        min_value = min_date,
        max_value = max_date,
    )

    st.markdown("---")

    generate = st.button("🚀 Generate Report", type="primary", use_container_width=True)

    st.markdown("---")

    if is_admin:
        token = make_token(st.session_state.username)
        admin_url = f"/Admin?u={st.session_state.username}&token={token}"
        st.markdown(f"🔒 [Admin Panel]({admin_url})")

    if st.button("Log Out", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user          = None
        st.query_params.clear()
        st.rerun()

# ── Header ────────────────────────────────────────────────────────────────────
_, col_center, _ = st.columns([1, 2, 1])
with col_center:
    vp_logo = os.path.join(os.path.dirname(__file__), "assets",
                           "VP Logo Horizontal Transparent White Lettering.png")
    if os.path.exists(vp_logo):
        st.image(vp_logo, width=300)
    st.markdown(
        "<h1 style='text-align:center; margin-top:8px; margin-bottom:4px;'>Warehouse Storage Cost Report</h1>",
        unsafe_allow_html=True,
    )

st.markdown("---")

if not available_dates:
    st.warning(
        "No inventory snapshots found yet. "
        "The daily pipeline runs at 6am — check back after the first run."
    )
    st.stop()

# ── Generate Report ───────────────────────────────────────────────────────────
if generate:

    if not selected_customers:
        st.warning("Please select at least one customer.")
        st.stop()

    num_days = max((end_date - start_date).days, 1)
    cust_set = set(selected_customers)
    tag_set  = set(selected_tags)

    with st.spinner("Loading inventory snapshot..."):
        snapshots = load_date_range(str(start_date), str(end_date))

    if not snapshots:
        st.error(
            f"No snapshots available between {start_date} and {end_date}. "
            "Try widening your date range."
        )
        st.stop()

    snapshot_date = max(snapshots.keys())
    rows          = snapshots[snapshot_date]

    filtered_rows = [r for r in rows if r.get("customer") in cust_set]

    if tag_set:
        filtered_rows = [
            r for r in filtered_rows
            if tag_set.intersection(set(r.get("tags") or []))
        ]

    if not filtered_rows:
        st.warning("No inventory rows match the selected filters.")
        st.stop()

    st.caption(
        f"Snapshot date: **{snapshot_date}** · "
        f"{len(filtered_rows):,} rows matched · "
        f"{num_days} day(s)"
    )

    df         = calculate_costs(filtered_rows, num_days)
    total_cost = df["Total Cost"].sum()

    m1, m2, m3 = st.columns(3)
    m1.metric("💰 Total Period Cost", f"${total_cost:,.2f}")
    m2.metric("📦 Total SKUs",        f"{df['SKU'].nunique():,}")
    m3.metric("📍 Total Locations",   f"{(df['Location'] != 'No Active Bin').sum():,}")

    st.markdown("---")

    display_df = df.copy()
    display_df["Daily Rate"] = display_df["Daily Rate"].apply(lambda x: f"${x:.4f}")
    display_df["Total Cost"] = display_df["Total Cost"].apply(lambda x: f"${x:,.2f}")

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    csv = df.to_csv(index=False)
    st.download_button(
        label     = "📥 Download CSV",
        data      = csv,
        file_name = f"storage_report_{start_date}_to_{end_date}.csv",
        mime      = "text/csv",
    )
