"""
CLI to (re)generate the sample dataset (data_sample.json).

Usage:  python seed_sample_data.py

Reads the player roster from your real data.json (read-only) and writes synthetic match
days to data_sample.json. Your real data is never modified. You can also regenerate from
inside the app: switch to Sample mode in the sidebar and click "Regenerate sample data".

All generation logic lives in core/sample_data.py so the app and this CLI share it.
"""
from core.constants import DATA_FILES
from core.sample_data import generate_sample

if __name__ == "__main__":
    summary = generate_sample(seed=42)  # fixed seed → reproducible CLI output
    print(
        f"Wrote {DATA_FILES['sample']}: {summary['match_days']} synthetic match days "
        f"({summary['games']} games, {summary['nets']} nets), "
        f"roster of {summary['players']} players. {DATA_FILES['real']} untouched."
    )
