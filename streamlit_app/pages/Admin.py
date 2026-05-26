import streamlit as st
import pandas as pd
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from logic.spaces import load_users, save_users, get_all_customers, list_available_dates

st.set_page_config(
    page_title = "Admin Panel",
    layout     = "centered",
    initial_sidebar_state = "collapsed",
)

# ── Auth check ────────────────────────────────────────────────────────────────
if not st.session_state.get("authenticated") or not st.session_state.get("user", {}).get("is_admin"):
    st.error("Access denied. Please log in as an admin.")
    st.stop()

st.markdown("## ⚙️ Admin Panel")

if st.button("← Back to Report"):
    st.switch_page("app.py")

st.markdown("---")

# ── Load data ─────────────────────────────────────────────────────────────────
users = load_users()

available_dates = list_available_dates()
all_customers   = get_all_customers(available_dates[-1]) if available_dates else []

# ── User list ─────────────────────────────────────────────────────────────────
st.markdown(f"### Users ({len(users)})")

if users:
    for username, info in sorted(users.items()):
        with st.expander(
            f"{'🔑 ' if info.get('is_admin') else '👤 '}{username}"
            + (" — Admin" if info.get("is_admin") else f" — {', '.join(info.get('customers') or ['All']) if info.get('is_admin') else ', '.join(info.get('customers') or ['None'])}")
        ):
            col_info, col_delete = st.columns([4, 1])

            with col_info:
                if info.get("is_admin"):
                    st.caption("Admin user — has access to all customers")
                else:
                    assigned = info.get("customers") or []
                    st.caption(
                        f"Assigned customers: **{', '.join(assigned)}**"
                        if assigned else "No customers assigned"
                    )

            with col_delete:
                if username != st.session_state.get("username"):
                    if st.button("Remove", key=f"remove_{username}", type="secondary"):
                        del users[username]
                        save_users(users)
                        st.success(f"Removed user **{username}**")
                        st.rerun()
                else:
                    st.caption("(you)")

            # Edit customers
            if not info.get("is_admin"):
                new_customers = st.multiselect(
                    "Update customer access",
                    options  = all_customers,
                    default  = [c for c in (info.get("customers") or []) if c in all_customers],
                    key      = f"customers_{username}",
                )
                new_password = st.text_input(
                    "New password (leave blank to keep current)",
                    type = "password",
                    key  = f"password_{username}",
                )
                if st.button("Save Changes", key=f"save_{username}", type="primary"):
                    users[username]["customers"] = new_customers
                    if new_password.strip():
                        users[username]["password"] = new_password.strip()
                    save_users(users)
                    st.success(f"Updated **{username}**")
                    st.rerun()
else:
    st.info("No users found.")

st.markdown("---")

# ── Add new user ──────────────────────────────────────────────────────────────
st.markdown("### Add New User")

col1, col2 = st.columns(2)
with col1:
    new_username = st.text_input("Username", placeholder="e.g. universalparks")
with col2:
    new_password = st.text_input("Password", type="password", placeholder="Set a password")

new_is_admin = st.checkbox("Admin user (access to everything)")

if not new_is_admin:
    new_customers = st.multiselect(
        "Assign customers",
        options = all_customers,
        help    = "Select which 3PL customers this user can see",
    )
else:
    new_customers = None

if st.button("➕ Add User", type="primary"):
    if not new_username.strip():
        st.warning("Please enter a username.")
    elif not new_password.strip():
        st.warning("Please enter a password.")
    elif new_username.strip().lower() in users:
        st.warning(f"Username **{new_username}** already exists.")
    elif not new_is_admin and not new_customers:
        st.warning("Please assign at least one customer.")
    else:
        users[new_username.strip().lower()] = {
            "password":  new_password.strip(),
            "customers": new_customers,
            "is_admin":  new_is_admin,
        }
        save_users(users)
        st.success(f"Added user **{new_username.strip().lower()}**")
        st.rerun()
