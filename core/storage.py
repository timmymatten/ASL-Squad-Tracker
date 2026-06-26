"""
Storage backend for datasets. One place that knows "Supabase vs local file".

If SUPABASE_URL / SUPABASE_KEY are in the environment (and the supabase client is
installed), datasets are read/written as a single jsonb blob per name in a `datasets`
table. Otherwise it transparently falls back to the local JSON files used in dev.

No Streamlit dependency — credentials come from os.environ, so this works from the app,
the CLI seeder, and the migration script alike. app.py bridges st.secrets → os.environ.
"""
import os
import json

from core.constants import DATA_FILES

_client = None
_client_resolved = False


def _empty():
    return {"players": {}, "match_days": []}


def _normalize_url(url):
    """Reduce any Supabase URL to its base (the client appends /rest/v1 itself)."""
    if not url:
        return url
    url = url.strip().rstrip("/")
    for suffix in ("/rest/v1", "/rest"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url.rstrip("/")


def _creds():
    """Supabase (base_url, key) from env, falling back to .streamlit/secrets.toml."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not (url and key):
        # Fallback so the CLI/migration use the same secrets file as the app.
        try:
            import tomllib
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            with open(os.path.join(root, ".streamlit", "secrets.toml"), "rb") as f:
                data = tomllib.load(f)
            url = url or data.get("SUPABASE_URL")
            key = key or data.get("SUPABASE_KEY")
        except Exception:
            pass
    return _normalize_url(url), key


def _get_client():
    """
    Lazily build a process-cached Supabase client, or None to use local files.

    No creds, or the `supabase` package not installed → return None (legit local
    fallback). But if creds ARE provided and the client still can't be built, let the
    error surface — silently falling back would hide misconfiguration and risk writing
    to local files while you think you're on Supabase.
    """
    global _client, _client_resolved
    if _client_resolved:
        return _client
    _client_resolved = True
    url, key = _creds()
    if not (url and key):
        return None
    try:
        from supabase import create_client
    except ImportError:
        return None
    _client = create_client(url, key)
    return _client


def using_supabase():
    return _get_client() is not None


def read_dataset(name):
    """Return the dataset dict for `name` ('real'|'sample'), or an empty default."""
    client = _get_client()
    if client is not None:
        res = client.table("datasets").select("data").eq("name", name).execute()
        rows = res.data or []
        return rows[0]["data"] if rows else _empty()

    path = DATA_FILES[name]
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return _empty()


def write_dataset(name, data):
    """Persist the dataset dict for `name`."""
    client = _get_client()
    if client is not None:
        client.table("datasets").upsert({"name": name, "data": data}).execute()
        return

    with open(DATA_FILES[name], "w") as f:
        json.dump(data, f, indent=2)
