import random

from core.lineups import OPEN_PER_SQUAD, WOMEN_PER_SQUAD, split_pools


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


def generate_format_squads(present_ids, players):
    """
    Split a full turnout (2×7 open, 2×3 women) into two squads: the open pool and the
    women's pool are each split skill-balanced on their own, so every squad gets exactly
    7 open players and 3 women.
    """
    open_ids, women_ids = split_pools(present_ids, players)
    oa, ob = generate_squads(open_ids, players)
    wa, wb = generate_squads(women_ids, players)
    return oa + wa, ob + wb


def player_attendance(match_days):
    """Return {pid: number_of_completed_match_days_attended}."""
    counts = {}
    for md in match_days:
        if not md.get("completed"):
            continue
        for pid in md.get("present", []):
            counts[pid] = counts.get(pid, 0) + 1
    return counts


def select_players_for_session(checked_ids, players, match_days, max_players):
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


def select_players_for_format(checked_ids, players, match_days):
    """
    Cap the open and women's pools separately at what two squads need (14 open, 6 women),
    each by fewest match days attended within skill group. Returns (selected, benched).
    """
    open_ids, women_ids = split_pools(checked_ids, players)
    so, bo = select_players_for_session(open_ids, players, match_days, 2 * OPEN_PER_SQUAD)
    sw, bw = select_players_for_session(women_ids, players, match_days, 2 * WOMEN_PER_SQUAD)
    return so + sw, bo + bw
