import streamlit as st
import streamlit.components.v1 as components
import uuid
import random
from datetime import date

from core.constants import GROUP_LABELS, GROUP_COLORS
from core.persistence import get_data, persist, get_clustering_mode
from core.match_state import get_match, set_match
from core.stats import compute_stats, order_strength, MIN_ORDER_GAMES
from core import clustering
from core.algorithms import (
    generate_format_squads,
    player_attendance,
    select_players_for_format,
)
from core.lineups import (
    OPEN_PER_SQUAD,
    WOMEN_PER_SQUAD,
    N_NETS,
    MATCH_TOLERANCE,
    SHAPES,
    NET_LABELS,
    NET_ICONS,
    NET_SLOTS,
    split_pools,
    squad_ranks,
    rank_label,
    pair_score,
    net_gaps,
    setting_side,
    composition_errors,
    lineup_errors,
    suggest_setting_lineup,
    matching_candidates,
    is_legal,
)

SQUAD_NAME = {"a": "🔵 Squad A", "b": "🔴 Squad B"}
EMPTY = "—"


def _effective_players(players, match):
    """
    Players with skill `group` overridden by the match day's k-means cluster assignment.

    Clusters are computed once when squads are generated (see below) and stored on the
    match as {pid: group}. Everything downstream — squad generation, ranking, lineups —
    reads players[pid]["group"] unchanged; it just sees the clustered group instead of
    the static roster group. Players not in the assignment keep their roster group.
    """
    groups = (match or {}).get("groups")
    if not groups:
        return players
    return {
        pid: ({**p, "group": groups[pid]} if pid in groups else p)
        for pid, p in players.items()
    }


def page_match_day():
    data = get_data()
    players = data["players"]
    match = get_match()

    st.title("🎯 Match Day")

    if match and not match.get("completed"):
        st.info(f"Match in progress — **{match['date']}**")
        if st.button("❌ Abandon this match day"):
            set_match(None)
            st.rerun()
        st.divider()
        _match_in_progress(data, match, _effective_players(players, match))
        return

    # ── New match day setup ──
    st.subheader("Start a New Match Day")
    st.caption(f"Format: two squads of **{OPEN_PER_SQUAD} open + {WOMEN_PER_SQUAD} women**, "
               f"{N_NETS} nets per game.")
    active = [(pid, p) for pid, p in players.items() if p["active"]]

    match_date = st.date_input("Match date", value=date.today())
    st.write("**Select present players:**")

    present = []
    for g in [1, 2, 3, 4]:
        grp = sorted(
            [(pid, p) for pid, p in active if p["group"] == g],
            key=lambda x: x[1]["name"],
        )
        if not grp:
            continue
        st.markdown(f"*{GROUP_COLORS[g]} {GROUP_LABELS[g]}*")
        cols = st.columns(min(4, len(grp)))
        for i, (pid, p) in enumerate(grp):
            with cols[i % 4]:
                if st.checkbox(p["name"], value=True, key=f"pres_{pid}"):
                    present.append(pid)

    need_open, need_women = 2 * OPEN_PER_SQUAD, 2 * WOMEN_PER_SQUAD
    open_in, women_in = split_pools(present, players)
    st.caption(f"Checked in: **{len(open_in)}/{need_open} open** · "
               f"**{len(women_in)}/{need_women} women** "
               "(players without a gender set count as open).")
    short = []
    if len(open_in) < need_open:
        short.append(f"{need_open - len(open_in)} more open player(s)")
    if len(women_in) < need_women:
        short.append(f"{need_women - len(women_in)} more woman/women")
    if short:
        st.warning(f"Need {' and '.join(short)} to fill two squads of "
                   f"{OPEN_PER_SQUAD} open + {WOMEN_PER_SQUAD} women.")
        return

    attend = player_attendance(data["match_days"])

    if len(open_in) > need_open or len(women_in) > need_women:
        playing, benched = select_players_for_format(present, players, data["match_days"])
        st.divider()
        st.warning(
            f"**{len(present)} players checked in — capped at {need_open} open + "
            f"{need_women} women.** Players were selected within each pool and skill group "
            "by fewest match days attended."
        )

        c_in, c_out = st.columns(2)
        for col, pids_all, title in (
            (c_in, playing, f"**✅ Playing today ({len(playing)})**"),
            (c_out, benched, f"**🪑 Sitting out ({len(benched)})**"),
        ):
            with col:
                st.markdown(title)
                for g in [1, 2, 3, 4]:
                    pids = sorted(
                        [p for p in pids_all if players[p]["group"] == g],
                        key=lambda p: (attend.get(p, 0), players[p]["name"]),
                    )
                    for pid in pids:
                        tag = " ♀" if pid in women_in else ""
                        st.write(f"{GROUP_COLORS[g]} {players[pid]['name']}{tag} — "
                                 f"{attend.get(pid, 0)} days")
        present = playing

    st.success(f"**{len(present)} players** → 2 squads of {OPEN_PER_SQUAD} open + "
               f"{WOMEN_PER_SQUAD} women, {N_NETS} nets per game")

    # Preview which skill groups clustering will assign for this turnout.
    mode = get_clustering_mode()
    stats = compute_stats(data)
    preview = clustering.compute_clusters(mode, present, players, stats)
    mode_label = ("Rating-Based (Glicko-2)" if mode == clustering.MODE_RATING
                  else "Performance-Based (win rate + games)")
    st.caption(f"Skill groups will be set by **{mode_label}** k-means clustering "
               f"(change on the 🏠 Home page). {preview['k']} groups from {len(present)} players.")
    if preview["n_flagged"]:
        flag_word = "unrated" if mode == clustering.MODE_RATING else "insufficient data"
        st.caption(f"⚠️ {preview['n_flagged']} player(s) with {flag_word} → defaulted to "
                   f"Group {preview['median_group']}.")

    if st.button("🏆 Generate Squads →", type="primary"):
        groups = preview["groups"]
        eff_players = _effective_players(players, {"groups": groups})
        squad_a, squad_b = generate_format_squads(present, eff_players)
        set_match(
            {
                "id": str(uuid.uuid4())[:8],
                "date": str(match_date),
                "present": present,
                "squad_a": squad_a,
                "squad_b": squad_b,
                "games": [],
                "squad_wins": {"a": 0, "b": 0},
                "completed": False,
                "step": "squads",
                # Coin flip: which squad sets the Game 1 lineup (then it alternates).
                "setting_first": random.choice(["a", "b"]),
                # k-means output, computed once here and reused for the whole match day.
                "groups": groups,
                "clustering": {
                    "mode": preview["mode"],
                    "k": preview["k"],
                    "n_flagged": preview["n_flagged"],
                    "median_group": preview["median_group"],
                    "flagged": preview["flagged"],
                    "centroids": preview["centroids"],
                    "values": preview["values"],
                },
            }
        )
        st.rerun()


def _ranks(match, players):
    """{pid: rank} per squad — open O1..O7, women W1..W3 (stats are fixed for the day)."""
    stats = compute_stats(get_data())
    return (squad_ranks(match["squad_a"], stats, players),
            squad_ranks(match["squad_b"], stats, players))


def _pname(pid, players, ranks):
    return f"{players[pid]['name']} ({rank_label(pid, ranks, players)})"


def _squad_display(squad_ids, players, ranks, label):
    st.markdown(f"**{label}** ({len(squad_ids)} players)")
    open_ids, women_ids = split_pools(squad_ids, players)
    for pool in (open_ids, women_ids):
        for pid in sorted(pool, key=lambda p: ranks[p]):
            p = players[pid]
            st.write(f"`{rank_label(pid, ranks, players)}` {GROUP_COLORS[p['group']]} "
                     f"{p['name']} — G{p['group']}")


def _match_in_progress(data, match, players):
    ranks_a, ranks_b = _ranks(match, players)
    step = match.get("step", "squads")

    if step == "flip":
        _step_flip(match)  # first thing on screen, so nobody scrolls past the animation
        st.divider()

    def squads():
        c_a, c_b = st.columns(2)
        with c_a:
            _squad_display(match["squad_a"], players, ranks_a, SQUAD_NAME["a"])
        with c_b:
            _squad_display(match["squad_b"], players, ranks_b, SQUAD_NAME["b"])

    if step in ("squads", "flip"):
        squads()
        st.divider()
    else:
        with st.expander("👥 Squads & ranks"):
            squads()

    if step == "squads":
        _step_squads(match, players)
    elif step == "lineup":
        _step_setting_lineup(match, players, ranks_a, ranks_b)
    elif step == "matching":
        _step_matching(match, players, ranks_a, ranks_b)
    elif step == "results":
        _step_results(data, match, players, ranks_a, ranks_b)
    elif step == "done":
        st.success("✅ Match day complete — results saved!")
        set_match(None)
        st.rerun()


# ─── Step: adjust squads ──────────────────────────────────────────────────────


def _step_squads(match, players):
    squad_a = match["squad_a"]
    squad_b = match["squad_b"]

    st.subheader("Adjust Squads")
    st.caption(
        f"Each squad needs exactly {OPEN_PER_SQUAD} open + {WOMEN_PER_SQUAD} women, so swaps "
        "are one-for-one within the same pool (open ↔ open, woman ↔ woman). Ranks update "
        "automatically."
    )
    meta = match.get("clustering")
    if meta:
        mode_label = ("Rating-Based" if meta["mode"] == clustering.MODE_RATING
                      else "Performance-Based")
        flagged_note = (f" · {meta['n_flagged']} defaulted to Group {meta['median_group']}"
                        if meta.get("n_flagged") else "")
        st.caption(f"🧮 Groups set by **{mode_label}** k-means "
                   f"({meta['k']} clusters){flagged_note}. Locked for this match day.")

    def pid_label(pid):
        p = players[pid]
        return f"{p['name']} (G{p['group']}{', ♀' if p.get('gender') == 'F' else ''})"

    c1, c2 = st.columns(2)
    with c1:
        swap_a = st.selectbox("From Squad A", [EMPTY] + squad_a,
                              format_func=lambda x: x if x == EMPTY else pid_label(x), key="mv_a")
    with c2:
        swap_b = st.selectbox("From Squad B", [EMPTY] + squad_b,
                              format_func=lambda x: x if x == EMPTY else pid_label(x), key="mv_b")

    if st.button("↔️ Swap"):
        if swap_a == EMPTY or swap_b == EMPTY:
            st.error("Pick one player from each squad to swap.")
        elif (players[swap_a].get("gender") == "F") != (players[swap_b].get("gender") == "F"):
            st.error("Swap open with open or woman with woman so both squads stay 7 + 3.")
        else:
            squad_a[squad_a.index(swap_a)] = swap_b
            squad_b[squad_b.index(swap_b)] = swap_a
            set_match(match)
            st.rerun()

    st.divider()
    st.caption(
        "**Ranking:** open players and women are ranked separately within each squad — "
        "by skill group, then by **average point differential per game** (Leaderboard +/− "
        f"÷ games). Players with under {MIN_ORDER_GAMES} games sit in the middle of their "
        "group until they've played enough. A pair's score is the sum of its two ranks; "
        f"opposing pairs must be within ±{MATCH_TOLERANCE}."
    )
    stats = compute_stats(get_data())
    with st.expander("Ranking detail"):
        col_a, col_b = st.columns(2)
        for col, squad, side in ((col_a, squad_a, "a"), (col_b, squad_b, "b")):
            ranks = squad_ranks(squad, stats, players)
            with col:
                st.markdown(f"**{SQUAD_NAME[side]}**")
                for pid in sorted(squad, key=lambda p: (players[p].get("gender") == "F", ranks[p])):
                    g = stats[pid]["games"]
                    metric = (f"{order_strength(pid, stats):+.1f}/game" if g >= MIN_ORDER_GAMES
                              else f"new ({g} g)")
                    st.write(f"`{rank_label(pid, ranks, players)}` {players[pid]['name']} · {metric}")

    st.divider()
    problems = [f"{SQUAD_NAME[s]} {e}" for s in ("a", "b")
                for e in composition_errors(match[f"squad_{s}"], players)]
    for p in problems:
        st.error(p)
    if st.button("✅ Confirm Squads — Flip for Setting Team!", type="primary",
                 disabled=bool(problems)):
        match["step"] = "flip"
        set_match(match)
        st.rerun()


# ─── Step: coin flip for the setting team ────────────────────────────────────


FLIP_HTML = """
<style>
  :root { --a: #2a78d6; --b: #d64545; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         display: flex; flex-direction: column; align-items: center; }
  .caption { color: #888; font-size: 13px; letter-spacing: .08em; text-transform: uppercase;
             margin: 6px 0 0; }
  .stage { height: 270px; width: 100%; display: flex; align-items: flex-end;
           justify-content: center; perspective: 900px; position: relative; }
  .toss { margin-bottom: 26px; }
  .coin { width: 128px; height: 128px; position: relative; transform-style: preserve-3d; }
  .face { position: absolute; inset: 0; border-radius: 50%; backface-visibility: hidden;
          display: flex; flex-direction: column; align-items: center; justify-content: center;
          color: #fff; box-shadow: inset 0 0 0 6px rgba(255,255,255,.35), inset 0 -10px 18px rgba(0,0,0,.25); }
  .face b { font-size: 56px; line-height: 1; }
  .face small { font-size: 11px; letter-spacing: .12em; text-transform: uppercase; opacity: .9; margin-top: 4px; }
  .fa { background: radial-gradient(circle at 35% 30%, #5c9ce6, var(--a) 70%); }
  .fb { background: radial-gradient(circle at 35% 30%, #e87878, var(--b) 70%); transform: rotateX(180deg); }
  .shadow { position: absolute; bottom: 12px; width: 110px; height: 14px; border-radius: 50%;
            background: rgba(0,0,0,.18); filter: blur(3px); }
  .play .toss   { animation: toss 2.6s cubic-bezier(.3,.0,.4,1) forwards; }
  .play .coin   { animation: spin 2.6s cubic-bezier(.15,.55,.25,1) forwards; }
  .play .shadow { animation: shadow 2.6s cubic-bezier(.3,.0,.4,1) forwards; }
  @keyframes toss { 0% { transform: translateY(0); } 45% { transform: translateY(-105px); }
                    80% { transform: translateY(0); } 88% { transform: translateY(-12px); }
                    100% { transform: translateY(0); } }
  @keyframes spin { from { transform: rotateX(0); } to { transform: rotateX(__DEG__deg); } }
  @keyframes shadow { 0%,100% { transform: scale(1); opacity: 1; } 45% { transform: scale(.55); opacity: .45; } }
  .result { margin-top: 4px; padding: 10px 22px; border-radius: 999px; color: #fff; font-weight: 700;
            font-size: 20px; background: var(--__SIDE__); opacity: 0; transform: translateY(8px) scale(.96); }
  .sub { color: #888; font-size: 13px; margin-top: 8px; opacity: 0; }
  .play .result { animation: reveal .45s 2.65s ease-out forwards; }
  .play .sub    { animation: reveal .45s 2.9s ease-out forwards; }
  @keyframes reveal { to { opacity: 1; transform: none; } }
  button { margin-top: 12px; background: none; border: 1px solid #8884; color: #888; border-radius: 6px;
           padding: 4px 12px; font-size: 12px; cursor: pointer; }
  @media (prefers-reduced-motion: reduce) {
    .play .toss, .play .coin, .play .shadow { animation-duration: 1ms; }
    .play .result, .play .sub { animation-delay: 0s; }
  }
</style>
<div id="root" class="play">
  <p class="caption">Who sets the first lineup?</p>
  <div class="stage">
    <div class="toss"><div class="coin">
      <div class="face fa"><b>A</b><small>Squad A</small></div>
      <div class="face fb"><b>B</b><small>Squad B</small></div>
    </div></div>
    <div class="shadow"></div>
  </div>
  <div class="result" style="text-align:center">__NAME__ sets first!</div>
  <div class="sub">Setting alternates each game</div>
  <button onclick="var r=document.getElementById('root');r.classList.remove('play');void r.offsetWidth;r.classList.add('play');">↻ Replay</button>
</div>
"""


def _step_flip(match):
    side = match["setting_first"]
    # Land on the winning face: whole turns show A, a half turn more shows B.
    deg = 360 * 6 + (180 if side == "b" else 0)
    html = (FLIP_HTML.replace("__DEG__", str(deg))
            .replace("__SIDE__", side)
            .replace("__NAME__", "🔵 Squad A" if side == "a" else "🔴 Squad B"))
    components.html(html, height=430)

    st.caption(f"The setting team picks a lineup shape and fills all {N_NETS} nets; the other "
               f"squad then matches every net within ±{MATCH_TOLERANCE}.")
    if st.button("▶️ Continue to Game 1", type="primary"):
        match["step"] = "lineup"
        set_match(match)
        st.rerun()


# ─── Step: setting team sets the lineup ──────────────────────────────────────


def _seat_options(squad_ids, pool, players, ranks):
    open_ids, women_ids = split_pools(squad_ids, players)
    return [EMPTY] + sorted(women_ids if pool == "women" else open_ids, key=lambda p: ranks[p])


def _fill_seats(prefix, pairs):
    for i, pair in enumerate(pairs):
        for seat, pid in enumerate(pair):
            st.session_state[f"{prefix}_{i}_{seat}"] = pid


def _read_seats(prefix, n):
    def val(k):
        v = st.session_state.get(k, EMPTY)
        return None if v == EMPTY else v
    return [[val(f"{prefix}_{i}_0"), val(f"{prefix}_{i}_1")] for i in range(n)]


def _seat_select(col, label, prefix, i, seat, options, players, ranks):
    col.selectbox(
        label, options, key=f"{prefix}_{i}_{seat}", label_visibility="collapsed",
        format_func=lambda x: x if x == EMPTY else _pname(x, players, ranks),
    )


def _step_setting_lineup(match, players, ranks_a, ranks_b):
    game_num = len(match["games"]) + 1
    side = setting_side(match, game_num)
    other = "b" if side == "a" else "a"
    squad = match[f"squad_{side}"]
    ranks = ranks_a if side == "a" else ranks_b

    st.subheader(f"Game {game_num} — {SQUAD_NAME[side]} sets the lineup")
    st.caption(f"Pick a shape and fill all {N_NETS} nets. {SQUAD_NAME[other]} matches next.")

    shape = st.radio(
        "Lineup shape", list(SHAPES), horizontal=True,
        format_func=lambda s: SHAPES[s]["label"], key=f"shape_{match['id']}_{game_num}",
    )
    net_types = SHAPES[shape]["nets"]
    prefix = f"set_{match['id']}_{game_num}_{shape}"
    nonce_key = f"{prefix}_nonce"

    def autofill(variant):
        st.session_state[nonce_key] = variant
        pairs = suggest_setting_lineup(squad, shape, ranks, players, variant=variant)
        if pairs:
            _fill_seats(prefix, pairs)

    if nonce_key not in st.session_state:
        autofill(0)  # start from a balanced suggestion; edit freely below

    st.button("✨ Suggest another balanced lineup",
              on_click=autofill, args=(st.session_state[nonce_key] + 1,))

    hdr = st.columns([1, 2, 4, 4, 1])
    for c, h in zip(hdr, ["**Net**", "**Type**", "**Player**", "**Player**", "**Score**"]):
        c.markdown(h)
    for i, t in enumerate(net_types):
        row = st.columns([1, 2, 4, 4, 1])
        row[0].write(f"**{i+1}**")
        row[1].write(f"{NET_ICONS[t]} {NET_LABELS[t]}")
        for seat, pool in enumerate(NET_SLOTS[t]):
            _seat_select(row[2 + seat], f"Net {i+1} seat {seat+1}", prefix, i, seat,
                         _seat_options(squad, pool, players, ranks), players, ranks)
        pair = _read_seats(prefix, len(net_types))[i]
        row[4].write(str(pair_score(pair, ranks)) if None not in pair else "")

    pairs = _read_seats(prefix, len(net_types))
    errors = lineup_errors(pairs, net_types, squad, players)
    st.divider()
    for e in errors:
        st.warning(f"⚠️ {e}")
    if st.button(f"🔒 Lock lineup — {SQUAD_NAME[other]} to match", type="primary",
                 disabled=bool(errors)):
        match["pending"] = {"game_num": game_num, "setting": side, "shape": shape,
                            "net_types": net_types, "setting_pairs": pairs}
        match["step"] = "matching"
        set_match(match)
        st.rerun()


# ─── Step: opposing team matches ─────────────────────────────────────────────


def _step_matching(match, players, ranks_a, ranks_b):
    pending = match["pending"]
    game_num = pending["game_num"]
    side = pending["setting"]
    other = "b" if side == "a" else "a"
    net_types = pending["net_types"]
    set_pairs = pending["setting_pairs"]
    ranks_set = ranks_a if side == "a" else ranks_b
    ranks_mat = ranks_b if side == "a" else ranks_a
    squad = match[f"squad_{other}"]

    st.subheader(f"Game {game_num} — {SQUAD_NAME[other]} matches")
    st.caption(f"{SQUAD_NAME[side]} set **{SHAPES[pending['shape']]['label']}**. Field a pair "
               f"of the same type on every net, within ±{MATCH_TOLERANCE} of the opposing "
               "pair's score.")

    candidates = matching_candidates(set_pairs, net_types, ranks_set, squad, ranks_mat, players)
    legal = [c for c in candidates if is_legal(c[1])]
    cycle = legal or candidates[:1]

    prefix = f"mat_{match['id']}_{game_num}_{pending['shape']}_" + "_".join(
        "-".join(p) for p in set_pairs)
    nonce_key = f"{prefix}_nonce"

    def autofill(variant):
        st.session_state[nonce_key] = variant
        _fill_seats(prefix, cycle[variant % len(cycle)][0])

    if nonce_key not in st.session_state:
        autofill(0)  # most even legal matchup

    if legal:
        st.caption(f"{len(legal)} legal matchup(s) available.")
        st.button("🔄 Next legal matchup", on_click=autofill,
                  args=(st.session_state[nonce_key] + 1,))
    else:
        st.warning(f"⚠️ No lineup can match every net within ±{MATCH_TOLERANCE}. Showing the "
                   "closest possible — you may start anyway, or go back and re-set.")

    pairs = _read_seats(prefix, len(net_types))
    widths = [0.4, 1.1, 2.8, 0.6, 6.6, 0.6, 0.8]
    hdr = st.columns(widths)
    for c, h in zip(hdr, ["**#**", "**Type**", f"**{SQUAD_NAME[side]}**", "**Pts**",
                          f"**{SQUAD_NAME[other]}**", "**Pts**", "**Gap**"]):
        c.markdown(h)
    for i, t in enumerate(net_types):
        sp = set_pairs[i]
        row = st.columns(widths[:4] + [3.3, 3.3] + widths[5:])
        row[0].write(f"**{i+1}**")
        row[1].write(f"{NET_ICONS[t]} {NET_LABELS[t]}")
        row[2].write(" & ".join(_pname(p, players, ranks_set) for p in sp))
        row[3].write(str(pair_score(sp, ranks_set)))
        for seat, pool in enumerate(NET_SLOTS[t]):
            _seat_select(row[4 + seat], f"Net {i+1} seat {seat+1}", prefix, i, seat,
                         _seat_options(squad, pool, players, ranks_mat), players, ranks_mat)
        pairs = _read_seats(prefix, len(net_types))
        if None not in pairs[i]:
            ms = pair_score(pairs[i], ranks_mat)
            gap = abs(ms - pair_score(sp, ranks_set))
            row[6].write(str(ms))
            row[7].write(f"{gap} {'✓' if gap <= MATCH_TOLERANCE else '⚠️'}")

    errors = lineup_errors(pairs, net_types, squad, players)
    st.divider()
    for e in errors:
        st.warning(f"⚠️ {e}")
    blocked = bool(errors)
    if not errors:
        gaps = net_gaps(set_pairs, pairs, ranks_set, ranks_mat)
        bad = [i + 1 for i, g in enumerate(gaps) if g > MATCH_TOLERANCE]
        if not bad:
            st.success(f"✅ Every net within ±{MATCH_TOLERANCE}")
        elif legal:
            st.error(f"Net(s) {', '.join(map(str, bad))} exceed ±{MATCH_TOLERANCE} — adjust "
                     "before starting.")
            blocked = True

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✏️ Back to setting lineup"):
            match["step"] = "lineup"
            set_match(match)
            st.rerun()
    with c2:
        if st.button("▶️ Start Game", type="primary", disabled=blocked):
            pairs_set, pairs_mat = set_pairs, pairs
            match["games"].append({
                "game_num": game_num,
                "setting": side,
                "shape": pending["shape"],
                "net_types": net_types,
                "pairings_a": pairs_set if side == "a" else pairs_mat,
                "pairings_b": pairs_mat if side == "a" else pairs_set,
                "ranks_a": ranks_a,
                "ranks_b": ranks_b,
                "sit_a": None,
                "sit_b": None,
                "n_nets": len(net_types),
                "results": None,
                "game_winner": None,
            })
            match.pop("pending", None)
            match["step"] = "results"
            set_match(match)
            st.rerun()


# ─── Step: results ───────────────────────────────────────────────────────────


def _step_results(data, match, players, ranks_a, ranks_b):
    games = match["games"]
    game = games[-1]
    game_num = game["game_num"]
    n_nets = game["n_nets"]
    pairs_a = game["pairings_a"]
    pairs_b = game["pairings_b"]
    net_types = game.get("net_types") or [None] * n_nets

    st.subheader(f"Game {game_num} — Enter Results")
    st.caption(f"{SQUAD_NAME[game['setting']]} set **{SHAPES[game['shape']]['label']}**. "
               "Enter each net's final score — the winner is the higher score.")

    widths = [1, 2, 4, 2, 2, 4]
    hdr = st.columns(widths)
    for c, h in zip(hdr, ["**Net**", "**Type**", "**🔵 Squad A**", "**A score**",
                          "**B score**", "**🔴 Squad B**"]):
        c.markdown(h)

    scores = []
    net_winners = []
    has_tie = False
    for i in range(n_nets):
        row = st.columns(widths)
        row[0].write(f"**{i+1}**")
        t = net_types[i]
        row[1].write(f"{NET_ICONS[t]} {NET_LABELS[t]}" if t else "")
        row[2].write(" & ".join(_pname(p, players, ranks_a) for p in pairs_a[i]))
        a_pts = row[3].number_input(
            f"A score net {i+1}", min_value=0, step=1, value=0,
            label_visibility="collapsed", key=f"score_a_{match['id']}_{game_num}_{i}",
        )
        b_pts = row[4].number_input(
            f"B score net {i+1}", min_value=0, step=1, value=0,
            label_visibility="collapsed", key=f"score_b_{match['id']}_{game_num}_{i}",
        )
        row[5].write(" & ".join(_pname(p, players, ranks_b) for p in pairs_b[i]))
        scores.append([int(a_pts), int(b_pts)])
        if a_pts > b_pts:
            net_winners.append("A")
        elif b_pts > a_pts:
            net_winners.append("B")
        else:
            net_winners.append(None)
            has_tie = True

    wins_a = net_winners.count("A")
    wins_b = net_winners.count("B")
    pts_a = sum(s[0] for s in scores)
    pts_b = sum(s[1] for s in scores)
    st.divider()
    st.markdown(
        f"**Running tally → 🔵 A: {wins_a} nets ({pts_a} pts) | "
        f"🔴 B: {wins_b} nets ({pts_b} pts)**"
    )
    if wins_a > wins_b:
        st.success("🔵 Squad A leads")
    elif wins_b > wins_a:
        st.success("🔴 Squad B leads")
    else:
        st.info("All square so far")

    if has_tie:
        st.warning("⚠️ Every net needs a winner — fix any tied scores before saving.")

    next_side = setting_side(match, game_num + 1)
    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"💾 Save & Play Another Game ({SQUAD_NAME[next_side]} sets)",
                     type="primary", disabled=has_tie):
            _commit_game_results(match, game, net_winners, scores, wins_a, wins_b)
            match["step"] = "lineup"
            set_match(match)
            st.rerun()
    with c2:
        if st.button("🏁 Save & End Match Day", disabled=has_tie):
            _commit_game_results(match, game, net_winners, scores, wins_a, wins_b)
            match["completed"] = True
            match["step"] = "done"
            data["match_days"].append(match)
            persist(data)
            set_match(match)
            st.balloons()
            st.rerun()


def _commit_game_results(match, game, net_winners, scores, wins_a, wins_b):
    game["results"] = net_winners
    game["scores"] = scores
    game["game_winner"] = "a" if wins_a > wins_b else ("b" if wins_b > wins_a else "tie")
    match["squad_wins"]["a"] += wins_a
    match["squad_wins"]["b"] += wins_b
