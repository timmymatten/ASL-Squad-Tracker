"""
One-time migration: push local JSON datasets into Supabase.

Run from the repo root (credentials via .streamlit/secrets.toml or env vars):
    python scripts/migrate_to_supabase.py

Reads the local data.json ('real') and data_sample.json ('sample') and upserts each as a
jsonb blob into the `datasets` table (see docs/DEPLOY.md for the table SQL). A dataset
whose local file is missing is skipped. Safe to re-run (upsert overwrites the row).
"""
import json
import os
import sys

# Allow running as `python scripts/migrate_to_supabase.py` from the repo root by putting
# the project root (this file's parent's parent) on the import path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.constants import DATA_FILES
from core import storage

if __name__ == "__main__":
    if not storage.using_supabase():
        sys.exit(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY in the "
            "environment (and `pip install supabase`) before running this."
        )

    for name, path in DATA_FILES.items():
        if not os.path.exists(path):
            print(f"• {name}: local file {path} not found — skipped")
            continue
        with open(path) as f:
            data = json.load(f)
        storage.write_dataset(name, data)
        print(
            f"• {name}: upserted from {path} "
            f"({len(data.get('players', {}))} players, "
            f"{len(data.get('match_days', []))} match days)"
        )
    print("Done.")
