import streamlit as st
import pandas as pd
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from logic.spaces     import list_available_dates, load_snapshot, load_date_range
from logic.calculator import calculate_costs

st.set_page_config(
    page_title = "Warehouse Storage Cost Report",
    layout     = "wide",
    initial_sidebar_state = "expanded",
)

@st.cache_data
def load_loc_map():
    csv_path = os.path.join(os.path.dirname(__file__), "data",
                        "ShipHero - Location Names and Info.csv")
    df = pd.read_csv(csv_path)
    return dict(zip(df["Location"], df["Type"]))

loc_type_map = load_loc_map()

with st.sidebar:
    logo_path = os.path.join(os.path.dirname(__file__), "assets", "vertical_passage_logo.png")
    if os.path.exists(logo_path):
        st.image(logo_path, use_column_width=True)

    st.markdown("---")

    available_dates = list_available_dates()
    if available_dates:
        min_date = date.fromisoformat(available_dates[0])
        max_date = date.fromisoformat(available_dates[-1])
    else:
        min_date = max_date = date.today()

    start_date = st.date_input(
        "Start Date",
        value     = max_date - timedelta(days=30),
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
    st.caption("🔒 [Admin Panel](/Admin)")

_, col_center, _ = st.columns([1, 2, 1])
with col_center:
    st.markdown(
        "<h1 style='text-align:center; margin-bottom:0;'>Warehouse Storage Cost Report</h1>",
        unsafe_allow_html=True,
    )
    logo_sc = os.path.join(os.path.dirname(__file__), "assets", "snow_commerce_logo.png")
    if os.path.exists(logo_sc):
        st.image(logo_sc, use_column_width=True)

st.markdown("---")

if not available_dates:
    st.warning(
        "No inventory snapshots found yet. "
        "The nightly pull runs at 2am — check back after the first run."
    )
    st.stop()

@st.cache_data(ttl=3600)
def get_all_tags(snapshot_date: str) -> list[str]:
    rows = load_snapshot(snapshot_date)
    tags = set()
    for row in rows:
        for t in (row.get("tags") or []):
            if t:
                tags.add(t)
    return sorted(tags)

latest_date = available_dates[-1]
all_tags    = get_all_tags(latest_date)

selected_tags = st.multiselect(
    "Filter by Client / Brand Tag",
    options = all_tags,
    default = all_tags[:3] if all_tags else [],
    help    = "Show only products that have at least one of the selected tags",
)

if st.button("🚀 Generate Report", type="primary"):

    if not selected_tags:
        st.warning("Please select at least one tag.")
        st.stop()

    num_days = max((end_date - start_date).days, 1)
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

    filtered_rows = [
        r for r in rows
        if tag_set.intersection(set(r.get("tags") or []))
    ]

    if not filtered_rows:
        st.warning("No inventory rows match the selected tags in this date range.")
        st.stop()

    st.caption(
        f"Snapshot date: **{snapshot_date}** · "
        f"{len(filtered_rows):,} rows matched · "
        f"{num_days} day(s)"
    )

    df         = calculate_costs(filtered_rows, num_days, loc_type_map)
    total_cost = df["Total Cost"].sum()

    m1, m2, m3 = st.columns(3)
    m1.metric("💰 Total Period Cost",  f"${total_cost:,.2f}")
    m2.metric("📦 Total SKUs",         f"{df['SKU'].nunique():,}")
    m3.metric("📍 Total Locations",    f"{(df['Location'] != 'No Active Bin').sum():,}")

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