import random


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


PAIRING_SLACK = 2  # how far above the best pair-score spread an alternate matchup may stray


def find_best_pairing(active_squad, ranks, forbidden, variant=None, slack=PAIRING_SLACK):
    """
    Return a perfect matching of active_squad that avoids all forbidden frozensets
    (falling back to ignoring forbidden if none qualify).

    variant=None (default): deterministic — the minimum pair-score-spread matching.
        Identical to the original behavior.
    variant=<int>: pick from the near-optimal matchings (spread within `slack` of the
        best), rotating by the integer so consecutive values yield different — and not
        necessarily zero-spread — matchups. Powers the UI's "Regenerate" button.
    """
    LIMIT = 10_000  # cap for very large squads

    def collect(relax):
        out = []
        for i, matching in enumerate(_perfect_matchings(list(active_squad))):
            if i >= LIMIT:
                break
            if not relax and any(frozenset(p) in forbidden for p in matching):
                continue
            out.append(matching)
        return out

    candidates = collect(relax=False) or collect(relax=True)
    if not candidates:
        return None

    spreads = [_spread(m, ranks) for m in candidates]
    best_spread = min(spreads)

    if variant is None:
        return candidates[spreads.index(best_spread)]

    pool = [m for m, sp in zip(candidates, spreads) if sp <= best_spread + slack]
    pool.sort(key=lambda m: _spread(m, ranks))
    return pool[variant % len(pool)]


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


def pick_sitter(squad_ids, sit_history, rng=None):
    """
    Rotate sitters so no player sits more than 2 games in a row.
    sit_history is an ordered list of pids who sat (oldest first).
    Pass rng (a random.Random) to make the tie-break reproducible.
    """
    rng = rng or random
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
        return rng.choice(never)
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
