"""
One-time migration: push local JSON datasets into Supabase.

Usage:
    export SUPABASE_URL="https://<project>.supabase.co"
    export SUPABASE_KEY="<service-role key>"
    python migrate_to_supabase.py

Reads the local data.json ('real') and data_sample.json ('sample') and upserts each as a
jsonb blob into the `datasets` table (see DEPLOY.md for the table SQL). A dataset whose
local file is missing is skipped. Safe to re-run (upsert overwrites the row).
"""
import json
import os
import sys

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
