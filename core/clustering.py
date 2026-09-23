"""
K-means performance clustering for the Home page chart (reference only — it never
changes a player's roster group).

Clusters players with KMeans(n_clusters=4) on (win_rate, games_played) from this app's
own stats, standardized so the two very-different scales weigh equally. Clusters are
relabelled by centroid so Group 1 is always the strongest cluster.

Edge cases handled:
  * Fewer than 4 distinct feature values → fall back to k = #distinct.
  * Players with zero games → assigned to the median cluster and flagged
    "insufficient data" so the UI can surface the fallback.
"""
import statistics

import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

MIN_GAMES = 3  # "enough games played" threshold used for the home banner


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
        "groups": groups,
        "flagged": flagged,
        "values": values,
        "centroids": centroids,
        "k": k,
        "n_players": len(pids),
        "n_flagged": len(flagged),
        "median_group": med,
    }


def enough_games_summary(pids, stats, threshold=MIN_GAMES):
    """Return (n_with_enough, total) for the home-page banner."""
    pids = list(pids)
    n = sum(1 for pid in pids if stats.get(pid, {}).get("games", 0) >= threshold)
    return n, len(pids)
