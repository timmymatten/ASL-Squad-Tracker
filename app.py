import streamlit as st
import json
import os
import uuid
import random
from datetime import date

DATA_FILE = "data.json"

GROUP_LABELS = {
    1: "Group 1 — Elite",
    2: "Group 2 — Advanced",
    3: "Group 3 — Intermediate",
    4: "Group 4 — Beginner",
}
GROUP_COLORS = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢"}

# ─── Persistence ──────────────────────────────────────────────────────────────

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"players": {}, "match_days": []}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_data():
    if "data" not in st.session_state:
        st.session_state.data = load_data()
    return st.session_state.data


def persist(data):
    save_data(data)
    st.session_state.data = data


# ─── Core algorithms ──────────────────────────────────────────────────────────

def squad_ranks(squad_ids, players):
    """Return {pid: rank} where rank 1 = best skill (group 1 = lowest rank numbers)."""
    sorted_ids = sorted(
        squad_ids,
        key=lambda p: (players[p]["group"], players[p]["name"]),
    )
    return {pid: i + 1 for i, pid in enumerate(sorted_ids)}


def _perfect_matchings(lst):
    """Yield all perfect matchings of a list."""
    if not lst:
        yield []
        return
    first = lst[0]
    for i in range(1, len(lst)):
        partner = lst[i]
        rest = lst[1:i] + lst[i + 1 :]
        for tail in _perfect_matchings(rest):
            yield [(first, partner)] + tail


def _spread(pairs, ranks):
    if not pairs:
        return 0
    scores = [ranks[a] + ranks[b] for a, b in pairs]
    return max(scores) - min(scores)


def find_best_pairing(active_squad, ranks, forbidden):
    """
    Find the perfect matching of active_squad with minimum pair-score spread
    that avoids all forbidden frozensets.  Falls back without forbidden
    constraint if no valid matching exists.
    """
    best, best_spread = None, float("inf")
    checked = 0
    LIMIT = 10_000  # cap for very large squads

    def search(relax=False):
        nonlocal best, best_spread, checked
        for matching in _perfect_matchings(list(active_squad)):
            checked += 1
            if checked > LIMIT:
                break
            if not relax and any(frozenset(p) in forbidden for p in matching):
                continue
            sp = _spread(matching, ranks)
            if sp < best_spread:
                best_spread = sp
                best = matching

    search(relax=False)
    if best is None:
        search(relax=True)
    return best


def generate_squads(present_ids, players):
    """Split present players into two skill-balanced squads."""
    by_group = {}
    for pid in present_ids:
        by_group.setdefault(players[pid]["group"], []).append(pid)

    squad_a, squad_b = [], []
    for g in sorted(by_group):
        grp = by_group[g][:]
        random.shuffle(grp)
        mid = len(grp) // 2
        squad_a.extend(grp[:mid])
        squad_b.extend(grp[mid : 2 * mid])  # exactly mid players, not the odd remainder
        if len(grp) % 2:
            extra = grp[2 * mid]
            (squad_a if len(squad_a) <= len(squad_b) else squad_b).append(extra)

    # Equalise sizes (difference > 1 shouldn't happen, but be safe)
    while len(squad_a) - len(squad_b) > 1:
        squad_b.append(squad_a.pop(random.randrange(len(squad_a))))
    while len(squad_b) - len(squad_a) > 1:
        squad_a.append(squad_b.pop(random.randrange(len(squad_b))))

    return squad_a, squad_b


def pick_sitter(squad_ids, sit_history):
    """
    Rotate sitters so no player sits more than 2 games in a row.
    sit_history is an ordered list of pids who sat (oldest first).
    """
    consec = {}
    for pid in squad_ids:
        cnt = 0
        for past in reversed(sit_history):
            if past == pid:
                cnt += 1
            else:
                break
        consec[pid] = cnt

    eligible = [p for p in squad_ids if consec[p] < 2] or list(squad_ids)
    never = [p for p in eligible if p not in sit_history]
    if never:
        return random.choice(never)
    last_idx = {p: max(i for i, x in enumerate(sit_history) if x == p) for p in eligible}
    return min(last_idx, key=last_idx.get)


def _enforce_gender_balance(squad_a, squad_b, players):
    """
    Ensure each squad has at least one woman by swapping if necessary.
    Swaps the woman with the least skill disruption (same group preferred).
    """
    def women(sq):
        return [p for p in sq if players[p].get("gender") == "F"]

    sa, sb = list(squad_a), list(squad_b)

    # If both already have a woman, nothing to do
    if women(sa) and women(sb):
        return sa, sb

    # One squad has all women, other has none — move one woman across
    if women(sa) and not women(sb):
        donor, receiver = sa, sb
    else:
        donor, receiver = sb, sa

    # Pick woman from donor whose group best matches the receiver's composition
    donor_women = women(donor)
    receiver_groups = [players[p]["group"] for p in receiver]
    avg_recv = sum(receiver_groups) / len(receiver_groups) if receiver_groups else 2
    move_w = min(donor_women, key=lambda p: abs(players[p]["group"] - avg_recv))

    # Swap her with a man of similar group from receiver
    receiver_men = [p for p in receiver if players[p].get("gender", "M") == "M"]
    if receiver_men:
        swap_target = min(receiver_men, key=lambda p: abs(players[p]["group"] - players[move_w]["group"]))
        donor.remove(move_w);   receiver.remove(swap_target)
        donor.append(swap_target); receiver.append(move_w)

    return (sa, sb) if donor is sa else (sb, sa)


# ─── Session state helpers ────────────────────────────────────────────────────

def get_match():
    return st.session_state.get("current_match")


def set_match(m):
    st.session_state.current_match = m


# ─── Page: Roster ─────────────────────────────────────────────────────────────

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


# ─── Page: Match Day ──────────────────────────────────────────────────────────

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


def player_attendance(match_days):
    """Return {pid: number_of_completed_match_days_attended}."""
    counts = {}
    for md in match_days:
        if not md.get("completed"):
            continue
        for pid in md.get("present", []):
            counts[pid] = counts.get(pid, 0) + 1
    return counts


def select_players_for_session(checked_ids, players, match_days, max_players=16):
    """
    From the checked-in players, pick at most `max_players` giving priority
    to those with fewer completed match days, applied at the skill-group level.

    Returns (selected, benched) both as lists of pids.
    Benched players are the ones cut due to the cap.
    """
    if len(checked_ids) <= max_players:
        return list(checked_ids), []

    attend = player_attendance(match_days)

    # Group players by skill group
    by_group = {}
    for pid in checked_ids:
        g = players[pid]["group"]
        by_group.setdefault(g, []).append(pid)

    # Proportional allocation across groups, summing to max_players
    total = len(checked_ids)
    groups = sorted(by_group.keys())
    raw = {g: max_players * len(by_group[g]) / total for g in groups}
    alloc = {g: int(raw[g]) for g in groups}
    remainder = max_players - sum(alloc.values())
    # Give leftover slots to groups with largest fractional parts
    fractional = sorted(groups, key=lambda g: raw[g] - alloc[g], reverse=True)
    for g in fractional[:remainder]:
        alloc[g] += 1

    selected, benched = [], []
    for g in groups:
        # Within each group, sort ascending by attendance (fewest days first),
        # break ties randomly so it isn't always the same person bumped
        group_pids = by_group[g][:]
        random.shuffle(group_pids)  # shuffle first for tie-breaking
        group_pids.sort(key=lambda p: attend.get(p, 0))
        n = alloc[g]
        selected.extend(group_pids[:n])
        benched.extend(group_pids[n:])

    return selected, benched


def sort_pairs_by_score(pairs, ranks):
    """Sort pairs ascending by combined rank score so opponents align correctly."""
    return sorted(pairs, key=lambda p: ranks[p[0]] + ranks[p[1]])


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

    hdr = st.columns([1, 4, 3, 4])
    hdr[0].markdown("**Net**")
    hdr[1].markdown("**🔵 Squad A**")
    hdr[2].markdown("**Winner**")
    hdr[3].markdown("**🔴 Squad B**")

    net_winners = []
    for i in range(n_nets):
        pa1, pa2 = pairs_a[i]
        pb1, pb2 = pairs_b[i]
        row = st.columns([1, 4, 3, 4])
        row[0].write(f"**{i+1}**")
        row[1].write(f"{players[pa1]['name']} & {players[pa2]['name']}")
        winner = row[2].radio(
            f"w{i}",
            ["A", "B"],
            horizontal=True,
            label_visibility="collapsed",
            key=f"res_{game_num}_{i}",
        )
        net_winners.append(winner)
        row[3].write(f"{players[pb1]['name']} & {players[pb2]['name']}")

    wins_a = net_winners.count("A")
    wins_b = net_winners.count("B")
    st.divider()
    st.markdown(f"**Running tally → 🔵 A: {wins_a} nets | 🔴 B: {wins_b} nets**")
    if wins_a > wins_b:
        st.success("🔵 Squad A leads")
    elif wins_b > wins_a:
        st.success("🔴 Squad B leads")
    else:
        st.info("All square so far")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 Save & Play Another Game", type="primary"):
            _commit_game_results(match, game, net_winners, wins_a, wins_b)
            match["step"] = "pairing"
            set_match(match)
            st.rerun()
    with c2:
        if st.button("🏁 Save & End Match Day"):
            _commit_game_results(match, game, net_winners, wins_a, wins_b)
            match["completed"] = True
            match["step"] = "done"
            data["match_days"].append(match)
            persist(data)
            set_match(match)
            st.balloons()
            st.rerun()


def _commit_game_results(match, game, net_winners, wins_a, wins_b):
    game["results"] = net_winners
    game["game_winner"] = "a" if wins_a > wins_b else ("b" if wins_b > wins_a else "tie")
    match["squad_wins"]["a"] += wins_a
    match["squad_wins"]["b"] += wins_b


# ─── Page: Leaderboard ────────────────────────────────────────────────────────

def _compute_stats(data):
    players = data["players"]
    stats = {
        pid: {
            "name": p["name"],
            "group": p["group"],
            "wins": 0,
            "games": 0,
            "attendance": 0,
            "upsets": 0,
        }
        for pid, p in players.items()
    }

    for md in data["match_days"]:
        if not md.get("completed"):
            continue

        squad_a = set(md.get("squad_a", []))
        squad_b = set(md.get("squad_b", []))

        for pid in md.get("present", []):
            if pid in stats:
                stats[pid]["attendance"] += 1

        def avg_group(sq):
            gs = [players[p]["group"] for p in sq if p in players]
            return sum(gs) / len(gs) if gs else 0

        avg_a = avg_group(squad_a)
        avg_b = avg_group(squad_b)

        md_net_a = md_net_b = 0

        for game in md.get("games", []):
            results = game.get("results") or []
            pairs_a = game.get("pairings_a", [])
            pairs_b = game.get("pairings_b", [])

            for i, winner in enumerate(results):
                pa_pair = pairs_a[i] if i < len(pairs_a) else []
                pb_pair = pairs_b[i] if i < len(pairs_b) else []

                if winner == "A":
                    md_net_a += 1
                    for pid in pa_pair:
                        if pid in stats:
                            stats[pid]["wins"] += 1
                            stats[pid]["games"] += 1
                    for pid in pb_pair:
                        if pid in stats:
                            stats[pid]["games"] += 1
                elif winner == "B":
                    md_net_b += 1
                    for pid in pb_pair:
                        if pid in stats:
                            stats[pid]["wins"] += 1
                            stats[pid]["games"] += 1
                    for pid in pa_pair:
                        if pid in stats:
                            stats[pid]["games"] += 1

        # Upset: weaker squad (higher avg group #) won more nets
        if md_net_a != md_net_b:
            winning_sq = squad_a if md_net_a > md_net_b else squad_b
            winning_avg = avg_a if md_net_a > md_net_b else avg_b
            losing_avg = avg_b if md_net_a > md_net_b else avg_a
            if winning_avg > losing_avg:  # winner had worse avg skill
                for pid in winning_sq:
                    if pid in stats:
                        stats[pid]["upsets"] += 1

    return stats


def page_leaderboard():
    data = get_data()
    if not data["players"]:
        st.title("🏆 Leaderboard")
        st.info("No players yet.")
        return

    stats = _compute_stats(data)
    st.title("🏆 Leaderboard")

    sort_opt = st.selectbox(
        "Sort by",
        ["Win Rate", "Total Wins", "Games Played", "Attendance", "Upsets"],
    )
    sort_fns = {
        "Win Rate": lambda x: x["wins"] / max(x["games"], 1),
        "Total Wins": lambda x: x["wins"],
        "Games Played": lambda x: x["games"],
        "Attendance": lambda x: x["attendance"],
        "Upsets": lambda x: x["upsets"],
    }
    ranked = sorted(stats.values(), key=sort_fns[sort_opt], reverse=True)

    st.divider()
    hdr = st.columns([1, 3, 1, 1, 1, 1, 1, 1])
    for col, lbl in zip(hdr, ["#", "Player", "Grp", "Wins", "Games", "Win%", "Attend", "Upsets"]):
        col.markdown(f"**{lbl}**")

    for rank, s in enumerate(ranked, 1):
        win_pct = f"{100*s['wins']/s['games']:.0f}%" if s["games"] else "—"
        row = st.columns([1, 3, 1, 1, 1, 1, 1, 1])
        row[0].write(f"**#{rank}**")
        row[1].write(f"{GROUP_COLORS[s['group']]} {s['name']}")
        row[2].write(f"G{s['group']}")
        row[3].write(s["wins"])
        row[4].write(s["games"])
        row[5].write(win_pct)
        row[6].write(s["attendance"])
        row[7].write(s["upsets"])

    # Group averages
    st.divider()
    st.subheader("Group Averages")
    group_rates = {}
    for s in stats.values():
        group_rates.setdefault(s["group"], []).append(
            s["wins"] / max(s["games"], 1)
        )

    gcols = st.columns(4)
    for i, g in enumerate([1, 2, 3, 4]):
        rates = group_rates.get(g, [])
        avg = sum(rates) / len(rates) * 100 if rates else 0
        gcols[i].metric(
            f"{GROUP_COLORS[g]} Group {g}",
            f"{avg:.0f}%" if rates else "—",
            help=f"{len(rates)} players",
        )


# ─── Page: History ────────────────────────────────────────────────────────────

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

                    row = st.columns([1, 4, 2, 4])
                    row[0].write(f"**{i+1}**")
                    row[1].write(
                        " & ".join(pname(p) for p in pa) if pa else "—"
                    )
                    row[2].write(win_icon)
                    row[3].write(
                        " & ".join(pname(p) for p in pb) if pb else "—"
                    )


# ─── Main ─────────────────────────────────────────────────────────────────────

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
        data = get_data()
        active_count = sum(1 for p in data["players"].values() if p["active"])
        st.caption(f"{len(data['players'])} players · {active_count} active")
        st.caption(f"{len(data['match_days'])} match days logged")

    pages[page]()


if __name__ == "__main__":
    main()
