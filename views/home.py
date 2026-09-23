import plotly.graph_objects as go
import streamlit as st

from core.constants import GROUP_PALETTE, GROUP_RANK_LABELS
from core.persistence import get_data
from core.stats import compute_stats
from core import clustering


def _legend_name(group):
    return GROUP_RANK_LABELS.get(group, f"Group {group}")


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
        return "Every player has game history — no fallback assignments."
    return (f"⚠️ {n} player{'s' if n != 1 else ''} with no games yet — "
            f"defaulted to the median cluster (Group {result['median_group']}) and marked with an ✕.")


def page_home():
    data = get_data()
    players = data["players"]
    active = [pid for pid, p in players.items() if p["active"]]

    st.title("🏠 Home")
    st.caption("For reference only: k-means clustering of players by **win rate** and "
               "**games played**. Match days use each player's **roster group**; nothing "
               "here changes them.")

    if len(active) < 2:
        st.warning("Add at least 2 active players on the Roster page to see clustering.")
        return

    stats = compute_stats(data)
    result = clustering.cluster_by_performance(active, players, stats)

    if result["k"] == 0:
        st.info("No games recorded yet — play a match day to see the chart.")
    else:
        st.plotly_chart(_build_performance_chart(result, players), use_container_width=True)
        st.caption(_fallback_caption(result))

    n_enough, total = clustering.enough_games_summary(active, stats)
    st.divider()
    st.markdown(f"**{n_enough} of {total} players have {clustering.MIN_GAMES}+ games played.**")
