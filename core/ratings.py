"""
Glicko-2 rating access, sourced from the nats-rankings-monitor project.

That repo scrapes the USA Roundnet (NATS) Glicko-2 rankings and stores the current
values in a single `snapshot.json` at its repo root. We read that file's schema
verbatim rather than reinventing one:

    {
      "checks_paused_until": "...",
      "players": {
        "AIDAN SPROULS|open": {
          "division": "open", "name": "AIDAN SPROULS",
          "rank": 191, "rating": 1651.7, "slack_id": "...", "tier": "Silver"
        },
        ...
      }
    }

Entries are keyed "NAME|division"; the `open` division contains everyone (men and
women), so we read ratings from it. Names on the rankings page are UPPERCASE and don't
always match our roster spelling (e.g. "Dan Vogt" vs "DANIEL VOGT", "Ty Kamenitzer" vs
"TYRUS KAMENITZER"), so lookups match on a normalized (first-initial, last-name) key
with suffix/punctuation handling. Players with no match are reported as unrated so the
caller can default + flag them.
"""
import json
import os
import re
import urllib.request

# Raw snapshot.json from the public monitor repo. A local ratings_snapshot.json in this
# repo's root (if present) takes precedence, so the app works offline / in tests.
SNAPSHOT_URL = (
    "https://raw.githubusercontent.com/timmymatten/nats-rankings-monitor/main/snapshot.json"
)
_LOCAL_SNAPSHOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ratings_snapshot.json"
)

_SUFFIXES = {"JR", "SR", "II", "III", "IV"}


def _fetch_snapshot():
    """Return the parsed snapshot dict, or None if it can't be read.

    Prefers a local ratings_snapshot.json (offline/test use), then the remote file.
    Never raises — a failure just means every player defaults to unrated.
    """
    if os.path.exists(_LOCAL_SNAPSHOT):
        try:
            with open(_LOCAL_SNAPSHOT) as f:
                return json.load(f)
        except Exception:
            pass
    try:
        with urllib.request.urlopen(SNAPSHOT_URL, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _normalize_tokens(name):
    """Uppercase alphabetic tokens with punctuation stripped and suffixes removed."""
    cleaned = re.sub(r"[^A-Za-z\s]", "", (name or "").upper())
    tokens = [t for t in cleaned.split() if t and t not in _SUFFIXES]
    return tokens


def _build_index(snapshot):
    """
    From the snapshot's open-division entries, build lookup indexes:
      full[normalized_full_name] -> rating
      partial[(initial, last_name)] -> rating   (best/highest rating on collision)
      first_only[first_name] -> rating          (for single-token roster names)
    Restricting to the open division avoids women-division duplicates of the same player.
    """
    full, partial, first_only = {}, {}, {}
    for entry in (snapshot or {}).get("players", {}).values():
        if entry.get("division") != "open":
            continue
        rating = entry.get("rating")
        if rating is None:
            continue
        tokens = _normalize_tokens(entry.get("name", ""))
        if not tokens:
            continue
        full[" ".join(tokens)] = rating
        if len(tokens) >= 2:
            key = (tokens[0][0], tokens[-1])
            # On collision keep the higher rating (deterministic, avoids a stale low value).
            if key not in partial or rating > partial[key]:
                partial[key] = rating
        first_only.setdefault(tokens[0], rating)
    return full, partial, first_only


def player_ratings(players):
    """
    Map each player id to their current Glicko-2 rating.

    Returns (ratings, unmatched) where:
      ratings  = {pid: float}   only for players found in the snapshot
      unmatched = [pid, ...]    players with no rating on record

    `players` is the app's {pid: {name, group, ...}} dict.
    """
    snapshot = _fetch_snapshot()
    full, partial, first_only = _build_index(snapshot)

    ratings, unmatched = {}, []
    for pid, p in players.items():
        tokens = _normalize_tokens(p.get("name", ""))
        rating = None
        if tokens:
            rating = full.get(" ".join(tokens))
            if rating is None and len(tokens) >= 2:
                rating = partial.get((tokens[0][0], tokens[-1]))
            if rating is None and len(tokens) == 1:
                rating = first_only.get(tokens[0])
        if rating is None:
            unmatched.append(pid)
        else:
            ratings[pid] = float(rating)
    return ratings, unmatched


def snapshot_available():
    """True if a ratings snapshot (local or remote) could be loaded."""
    return _fetch_snapshot() is not None
