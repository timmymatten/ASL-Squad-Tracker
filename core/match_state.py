import streamlit as st


def get_match():
    return st.session_state.get("current_match")


def set_match(m):
    st.session_state.current_match = m
