"""
Generate the SAMPLE dataset (data_sample.json) full of realistic history.

This NEVER touches your real data — it only reads the player roster from the real file,
then writes synthetic match days to the sample file. Callable from the app (sidebar
"Regenerate" button) or the command line (seed_sample_data.py).

Realism guarantee: this reuses the *exact* match-day pipeline the app uses
(generate_squads, pick_sitter, find_best_pairing, sort_pairs_by_score, the 16-player
cap, the no-repeat-pair rule, sitter rotation). Every produced match day is therefore
something the app itself could have generated. Net scores are simulated as standard
games to 21, with the stronger pair (lower average skill group) modestly favored — the
same gentle tilt you'd see IRL despite balanced squads.

No Streamlit dependency, so it stays importable from a plain CLI.
"""
import random
import uuid
from datetime import date, timedelta

from core import storage
from core.algorithms import (
    generate_squads,
    find_best_pairing,
    pick_sitter,
    sort_pairs_by_score,
    select_players_for_session,
)

N_MATCH_DAYS = 50
MAX_PLAYERS = 16


def _default_rank_order(squad_ids, players):
    return sorted(squad_ids, key=lambda p: (players[p]["group"], players[p]["name"]))


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


def _simulate_match_day(d, players, active, attend_rate, match_days_so_far):
    # Attendance: each regular shows up per their personal rate.
    present = [pid for pid in active if random.random() < attend_rate[pid]]
    while len(present) < 4:
        present = random.sample(active, min(len(active), max(4, len(present) + 2)))

    # 16-player cap, exactly like the app (uses attendance history for fairness).
    if len(present) > MAX_PLAYERS:
        present, _ = select_players_for_session(present, players, match_days_so_far, MAX_PLAYERS)

    squad_a, squad_b = generate_squads(present, players)
    rank_a = _default_rank_order(squad_a, players)
    rank_b = _default_rank_order(squad_b, players)
    ranks_a = {pid: i + 1 for i, pid in enumerate(rank_a)}
    ranks_b = {pid: i + 1 for i, pid in enumerate(rank_b)}

    games = []
    sit_hist_a, sit_hist_b = [], []
    squad_wins = {"a": 0, "b": 0}

    for game_num in range(1, random.randint(2, 5) + 1):
        # Avoid repeating last game's pairs (same rule as _pairing_context).
        forbidden_a, forbidden_b = set(), set()
        if games:
            for p in games[-1]["pairings_a"]:
                forbidden_a.add(frozenset(p))
            for p in games[-1]["pairings_b"]:
                forbidden_b.add(frozenset(p))

        active_a, active_b = list(squad_a), list(squad_b)
        sit_a = sit_b = None
        if len(active_a) % 2:
            sit_a = pick_sitter(active_a, sit_hist_a)
            active_a = [p for p in active_a if p != sit_a]
            sit_hist_a.append(sit_a)
        if len(active_b) % 2:
            sit_b = pick_sitter(active_b, sit_hist_b)
            active_b = [p for p in active_b if p != sit_b]
            sit_hist_b.append(sit_b)

        pairs_a = find_best_pairing(active_a, ranks_a, forbidden_a)
        pairs_b = find_best_pairing(active_b, ranks_b, forbidden_b)
        if not pairs_a or not pairs_b:
            break
        pairs_a = sort_pairs_by_score(pairs_a, ranks_a)
        pairs_b = sort_pairs_by_score(pairs_b, ranks_b)
        n_nets = min(len(pairs_a), len(pairs_b))

        results, scores = [], []
        for i in range(n_nets):
            a_pts, b_pts, winner = _simulate_net(pairs_a[i], pairs_b[i], players)
            results.append(winner)
            scores.append([a_pts, b_pts])

        wins_a = results.count("A")
        wins_b = results.count("B")
        squad_wins["a"] += wins_a
        squad_wins["b"] += wins_b

        games.append({
            "game_num": game_num,
            "pairings_a": [list(p) for p in pairs_a],
            "pairings_b": [list(p) for p in pairs_b],
            "sit_a": sit_a,
            "sit_b": sit_b,
            "n_nets": n_nets,
            "results": results,
            "scores": scores,
            "game_winner": "a" if wins_a > wins_b else ("b" if wins_b > wins_a else "tie"),
        })

    return {
        "id": str(uuid.uuid4())[:8],
        "date": str(d),
        "present": present,
        "squad_a": squad_a,
        "squad_b": squad_b,
        "rank_a": rank_a,
        "rank_b": rank_b,
        "games": games,
        "squad_wins": squad_wins,
        "completed": True,
        "step": "done",
        "synthetic": True,
    }


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
    players = source["players"]
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
