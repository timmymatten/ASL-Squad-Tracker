import streamlit as st
import json
import os

# "real" is your live data; "sample" is throwaway test data (see core/sample_data.py).
# Each persists only to its own file, so switching between them in the sidebar can never
# let one contaminate the other. Paths live in core.constants (no Streamlit dependency).
from core.constants import DATA_FILES, DEFAULT_DATASET


def active_dataset():
    return st.session_state.get("dataset", DEFAULT_DATASET)


def data_path():
    return DATA_FILES[active_dataset()]


def set_dataset(name):
    """Switch the active dataset and drop any state tied to the previous one."""
    if name not in DATA_FILES:
        return
    st.session_state.dataset = name
    # Force a reload from the new file and abandon any in-progress match so the
    # two datasets never share live state.
    st.session_state.pop("data", None)
    st.session_state.pop("data_for", None)
    st.session_state.pop("current_match", None)


def load_data():
    path = data_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"players": {}, "match_days": []}


def save_data(data):
    with open(data_path(), "w") as f:
        json.dump(data, f, indent=2)


def get_data():
    # Reload whenever the cached data belongs to a different dataset.
    ds = active_dataset()
    if "data" not in st.session_state or st.session_state.get("data_for") != ds:
        st.session_state.data = load_data()
        st.session_state.data_for = ds
    return st.session_state.data


def persist(data):
    save_data(data)
    st.session_state.data = data
    st.session_state.data_for = active_dataset()
