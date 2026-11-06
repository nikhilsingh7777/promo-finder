"""Promo Finder: results viewer.

Browses the ranked promos produced by `python -m promo_finder run`.
Reads a CSV only, so it needs no API key. Default: the sample from the full
50-episode run shipped in samples/; upload any promos_ranked.csv to view another run.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

SAMPLE = Path(__file__).parent / "samples" / "promos_ranked_full.csv"
REPORT = Path(__file__).parent / "samples" / "ranking_report.md"

st.set_page_config(page_title="Promo Finder", page_icon="🎬", layout="wide")
st.title("Promo Finder: ranked promos")
st.caption(
    "20–60 s clips from microdrama screenplays: hook in the first 3 s, ends on a cliffhanger, "
    "makes sense alone. The AI picks the lines; code computes every timestamp and enforces every rule."
)

with st.sidebar:
    st.header("Data")
    up = st.file_uploader("promos_ranked.csv from any run", type="csv")
    st.markdown("No file: shows all 90 promos from the full 50-episode run.")
    st.markdown("[Source on GitHub](https://github.com/nikhilsingh7777/promo-finder)")

df = pd.read_csv(up) if up is not None else pd.read_csv(SAMPLE)
df = df.sort_values("rank")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Promos", len(df))
c2.metric("Episodes covered", df["episodes"].nunique())
c3.metric("Mean length", f"{df['duration_s'].mean():.0f} s")
if "blind_understood" in df:
    ok = df["blind_understood"].astype(str).str.lower().eq("true").sum()
    c4.metric("Blind viewer understood", f"{ok} / {len(df)}")

eps = sorted(df["episodes"].astype(str).unique(), key=lambda s: int(str(s).split(",")[0]))
pick = st.multiselect("Filter by episode", eps)
view = df[df["episodes"].astype(str).isin(pick)] if pick else df

st.subheader("Ranked list")
cols = ["rank", "episodes", "segments", "duration_s", "hook", "cliffhanger", "why_it_works", "composite"]
cols = [c for c in cols if c in view]
st.dataframe(view[cols], use_container_width=True, hide_index=True,
             column_config={"segments": "segments (start–end, in order)", "duration_s": "s",
                            "composite": st.column_config.NumberColumn("score", format="%.3f")})

st.subheader("Promo detail")
choice = st.selectbox("Pick a promo", view["rank"].tolist(),
                      format_func=lambda r: f"#{r}  ·  {view.loc[view['rank'] == r, 'promo_id'].iloc[0]}")
row = view[view["rank"] == choice].iloc[0]
a, b = st.columns([1, 1])
with a:
    st.markdown(f"**Episode(s):** {row['episodes']}  \n**Segments:** {row['segments']}  \n"
                f"**Length:** {row['duration_s']} s")
    st.markdown(f"**Hook (first 3 s):** {row['hook']}")
    st.markdown(f"**Cliffhanger:** {row['cliffhanger']}")
with b:
    if "unresolved_question" in row:
        st.markdown(f"**Question left open:** {row['unresolved_question']}")
    st.markdown(f"**Why it works:** {row['why_it_works']}")
    if "proposer_model" in row:
        st.caption(f"Proposed by {row['proposer_model']} · score {row['composite']}")

if REPORT.exists() and up is None:
    with st.expander("Suggested posting order and full ranking report"):
        st.markdown(REPORT.read_text())
