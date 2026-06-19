import streamlit as st
import uuid

from core.constants import GROUP_LABELS, GROUP_COLORS
from core.persistence import get_data, persist


def page_roster():
    data = get_data()
    players = data["players"]

    st.title("📋 Player Roster")

    with st.expander("➕ Add New Player"):
        with st.form("add_player", clear_on_submit=True):
            name = st.text_input("Name")
            c1, c2 = st.columns(2)
            group = c1.selectbox("Skill Group", [1, 2, 3, 4], format_func=lambda x: GROUP_LABELS[x])
            gender = c2.selectbox("Gender", ["M", "F"])
            if st.form_submit_button("Add Player") and name.strip():
                pid = str(uuid.uuid4())[:8]
                players[pid] = {"name": name.strip(), "group": group, "gender": gender, "active": True}
                persist(data)
                st.success(f"Added **{name.strip()}**")
                st.rerun()

    if not players:
        st.info("No players yet — add some above!")
        return

    show_inactive = st.checkbox("Show inactive players")
    st.divider()
    _roster_table_fragment(show_inactive)


@st.fragment
def _roster_table_fragment(show_inactive):
    data = get_data()
    players = data["players"]

    if "editing_pid" not in st.session_state:
        st.session_state.editing_pid = None

    total = 0
    for g in [1, 2, 3, 4]:
        group_players = [
            (pid, p)
            for pid, p in players.items()
            if p["group"] == g and (show_inactive or p["active"])
        ]
        if not group_players:
            continue
        total += len(group_players)
        st.markdown(f"#### {GROUP_COLORS[g]} {GROUP_LABELS[g]}")

        for pid, p in sorted(group_players, key=lambda x: x[1]["name"]):
            gender = p.get("gender", "M")
            gender_badge = "♀" if gender == "F" else "♂"

            if st.session_state.editing_pid == pid:
                # ── Inline edit form ──────────────────────────────────────────
                with st.form(key=f"edit_form_{pid}"):
                    ec1, ec2, ec3 = st.columns([3, 2, 1])
                    new_name = ec1.text_input("Name", value=p["name"], key=f"en_{pid}")
                    new_group = ec2.selectbox(
                        "Group", [1, 2, 3, 4],
                        index=p["group"] - 1,
                        format_func=lambda x: f"Group {x}",
                        key=f"eg_{pid}",
                    )
                    new_gender = ec3.selectbox(
                        "Gender", ["M", "F"],
                        index=0 if gender == "M" else 1,
                        key=f"egn_{pid}",
                    )
                    sc1, sc2 = st.columns(2)
                    if sc1.form_submit_button("💾 Save", type="primary"):
                        if new_name.strip():
                            players[pid]["name"] = new_name.strip()
                            players[pid]["group"] = new_group
                            players[pid]["gender"] = new_gender
                            persist(data)
                        st.session_state.editing_pid = None
                        st.rerun()
                    if sc2.form_submit_button("Cancel"):
                        st.session_state.editing_pid = None
                        st.rerun()
            else:
                # ── Normal row ────────────────────────────────────────────────
                c1, c2, c3, c4 = st.columns([4, 2, 1, 1])
                c1.write(p["name"])
                active_label = "✅ Active" if p["active"] else "💤 Inactive"
                if c2.button(active_label, key=f"tog_{pid}"):
                    players[pid]["active"] = not p["active"]
                    persist(data)
                    st.rerun()
                if c3.button("✏️", key=f"edit_{pid}", help="Edit player"):
                    st.session_state.editing_pid = pid
                    st.rerun()
                if c4.button("🗑️", key=f"del_{pid}", help="Delete player"):
                    del players[pid]
                    persist(data)
                    st.rerun()

        st.divider()
    st.caption(f"{total} players shown")
