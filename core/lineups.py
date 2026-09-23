"""
Squad lineup format: 10 per squad (7 open + 3 women), 5 nets per game.

Each game one squad is the **setting team**. It picks a lineup shape —

    * 2 Open + 3 Coed               (4 open on open nets, 3 open + 3 women on coed)
    * 3 Open + 1 Women's + 1 Coed   (6 open on open nets, 2 women, 1 open + 1 woman)

— and fills all five nets. The **matching team** then fields a pair of the same type on
every net, and each matchup must be within ±MATCH_TOLERANCE on combined rank.

Ranks are per pool within a squad: open players are ranked O1..O7 and women W1..W3
(lower = stronger); a pair's score is the sum of its two ranks. Coed pairs are stored
as [open, woman].

Pure — no Streamlit — so the app and the sample-data generator share it.
"""
from itertools import permutations

from core.stats import squad_order

OPEN_PER_SQUAD = 7
WOMEN_PER_SQUAD = 3
SQUAD_SIZE = OPEN_PER_SQUAD + WOMEN_PER_SQUAD
N_NETS = 5
MATCH_TOLERANCE = 3  # max combined-rank gap between opposing pairs on a net

SHAPES = {
    "2o3c": {"label": "2 Open + 3 Coed", "nets": ["open", "open", "coed", "coed", "coed"]},
    "3o1w1c": {"label": "3 Open + 1 Women's + 1 Coed",
               "nets": ["open", "open", "open", "women", "coed"]},
}
NET_LABELS = {"open": "Open", "women": "Women's", "coed": "Coed"}
NET_ICONS = {"open": "🟦", "women": "🟪", "coed": "🟩"}
# Which pool fills each seat of a net type.
NET_SLOTS = {"open": ("open", "open"), "women": ("women", "women"), "coed": ("open", "women")}

SUGGEST_SLACK = 2  # how far above the most balanced setting lineup a suggestion may stray


def is_woman(player):
    return player.get("gender") == "F"


def split_pools(pids, players):
    """(open_ids, women_ids) — anyone not marked F plays in the open pool."""
    women = [p for p in pids if is_woman(players[p])]
    return [p for p in pids if p not in women], women


def squad_ranks(squad_ids, stats, players):
    """{pid: rank} — open ranked 1..n, women ranked 1..m, each via squad_order."""
    open_ids, women_ids = split_pools(squad_ids, players)
    ranks = {}
    for pool in (open_ids, women_ids):
        for i, pid in enumerate(squad_order(pool, stats, players)):
            ranks[pid] = i + 1
    return ranks


def default_rank_order(squad_ids, stats, players):
    """Starting order for a squad: open then women, each by roster group (then avg +/-)."""
    open_ids, women_ids = split_pools(squad_ids, players)
    return squad_order(open_ids, stats, players) + squad_order(women_ids, stats, players)


def ranks_from_order(order, players):
    """{pid: rank} from a manual order — open and women numbered separately from 1."""
    counters, ranks = {"open": 0, "women": 0}, {}
    for pid in order:
        pool = "women" if is_woman(players[pid]) else "open"
        counters[pool] += 1
        ranks[pid] = counters[pool]
    return ranks


def rank_label(pid, ranks, players):
    return f"{'W' if is_woman(players[pid]) else 'O'}{ranks[pid]}"


def pair_score(pair, ranks):
    return ranks[pair[0]] + ranks[pair[1]]


def net_gaps(setting_pairs, matching_pairs, ranks_set, ranks_match):
    return [abs(pair_score(s, ranks_set) - pair_score(m, ranks_match))
            for s, m in zip(setting_pairs, matching_pairs)]


def setting_side(match, game_num):
    """Squad ("a"/"b") setting the lineup for game_num: the flip winner, then alternating."""
    first = match.get("setting_first", "a")
    other = "b" if first == "a" else "a"
    return first if game_num % 2 == 1 else other


def composition_errors(squad_ids, players):
    """Why a squad can't play this format (empty list when it can)."""
    open_ids, women_ids = split_pools(squad_ids, players)
    errors = []
    if len(open_ids) != OPEN_PER_SQUAD:
        errors.append(f"needs {OPEN_PER_SQUAD} open players (has {len(open_ids)})")
    if len(women_ids) != WOMEN_PER_SQUAD:
        errors.append(f"needs {WOMEN_PER_SQUAD} women (has {len(women_ids)})")
    return errors


def lineup_errors(pairs, net_types, squad_ids, players):
    """Validate a lineup: every seat filled from the right pool, everyone plays exactly once."""
    errors = []
    seen = []
    for i, (pair, t) in enumerate(zip(pairs, net_types)):
        for seat, (pid, pool) in enumerate(zip(pair, NET_SLOTS[t])):
            if pid is None:
                errors.append(f"Net {i+1}: seat {seat+1} is empty")
                continue
            if (pool == "women") != is_woman(players[pid]):
                errors.append(f"Net {i+1}: {players[pid]['name']} can't fill a "
                              f"{'women' if pool == 'women' else 'open'} seat")
            seen.append(pid)
    dupes = sorted({players[p]["name"] for p in seen if seen.count(p) > 1})
    if dupes:
        errors.append(f"Listed on more than one net: {', '.join(dupes)}")
    missing = [players[p]["name"] for p in squad_ids if p not in seen]
    if missing and not any("empty" in e for e in errors):
        errors.append(f"Not on a net: {', '.join(missing)}")
    return errors


def _slots(net_types):
    open_slots, women_slots = [], []
    for i, t in enumerate(net_types):
        for seat, pool in enumerate(NET_SLOTS[t]):
            (women_slots if pool == "women" else open_slots).append((i, seat))
    return open_slots, women_slots


def enumerate_lineups(squad_ids, net_types, players):
    """
    Every distinct way to seat a squad on the given nets (net order matters; the order
    of two same-pool partners doesn't). ≤ 7!·3! / symmetries ≈ a few thousand lineups.
    """
    open_ids, women_ids = split_pools(squad_ids, players)
    open_slots, women_slots = _slots(net_types)
    if len(open_ids) != len(open_slots) or len(women_ids) != len(women_slots):
        return []
    same_pool = [i for i, t in enumerate(net_types) if t != "coed"]
    out = []
    for op in permutations(sorted(open_ids)):
        for wp in permutations(sorted(women_ids)):
            nets = [[None, None] for _ in net_types]
            for (i, seat), pid in zip(open_slots, op):
                nets[i][seat] = pid
            for (i, seat), pid in zip(women_slots, wp):
                nets[i][seat] = pid
            if any(nets[i][0] > nets[i][1] for i in same_pool):
                continue  # mirror image of a lineup already produced
            out.append(nets)
    return out


def _tidy(nets, net_types, ranks):
    """Same-pool partners listed stronger-first (coed stays [open, woman])."""
    return [list(p) if t == "coed" else sorted(p, key=lambda pid: ranks[pid])
            for p, t in zip(nets, net_types)]


def suggest_setting_lineup(squad_ids, shape, ranks, players, variant=0):
    """
    A starting-point lineup for the setting team: pairs strong with developing players so
    pair scores within each net type are as even as possible. Nets of the same type are
    listed strongest-first. variant rotates through other near-balanced lineups.
    """
    net_types = SHAPES[shape]["nets"]
    by_key = {}
    for nets in enumerate_lineups(squad_ids, net_types, players):
        # Canonical form: within each net type, order nets by score (then ids).
        order = sorted(range(len(nets)),
                       key=lambda i: (net_types.index(net_types[i]), pair_score(nets[i], ranks), nets[i]))
        canon = [nets[i] for i in order]
        by_key.setdefault(tuple(tuple(p) for p in canon), canon)

    def imbalance(nets):
        total = 0
        for t in set(net_types):
            scores = [pair_score(p, ranks) for p, nt in zip(nets, net_types) if nt == t]
            total += max(scores) - min(scores)
        return total

    def open_net_strength(nets):
        # Tie-break: strongest open players on the open nets (lower total = stronger).
        return sum(pair_score(p, ranks) for p, t in zip(nets, net_types) if t == "open")

    candidates = sorted(by_key.values(), key=lambda n: (imbalance(n), open_net_strength(n), n))
    if not candidates:
        return None
    best = imbalance(candidates[0])
    pool = [n for n in candidates if imbalance(n) <= best + SUGGEST_SLACK]
    return _tidy(pool[variant % len(pool)], net_types, ranks)


def matching_candidates(setting_pairs, net_types, ranks_set, squad_ids, ranks_match, players):
    """
    All lineups the matching team could field, most even first: sorted by (largest net
    gap, total gap). Returns [(pairs, gaps)]. A lineup is legal when every gap ≤ tolerance.
    """
    scored = []
    for nets in enumerate_lineups(squad_ids, net_types, players):
        gaps = net_gaps(setting_pairs, nets, ranks_set, ranks_match)
        scored.append((_tidy(nets, net_types, ranks_match), gaps))
    scored.sort(key=lambda x: (max(x[1]), sum(x[1]), x[0]))
    return scored


def is_legal(gaps, tolerance=MATCH_TOLERANCE):
    return all(g <= tolerance for g in gaps)
