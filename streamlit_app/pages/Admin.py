import streamlit as st
import pandas as pd
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from logic.spaces import load_tracked_tags, save_tracked_tags

st.set_page_config(
    page_title = "Admin — Tag Manager",
    layout     = "centered",
    initial_sidebar_state = "collapsed",
)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("## 🔒 Admin Login")
    pwd = st.text_input("Password", type="password")
    if st.button("Log In"):
        if pwd == ADMIN_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

st.markdown("## ⚙️ Tag Manager")
st.caption(
    "These are the product tags the nightly ShipHero pull searches for. "
    "Any product that has **at least one** of these tags will be included "
    "in the nightly snapshot."
)

if st.button("🔓 Log Out", type="secondary"):
    st.session_state.authenticated = False
    st.rerun()

st.markdown("---")

config       = load_tracked_tags()
current_tags = config.get("tags", [])
last_mod     = config.get("last_modified")
last_by      = config.get("last_modified_by")

if last_mod:
    try:
        ts = datetime.fromisoformat(last_mod).strftime("%B %d, %Y at %I:%M %p UTC")
    except Exception:
        ts = last_mod
    st.caption(f"Last updated: **{ts}** by `{last_by}`")

st.markdown(f"### Current Tags ({len(current_tags)})")

if current_tags:
    for tag in sorted(current_tags):
        col_tag, col_btn = st.columns([5, 1])
        col_tag.markdown(f"🏷️ &nbsp; `{tag}`", unsafe_allow_html=True)
        if col_btn.button("Remove", key=f"remove_{tag}"):
            updated = [t for t in current_tags if t != tag]
            if save_tracked_tags(updated, modified_by="admin"):
                st.success(f"Removed **{tag}**")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Failed to save — check Spaces credentials.")
else:
    st.info("No tags configured yet.")

st.markdown("---")

st.markdown("### Add a Tag")

col_input, col_add = st.columns([4, 1])
new_tag = col_input.text_input(
    "Tag name",
    placeholder = "e.g. Universal Parks",
    label_visibility = "collapsed",
)
if col_add.button("Add", type="primary"):
    new_tag = new_tag.strip()
    if not new_tag:
        st.warning("Please enter a tag name.")
    elif new_tag in current_tags:
        st.warning(f"**{new_tag}** is already in the list.")
    else:
        updated = current_tags + [new_tag]
        if save_tracked_tags(updated, modified_by="admin"):
            st.success(f"Added **{new_tag}**")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("Failed to save — check Spaces credentials.")

st.markdown("---")

st.markdown("### Bulk Upload via CSV")
st.caption(
    "Upload a CSV with a column named **tag** (one tag per row). "
    "Tags will be **merged** with the existing list — nothing is removed."
)

uploaded = st.file_uploader("Upload CSV", type=["csv"])
if uploaded:
    try:
        df = pd.read_csv(uploaded)
        col = next(
            (c for c in df.columns if c.strip().lower() in ("tag", "tags")),
            None
        )
        if col is None:
            st.error("CSV must have a column named 'tag' or 'tags'.")
        else:
            new_tags    = [str(t).strip() for t in df[col].dropna() if str(t).strip()]
            merged      = sorted(set(current_tags) | set(new_tags))
            added_count = len(merged) - len(current_tags)

            st.markdown(f"**Preview:** {len(new_tags)} tags in file, "
                        f"**{added_count} new** tags will be added.")
            st.dataframe(
                pd.DataFrame({"Tag": new_tags}),
                use_container_width=True,
                hide_index=True,
            )

            if st.button("✅ Confirm Import", type="primary"):
                if save_tracked_tags(merged, modified_by="admin (csv import)"):
                    st.success(f"Imported — {added_count} new tags added. "
                               f"Total: {len(merged)} tags.")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Failed to save — check Spaces credentials.")
    except Exception as e:
        st.error(f"Could not read CSV: {e}")

st.markdown("---")

with st.expander("⚠️ Danger Zone"):
    st.warning("This will remove ALL tracked tags. The next nightly pull will return no results.")
    if st.button("🗑️ Clear All Tags", type="secondary"):
        if save_tracked_tags([], modified_by="admin"):
            st.success("All tags cleared.")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error("Failed to save.")