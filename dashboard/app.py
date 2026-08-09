"""VRF Analyzer dashboard (Streamlit).

Run with:  streamlit run dashboard/app.py

A UI-agnostic engine sits underneath (vrf_analyzer.*), so this front-end can be
swapped for React/other later without touching the analysis code.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vrf_analyzer import synth  # noqa: E402
from vrf_analyzer.index import IndexStore  # noqa: E402
from vrf_analyzer.ingest import load_csv, PROFILES  # noqa: E402
from vrf_analyzer.report import summarize  # noqa: E402
from vrf_analyzer.rules import assess, coverage, findings_to_frame, Severity  # noqa: E402

st.set_page_config(page_title="Mitsubishi VRF Analyzer", page_icon="", layout="wide")

SEV_COLOR = {
    "Critical": "#b3001b", "High": "#e8590c", "Medium": "#f08c00",
    "Low": "#2f9e44", "Info": "#4c6ef5",
}

st.title("Mitsubishi VRF Analyzer")
st.caption("Ingest -> index -> assess CSV logs against the top 25 VRF issues.")


# --- data loading ----------------------------------------------------------
@st.cache_data(show_spinner=False)
def _load_dataframe(source: str, upload_bytes, profile_name: str) -> pd.DataFrame:
    if source == "synthetic":
        return synth.generate()
    import io, tempfile
    with tempfile.NamedTemporaryFile("wb", suffix=".csv", delete=False) as tmp:
        tmp.write(upload_bytes)
        tmp_path = tmp.name
    prof = None if profile_name == "(auto-detect)" else profile_name
    return load_csv(tmp_path, profile=prof)


with st.sidebar:
    st.header("Data source")
    source = st.radio("Source", ["Synthetic demo data", "Upload CSV"], index=0)
    uploaded, profile_name = None, "(auto-detect)"
    if source == "Upload CSV":
        uploaded = st.file_uploader("Mitsubishi VRF CSV", type=["csv"])
        profile_name = st.selectbox(
            "Format profile", ["(auto-detect)"] + list(PROFILES.keys())
        )
    st.divider()
    st.caption("Detector coverage")
    cov = coverage()
    live = sum(1 for c in cov if c.implemented)
    st.metric("Detectors live", f"{live} / {len(cov)}")

if source == "Upload CSV" and uploaded is None:
    st.info("Upload a CSV in the sidebar, or switch to synthetic demo data.")
    st.stop()

try:
    df = _load_dataframe(
        "synthetic" if source == "Synthetic demo data" else "upload",
        uploaded.getvalue() if uploaded else None,
        profile_name,
    )
except Exception as exc:
    st.error(f"Failed to load data: {exc}")
    st.stop()

# --- assessment ------------------------------------------------------------
findings = assess(df)
fdf = findings_to_frame(findings)
summary = summarize(findings)

# --- top metrics -----------------------------------------------------------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Rows", f"{len(df):,}")
c2.metric("Units", df["unit_id"].nunique())
c3.metric("Findings", summary["total_findings"])
c4.metric("Max severity", summary["max_severity"] or "None")
crit = summary["by_severity"].get("Critical", 0) + summary["by_severity"].get("High", 0)
c5.metric("High/Critical", crit)

tab_findings, tab_explore, tab_catalog = st.tabs(
    ["Findings", "Signal explorer", "Issue catalog (top 25)"]
)

# --- findings tab ----------------------------------------------------------
with tab_findings:
    if fdf.empty:
        st.success("No issues detected.")
    else:
        left, right = st.columns([2, 1])
        with right:
            sev_counts = fdf["severity_label"].value_counts().reindex(
                ["Critical", "High", "Medium", "Low", "Info"]
            ).dropna()
            fig = px.bar(
                x=sev_counts.values, y=sev_counts.index, orientation="h",
                color=sev_counts.index, color_discrete_map=SEV_COLOR,
                labels={"x": "count", "y": ""},
            )
            fig.update_layout(showlegend=False, height=260, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)
        with left:
            sel_units = st.multiselect(
                "Filter units", sorted(fdf["unit_id"].unique()),
                default=sorted(fdf["unit_id"].unique()),
            )
            sel_sev = st.multiselect(
                "Filter severity", ["Critical", "High", "Medium", "Low", "Info"],
                default=["Critical", "High", "Medium", "Low", "Info"],
            )
        view = fdf[fdf["unit_id"].isin(sel_units) & fdf["severity_label"].isin(sel_sev)]
        st.dataframe(
            view[["severity_label", "rule_id", "title", "unit_id",
                  "start", "end", "message", "recommendation"]],
            use_container_width=True, hide_index=True,
        )

# --- explorer tab ----------------------------------------------------------
with tab_explore:
    units = sorted(df["unit_id"].unique())
    unit = st.selectbox("Unit", units)
    udf = df[df["unit_id"] == unit].sort_values("timestamp")
    numeric = [
        c for c in udf.columns
        if udf[c].notna().any() and pd.api.types.is_numeric_dtype(udf[c])
        and c not in ("system_id", "unit_id")
    ]
    default_sigs = [s for s in ["room_temp", "set_temp", "discharge_temp",
                                "subcool", "superheat", "comp_freq"] if s in numeric]
    sigs = st.multiselect("Signals", numeric, default=default_sigs[:4] or numeric[:3])
    if sigs:
        fig = go.Figure()
        for s in sigs:
            fig.add_trace(go.Scatter(x=udf["timestamp"], y=udf[s], name=s, mode="lines"))
        fig.update_layout(height=460, margin=dict(l=0, r=0, t=10, b=0),
                          legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
        # overlay this unit's finding windows
        ufind = fdf[fdf["unit_id"] == unit] if not fdf.empty else fdf
        if not ufind.empty:
            st.caption("Findings on this unit")
            st.dataframe(ufind[["severity_label", "title", "start", "end", "message"]],
                         use_container_width=True, hide_index=True)

# --- catalog tab -----------------------------------------------------------
with tab_catalog:
    cov_df = pd.DataFrame([{
        "rule_id": c.rule_id, "title": c.title, "category": c.category,
        "severity": c.default_severity.label,
        "status": "LIVE" if c.implemented else "planned",
        "signals": ", ".join(c.signals), "description": c.description,
    } for c in coverage()])
    st.dataframe(cov_df, use_container_width=True, hide_index=True)
