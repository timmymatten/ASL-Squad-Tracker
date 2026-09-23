"""
K-means skill grouping.

Replaces manual skill-group assignment with KMeans(n_clusters=4) over one of two
feature sets:

  * "rating"      — each player's current Glicko-2 rating (1-D), from core.ratings.
  * "performance" — each player's (win_rate, games_played) from this app's own stats,
                    standardized so the two very-different scales weigh equally.

Clusters are relabelled by centroid so numbering is stable match to match: Group 1 is
always the strongest cluster, Group 4 the weakest. The output — {pid: group} with groups
1..4 — is exactly what generate_squads / the pairing engine already consume, so nothing
downstream changes.

Edge cases handled:
  * Fewer than 4 distinct feature values (small turnout) → fall back to k = #distinct.
  * Players with no rating / zero games → assigned to the median cluster and flagged
    ("unrated" / "insufficient data") so the UI can surface the fallback.
"""
import statistics

import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from core import ratings as ratings_mod

MODE_RATING = "rating"
MODE_PERFORMANCE = "performance"
DEFAULT_MODE = MODE_RATING

MIN_GAMES_FOR_PERFORMANCE = 3  # "enough games played" threshold used for the home banner


def _kmeans_labels(feature_matrix, k):
    """Fit KMeans and return (labels, model). feature_matrix is (n_samples, n_features)."""
    model = KMeans(n_clusters=k, n_init=10, random_state=0)
    labels = model.fit_predict(feature_matrix)
    return labels, model


def _relabel_by_centroid(rank_values):
    """
    Map raw KMeans labels → group numbers 1..k, strongest cluster = Group 1.

    rank_values[label] is the sort key for a cluster (higher = stronger). Returns
    {raw_label: group_number}.
    """
    ordered = sorted(rank_values, key=lambda lbl: rank_values[lbl], reverse=True)
    return {lbl: i + 1 for i, lbl in enumerate(ordered)}


def _median_group(assigned_groups, k):
    """Group number of the median cluster, for defaulting flagged players."""
    if assigned_groups:
        return max(1, min(k, int(round(statistics.median(assigned_groups)))))
    return (k + 1) // 2


def cluster_by_rating(pids, players):
    """
    Cluster the given player ids by Glicko-2 rating. Returns a result dict (see
    _result_shape below). Players without a rating are flagged "unrated" and placed
    in the median cluster.
    """
    ratings, _unmatched = ratings_mod.player_ratings({pid: players[pid] for pid in pids})

    rated = [pid for pid in pids if pid in ratings]
    flagged = {pid: "unrated" for pid in pids if pid not in ratings}

    groups = {}
    centroids = []
    distinct = sorted({round(ratings[pid], 6) for pid in rated})
    k = min(4, len(distinct)) if distinct else 0

    if k >= 1:
        X = np.array([[ratings[pid]] for pid in rated], dtype=float)
        labels, model = _kmeans_labels(X, k)
        centroid_val = {lbl: float(model.cluster_centers_[lbl][0]) for lbl in set(labels)}
        remap = _relabel_by_centroid(centroid_val)
        for pid, lbl in zip(rated, labels):
            groups[pid] = remap[lbl]
        for lbl, grp in remap.items():
            centroids.append({"group": grp, "rating": centroid_val[lbl]})
        centroids.sort(key=lambda c: c["group"])

    med = _median_group(list(groups.values()), max(k, 1))
    for pid in flagged:
        groups[pid] = med

    # Underlying value per player for the viz/hover (defaulted → the median centroid rating).
    med_rating = next((c["rating"] for c in centroids if c["group"] == med), None)
    values = {}
    for pid in pids:
        values[pid] = {
            "rating": ratings.get(pid, med_rating),
            "defaulted": pid in flagged,
        }

    return {
        "mode": MODE_RATING,
        "groups": groups,
        "flagged": flagged,
        "values": values,
        "centroids": centroids,
        "k": k,
        "n_players": len(pids),
        "n_flagged": len(flagged),
        "median_group": med,
    }


def cluster_by_performance(pids, players, stats):
    """
    Cluster the given player ids by standardized (win_rate, games_played) from this app's
    stats. Players with zero games are flagged "insufficient data" and placed in the
    median cluster. `stats` is core.stats.compute_stats output.
    """
    def win_rate(pid):
        s = stats.get(pid, {})
        g = s.get("games", 0)
        return (s.get("wins", 0) / g) if g else 0.0

    def games(pid):
        return stats.get(pid, {}).get("games", 0)

    played = [pid for pid in pids if games(pid) > 0]
    flagged = {pid: "insufficient data" for pid in pids if games(pid) == 0}

    groups = {}
    centroids = []
    # Distinct on the raw (win_rate, games) pairs decides the achievable cluster count.
    distinct = sorted({(round(win_rate(pid), 6), games(pid)) for pid in played})
    k = min(4, len(distinct)) if distinct else 0

    if k >= 1:
        raw = np.array([[win_rate(pid), games(pid)] for pid in played], dtype=float)
        scaler = StandardScaler()
        X = scaler.fit_transform(raw)
        labels, model = _kmeans_labels(X, k)
        # Centroids back in real units for ranking + display.
        real_centroids = scaler.inverse_transform(model.cluster_centers_)
        centroid_map = {
            lbl: {"win_rate": float(real_centroids[lbl][0]), "games": float(real_centroids[lbl][1])}
            for lbl in set(labels)
        }
        # Rank by win_rate centroid, ties broken by games_played centroid.
        rank_values = {
            lbl: (centroid_map[lbl]["win_rate"], centroid_map[lbl]["games"]) for lbl in centroid_map
        }
        remap = _relabel_by_centroid(rank_values)
        for pid, lbl in zip(played, labels):
            groups[pid] = remap[lbl]
        for lbl, grp in remap.items():
            centroids.append({"group": grp, **centroid_map[lbl]})
        centroids.sort(key=lambda c: c["group"])

    med = _median_group(list(groups.values()), max(k, 1))
    for pid in flagged:
        groups[pid] = med

    values = {}
    for pid in pids:
        values[pid] = {
            "win_rate": win_rate(pid),
            "games": games(pid),
            "defaulted": pid in flagged,
        }

    return {
        "mode": MODE_PERFORMANCE,
        "groups": groups,
        "flagged": flagged,
        "values": values,
        "centroids": centroids,
        "k": k,
        "n_players": len(pids),
        "n_flagged": len(flagged),
        "median_group": med,
    }


def compute_clusters(mode, pids, players, stats=None):
    """Dispatch to the right clustering function for `mode`."""
    pids = list(pids)
    if mode == MODE_PERFORMANCE:
        return cluster_by_performance(pids, players, stats or {})
    return cluster_by_rating(pids, players)


def enough_games_summary(pids, stats, threshold=MIN_GAMES_FOR_PERFORMANCE):
    """Return (n_with_enough, total) for the home-page banner."""
    pids = list(pids)
    n = sum(1 for pid in pids if stats.get(pid, {}).get("games", 0) >= threshold)
    return n, len(pids)
