GROUP_LABELS = {
    1: "Group 1 — Elite",
    2: "Group 2 — Advanced",
    3: "Group 3 — Intermediate",
    4: "Group 4 — Beginner",
}
GROUP_COLORS = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢"}

# Two independent datasets, each persisted to its own file so they never mix.
DATA_FILES = {"real": "data.json", "sample": "data_sample.json"}
DEFAULT_DATASET = "real"
