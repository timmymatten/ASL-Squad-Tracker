import streamlit as st

from core.constants import GROUP_COLORS
from core.persistence import get_data, persist


def page_history():
    data = get_data()
    players = data["players"]
    done = [md for md in data["match_days"] if md.get("completed")]

    st.title("📅 Match Day History")

    if not done:
        st.info("No completed match days yet.")
        return

    # Track which match is pending delete confirmation
    if "confirm_delete_id" not in st.session_state:
        st.session_state.confirm_delete_id = None

    for md in reversed(done):
        mid = md["id"]
        wins_a = md["squad_wins"]["a"]
        wins_b = md["squad_wins"]["b"]
        n_games = len(md.get("games", []))
        overall = "🔵 A" if wins_a > wins_b else ("🔴 B" if wins_b > wins_a else "Tie")
        title = (
            f"📅 {md['date']}  —  {n_games} games  |  "
            f"A: {wins_a} nets, B: {wins_b} nets  →  {overall} wins"
        )
        with st.expander(title):
            def pname(pid):
                return players.get(pid, {}).get("name", "?")

            # Delete controls
            if st.session_state.confirm_delete_id == mid:
                st.error("**Delete this match day?** This will remove all its games and update all stats.")
                dc1, dc2 = st.columns(2)
                with dc1:
                    if st.button("🗑️ Yes, delete it", key=f"confirm_del_{mid}", type="primary"):
                        data["match_days"] = [m for m in data["match_days"] if m["id"] != mid]
                        persist(data)
                        st.session_state.confirm_delete_id = None
                        st.rerun()
                with dc2:
                    if st.button("Cancel", key=f"cancel_del_{mid}"):
                        st.session_state.confirm_delete_id = None
                        st.rerun()
            else:
                if st.button("🗑️ Delete this match day", key=f"del_{mid}"):
                    st.session_state.confirm_delete_id = mid
                    st.rerun()

            st.divider()

            c_a, c_b = st.columns(2)
            with c_a:
                st.markdown("**🔵 Squad A**")
                for pid in md.get("squad_a", []):
                    p = players.get(pid)
                    if p:
                        st.write(f"{GROUP_COLORS[p['group']]} {p['name']}")
            with c_b:
                st.markdown("**🔴 Squad B**")
                for pid in md.get("squad_b", []):
                    p = players.get(pid)
                    if p:
                        st.write(f"{GROUP_COLORS[p['group']]} {p['name']}")

            for game in md.get("games", []):
                n = game.get("n_nets", 0)
                results = game.get("results") or []
                ga = sum(1 for r in results if r == "A")
                gb = sum(1 for r in results if r == "B")
                gw = game.get("game_winner", "?")
                gw_str = "🔵 A" if gw == "a" else ("🔴 B" if gw == "b" else "Tie")

                st.markdown(f"---\n**Game {game['game_num']}** — A: {ga} nets, B: {gb} nets → {gw_str}")

                sit_a = game.get("sit_a")
                sit_b = game.get("sit_b")
                if sit_a:
                    st.write(f"🪑 A sat: {pname(sit_a)}")
                if sit_b:
                    st.write(f"🪑 B sat: {pname(sit_b)}")

                pairs_a = game.get("pairings_a", [])
                pairs_b = game.get("pairings_b", [])
                scores = game.get("scores") or []

                hdr = st.columns([1, 4, 2, 4])
                hdr[0].markdown("**Net**")
                hdr[1].markdown("**🔵 Squad A**")
                hdr[2].markdown("**Result**")
                hdr[3].markdown("**🔴 Squad B**")

                for i in range(n):
                    pa = pairs_a[i] if i < len(pairs_a) else []
                    pb = pairs_b[i] if i < len(pairs_b) else []
                    winner = results[i] if i < len(results) else "?"
                    win_icon = "🔵 A" if winner == "A" else ("🔴 B" if winner == "B" else "?")
                    if i < len(scores):
                        win_icon = f"{scores[i][0]}–{scores[i][1]} {win_icon}"

                    row = st.columns([1, 4, 2, 4])
                    row[0].write(f"**{i+1}**")
                    row[1].write(
                        " & ".join(pname(p) for p in pa) if pa else "—"
                    )
                    row[2].write(win_icon)
                    row[3].write(
                        " & ".join(pname(p) for p in pb) if pb else "—"
                    )
