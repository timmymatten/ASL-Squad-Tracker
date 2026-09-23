import plotly.graph_objects as go
import streamlit as st

from core.constants import GROUP_PALETTE, GROUP_RANK_LABELS
from core.persistence import get_data, get_clustering_mode, set_clustering_mode
from core.stats import compute_stats
from core import clustering


# Deterministic vertical jitter so the strip plot is stable across reruns (no RNG).
def _jitter(i):
    return ((i * 0.6180339887) % 1.0 - 0.5) * 0.8


def _legend_name(group):
    return GROUP_RANK_LABELS.get(group, f"Group {group}")


def _build_rating_chart(result, players):
    """Horizontal strip plot of rating, one point per player, colored by group."""
    fig = go.Figure()
    groups_present = sorted({g for g in result["groups"].values()})

    for g in groups_present:
        pids = [pid for pid, grp in result["groups"].items() if grp == g]
        xs, ys, text, symbols, line_w = [], [], [], [], []
        for i, pid in enumerate(pids):
            v = result["values"][pid]
            xs.append(v["rating"])
            ys.append(_jitter(i))
            defaulted = v["defaulted"]
            tag = "<br><b>unrated — defaulted</b>" if defaulted else ""
            text.append(f"{players[pid]['name']}<br>Rating: {round(v['rating'])}{tag}")
            symbols.append("x" if defaulted else "circle")
            line_w.append(2)
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=_legend_name(g),
            marker=dict(size=13, color=GROUP_PALETTE.get(g, "#888"), symbol=symbols,
                        line=dict(width=line_w, color="#fcfcfb")),
            hovertext=text, hoverinfo="text",
        ))

    # Vertical dashed line marking each cluster centroid.
    for c in result["centroids"]:
        fig.add_vline(x=c["rating"], line=dict(color=GROUP_PALETTE.get(c["group"], "#888"),
                                               width=1, dash="dash"))

    fig.update_layout(
        height=340, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Glicko-2 rating", legend_title_text="",
        yaxis=dict(showticklabels=False, zeroline=False, range=[-0.8, 0.8]),
        hovermode="closest",
    )
    return fig


def _build_performance_chart(result, players):
    """Scatter of win_rate (x) vs games_played (y), colored by group."""
    fig = go.Figure()
    groups_present = sorted({g for g in result["groups"].values()})

    for g in groups_present:
        pids = [pid for pid, grp in result["groups"].items() if grp == g]
        xs, ys, text, symbols = [], [], [], []
        for pid in pids:
            v = result["values"][pid]
            xs.append(v["win_rate"])
            ys.append(v["games"])
            defaulted = v["defaulted"]
            tag = "<br><b>insufficient data — defaulted</b>" if defaulted else ""
            text.append(f"{players[pid]['name']}<br>Win rate: {v['win_rate']:.0%}"
                        f"<br>Games: {v['games']}{tag}")
            symbols.append("x" if defaulted else "circle")
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=_legend_name(g),
            marker=dict(size=13, color=GROUP_PALETTE.get(g, "#888"), symbol=symbols,
                        line=dict(width=2, color="#fcfcfb")),
            hovertext=text, hoverinfo="text",
        ))

    # Larger X at each cluster centroid.
    for c in result["centroids"]:
        fig.add_trace(go.Scatter(
            x=[c["win_rate"]], y=[c["games"]], mode="markers",
            marker=dict(size=20, symbol="x-thin", line=dict(width=3,
                        color=GROUP_PALETTE.get(c["group"], "#888"))),
            name=f"{_legend_name(c['group'])} centroid", showlegend=False,
            hovertext=f"{_legend_name(c['group'])} centroid<br>"
                      f"Win rate: {c['win_rate']:.0%}<br>Games: {round(c['games'])}",
            hoverinfo="text",
        ))

    fig.update_layout(
        height=340, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Win rate", yaxis_title="Games played", legend_title_text="",
        xaxis=dict(tickformat=".0%"), hovermode="closest",
    )
    return fig


def _fallback_caption(result):
    n = result["n_flagged"]
    if n == 0:
        return "All players had a value on record — no fallback assignments."
    word = "unrated" if result["mode"] == clustering.MODE_RATING else "with insufficient data"
    return (f"⚠️ {n} player{'s' if n != 1 else ''} {word} — "
            f"defaulted to the median cluster (Group {result['median_group']}) and marked with an ✕.")


def page_home():
    data = get_data()
    players = data["players"]
    active = [pid for pid, p in players.items() if p["active"]]

    st.title("🏠 Home")
    st.caption("Skill groups are built by k-means clustering. Choose what to cluster on; "
               "groups are recomputed at the start of each match day.")

    if len(active) < 2:
        st.warning("Add at least 2 active players on the Roster page to see clustering.")
        return

    # ── Clustering mode toggle (persisted in the dataset config) ────────────────
    mode = get_clustering_mode()
    labels = {
        clustering.MODE_RATING: "Rating-Based (Glicko-2)",
        clustering.MODE_PERFORMANCE: "Performance-Based (win rate + games)",
    }
    order = [clustering.MODE_RATING, clustering.MODE_PERFORMANCE]
    choice = st.radio(
        "Clustering Mode",
        order,
        index=order.index(mode) if mode in order else 0,
        format_func=lambda m: labels[m],
        horizontal=True,
        help="Rating-Based uses live NATS Glicko-2 ratings. Performance-Based uses this "
             "app's own win-rate and games-played history.",
    )
    if choice != mode:
        set_clustering_mode(choice)
        st.rerun()

    stats = compute_stats(data)
    result = clustering.compute_clusters(choice, active, players, stats)

    # ── Visualization ───────────────────────────────────────────────────────────
    if result["k"] == 0:
        st.info("Not enough data to cluster in this mode yet.")
    else:
        if choice == clustering.MODE_RATING:
            fig = _build_rating_chart(result, players)
        else:
            fig = _build_performance_chart(result, players)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(_fallback_caption(result))

    # ── Switch-mode banner ──────────────────────────────────────────────────────
    n_enough, total = clustering.enough_games_summary(active, stats)
    st.divider()
    st.markdown(f"**{n_enough} of {total} players have "
                f"{clustering.MIN_GAMES_FOR_PERFORMANCE}+ games played.**")
    if total and n_enough == total and choice == clustering.MODE_RATING:
        st.info("Everyone has enough game history — you could switch to **Performance-Based** "
                "mode. (Your call — the mode never changes automatically.)")
