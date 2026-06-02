import streamlit as st
import pandas as pd
import sys
import os
from datetime import date, timedelta, datetime

sys.path.insert(0, os.path.dirname(__file__))

from logic.spaces     import (
    list_available_dates, load_snapshot, load_date_range,
    authenticate, get_all_customers,
)
from logic.calculator import calculate_costs
from logic.auth       import make_token, verify_token

APP_VERSION = "v1.0"

st.set_page_config(
    page_title = "ShipHero Storage Cost Analytics",
    page_icon  = os.path.join(os.path.dirname(__file__), "assets", "VP Warehouse Icon TP.png"),
    layout     = "wide",
    initial_sidebar_state = "expanded",
)

st.markdown("""
    <style>
    [data-testid="stImage"] button { display: none !important; }
    [data-testid="stImageToolbar"] { display: none !important; }
    [data-testid="stSidebarNav"] { display: none !important; }
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    [data-testid="stMetricValue"] { font-size: 2rem !important; }
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
if "report_data" not in st.session_state:
    st.session_state.report_data = None
if "last_activity" not in st.session_state:
    st.session_state.last_activity = datetime.utcnow()

# Auto-logout after 30 minutes of inactivity
if st.session_state.authenticated:
    inactive_minutes = (datetime.utcnow() - st.session_state.last_activity).total_seconds() / 60
    if inactive_minutes > 30:
        st.session_state.authenticated = False
        st.session_state.user          = None
        st.session_state.report_data   = None
        st.query_params.clear()
        st.rerun()
    else:
        st.session_state.last_activity = datetime.utcnow()

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
            import base64
            with open(vp_logo, "rb") as img_file:
                b64 = base64.b64encode(img_file.read()).decode()
            st.markdown(
                f"<div style='text-align:center;'><img src='data:image/png;base64,{b64}' width='210'/></div>",
                unsafe_allow_html=True,
            )

        st.markdown(
            "<h2 style='text-align:center; margin-top:12px; margin-bottom:24px;'>ShipHero Storage Cost Analytics</h2>",
            unsafe_allow_html=True,
        )

        # Fix browser autofill not triggering Streamlit input events
        st.markdown("""
            <script>
            window.addEventListener('load', function() {
                setTimeout(function() {
                    const inputs = window.parent.document.querySelectorAll('input');
                    inputs.forEach(function(input) {
                        if (input.value) {
                            input.dispatchEvent(new Event('input', { bubbles: true }));
                            input.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    });
                }, 500);
            });
            </script>
        """, unsafe_allow_html=True)

        username = st.text_input("Email Address", autocomplete="email")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        st.caption("💡 Using a saved password? Press **Tab** after autofill, then click Log In.")

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
                st.error("Incorrect email address or password.")

        st.markdown(
            f"<p style='text-align:center; color:#666; font-size:11px; margin-top:40px;'>{APP_VERSION} | Vertical Passage Operations</p>",
            unsafe_allow_html=True,
        )
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
        st.image(logo_path, width=180)

    st.markdown("### Storage Analytics")

    if len(allowed_customers) == 1:
        st.caption(f"{allowed_customers[0]} · VP Fulfillment")
    elif allowed_customers:
        st.caption(f"{len(allowed_customers)} customers · VP Fulfillment")

    st.markdown("---")

    # ── Date Range ────────────────────────────────────────────────────────────
    st.markdown("**Date Range**")
    st.markdown("**View**")

    date_mode = st.radio(
        "date_mode",
        options          = ["Today", "Select Date Range"],
        label_visibility = "collapsed",
    )

    if available_dates:
        min_date = date.fromisoformat(available_dates[0])
        max_date = date.fromisoformat(available_dates[-1])
    else:
        min_date = date.today()
        max_date = date.today()

    if date_mode == "Today":
        start_date = max_date
        end_date   = max_date
    else:
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

    # ── Filters ───────────────────────────────────────────────────────────────
    st.markdown("**Filters**")

    if not allowed_customers:
        st.warning("No customers assigned to your account.")
        st.stop()

    with st.expander("Warehouse", expanded=True):
        warehouses          = ["Primary", "VP North"]
        selected_warehouses = []
        for wh in warehouses:
            if st.checkbox(wh, value=True, key=f"wh_{wh}"):
                selected_warehouses.append(wh)

    if len(allowed_customers) > 1:
        with st.expander("Customer", expanded=True):
            selected_customers = []
            for customer in allowed_customers:
                if st.checkbox(customer, key=f"cust_{customer}"):
                    selected_customers.append(customer)
    else:
        selected_customers = allowed_customers

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
        all_tags = get_tags_for_customers(latest_date, tuple(sorted(selected_customers)))
        if all_tags:
            st.markdown("**Product Tag**")
            selected_tags = st.multiselect(
                "tag_filter",
                options          = all_tags,
                default          = [],
                placeholder      = "All tags",
                label_visibility = "collapsed",
            )
        else:
            selected_tags = []
    else:
        selected_tags = []

    st.markdown("---")

    generate = st.button("Generate Report", type="primary", use_container_width=True)

    st.markdown("---")

    if is_admin:
        token     = make_token(st.session_state.username)
        admin_url = f"/Admin?u={st.session_state.username}&token={token}"
        st.markdown(f"🔒 [Admin Panel]({admin_url})")

    if st.button("Sign Out", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user          = None
        st.query_params.clear()
        st.rerun()

    st.markdown(
        f"<p style='text-align:center; color:#444; font-size:11px; margin-top:20px;'>{APP_VERSION}</p>",
        unsafe_allow_html=True,
    )

# ── Main content ──────────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='text-align:center; margin-bottom:8px;'>ShipHero Storage Cost Analytics</h1>",
    unsafe_allow_html=True,
)
st.markdown("---")

if not available_dates:
    st.warning("No inventory snapshots found yet. The daily pipeline runs at 6am.")
    st.stop()

# ── Show persisted report if not regenerating ─────────────────────────────────
if not generate and st.session_state.report_data:
    rd         = st.session_state.report_data
    df         = rd["df"]
    total_cost = rd["total_cost"]
    avg_daily  = rd["avg_daily"]
    total_locs = rd["total_locs"]
    total_skus = rd["total_skus"]
    snapshot_date = rd["snapshot_date"]
    filtered_rows = rd["filtered_rows"]
    num_days      = rd["num_days"]
    start_date    = rd["start_date"]
    end_date      = rd["end_date"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Cost (Date Range)", f"${total_cost:,.2f}")
    m2.metric("Avg Daily Cost",          f"${avg_daily:,.2f}")
    m3.metric("Occupied Locations",      f"{total_locs:,}")
    m4.metric("In Stock SKUs",           f"{total_skus:,}")

    st.markdown("---")
    st.markdown("### Cost By Location Type")
    loc_summary = (
        df[df["Location"] != "No Active Bin"]
        .groupby("Storage Type")
        .agg(
            Occupied_Locations = ("Location", "count"),
            Unique_SKUs        = ("SKU", "nunique"),
            Total_Daily_Cost   = ("Total Cost", "sum"),
        )
        .reset_index()
        .sort_values("Total_Daily_Cost", ascending=False)
        .rename(columns={
            "Storage Type":       "Location Type",
            "Occupied_Locations": "Occupied Locations",
            "Unique_SKUs":        "Unique SKUs",
            "Total_Daily_Cost":   "Total Daily Cost",
        })
    )
    loc_summary["Total Daily Cost"] = loc_summary["Total Daily Cost"].apply(lambda x: f"${x:,.2f}")
    st.dataframe(loc_summary, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Product Detail")
    search = st.text_input("Search By SKU Or Product Name", placeholder="e.g. UNI-1234 or plush", key="search_persist")
    display_df = df.copy()
    display_df["Daily Rate"] = display_df["Daily Rate"].apply(lambda x: f"${x:.4f}")
    display_df["Total Cost"] = display_df["Total Cost"].apply(lambda x: f"${x:,.2f}")
    if search.strip():
        mask = (
            display_df["SKU"].str.contains(search.strip(), case=False, na=False) |
            display_df["Product Name"].str.contains(search.strip(), case=False, na=False)
        )
        display_df = display_df[mask]
        st.caption(f"{len(display_df):,} results for '{search.strip()}'")
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    csv = df.to_csv(index=False)
    st.download_button(
        label     = "📥 Download CSV",
        data      = csv,
        file_name = f"storage_report_{start_date}_to_{end_date}.csv",
        mime      = "text/csv",
    )
    st.markdown("---")
    st.markdown(
        f"<p style='text-align:center; color:#444; font-size:11px;'>"
        f"Snapshot: {snapshot_date} · {len(filtered_rows):,} rows · {num_days} day(s) · {APP_VERSION} | Vertical Passage Operations"
        f"</p>",
        unsafe_allow_html=True,
    )

# ── Generate Report ───────────────────────────────────────────────────────────
if generate:

    if not selected_customers:
        st.warning("Please select at least one customer.")
        st.stop()

    num_days = max((end_date - start_date).days + 1, 1)
    cust_set = set(selected_customers)
    tag_set  = set(selected_tags)
    wh_set   = set(selected_warehouses)

    with st.spinner("Loading inventory snapshot..."):
        snapshots = load_date_range(str(start_date), str(end_date))

    if not snapshots:
        st.error(f"No snapshots available between {start_date} and {end_date}.")
        st.stop()

    snapshot_date = max(snapshots.keys())
    rows          = snapshots[snapshot_date]

    filtered_rows = [r for r in rows if r.get("customer") in cust_set]

    if selected_warehouses:
        filtered_rows = [
            r for r in filtered_rows
            if any(wh.lower() in (r.get("warehouse") or "").lower() for wh in wh_set)
        ]

    if tag_set:
        filtered_rows = [
            r for r in filtered_rows
            if tag_set.intersection(set(r.get("tags") or []))
        ]

    if not filtered_rows:
        st.warning("No inventory rows match the selected filters.")
        st.stop()

    df         = calculate_costs(filtered_rows, num_days)
    total_cost = df["Total Cost"].sum()
    avg_daily  = total_cost / num_days if num_days > 0 else 0
    total_locs = (df["Location"] != "No Active Bin").sum()
    total_skus = df["SKU"].nunique()

    st.session_state.report_data = {
        "df":            df,
        "total_cost":    total_cost,
        "avg_daily":     avg_daily,
        "total_locs":    total_locs,
        "total_skus":    total_skus,
        "snapshot_date": snapshot_date,
        "filtered_rows": filtered_rows,
        "num_days":      num_days,
        "start_date":    start_date,
        "end_date":      end_date,
    }

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Cost (Date Range)", f"${total_cost:,.2f}")
    m2.metric("Avg Daily Cost",          f"${avg_daily:,.2f}")
    m3.metric("Occupied Locations",      f"{total_locs:,}")
    m4.metric("In Stock SKUs",           f"{total_skus:,}")

    st.markdown("---")

    st.markdown("### Cost By Location Type")

    loc_summary = (
        df[df["Location"] != "No Active Bin"]
        .groupby("Storage Type")
        .agg(
            Occupied_Locations = ("Location", "count"),
            Unique_SKUs        = ("SKU", "nunique"),
            Total_Daily_Cost   = ("Total Cost", "sum"),
        )
        .reset_index()
        .sort_values("Total_Daily_Cost", ascending=False)
        .rename(columns={
            "Storage Type":       "Location Type",
            "Occupied_Locations": "Occupied Locations",
            "Unique_SKUs":        "Unique SKUs",
            "Total_Daily_Cost":   "Total Daily Cost",
        })
    )
    loc_summary["Total Daily Cost"] = loc_summary["Total Daily Cost"].apply(lambda x: f"${x:,.2f}")
    st.dataframe(loc_summary, use_container_width=True, hide_index=True)

    st.markdown("---")

    st.markdown("### Product Detail")

    search = st.text_input(
        "Search By SKU Or Product Name",
        placeholder = "e.g. UNI-1234 or plush",
    )

    display_df = df.copy()
    display_df["Daily Rate"] = display_df["Daily Rate"].apply(lambda x: f"${x:.4f}")
    display_df["Total Cost"] = display_df["Total Cost"].apply(lambda x: f"${x:,.2f}")

    if search.strip():
        mask = (
            display_df["SKU"].str.contains(search.strip(), case=False, na=False) |
            display_df["Product Name"].str.contains(search.strip(), case=False, na=False)
        )
        display_df = display_df[mask]
        st.caption(f"{len(display_df):,} results for '{search.strip()}'")

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    csv = df.to_csv(index=False)
    st.download_button(
        label     = "📥 Download CSV",
        data      = csv,
        file_name = f"storage_report_{start_date}_to_{end_date}.csv",
        mime      = "text/csv",
    )

    st.markdown("---")
    st.markdown(
        f"<p style='text-align:center; color:#444; font-size:11px;'>"
        f"Snapshot: {snapshot_date} · {len(filtered_rows):,} rows · {num_days} day(s) · {APP_VERSION}"
        f"</p>",
        unsafe_allow_html=True,
    )
