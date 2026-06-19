# ─── Partner chemistry ──────────────────────────────────────────────────────

MIN_PARTNER_GAMES = 3  # nets a duo must have played together to qualify for the leaderboard


def partnership_stats(data):
    """
    How each duo performs when teamed up, replayed from match history.

    Returns {(pid_lo, pid_hi): {"games", "wins", "point_diff"}} where the key is
    the order-independent partnership. point_diff is the duo's cumulative net margin
    (positive = outscored opponents). Mirrors compute_stats's replay + score guard.
    """
    pairs = {}

    def record(pair, won, margin):
        if len(pair) != 2 or pair[0] == pair[1]:
            return
        key = tuple(sorted(pair))
        rec = pairs.setdefault(key, {"games": 0, "wins": 0, "point_diff": 0})
        rec["games"] += 1
        rec["wins"] += 1 if won else 0
        rec["point_diff"] += margin

    for md in data["match_days"]:
        if not md.get("completed"):
            continue
        for game in md.get("games", []):
            results = game.get("results") or []
            scores = game.get("scores") or []
            pairings_a = game.get("pairings_a", [])
            pairings_b = game.get("pairings_b", [])

            for i, winner in enumerate(results):
                if i < len(scores):
                    a_pts, b_pts = scores[i]
                else:
                    a_pts = b_pts = 0
                if i < len(pairings_a):
                    record(pairings_a[i], winner == "A", a_pts - b_pts)
                if i < len(pairings_b):
                    record(pairings_b[i], winner == "B", b_pts - a_pts)

    return pairs


# ─── Promotion suggestions ──────────────────────────────────────────────────
# Squad/pairing balancing pushes every net toward a coin flip, so a player who
# keeps winning well above even despite balancing is under-ranked → promote.

MIN_GAMES = 10          # nets played before a player is eligible
PROMOTE_THRESHOLD = 0.10  # blended over-performance needed to suggest a promotion
STRONG_THRESHOLD = 0.20   # blended over-performance for a "strong" suggestion


def promotion_suggestions(stats):
    """
    From compute_stats output, return promotion suggestions sorted strongest first.

    A player is suggested for promotion (to a lower-numbered, stronger group) when,
    over at least MIN_GAMES nets, they over-perform both a 50% baseline and their
    group's average win rate, confirmed by a positive average point differential.
    Each suggestion is a dict:
        {pid, name, group, suggested_group, win_pct, games,
         point_diff, avg_diff, group_avg, blend, strength}
    """
    # Average win% of established players (>= MIN_GAMES) per group, for peer comparison.
    group_pcts = {}
    for s in stats.values():
        if s["games"] >= MIN_GAMES:
            group_pcts.setdefault(s["group"], []).append(s["wins"] / s["games"])

    suggestions = []
    for pid, s in stats.items():
        games = s["games"]
        group = s["group"]
        if games < MIN_GAMES or group <= 1:
            continue

        win_pct = s["wins"] / games
        avg_diff = s["point_diff"] / games

        # Peer baseline: other established players in the same group; else neutral 0.50.
        others = [p for p in group_pcts.get(group, []) if p != win_pct]
        group_avg = sum(others) / len(others) if others else 0.50

        blend = 0.5 * (win_pct - 0.50) + 0.5 * (win_pct - group_avg)

        if blend < PROMOTE_THRESHOLD or avg_diff <= 0:
            continue

        strength = "strong" if (blend >= STRONG_THRESHOLD and avg_diff >= 3) else "consider"
        suggestions.append({
            "pid": pid,
            "name": s["name"],
            "group": group,
            "suggested_group": group - 1,
            "win_pct": win_pct,
            "games": games,
            "point_diff": s["point_diff"],
            "avg_diff": avg_diff,
            "group_avg": group_avg,
            "blend": blend,
            "strength": strength,
        })

    suggestions.sort(key=lambda x: x["blend"], reverse=True)
    return suggestions


def compute_stats(data):
    players = data["players"]
    stats = {
        pid: {
            "name": p["name"],
            "group": p["group"],
            "wins": 0,
            "games": 0,
            "attendance": 0,
            "upsets": 0,
            "points_for": 0,
            "points_against": 0,
            "point_diff": 0,
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
            scores = game.get("scores") or []
            pairs_a = game.get("pairings_a", [])
            pairs_b = game.get("pairings_b", [])

            for i, winner in enumerate(results):
                pa_pair = pairs_a[i] if i < len(pairs_a) else []
                pb_pair = pairs_b[i] if i < len(pairs_b) else []

                if i < len(scores):
                    a_pts, b_pts = scores[i]
                    for pid in pa_pair:
                        if pid in stats:
                            stats[pid]["points_for"] += a_pts
                            stats[pid]["points_against"] += b_pts
                    for pid in pb_pair:
                        if pid in stats:
                            stats[pid]["points_for"] += b_pts
                            stats[pid]["points_against"] += a_pts

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

    for s in stats.values():
        s["point_diff"] = s["points_for"] - s["points_against"]

    return stats
