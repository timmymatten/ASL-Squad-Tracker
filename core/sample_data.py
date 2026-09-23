"""
Generate the SAMPLE dataset (data_sample.json) full of realistic history.

This NEVER touches your real data — it only reads the player roster from the real file,
then writes synthetic match days to the sample file. Callable from the app (sidebar
"Regenerate" button) or the command line (scripts/seed_sample_data.py).

Realism guarantee: this reuses the *exact* match-day pipeline the app uses
(select_players_for_format, generate_format_squads, squad ranking, the setting team's
suggested lineup and the matching team's most-even legal response). Every produced match
day is therefore something the app itself could have generated. Net scores are simulated
as standard games to 21, with the stronger pair (lower average skill group) modestly
favored — the same gentle tilt you'd see IRL despite balanced squads.

The format needs 14 open players + 6 women per match day, so if the real roster is short
of either, the sample roster is padded with clearly-named synthetic players (sample
dataset only — the real roster is never modified).

No Streamlit dependency, so it stays importable from a plain CLI.
"""
import random
import uuid
from datetime import date, timedelta

from core import storage
from core.algorithms import generate_format_squads, select_players_for_format
from core.lineups import (
    OPEN_PER_SQUAD,
    WOMEN_PER_SQUAD,
    SHAPES,
    split_pools,
    squad_ranks,
    setting_side,
    suggest_setting_lineup,
    matching_candidates,
    is_legal,
)
from core.stats import compute_stats

N_MATCH_DAYS = 50
# Pool sizes to keep active so random attendance usually fills a full match day.
MIN_OPEN_ROSTER = 2 * OPEN_PER_SQUAD + 4
MIN_WOMEN_ROSTER = 2 * WOMEN_PER_SQUAD + 2


def _pad_roster(players):
    """Copy of the roster with synthetic players added until each pool is deep enough."""
    players = dict(players)
    active = [pid for pid, p in players.items() if p.get("active")]
    open_ids, women_ids = split_pools(active, players)
    for pool, have, need, gender, word in (
        ("open", len(open_ids), MIN_OPEN_ROSTER, "M", "Open"),
        ("women", len(women_ids), MIN_WOMEN_ROSTER, "F", "Woman"),
    ):
        for i in range(need - have):
            pid = f"sample_{pool}_{i + 1}"
            players[pid] = {"name": f"Sample {word} {i + 1}", "group": random.randint(1, 4),
                            "gender": gender, "active": True, "synthetic": True}
    return players


def _pair_strength(pair, players):
    """Average skill group of a duo (lower = stronger)."""
    return sum(players[p]["group"] for p in pair) / len(pair)


def _simulate_net(pair_a, pair_b, players):
    """Standard game to 21. Stronger (lower-group) pair modestly favored."""
    gap = _pair_strength(pair_b, players) - _pair_strength(pair_a, players)  # >0 → A stronger
    p_a = 0.5 + max(-0.38, min(0.38, 0.13 * gap))
    a_wins = random.random() < p_a

    margin = int(round(random.uniform(2, 11) + abs(gap) * 2.0))
    margin = max(2, min(19, margin))
    loser = 21 - margin

    if a_wins:
        return 21, loser, "A"
    return loser, 21, "B"


def _attend(pool, attend_rate, need):
    """Who shows up from a pool; topped up from absentees so the format can be filled."""
    present = [pid for pid in pool if random.random() < attend_rate[pid]]
    absent = [pid for pid in pool if pid not in present]
    random.shuffle(absent)
    return present + absent[: max(0, need - len(present))]


def _simulate_match_day(d, players, active, attend_rate, match_days_so_far):
    open_pool, women_pool = split_pools(active, players)
    present = (_attend(open_pool, attend_rate, 2 * OPEN_PER_SQUAD)
               + _attend(women_pool, attend_rate, 2 * WOMEN_PER_SQUAD))
    # Per-pool cap, exactly like the app (uses attendance history for fairness).
    present, _ = select_players_for_format(present, players, match_days_so_far)

    squad_a, squad_b = generate_format_squads(present, players)
    stats = compute_stats({"players": players, "match_days": match_days_so_far})
    ranks = {"a": squad_ranks(squad_a, stats, players), "b": squad_ranks(squad_b, stats, players)}
    squads = {"a": squad_a, "b": squad_b}

    match = {
        "id": str(uuid.uuid4())[:8],
        "date": str(d),
        "present": present,
        "squad_a": squad_a,
        "squad_b": squad_b,
        "setting_first": random.choice(["a", "b"]),
        "games": [],
        "squad_wins": {"a": 0, "b": 0},
        "completed": True,
        "step": "done",
        "synthetic": True,
    }

    for game_num in range(1, random.randint(2, 5) + 1):
        side = setting_side(match, game_num)
        other = "b" if side == "a" else "a"
        shape = random.choice(list(SHAPES))
        net_types = SHAPES[shape]["nets"]
        set_pairs = suggest_setting_lineup(squads[side], shape, ranks[side], players,
                                           variant=random.randrange(10))
        candidates = matching_candidates(set_pairs, net_types, ranks[side],
                                         squads[other], ranks[other], players)
        legal = [c for c in candidates if is_legal(c[1])]
        mat_pairs = random.choice(legal[:10])[0] if legal else candidates[0][0]
        pairs = {side: set_pairs, other: mat_pairs}

        results, scores = [], []
        for pa, pb in zip(pairs["a"], pairs["b"]):
            a_pts, b_pts, winner = _simulate_net(pa, pb, players)
            results.append(winner)
            scores.append([a_pts, b_pts])

        wins_a = results.count("A")
        wins_b = results.count("B")
        match["squad_wins"]["a"] += wins_a
        match["squad_wins"]["b"] += wins_b

        match["games"].append({
            "game_num": game_num,
            "setting": side,
            "shape": shape,
            "net_types": net_types,
            "pairings_a": [list(p) for p in pairs["a"]],
            "pairings_b": [list(p) for p in pairs["b"]],
            "ranks_a": ranks["a"],
            "ranks_b": ranks["b"],
            "sit_a": None,
            "sit_b": None,
            "n_nets": len(net_types),
            "results": results,
            "scores": scores,
            "game_winner": "a" if wins_a > wins_b else ("b" if wins_b > wins_a else "tie"),
        })

    return match


def generate_sample(n_match_days=N_MATCH_DAYS, seed=None):
    """
    Build the 'sample' dataset from the real roster. Returns a summary dict:
        {"match_days", "games", "nets", "players"}.

    Reads only the 'real' dataset (for the roster); writes only the 'sample' dataset.
    Backend (Supabase or local file) is whatever core.storage is configured for.
    Pass seed=<int> for reproducible output; seed=None gives fresh data each call.
    """
    if seed is not None:
        random.seed(seed)

    source = storage.read_dataset("real")
    players = _pad_roster(source["players"])
    active = [pid for pid, p in players.items() if p.get("active")]

    # Personal attendance rates → realistic mix of regulars and occasionals.
    attend_rate = {pid: random.uniform(0.45, 0.9) for pid in active}

    # Anchor the synthetic season in the weeks before the earliest real session.
    real_dates = [md["date"] for md in source.get("match_days", []) if md.get("date")]
    anchor = min(real_dates) if real_dates else str(date.today())
    anchor_date = date.fromisoformat(anchor)
    dates = [anchor_date - timedelta(weeks=i) for i in range(1, n_match_days + 1)]
    dates.reverse()  # oldest first → chronological

    synthetic = []
    for d in dates:
        synthetic.append(_simulate_match_day(d, players, active, attend_rate, synthetic))

    sample = {"players": players, "match_days": synthetic}
    storage.write_dataset("sample", sample)

    return {
        "match_days": len(synthetic),
        "games": sum(len(md["games"]) for md in synthetic),
        "nets": sum(len(g["results"]) for md in synthetic for g in md["games"]),
        "players": len(players),
    }
