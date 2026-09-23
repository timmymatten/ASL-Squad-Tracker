# 🏐 ASL Squad Tracker

A [Streamlit](https://streamlit.io) app for running **Northeastern Club Roundnet** match
days: build skill-balanced squads, auto-generate fair net pairings, record scores, and
track per-player performance over a season — wins, point differential, partner chemistry,
head-to-head records, and dynamic skill-group suggestions.

Roundnet here is **doubles**: each match day splits attendees into **Squad A vs Squad B**,
and within each game players pair up to play head-to-head **nets**.

---

## Features

### 🏠 Home — k-means skill grouping
Skill groups (1–4) are built automatically by **k-means clustering** (`scikit-learn`,
`KMeans(n_clusters=4)`) instead of manual assignment, in one of two modes (toggle persists
with the dataset and holds across the match day):

- **Rating-Based** (default) — clusters players on their live **NATS Glicko-2 rating**,
  read straight from the [`nats-rankings-monitor`](https://github.com/timmymatten/nats-rankings-monitor)
  project's `snapshot.json` schema (`core/ratings.py` matches roster names to the rankings
  page). Players with no rating on record are defaulted to the median cluster and flagged
  **"unrated"**.
- **Performance-Based** — clusters on this app's own **(win_rate, games_played)**,
  standardized (`StandardScaler`) so the two scales weigh equally. Players with 0 games are
  defaulted to the median cluster and flagged **"insufficient data"**.

Clusters are relabelled by centroid so **Group 1 is always the strongest**, keeping numbering
stable match to match. A **Plotly** chart on the Home page visualizes the current grouping
(rating strip plot with centroid lines, or win-rate-vs-games scatter with centroid markers),
and a banner reports how many players have enough game history to consider switching modes.
Clusters are computed **once at the start of each match day** and stored on the match record
(auditable in history); their output feeds the existing squad/pairing logic unchanged.


### 📋 Roster
Add, edit, activate/deactivate, and remove players. Each player has a **skill group**
(1–4) and gender. Only active players appear on match days.

| Group | Label |
|------|-------|
| 1 | Premier / Bronze+ |
| 2 | Contender |
| 3 | Intermediate / Advanced |
| 4 | Rookies |

### 🎯 Match Day
Match days use a fixed squad format: **two squads of 10, each 7 open + 3 women**, playing
**5 nets per game** (no sitters). Runs an entire session end to end:
1. **Check in** present players. Needs **14 open + 6 women** (players with no gender set
   count as open). If more show up, each pool is capped separately, with spots allocated
   per skill group to players with the **fewest match days attended** (fair rotation).
2. **Generate squads**: the open pool and the women's pool are each split skill-balanced,
   so every squad gets exactly 7 + 3. Hand-swaps are one-for-one within a pool.
3. **Rank**: within each squad, open players are ranked **O1–O7** and women **W1–W3**
   (by skill group, then **average point differential per game**; newcomers with fewer
   than 5 games sit neutral). A pair's **score** is the sum of its two ranks.
4. **Coin flip**: an animated coin toss picks the squad that **sets** Game 1. Setting then
   alternates each game.
5. **Setting team sets the lineup**: it picks a shape and fills all five nets:
   - **2 Open + 3 Coed**, or
   - **3 Open + 1 Women's + 1 Coed**

   A balanced lineup is pre-filled as a starting point ("Suggest another" cycles options).
6. **Opposing team matches**: it fields a pair of the same type on every net, and each
   matchup must be within **±3** on pair score. The most even legal matchup is pre-filled;
   **🔄 Next legal matchup** cycles alternatives, and manual edits are checked live. (If no
   lineup can satisfy ±3 on every net, the closest is shown and the game may still start.)
7. **Enter scores** per net (games to 21). The winner is the higher score; **point
   differential** is recorded.

Each saved game records the setting squad, shape, net types and the ranks used, so History
shows exactly how every game was set.

### 🏆 Leaderboard
Per-player **Wins, Games, Win %, Points For / Against / Differential, Attendance, Upsets**,
sortable by any column, plus group win-rate averages and a **CSV export**.

- **Upset** = your pair beat an opposing pair from a *stronger* skill group on a net
  (credited per net to the winning pair).
- **📈 Promotion suggestions** — flags players over-performing their group (blending
  deviation from 50% and their group average win rate, gated to ≥ 10 games and confirmed
  by positive point differential), with one-click promote. Balancing pushes everyone
  toward ~50%, so consistently winning above that suggests someone is under-ranked.

### 🤝 Chemistry
How duos perform **when teamed up**:
- **Best / worst partnerships** leaderboard (duos with ≥ 3 games together).
- A **full chemistry matrix** heatmap (win %, games, or avg point diff) for everyone
  who's partnered at least once.

### 👤 Player Dashboard
A per-player page tying everything together: key metrics, current win/loss **streak**,
**per-session trend charts** (point diff + win %), **best/worst partners**, **nemesis /
owns** opponents (head-to-head), a promotion badge when applicable, and recent sessions.

### 📅 History
Every completed match day with per-game, per-net detail (pairings, scores, sitters), and
delete-with-confirmation.

---

## Data & persistence

State is a single JSON document per dataset:
`{ "players": {…}, "match_days": [...], "config": {…} }`. All stats are **derived on each
render** by replaying match history — nothing is denormalized or cached on disk. `config`
holds the selected clustering mode; each completed match day also stores the `groups`
(pid → cluster group) and `clustering` metadata (mode, centroids, flagged players) used that
day, so past grouping decisions are auditable.

Two independent datasets, switchable from the sidebar (they never mix):
- **🟢 Real** — your live data.
- **🧪 Sample** — throwaway test data (50 synthetic match days) you can regenerate
  anytime via the sidebar button or `python scripts/seed_sample_data.py`. Synthetic match days are
  produced by replaying the *real* matchmaking pipeline, so every one is realistic. If the
  real roster is short of 14+ open or 6+ women, the sample roster is padded with clearly
  named synthetic players ("Sample Woman 1", …). The real roster is never modified.

**Storage backend** (`core/storage.py`) is pluggable:
- If `SUPABASE_URL` / `SUPABASE_KEY` are set (env vars **or** `.streamlit/secrets.toml`),
  each dataset is stored as a `jsonb` blob in a Supabase `datasets` table — durable, free,
  and the only option that survives Streamlit Cloud's ephemeral filesystem.
- Otherwise it falls back to local files (`data.json`, `data_sample.json`) — ideal for
  local development with zero setup.

See **[docs/DEPLOY.md](docs/DEPLOY.md)** for the full Supabase + Streamlit Community Cloud setup.

---

## Project structure

```
app.py                 # entry point: page config, sidebar nav, dataset switch
core/
  constants.py         # group labels/colors/palette, dataset file names
  storage.py           # Supabase-or-local backend (read/write_dataset)
  persistence.py       # session-cached get_data / persist / dataset + clustering-mode config
  match_state.py       # in-progress match (session state)
  algorithms.py        # squad generation and attendance-fair selection
  lineups.py           # 7+3 format: ranks, lineup shapes, setting/matching, ±3 rule
  stats.py             # compute_stats, squad_order, partnerships, head-to-head, promotions
  ratings.py           # NATS Glicko-2 ratings from nats-rankings-monitor's snapshot.json
  clustering.py        # k-means skill grouping (rating / performance modes)
  sample_data.py       # synthetic match-day generator
views/
  home.py  roster.py  match_day.py  leaderboard.py  chemistry.py  player.py  history.py
scripts/
  seed_sample_data.py    # CLI: (re)generate the sample dataset
  migrate_to_supabase.py # CLI: push local JSON into Supabase
docs/
  DEPLOY.md              # Supabase + Streamlit Community Cloud setup
```

`core/` modules are pure/Streamlit-light and unit-testable; `views/` hold the UI.

---

## Run locally

Requires **Python 3.11–3.12** (3.14 isn't supported yet — Streamlit 1.37's Pillow pin has
no wheel for it).

```bash
pip install -r requirements.txt
streamlit run app.py
```

With no Supabase credentials configured, the app reads/writes local `data.json` /
`data_sample.json`, so you can start immediately. To exercise the analytics with a full
season of data, switch to **🧪 Sample** in the sidebar (or run `python scripts/seed_sample_data.py`).

---

## Configuration knobs

Tunable constants (no code restructure needed):
- `core/lineups.py`: `MATCH_TOLERANCE` (±3 matchup rule), `SHAPES` (lineup shapes),
  `OPEN_PER_SQUAD` / `WOMEN_PER_SQUAD`, `SUGGEST_SLACK` (variety of suggested lineups).
- `core/stats.py` — `MIN_ORDER_GAMES` (games before point-diff affects ranking),
  `MIN_PARTNER_GAMES` (chemistry/head-to-head qualification), and the promotion thresholds
  `MIN_GAMES` / `PROMOTE_THRESHOLD` / `STRONG_THRESHOLD`.

---

## Security note

The Supabase key is a **secret** — keep it only in `.streamlit/secrets.toml` (gitignored)
and in Streamlit Cloud's Secrets. Never commit or share it. If it's ever exposed, rotate it
in the Supabase dashboard and update both locations.
