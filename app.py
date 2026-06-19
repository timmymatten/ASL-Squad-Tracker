import streamlit as st

from core.persistence import get_data, active_dataset, set_dataset, DATA_FILES
from core.match_state import get_match
from views.roster import page_roster
from views.match_day import page_match_day
from views.leaderboard import page_leaderboard
from views.chemistry import page_chemistry
from views.history import page_history


def main():
    st.set_page_config(
        page_title="ASL Squad Tracker",
        page_icon="🥏",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    pages = {
        "📋 Roster": page_roster,
        "🎯 Match Day": page_match_day,
        "🏆 Leaderboard": page_leaderboard,
        "🤝 Chemistry": page_chemistry,
        "📅 History": page_history,
    }

    with st.sidebar:
        st.markdown("# 🥏 ASL Squad Tracker")
        st.caption("Northeastern Club Roundnet")
        st.divider()
        page = st.radio("", list(pages.keys()), label_visibility="collapsed")

        match = get_match()
        if match and not match.get("completed"):
            st.divider()
            games_done = len(match.get("games", []))
            step_label = {
                "squads": "Adjusting squads",
                "pairing": f"Game {games_done + 1} — pairings",
                "results": f"Game {games_done} — results",
            }.get(match.get("step", ""), "In progress")
            st.info(f"**Match in progress**\n\n{match['date']}\n\n{step_label}")

        st.divider()
        # ── Dataset switch: Real vs Sample (test) ──────────────────────────────
        labels = {"real": "🟢 Real data", "sample": "🧪 Sample data"}
        current = active_dataset()
        choice = st.radio(
            "Dataset",
            list(DATA_FILES.keys()),
            index=list(DATA_FILES.keys()).index(current),
            format_func=lambda k: labels[k],
            help="Switch between your real data and throwaway test data. "
                 "Each saves to its own file — they never mix.",
        )
        if choice != current:
            set_dataset(choice)
            st.rerun()
        if current == "sample":
            st.warning("🧪 **Sample mode** — edits save to the test file, not your real data.")
            if st.button("♻️ Regenerate sample data", use_container_width=True,
                         help="Rebuild the sample dataset from your current real roster. "
                              "Your real data is not touched."):
                from core.sample_data import generate_sample
                summary = generate_sample()  # fresh random data each click
                set_dataset("sample")  # drop cached data so the new file is reloaded
                st.toast(
                    f"Regenerated sample: {summary['match_days']} match days, "
                    f"{summary['games']} games."
                )
                st.rerun()
        st.caption(f"File: `{DATA_FILES[current]}`")

        st.divider()
        data = get_data()
        active_count = sum(1 for p in data["players"].values() if p["active"])
        st.caption(f"{len(data['players'])} players · {active_count} active")
        st.caption(f"{len(data['match_days'])} match days logged")

    pages[page]()


if __name__ == "__main__":
    main()
