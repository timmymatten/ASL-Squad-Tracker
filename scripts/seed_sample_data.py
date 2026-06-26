"""
CLI to (re)generate the 'sample' dataset.

Run from the repo root:  python scripts/seed_sample_data.py

Reads the player roster from the 'real' dataset (read-only) and writes synthetic match
days to the 'sample' dataset. Your real data is never modified. You can also regenerate
from inside the app: switch to Sample mode in the sidebar and click "Regenerate sample
data".

Targets whatever core.storage is configured for: Supabase if SUPABASE_URL / SUPABASE_KEY
are set (env or .streamlit/secrets.toml), otherwise the local JSON files. All generation
logic lives in core/sample_data.py so the app and this CLI share it.
"""
import os
import sys

# Allow running as `python scripts/seed_sample_data.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import storage
from core.sample_data import generate_sample

if __name__ == "__main__":
    summary = generate_sample(seed=42)  # fixed seed → reproducible CLI output
    backend = "Supabase" if storage.using_supabase() else "local data_sample.json"
    print(
        f"Wrote 'sample' dataset to {backend}: {summary['match_days']} synthetic match "
        f"days ({summary['games']} games, {summary['nets']} nets), "
        f"roster of {summary['players']} players. 'real' dataset untouched."
    )
