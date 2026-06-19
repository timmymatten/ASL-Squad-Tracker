import streamlit as st
import uuid
from datetime import date

from core.constants import GROUP_LABELS, GROUP_COLORS
from core.persistence import get_data, persist
from core.match_state import get_match, set_match
from core.algorithms import (
    generate_squads,
    _enforce_gender_balance,
    find_best_pairing,
    sort_pairs_by_score,
    pick_sitter,
    player_attendance,
    select_players_for_session,
)


def page_match_day():
    data = get_data()
    players = data["players"]
    match = get_match()

    st.title("🎯 Match Day")

    if match and not match.get("completed"):
        st.info(f"Match in progress — **{match['date']}**")
        if st.button("❌ Abandon this match day"):
            set_match(None)
            st.rerun()
        st.divider()
        _match_in_progress(data, match, players)
        return

    # ── New match day setup ──
    st.subheader("Start a New Match Day")
    active = [(pid, p) for pid, p in players.items() if p["active"]]
    if len(active) < 4:
        st.warning("Add at least 4 active players on the Roster page first.")
        return

    match_date = st.date_input("Match date", value=date.today())
    st.write("**Select present players:**")

    present = []
    for g in [1, 2, 3, 4]:
        grp = sorted(
            [(pid, p) for pid, p in active if p["group"] == g],
            key=lambda x: x[1]["name"],
        )
        if not grp:
            continue
        st.markdown(f"*{GROUP_COLORS[g]} {GROUP_LABELS[g]}*")
        cols = st.columns(min(4, len(grp)))
        for i, (pid, p) in enumerate(grp):
            with cols[i % 4]:
                if st.checkbox(p["name"], value=True, key=f"pres_{pid}"):
                    present.append(pid)

    if len(present) < 4:
        st.warning("Select at least 4 players.")
        return

    MAX_PLAYERS = 16
    attend = player_attendance(data["match_days"])

    if len(present) > MAX_PLAYERS:
        playing, benched = select_players_for_session(
            present, players, data["match_days"], MAX_PLAYERS
        )
        st.divider()
        st.warning(
            f"**{len(present)} players checked in — capped at {MAX_PLAYERS}.** "
            f"Players were selected within each skill group by fewest match days attended."
        )

        # Show who's in vs. benched, grouped
        c_in, c_out = st.columns(2)
        with c_in:
            st.markdown(f"**✅ Playing today ({len(playing)})**")
            for g in [1, 2, 3, 4]:
                pids = sorted(
                    [p for p in playing if players[p]["group"] == g],
                    key=lambda p: (attend.get(p, 0), players[p]["name"]),
                )
                for pid in pids:
                    days = attend.get(pid, 0)
                    st.write(f"{GROUP_COLORS[g]} {players[pid]['name']} — {days} days")
        with c_out:
            st.markdown(f"**🪑 Sitting out ({len(benched)})**")
            for g in [1, 2, 3, 4]:
                pids = sorted(
                    [p for p in benched if players[p]["group"] == g],
                    key=lambda p: (attend.get(p, 0), players[p]["name"]),
                )
                for pid in pids:
                    days = attend.get(pid, 0)
                    st.write(f"{GROUP_COLORS[g]} {players[pid]['name']} — {days} days")

        present = playing
    else:
        benched = []

    n = len(present)
    if n % 2 != 0:
        st.warning(
            f"⚠️ {n} players (odd). One squad will have an extra player — "
            "an upset is possible and will be tracked."
        )
    else:
        st.success(f"**{n} players** → {n//2} per squad, {n//4} nets per game")

    women_present = [p for p in present if players[p].get("gender") == "F"]
    enforce_gender = st.checkbox(
        "Require ≥ 1 woman per squad",
        value=False,
        disabled=len(women_present) < 2,
        help=(
            "Ensures each squad has at least one woman. "
            "Requires ≥ 2 women checked in."
            if len(women_present) >= 2
            else f"Only {len(women_present)} woman checked in — need at least 2."
        ),
    )

    if st.button("🏆 Generate Squads →", type="primary"):
        squad_a, squad_b = generate_squads(present, players)
        if enforce_gender and len(women_present) >= 2:
            squad_a, squad_b = _enforce_gender_balance(squad_a, squad_b, players)
        set_match(
            {
                "id": str(uuid.uuid4())[:8],
                "date": str(match_date),
                "present": present,
                "squad_a": squad_a,
                "squad_b": squad_b,
                "rank_a": _default_rank_order(squad_a, players),
                "rank_b": _default_rank_order(squad_b, players),
                "games": [],
                "squad_wins": {"a": 0, "b": 0},
                "completed": False,
                "step": "squads",
            }
        )
        st.rerun()


def _default_rank_order(squad_ids, players):
    """Default rank: sort by skill group then name (group 1 = rank 1)."""
    return sorted(squad_ids, key=lambda p: (players[p]["group"], players[p]["name"]))


def _squad_display(squad_ids, players, label, color):
    st.markdown(f"**{color} {label}** ({len(squad_ids)} players)")
    for pid in sorted(squad_ids, key=lambda p: (players[p]["group"], players[p]["name"])):
        p = players[pid]
        st.write(f"{GROUP_COLORS[p['group']]} {p['name']} — G{p['group']}")


def _match_in_progress(data, match, players):
    squad_a = match["squad_a"]
    squad_b = match["squad_b"]

    # Sidebar squad overview
    c_a, c_b = st.columns(2)
    with c_a:
        _squad_display(squad_a, players, "Squad A", "🔵")
    with c_b:
        _squad_display(squad_b, players, "Squad B", "🔴")

    step = match.get("step", "squads")
    st.divider()

    if step == "squads":
        _step_squads(match, players)
    elif step == "pairing":
        _step_pairing(match, players)
    elif step == "results":
        _step_results(data, match, players)
    elif step == "done":
        st.success("✅ Match day complete — results saved!")
        set_match(None)
        st.rerun()


@st.fragment
def _rank_list_fragment(rank_key, col_key):
    """Rank-ordered player list with ↑/↓ buttons. Fragment = no scroll-to-top."""
    match = get_match()
    data = get_data()
    players = data["players"]
    if not match:
        return
    order = list(match.get(rank_key) or [])
    for i, pid in enumerate(order):
        p = players[pid]
        c_name, c_up, c_dn = st.columns([5, 1, 1])
        c_name.write(f"**#{i+1}** {GROUP_COLORS[p['group']]} {p['name']} — G{p['group']}")
        if i > 0:
            if c_up.button("↑", key=f"{col_key}_up_{pid}", help="Move up"):
                order[i], order[i - 1] = order[i - 1], order[i]
                match[rank_key] = order
                set_match(match)
                st.rerun()
        if i < len(order) - 1:
            if c_dn.button("↓", key=f"{col_key}_dn_{pid}", help="Move down"):
                order[i], order[i + 1] = order[i + 1], order[i]
                match[rank_key] = order
                set_match(match)
                st.rerun()


def _step_squads(match, players):
    squad_a = match["squad_a"]
    squad_b = match["squad_b"]

    # Ensure rank lists exist (backward compat)
    if "rank_a" not in match:
        match["rank_a"] = _default_rank_order(squad_a, players)
    if "rank_b" not in match:
        match["rank_b"] = _default_rank_order(squad_b, players)

    # ── Swap players ──────────────────────────────────────────────────────────
    st.subheader("Adjust Squads")
    st.caption("Swap players between squads, then set each squad's rank order.")

    def pid_label(pid):
        p = players[pid]
        return f"{p['name']} (G{p['group']})"

    c1, c2 = st.columns(2)
    with c1:
        move_from_a = st.selectbox(
            "Move from A → B",
            ["—"] + squad_a,
            format_func=lambda x: "—" if x == "—" else pid_label(x),
            key="mv_a",
        )
    with c2:
        move_from_b = st.selectbox(
            "Move from B → A",
            ["—"] + squad_b,
            format_func=lambda x: "—" if x == "—" else pid_label(x),
            key="mv_b",
        )

    if st.button("↔️ Apply Swap"):
        pa = move_from_a if move_from_a != "—" else None
        pb = move_from_b if move_from_b != "—" else None
        if pa and pb:
            squad_a.remove(pa); squad_b.remove(pb)
            squad_a.append(pb); squad_b.append(pa)
            match["rank_a"].remove(pa); match["rank_b"].remove(pb)
            match["rank_a"].append(pb); match["rank_b"].append(pa)
        elif pa:
            squad_a.remove(pa); squad_b.append(pa)
            match["rank_a"].remove(pa); match["rank_b"].append(pa)
        elif pb:
            squad_b.remove(pb); squad_a.append(pb)
            match["rank_b"].remove(pb); match["rank_a"].append(pb)
        match["squad_a"] = squad_a
        match["squad_b"] = squad_b
        set_match(match)
        st.rerun()

    # ── Rank ordering ─────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Set Rank Order")
    st.caption("Rank 1 = best player. Pairs are built using these ranks.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**🔵 Squad A**")
        _rank_list_fragment("rank_a", "ra")
    with col_b:
        st.markdown("**🔴 Squad B**")
        _rank_list_fragment("rank_b", "rb")

    st.divider()
    if st.button("✅ Confirm Squads & Rankings — Begin Match!", type="primary"):
        match["step"] = "pairing"
        set_match(match)
        st.rerun()


def _pairing_context(match, players):
    """Compute shared context needed by both auto and manual pairing modes."""
    squad_a = match["squad_a"]
    squad_b = match["squad_b"]
    games = match["games"]

    forbidden_a, forbidden_b = set(), set()
    if games:
        last = games[-1]
        for pair in last.get("pairings_a", []):
            forbidden_a.add(frozenset(pair))
        for pair in last.get("pairings_b", []):
            forbidden_b.add(frozenset(pair))

    sit_hist_a = [g["sit_a"] for g in games if g.get("sit_a")]
    sit_hist_b = [g["sit_b"] for g in games if g.get("sit_b")]

    active_a = list(squad_a)
    active_b = list(squad_b)
    sit_a = sit_b = None

    if len(active_a) % 2:
        sit_a = pick_sitter(active_a, sit_hist_a)
        active_a = [p for p in active_a if p != sit_a]
    if len(active_b) % 2:
        sit_b = pick_sitter(active_b, sit_hist_b)
        active_b = [p for p in active_b if p != sit_b]

    # Use manually set rank order if present, otherwise fall back to skill-group order
    rank_order_a = match.get("rank_a") or _default_rank_order(squad_a, players)
    rank_order_b = match.get("rank_b") or _default_rank_order(squad_b, players)
    ranks_a = {pid: i + 1 for i, pid in enumerate(rank_order_a)}
    ranks_b = {pid: i + 1 for i, pid in enumerate(rank_order_b)}

    return active_a, active_b, sit_a, sit_b, ranks_a, ranks_b, forbidden_a, forbidden_b


def _check_pairing_rules(pairs_a, pairs_b, ranks_a, ranks_b, forbidden_a, forbidden_b):
    """
    Return (violations, max_net_diff).
    Net variance rule: on each net, |score_a - score_b| must not exceed 3.
    Pairs must be pre-sorted by score before calling so alignment is meaningful.
    """
    violations = []
    n_nets = min(len(pairs_a), len(pairs_b))

    # Repeat-pair check
    for i, pair in enumerate(pairs_a[:n_nets]):
        if frozenset(pair) in forbidden_a:
            violations.append(f"🔵 Squad A Net {i+1}: same pair as last game")
    for i, pair in enumerate(pairs_b[:n_nets]):
        if frozenset(pair) in forbidden_b:
            violations.append(f"🔴 Squad B Net {i+1}: same pair as last game")

    # Net variance rule: opposing pair scores on the same net must be within 3
    max_diff = 0
    for i in range(n_nets):
        sa = ranks_a[pairs_a[i][0]] + ranks_a[pairs_a[i][1]]
        sb = ranks_b[pairs_b[i][0]] + ranks_b[pairs_b[i][1]]
        diff = abs(sa - sb)
        max_diff = max(max_diff, diff)
        if diff > 3:
            violations.append(
                f"Net {i+1}: score gap = **{diff}** (A: {sa} vs B: {sb}, rule: ≤ 3)"
            )

    return violations, max_diff


def _display_pairing_table(pairs_a, pairs_b, ranks_a, ranks_b, players):
    n_nets = min(len(pairs_a), len(pairs_b))
    hdr = st.columns([1, 4, 3, 4])
    hdr[0].markdown("**Net**")
    hdr[1].markdown("**🔵 Squad A**")
    hdr[2].markdown("**Scores (gap)**")
    hdr[3].markdown("**🔴 Squad B**")
    for i in range(n_nets):
        pa1, pa2 = pairs_a[i]
        pb1, pb2 = pairs_b[i]
        sa = ranks_a[pa1] + ranks_a[pa2]
        sb = ranks_b[pb1] + ranks_b[pb2]
        diff = abs(sa - sb)
        gap_str = f"A:{sa} B:{sb} Δ{diff}"
        row = st.columns([1, 4, 3, 4])
        row[0].write(f"**{i+1}**")
        row[1].write(f"{players[pa1]['name']} & {players[pa2]['name']}")
        row[2].write(f"{'⚠️ ' if diff > 3 else ''}{gap_str}")
        row[3].write(f"{players[pb1]['name']} & {players[pb2]['name']}")


def _step_pairing(match, players):
    games = match["games"]
    game_num = len(games) + 1
    st.subheader(f"Game {game_num} — Pairings")

    active_a, active_b, sit_a, sit_b, ranks_a, ranks_b, forbidden_a, forbidden_b = \
        _pairing_context(match, players)

    if sit_a:
        st.info(f"🪑 **Squad A sitting:** {players[sit_a]['name']}")
    if sit_b:
        st.info(f"🪑 **Squad B sitting:** {players[sit_b]['name']}")

    tab_auto, tab_manual = st.tabs(["🤖 Auto", "✏️ Manual"])

    # ── Auto tab ──────────────────────────────────────────────────────────────
    with tab_auto:
        pairs_a = find_best_pairing(active_a, ranks_a, forbidden_a)
        pairs_b = find_best_pairing(active_b, ranks_b, forbidden_b)

        if not pairs_a or not pairs_b:
            st.error("Could not generate pairings — squad too small?")
            return

        # Sort by score so rank-1 A pair faces rank-1 B pair, etc.
        pairs_a = sort_pairs_by_score(pairs_a, ranks_a)
        pairs_b = sort_pairs_by_score(pairs_b, ranks_b)

        violations, max_diff = _check_pairing_rules(
            pairs_a, pairs_b, ranks_a, ranks_b, forbidden_a, forbidden_b
        )
        if violations:
            for v in violations:
                st.warning(f"⚠️ {v}")
        else:
            st.success(f"✅ All rules satisfied — max opposing score gap = **{max_diff}**")

        _display_pairing_table(pairs_a, pairs_b, ranks_a, ranks_b, players)

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔄 Regenerate", key="auto_regen"):
                st.rerun()
        with c2:
            if st.button("▶️ Start Game", type="primary", key="auto_start"):
                _commit_pairing(match, game_num, pairs_a, pairs_b, sit_a, sit_b)

    # ── Manual tab ────────────────────────────────────────────────────────────
    with tab_manual:
        n_nets = min(len(active_a), len(active_b)) // 2
        st.caption(
            f"Build {n_nets} pairs per squad. "
            f"Ranks shown in parentheses (1 = best). "
            f"Rules are checked live."
        )

        def player_options(active, ranks, squad_label):
            return sorted(active, key=lambda p: ranks[p])

        def pid_label_ranked(pid, ranks):
            p = players[pid]
            return f"{p['name']} (rank {ranks[pid]}, G{p['group']})"

        manual_pairs_a = []
        manual_pairs_b = []
        used_a: set = set()
        used_b: set = set()
        valid = True

        st.markdown("**🔵 Squad A pairs**")
        opts_a = player_options(active_a, ranks_a, "A")
        for i in range(n_nets):
            c1, c2 = st.columns(2)
            avail_a = [p for p in opts_a if p not in used_a]
            p1 = c1.selectbox(
                f"Net {i+1} — Player 1",
                ["—"] + avail_a,
                format_func=lambda x: "—" if x == "—" else pid_label_ranked(x, ranks_a),
                key=f"ma_p1_{i}",
            )
            # Second player excludes p1
            avail_a2 = [p for p in opts_a if p not in used_a and p != p1]
            p2 = c2.selectbox(
                f"Net {i+1} — Player 2",
                ["—"] + avail_a2,
                format_func=lambda x: "—" if x == "—" else pid_label_ranked(x, ranks_a),
                key=f"ma_p2_{i}",
            )
            if p1 != "—" and p2 != "—":
                manual_pairs_a.append([p1, p2])
                used_a.add(p1)
                used_a.add(p2)
            else:
                valid = False

        st.markdown("**🔴 Squad B pairs**")
        opts_b = player_options(active_b, ranks_b, "B")
        for i in range(n_nets):
            c1, c2 = st.columns(2)
            avail_b = [p for p in opts_b if p not in used_b]
            p1 = c1.selectbox(
                f"Net {i+1} — Player 1",
                ["—"] + avail_b,
                format_func=lambda x: "—" if x == "—" else pid_label_ranked(x, ranks_b),
                key=f"mb_p1_{i}",
            )
            avail_b2 = [p for p in opts_b if p not in used_b and p != p1]
            p2 = c2.selectbox(
                f"Net {i+1} — Player 2",
                ["—"] + avail_b2,
                format_func=lambda x: "—" if x == "—" else pid_label_ranked(x, ranks_b),
                key=f"mb_p2_{i}",
            )
            if p1 != "—" and p2 != "—":
                manual_pairs_b.append([p1, p2])
                used_b.add(p1)
                used_b.add(p2)
            else:
                valid = False

        # Live rule check — sort by score first so net alignment is meaningful
        st.divider()
        if valid and len(manual_pairs_a) == n_nets and len(manual_pairs_b) == n_nets:
            sorted_a = sort_pairs_by_score(manual_pairs_a, ranks_a)
            sorted_b = sort_pairs_by_score(manual_pairs_b, ranks_b)
            violations, max_diff = _check_pairing_rules(
                sorted_a, sorted_b,
                ranks_a, ranks_b,
                forbidden_a, forbidden_b,
            )
            if violations:
                for v in violations:
                    st.warning(f"⚠️ {v}")
                st.error("Fix rule violations before starting the game.")
            else:
                st.success(f"✅ All rules satisfied — max opposing score gap = **{max_diff}**")
                _display_pairing_table(sorted_a, sorted_b, ranks_a, ranks_b, players)
                if st.button("▶️ Start Game", type="primary", key="manual_start"):
                    _commit_pairing(match, game_num, sorted_a, sorted_b, sit_a, sit_b)
        else:
            st.info("Select all pairs above to see rule check.")


def _commit_pairing(match, game_num, pairs_a, pairs_b, sit_a, sit_b):
    n_nets = min(len(pairs_a), len(pairs_b))
    match["games"].append(
        {
            "game_num": game_num,
            "pairings_a": pairs_a,
            "pairings_b": pairs_b,
            "sit_a": sit_a,
            "sit_b": sit_b,
            "n_nets": n_nets,
            "results": None,
            "game_winner": None,
        }
    )
    match["step"] = "results"
    set_match(match)
    st.rerun()


def _step_results(data, match, players):
    games = match["games"]
    game = games[-1]
    game_num = game["game_num"]
    n_nets = game["n_nets"]
    pairs_a = game["pairings_a"]
    pairs_b = game["pairings_b"]

    st.subheader(f"Game {game_num} — Enter Results")

    st.caption("Enter each net's final score — the winner is the higher score.")

    hdr = st.columns([1, 4, 2, 2, 4])
    hdr[0].markdown("**Net**")
    hdr[1].markdown("**🔵 Squad A**")
    hdr[2].markdown("**A score**")
    hdr[3].markdown("**B score**")
    hdr[4].markdown("**🔴 Squad B**")

    scores = []
    net_winners = []
    has_tie = False
    for i in range(n_nets):
        pa1, pa2 = pairs_a[i]
        pb1, pb2 = pairs_b[i]
        row = st.columns([1, 4, 2, 2, 4])
        row[0].write(f"**{i+1}**")
        row[1].write(f"{players[pa1]['name']} & {players[pa2]['name']}")
        a_pts = row[2].number_input(
            f"A score net {i+1}",
            min_value=0, step=1, value=0,
            label_visibility="collapsed",
            key=f"score_a_{game_num}_{i}",
        )
        b_pts = row[3].number_input(
            f"B score net {i+1}",
            min_value=0, step=1, value=0,
            label_visibility="collapsed",
            key=f"score_b_{game_num}_{i}",
        )
        row[4].write(f"{players[pb1]['name']} & {players[pb2]['name']}")
        scores.append([int(a_pts), int(b_pts)])
        if a_pts > b_pts:
            net_winners.append("A")
        elif b_pts > a_pts:
            net_winners.append("B")
        else:
            net_winners.append(None)
            has_tie = True

    wins_a = net_winners.count("A")
    wins_b = net_winners.count("B")
    pts_a = sum(s[0] for s in scores)
    pts_b = sum(s[1] for s in scores)
    st.divider()
    st.markdown(
        f"**Running tally → 🔵 A: {wins_a} nets ({pts_a} pts) | "
        f"🔴 B: {wins_b} nets ({pts_b} pts)**"
    )
    if wins_a > wins_b:
        st.success("🔵 Squad A leads")
    elif wins_b > wins_a:
        st.success("🔴 Squad B leads")
    else:
        st.info("All square so far")

    if has_tie:
        st.warning("⚠️ Every net needs a winner — fix any tied scores before saving.")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 Save & Play Another Game", type="primary", disabled=has_tie):
            _commit_game_results(match, game, net_winners, scores, wins_a, wins_b)
            match["step"] = "pairing"
            set_match(match)
            st.rerun()
    with c2:
        if st.button("🏁 Save & End Match Day", disabled=has_tie):
            _commit_game_results(match, game, net_winners, scores, wins_a, wins_b)
            match["completed"] = True
            match["step"] = "done"
            data["match_days"].append(match)
            persist(data)
            set_match(match)
            st.balloons()
            st.rerun()


def _commit_game_results(match, game, net_winners, scores, wins_a, wins_b):
    game["results"] = net_winners
    game["scores"] = scores
    game["game_winner"] = "a" if wins_a > wins_b else ("b" if wins_b > wins_a else "tie")
    match["squad_wins"]["a"] += wins_a
    match["squad_wins"]["b"] += wins_b
