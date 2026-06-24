import streamlit as st
import altair as alt
import pandas as pd

from core.constants import GROUP_COLORS, GROUP_LABELS
from core.persistence import get_data
from core.stats import (
    compute_stats,
    partnership_stats,
    head_to_head_stats,
    player_timeline,
    promotion_suggestions,
    MIN_PARTNER_GAMES,
)


def page_player():
    data = get_data()
    players = data["players"]

    st.title("👤 Player Dashboard")

    if not players:
        st.info("No players yet — add some on the Roster page.")
        return

    def label(pid):
        p = players[pid]
        tag = "" if p.get("active", True) else "  (inactive)"
        return f"{GROUP_COLORS[p['group']]} {p['name']}{tag}"

    order = sorted(players, key=lambda pid: (players[pid]["group"], players[pid]["name"]))
    pid = st.selectbox("Player", order, format_func=label)
    st.divider()

    stats = compute_stats(data)
    s = stats[pid]
    p = players[pid]

    _header(p, s, pid, data, stats)

    if s["games"] == 0:
        st.info("This player hasn't played any games yet.")
        return

    _metrics(s)

    timeline = player_timeline(data, pid)
    _form(timeline)
    _trend_chart(timeline)
    _partners_and_opponents(data, pid, players)
    _recent_sessions(timeline)


def _header(p, s, pid, data, stats):
    timeline = player_timeline(data, pid)
    last_seen = timeline[-1]["date"] if timeline else "—"
    status = "✅ Active" if p.get("active", True) else "💤 Inactive"

    c1, c2 = st.columns([3, 2])
    with c1:
        st.subheader(f"{GROUP_COLORS[p['group']]} {p['name']}")
        st.caption(f"{GROUP_LABELS[p['group']]} · {status}")
    with c2:
        st.caption(f"🗓️ {s['attendance']} match days attended")
        st.caption(f"Last seen: {last_seen}")

    suggested = next((x for x in promotion_suggestions(stats) if x["pid"] == pid), None)
    if suggested:
        st.success(
            f"📈 Promotion candidate — outperforming Group {suggested['group']} "
            f"({suggested['win_pct']*100:.0f}% over {suggested['games']} games). "
            f"Suggested: Group {suggested['suggested_group']}."
        )


def _metrics(s):
    win_pct = s["wins"] / s["games"]
    avg_diff = s["point_diff"] / s["games"]
    cols = st.columns(6)
    cols[0].metric("Games", s["games"])
    cols[1].metric("Win %", f"{win_pct*100:.0f}%")
    cols[2].metric("Record", f"{s['wins']}-{s['games'] - s['wins']}")
    cols[3].metric("Point Diff", f"{s['point_diff']:+d}")
    cols[4].metric("Avg/game", f"{avg_diff:+.1f}")
    cols[5].metric("Upsets", s["upsets"])


def _form(timeline):
    """Current streak of winning vs losing *sessions* + a last-10-sessions record."""
    if not timeline:
        return

    def day_result(t):  # +1 winning day, -1 losing day, 0 even
        losses = t["games"] - t["wins"]
        return 1 if t["wins"] > losses else (-1 if losses > t["wins"] else 0)

    # Trailing run of same-direction (non-even) sessions, most recent first.
    streak, last_dir = 0, None
    for t in reversed(timeline):
        r = day_result(t)
        if r == 0 or (last_dir is not None and r != last_dir):
            break
        streak += 1
        last_dir = r

    if last_dir == 1:
        form = f"🔥 {streak} winning session(s) in a row"
    elif last_dir == -1:
        form = f"🧊 {streak} losing session(s) in a row"
    else:
        form = "even"

    recent = timeline[-10:]
    w = sum(t["wins"] for t in recent)
    g = sum(t["games"] for t in recent)
    st.caption(
        f"**Form:** {form} · last {len(recent)} sessions: {w}-{g - w} ({w / g * 100:.0f}%)"
    )


def _trend_chart(timeline):
    if len(timeline) < 2:
        return
    rows = []
    for t in timeline:
        rows.append({
            "date": t["date"],
            "Point diff": t["point_diff"],
            "Win %": round(t["wins"] / t["games"] * 100, 1),
        })
    df = pd.DataFrame(rows)

    st.markdown("**Per-session trend**")
    diff_chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("date:N", title=None, sort=None),
            y=alt.Y("Point diff:Q", title="Point diff"),
            color=alt.condition(alt.datum["Point diff"] >= 0,
                                alt.value("#2ca02c"), alt.value("#d62728")),
            tooltip=["date:N", "Point diff:Q", "Win %:Q"],
        )
        .properties(height=200)
    )
    st.altair_chart(diff_chart, use_container_width=True)

    pct_chart = (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("date:N", title=None, sort=None),
            y=alt.Y("Win %:Q", title="Win %", scale=alt.Scale(domain=[0, 100])),
            tooltip=["date:N", "Win %:Q"],
        )
        .properties(height=160)
    )
    st.altair_chart(pct_chart, use_container_width=True)


def _partners_and_opponents(data, pid, players):
    def pname(x):
        return players.get(x, {}).get("name", "?")

    pairs = partnership_stats(data)
    partners = []
    for (a, b), r in pairs.items():
        if pid in (a, b) and r["games"] >= MIN_PARTNER_GAMES:
            other = b if a == pid else a
            partners.append((other, r["wins"] / r["games"], r["games"], r["point_diff"]))

    h2h = head_to_head_stats(data).get(pid, {})
    opponents = [
        (opp, r["wins"] / r["games"], r["games"], r["point_diff"])
        for opp, r in h2h.items()
        if r["games"] >= MIN_PARTNER_GAMES
    ]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🤝 Partners**")
        if partners:
            best = sorted(partners, key=lambda x: x[1], reverse=True)
            for opp, wp, g, pd_ in best[:3]:
                st.write(f"🔥 {pname(opp)} — {wp*100:.0f}% ({g} games, {pd_:+d})")
            worst = best[-1]
            if len(best) > 3 and worst[1] < 0.5:
                st.write(f"🧊 {pname(worst[0])} — {worst[1]*100:.0f}% ({worst[2]} games)")
        else:
            st.caption(f"No partner with ≥ {MIN_PARTNER_GAMES} games together yet.")
    with c2:
        st.markdown("**⚔️ Opponents**")
        if opponents:
            ranked = sorted(opponents, key=lambda x: x[1])
            nem = ranked[0]
            owns = ranked[-1]
            st.write(f"😈 Nemesis: {pname(nem[0])} — {nem[1]*100:.0f}% ({nem[2]} games)")
            st.write(f"😇 Owns: {pname(owns[0])} — {owns[1]*100:.0f}% ({owns[2]} games)")
        else:
            st.caption(f"No opponent faced ≥ {MIN_PARTNER_GAMES} times yet.")


def _recent_sessions(timeline):
    if not timeline:
        return
    st.markdown("**🗓️ Recent sessions**")
    rows = []
    for t in reversed(timeline[-8:]):
        losses = t["games"] - t["wins"]
        rows.append({
            "Date": t["date"],
            "Record": f"{t['wins']}-{losses}",
            "Win %": f"{t['wins']/t['games']*100:.0f}%",
            "Point diff": f"{t['point_diff']:+d}",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
