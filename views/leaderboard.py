import streamlit as st
import csv
import io
from datetime import date

from core.constants import GROUP_COLORS, GROUP_LABELS
from core.persistence import get_data, persist
from core.stats import compute_stats, promotion_suggestions


def page_leaderboard():
    data = get_data()
    if not data["players"]:
        st.title("🏆 Leaderboard")
        st.info("No players yet.")
        return

    stats = compute_stats(data)
    st.title("🏆 Leaderboard")

    _promotion_suggestions_section(data, stats)

    sort_opt = st.selectbox(
        "Sort by",
        ["Win Rate", "Total Wins", "Point Differential", "Points For",
         "Games Played", "Attendance", "Upsets"],
    )
    sort_fns = {
        "Win Rate": lambda x: x["wins"] / max(x["games"], 1),
        "Total Wins": lambda x: x["wins"],
        "Point Differential": lambda x: x["point_diff"],
        "Points For": lambda x: x["points_for"],
        "Games Played": lambda x: x["games"],
        "Attendance": lambda x: x["attendance"],
        "Upsets": lambda x: x["upsets"],
    }
    ranked = sorted(stats.values(), key=sort_fns[sort_opt], reverse=True)

    st.download_button(
        "⬇️ Download CSV",
        data=_stats_csv(ranked),
        file_name=f"asl_leaderboard_{date.today()}.csv",
        mime="text/csv",
        help="Export the leaderboard (current sort order) as a CSV file.",
    )

    widths = [1, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    labels = ["#", "Player", "Grp", "Wins", "Games", "Win%",
              "PF", "PA", "Diff", "Attend", "Upsets"]
    st.divider()
    hdr = st.columns(widths)
    for col, lbl in zip(hdr, labels):
        col.markdown(f"**{lbl}**")

    for rank, s in enumerate(ranked, 1):
        win_pct = f"{100*s['wins']/s['games']:.0f}%" if s["games"] else "—"
        row = st.columns(widths)
        row[0].write(f"**#{rank}**")
        row[1].write(f"{GROUP_COLORS[s['group']]} {s['name']}")
        row[2].write(f"G{s['group']}")
        row[3].write(s["wins"])
        row[4].write(s["games"])
        row[5].write(win_pct)
        row[6].write(s["points_for"])
        row[7].write(s["points_against"])
        row[8].write(f"{s['point_diff']:+d}")
        row[9].write(s["attendance"])
        row[10].write(s["upsets"])

    # Group averages
    st.divider()
    st.subheader("Group Averages")
    group_rates = {}
    for s in stats.values():
        group_rates.setdefault(s["group"], []).append(
            s["wins"] / max(s["games"], 1)
        )

    gcols = st.columns(4)
    for i, g in enumerate([1, 2, 3, 4]):
        rates = group_rates.get(g, [])
        avg = sum(rates) / len(rates) * 100 if rates else 0
        gcols[i].metric(
            f"{GROUP_COLORS[g]} Group {g}",
            f"{avg:.0f}%" if rates else "—",
            help=f"{len(rates)} players",
        )


def _stats_csv(ranked):
    """Render the ranked leaderboard rows to a CSV string (current sort order)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Rank", "Player", "Group", "Wins", "Games", "Win%",
        "Points For", "Points Against", "Point Diff", "Attendance", "Upsets",
    ])
    for rank, s in enumerate(ranked, 1):
        win_pct = round(100 * s["wins"] / s["games"]) if s["games"] else ""
        writer.writerow([
            rank, s["name"], s["group"], s["wins"], s["games"], win_pct,
            s["points_for"], s["points_against"], s["point_diff"],
            s["attendance"], s["upsets"],
        ])
    return buf.getvalue()


def _promotion_suggestions_section(data, stats):
    """Surface over-performers and offer one-click promotion to a stronger group."""
    suggestions = promotion_suggestions(stats)

    st.subheader("📈 Promotion Suggestions")
    if not suggestions:
        st.caption(
            "No suggestions yet — a player needs ≥ 10 games and clear over-performance "
            "(winning above even and outscoring opponents) before one appears."
        )
        st.divider()
        return

    st.caption(
        "Squads are balanced to make every net a coin flip, so consistently winning "
        "above 50% suggests a player is under-ranked. Promotions are suggestions — you decide."
    )

    for s in suggestions:
        pid = s["pid"]
        flame = "🔥 " if s["strength"] == "strong" else ""
        c_info, c_btn = st.columns([5, 2])
        c_info.markdown(
            f"{flame}**{s['name']}** — {GROUP_COLORS[s['group']]} Group {s['group']} → "
            f"{GROUP_COLORS[s['suggested_group']]} **Group {s['suggested_group']}**  \n"
            f"{s['win_pct']*100:.0f}% win rate over {s['games']} games · "
            f"{s['point_diff']:+d} diff ({s['avg_diff']:+.1f}/game) · "
            f"group avg {s['group_avg']*100:.0f}%"
        )
        if c_btn.button(
            f"⬆️ Promote to Group {s['suggested_group']}",
            key=f"promote_{pid}",
            type="primary" if s["strength"] == "strong" else "secondary",
        ):
            player = data["players"].get(pid)
            if player and player["group"] > 1:
                player["group"] -= 1
                persist(data)
                st.success(f"Promoted **{s['name']}** to {GROUP_LABELS[player['group']]}")
                st.rerun()

    st.divider()
