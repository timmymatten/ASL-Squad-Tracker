"""
CLI to (re)generate the 'sample' dataset.

Usage:  python seed_sample_data.py

Reads the player roster from the 'real' dataset (read-only) and writes synthetic match
days to the 'sample' dataset. Your real data is never modified. You can also regenerate
from inside the app: switch to Sample mode in the sidebar and click "Regenerate sample
data".

Targets whatever core.storage is configured for: Supabase if SUPABASE_URL / SUPABASE_KEY
are set in the environment, otherwise the local JSON files. All generation logic lives in
core/sample_data.py so the app and this CLI share it.
"""
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
