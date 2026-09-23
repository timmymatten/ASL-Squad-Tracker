GROUP_LABELS = {
    1: "Group 1 — Premier/Bronze+",
    2: "Group 2 — Contender",
    3: "Group 3 — Intermediate/Advanced",
    4: "Group 4 — Rookies",
}
GROUP_COLORS = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢"}

# Chart colors for the clustering visualization — the first four slots of the dataviz
# reference categorical theme, kept in their CVD-optimized order (validated: worst
# adjacent ΔE 24.2). Identity is never color-alone: the chart also carries a legend,
# per-point hover, and dark marker outlines.
GROUP_PALETTE = {1: "#2a78d6", 2: "#1baf7a", 3: "#eda100", 4: "#008300"}

# Legend labels make the ranking explicit (Group 1 = strongest cluster).
GROUP_RANK_LABELS = {
    1: "Group 1 (highest)",
    2: "Group 2",
    3: "Group 3",
    4: "Group 4 (lowest)",
}

# Two independent datasets, each persisted to its own file so they never mix.
DATA_FILES = {"real": "data.json", "sample": "data_sample.json"}
DEFAULT_DATASET = "real"
