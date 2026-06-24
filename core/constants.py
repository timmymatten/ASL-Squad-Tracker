GROUP_LABELS = {
    1: "Group 1 — Premier/Bronze+",
    2: "Group 2 — Contender",
    3: "Group 3 — Intermediate/Advanced",
    4: "Group 4 — Rookies",
}
GROUP_COLORS = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢"}

# Two independent datasets, each persisted to its own file so they never mix.
DATA_FILES = {"real": "data.json", "sample": "data_sample.json"}
DEFAULT_DATASET = "real"
