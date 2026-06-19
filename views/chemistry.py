import streamlit as st
import altair as alt
import pandas as pd

from core.constants import GROUP_COLORS
from core.persistence import get_data
from core.stats import partnership_stats, MIN_PARTNER_GAMES


def page_chemistry():
    data = get_data()
    players = data["players"]

    st.title("🤝 Partner Chemistry")

    pairs = partnership_stats(data)
    if not pairs:
        st.info("No partnerships yet — play some match days first!")
        return

    def pname(pid):
        return players.get(pid, {}).get("name", "?")

    def pcolor(pid):
        p = players.get(pid)
        return GROUP_COLORS[p["group"]] if p else "⚪"

    tab_board, tab_matrix = st.tabs(["🏆 Partnerships", "🔲 Full Matrix"])

    with tab_board:
        _leaderboard_tab(pairs, pname, pcolor)

    with tab_matrix:
        _matrix_tab(pairs, players, pname)


def _leaderboard_tab(pairs, pname, pcolor):
    qualified = [
        {
            "a": a, "b": b,
            "games": r["games"],
            "wins": r["wins"],
            "win_pct": r["wins"] / r["games"],
            "point_diff": r["point_diff"],
            "avg_diff": r["point_diff"] / r["games"],
        }
        for (a, b), r in pairs.items()
        if r["games"] >= MIN_PARTNER_GAMES
    ]

    # Cheap bonus: most-paired duo across all data (no min-games gate).
    (top_a, top_b), top_rec = max(pairs.items(), key=lambda kv: kv[1]["games"])
    st.caption(
        f"Most-paired duo: **{pname(top_a)} & {pname(top_b)}** "
        f"({top_rec['games']} games together)"
    )

    if not qualified:
        st.info(
            f"No duo has played at least {MIN_PARTNER_GAMES} games together yet — "
            "partnerships need more shared games before they show up here."
        )
        return

    def render(rows, title):
        st.subheader(title)
        for s in rows:
            st.markdown(
                f"{pcolor(s['a'])} **{pname(s['a'])}** & {pcolor(s['b'])} **{pname(s['b'])}** "
                f"· {s['games']} games · **{s['win_pct']*100:.0f}%** "
                f"· {s['point_diff']:+d} diff ({s['avg_diff']:+.1f}/game)"
            )

    best = sorted(qualified, key=lambda s: (s["win_pct"], s["avg_diff"]), reverse=True)
    worst = sorted(qualified, key=lambda s: (s["win_pct"], s["avg_diff"]))

    st.caption(f"Duos with at least {MIN_PARTNER_GAMES} games together.")
    c1, c2 = st.columns(2)
    with c1:
        render(best[:10], "🔥 Best Partnerships")
    with c2:
        render(worst[:10], "🧊 Coldest Partnerships")


def _matrix_tab(pairs, players, pname):
    metric = st.radio(
        "Cell metric",
        ["Win %", "Games together", "Avg point diff"],
        horizontal=True,
    )

    # Players who have teamed up at least once, ordered by (group, name).
    involved = sorted(
        {pid for pair in pairs for pid in pair},
        key=lambda pid: (players.get(pid, {}).get("group", 99), pname(pid)),
    )
    order = [pname(pid) for pid in involved]

    # Symmetric long-form rows (both directions) for every duo with ≥1 game.
    rows = []
    for (a, b), r in pairs.items():
        win_pct = r["wins"] / r["games"]
        avg_diff = r["point_diff"] / r["games"]
        record = f"{r['wins']}-{r['games'] - r['wins']}"
        if metric == "Win %":
            value = round(win_pct * 100, 1)
        elif metric == "Games together":
            value = r["games"]
        else:
            value = round(avg_diff, 1)
        for x, y in ((a, b), (b, a)):
            rows.append({
                "Player": pname(x),
                "Partner": pname(y),
                "value": value,
                "games": r["games"],
                "record": record,
                "win_pct": f"{win_pct*100:.0f}%",
                "point_diff": r["point_diff"],
            })

    df = pd.DataFrame(rows)

    diverging = metric == "Avg point diff"
    scheme = "redyellowgreen" if diverging else "greens"
    color = alt.Color(
        "value:Q",
        title=metric,
        scale=alt.Scale(scheme=scheme, domainMid=0) if diverging else alt.Scale(scheme=scheme),
    )

    chart = (
        alt.Chart(df)
        .mark_rect()
        .encode(
            x=alt.X("Player:N", sort=order, title=None),
            y=alt.Y("Partner:N", sort=order, title=None),
            color=color,
            tooltip=[
                alt.Tooltip("Player:N"),
                alt.Tooltip("Partner:N"),
                alt.Tooltip("games:Q", title="Games together"),
                alt.Tooltip("record:N", title="Record (W-L)"),
                alt.Tooltip("win_pct:N", title="Win %"),
                alt.Tooltip("point_diff:Q", title="Point diff"),
            ],
        )
        .properties(height=max(300, 22 * len(order)))
    )

    st.altair_chart(chart, use_container_width=True)
    st.caption(
        "Every cell counts all shared games (no minimum here), so low-sample duos appear "
        "too — hover to see the game count. Blank cells = never teamed up."
    )
