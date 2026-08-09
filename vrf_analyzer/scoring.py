"""Failure-mode probability scoring.

Turns the raw signals into a graded probability that each of the 25 failure
modes is present in the system -- not a binary fired/not-fired, so a borderline
condition shows an honest mid-range confidence and a healthy axis shows a low
one. Modes we cannot evaluate (missing signals, or detector not yet implemented)
are reported with a status instead of a misleading 0%.

The model is transparent and heuristic, NOT a statistically calibrated
probability: each mode's evidence is a per-sample "severity ramp" between a
`warn` level (condition starts to matter) and a `fail` level (condition clearly
present), aggregated over active operation by blending persistence (how often)
with intensity (how far). Every score ships with the evidence behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

from .rules.base import Severity
from .rules.catalog import CATALOG, CATALOG_BY_ID
from .rules.detectors import _active_mask, _has, _span_days, _slope_per_day
from .rules.registry import REGISTRY


def _interval_min(df: pd.DataFrame) -> float:
    ts = pd.to_datetime(df["timestamp"])
    if len(ts) < 2:
        return 1.0
    return float(ts.diff().median().total_seconds()) / 60.0

_MIN_ACTIVE = 20          # need at least this many active samples to assess
_P_FLOOR, _P_CEIL = 1.0, 97.0   # never claim 0% or 100% certainty


@dataclass
class ModeProbability:
    rule_id: str
    title: str
    category: str
    probability: Optional[float]     # 0-100, or None if not assessable
    status: str                      # 'assessed' | 'insufficient_data' | 'not_implemented'
    severity_if_present: str
    unit_id: Optional[str] = None
    rationale: str = ""
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# --- aggregation helpers ----------------------------------------------------
def _ramp_high(v: pd.Series, warn: float, fail: float) -> pd.Series:
    return ((v - warn) / (fail - warn)).clip(0, 1)


def _ramp_low(v: pd.Series, warn: float, fail: float) -> pd.Series:
    # 'low is bad': warn > fail (e.g. subcool warn=4.5, fail=0.5)
    return ((warn - v) / (warn - fail)).clip(0, 1)


def _aggregate(ramp: pd.Series) -> float:
    """Blend persistence (mean) and intensity (90th pct) into evidence [0,1]."""
    ramp = ramp.dropna()
    if ramp.empty:
        return 0.0
    return float(0.6 * ramp.mean() + 0.4 * ramp.quantile(0.90))


def _prob(evidence: float) -> float:
    return float(np.clip(100.0 * evidence, _P_FLOOR, _P_CEIL))


# --- per-rule scorers -------------------------------------------------------
# Each takes a single unit's DataFrame and returns (probability, rationale,
# evidence_dict) or None if this unit can't be assessed for this rule.

def _s_undercharge(df):
    if "subcool" not in df or not df["subcool"].notna().any():
        return None
    run = df[_active_mask(df) & df["subcool"].notna()]
    if len(run) < _MIN_ACTIVE:
        return None
    sc_ev = _aggregate(_ramp_low(run["subcool"], warn=4.5, fail=0.5))
    sh_ev = 0.0
    sh_note = "superheat unavailable"
    if "superheat" in run and run["superheat"].notna().any():
        sh_ev = _aggregate(_ramp_high(run["superheat"], warn=12.0, fail=25.0))
        sh_note = f"superheat corroboration {sh_ev:.2f}"
    # low subcool is suggestive; high superheat corroborates (LEV saturated)
    ev = sc_ev * (0.6 + 0.4 * sh_ev)
    return (_prob(ev),
            f"low-subcool evidence {sc_ev:.2f}, {sh_note}",
            {"subcool_evidence": round(sc_ev, 3), "superheat_evidence": round(sh_ev, 3),
             "median_subcool_k": round(float(run["subcool"].median()), 2)})


def _s_overcharge(df):
    if "subcool" not in df or not df["subcool"].notna().any():
        return None
    run = df[_active_mask(df) & df["subcool"].notna()]
    if len(run) < _MIN_ACTIVE:
        return None
    sc_ev = _aggregate(_ramp_high(run["subcool"], warn=10.0, fail=18.0))
    hp_ev = 0.0
    if "high_pressure" in run and run["high_pressure"].notna().any():
        hp_ev = _aggregate(_ramp_high(run["high_pressure"], warn=3200, fail=4150))
    ev = sc_ev * (0.6 + 0.4 * hp_ev)
    return (_prob(ev), f"high-subcool evidence {sc_ev:.2f}, head-pressure {hp_ev:.2f}",
            {"subcool_evidence": round(sc_ev, 3), "hp_evidence": round(hp_ev, 3)})


def _s_high_discharge(df):
    if "discharge_temp" not in df or not df["discharge_temp"].notna().any():
        return None
    run = df[_active_mask(df)]
    if len(run) < _MIN_ACTIVE:
        return None
    ev = _aggregate(_ramp_high(run["discharge_temp"], warn=100.0, fail=125.0))
    return (_prob(ev), f"peak discharge {run['discharge_temp'].max():.1f} C (limit 110/125)",
            {"peak_c": round(float(run["discharge_temp"].max()), 1)})


def _s_hp_trip(df):
    if "high_pressure" not in df or not df["high_pressure"].notna().any():
        return None
    run = df[_active_mask(df)]
    if len(run) < _MIN_ACTIVE:
        return None
    ev = _aggregate(_ramp_high(run["high_pressure"], warn=3200, fail=4150))
    return (_prob(ev), f"peak {run['high_pressure'].max():.0f} kPa vs 4150 cutout",
            {"peak_kpa": round(float(run["high_pressure"].max()), 0)})


def _s_lp_trip(df):
    if "low_pressure" not in df or not df["low_pressure"].notna().any():
        return None
    run = df[_active_mask(df)]
    if len(run) < _MIN_ACTIVE:
        return None
    ev = _aggregate(_ramp_low(run["low_pressure"], warn=500, fail=250))
    return (_prob(ev), f"min {run['low_pressure'].min():.0f} kPa",
            {"min_kpa": round(float(run["low_pressure"].min()), 0)})


def _s_lev_fault(df):
    if "lev_pulse" not in df or "superheat" not in df:
        return None
    run = df[_active_mask(df) & df["lev_pulse"].notna() & df["superheat"].notna()]
    if len(run) < _MIN_ACTIVE:
        return None
    starved = ((run["lev_pulse"] >= 470) & (run["superheat"] > 15)).mean()
    flooded = ((run["lev_pulse"] <= 70) & (run["superheat"] < 1)).mean()
    ev = float(max(starved, flooded))
    return (_prob(ev), f"maxed+high-SH {starved:.2f}, closed+low-SH {flooded:.2f}",
            {"starved_duty": round(float(starved), 3), "flooded_duty": round(float(flooded), 3)})


def _s_dirty_condenser(df):
    if not {"cond_temp", "outdoor_temp"} <= set(df.columns):
        return None
    cooling = _active_mask(df) & (df.get("mode") == "cool")
    ap = (df["cond_temp"] - df["outdoor_temp"]).where(cooling)
    if ap.notna().sum() < _MIN_ACTIVE:
        return None
    ev = _aggregate(_ramp_high(ap, warn=12.0, fail=22.0))
    return (_prob(ev), f"condensing approach median {ap.median():.1f} K",
            {"median_approach_k": round(float(ap.median()), 1)})


def _s_evap_icing(df):
    if "evap_temp" not in df or not df["evap_temp"].notna().any():
        return None
    cooling = _active_mask(df)
    if "mode" in df:
        cooling = cooling & (df["mode"] == "cool")
    ev_series = df["evap_temp"].where(cooling)
    if ev_series.notna().sum() < _MIN_ACTIVE:
        return None
    ev = _aggregate(_ramp_low(ev_series, warn=0.0, fail=-8.0))
    return (_prob(ev), f"{(ev_series < 0).mean()*100:.0f}% of cooling below 0 C, "
            f"coldest {ev_series.min():.1f} C",
            {"frac_below_0c": round(float((ev_series < 0).mean()), 3),
             "coldest_c": round(float(ev_series.min()), 1)})


def _s_high_current(df):
    if not {"comp_current", "comp_freq"} <= set(df.columns):
        return None
    run = df[(df["comp_freq"] > 5) & (df["comp_current"] > 2)]
    if len(run) < _MIN_ACTIVE:
        return None
    ratio = run["comp_current"] / run["comp_freq"]
    base = float(ratio.median())
    ev = _aggregate(_ramp_high(ratio / base, warn=1.2, fail=1.6))
    return (_prob(ev), f"current/Hz max {ratio.max()/base:.2f}x baseline",
            {"baseline_a_per_hz": round(base, 3)})


def _s_inverter_overheat(df):
    if "heatsink_temp" not in df or not df["heatsink_temp"].notna().any():
        return None
    run = df[_active_mask(df)]
    if len(run) < _MIN_ACTIVE:
        return None
    ev = _aggregate(_ramp_high(run["heatsink_temp"], warn=80.0, fail=100.0))
    return (_prob(ev), f"peak heatsink {run['heatsink_temp'].max():.1f} C",
            {"peak_c": round(float(run["heatsink_temp"].max()), 1)})


def _s_short_cycling(df):
    if "comp_freq" not in df or not df["comp_freq"].notna().any():
        return None
    ts = pd.to_datetime(df["timestamp"])
    span_h = (ts.iloc[-1] - ts.iloc[0]).total_seconds() / 3600.0 if len(df) > 1 else 0
    if span_h < 1:
        return None
    on = (df["comp_freq"].fillna(0) > 5).astype(int)
    starts = int((on.diff() == 1).sum())
    cph = starts / span_h if span_h else 0
    ev = float(np.clip((cph - 4) / (10 - 4), 0, 1))
    return (_prob(ev), f"{cph:.1f} compressor starts/hour",
            {"cycles_per_hour": round(cph, 2)})


def _s_comfort(df):
    if not {"room_temp", "set_temp"} <= set(df.columns):
        return None
    active = df["room_temp"].notna() & df["set_temp"].notna()
    if active.sum() < _MIN_ACTIVE:
        return None
    err = (df["room_temp"] - df["set_temp"]).abs().where(active)
    ev = _aggregate(_ramp_high(err, warn=1.5, fail=4.0))
    return (_prob(ev), f"median |room-set| {err.median():.1f} K",
            {"median_abs_error_k": round(float(err.median()), 2)})


def _s_sensor_fault(df):
    sensors = ["liquid_pipe_temp", "gas_pipe_temp", "discharge_temp", "suction_temp"]
    active = _active_mask(df)
    worst = 0.0
    detail = {}
    for sig in sensors:
        if sig not in df or not df[sig].notna().any():
            continue
        s = df[sig].where(active)
        same = (s.diff() == 0) & active
        # longest flatline run
        run_len, longest = 0, 0
        for v in same.fillna(False).to_numpy():
            run_len = run_len + 1 if v else 0
            longest = max(longest, run_len)
        oor = ((s < -45) | (s > 140)).fillna(False).mean()
        ev = max(np.clip((longest - 30) / (180 - 30), 0, 1), min(1.0, oor * 5))
        if ev > worst:
            worst = float(ev)
            detail = {"sensor": sig, "longest_flatline": int(longest)}
    if not detail:
        return None
    return (_prob(worst), f"worst sensor '{detail['sensor']}' flatline "
            f"{detail['longest_flatline']} samples", detail)


def _s_ambient_limits(df):
    if not {"outdoor_temp", "mode"} <= set(df.columns):
        return None
    parts = []
    for mode, lo, hi in (("cool", -5.0, 46.0), ("heat", -25.0, 21.0)):
        sel = df["mode"] == mode
        if sel.any():
            t = df["outdoor_temp"].where(sel)
            over = _ramp_high(t, hi, hi + 8)
            under = _ramp_low(t, lo, lo - 8)
            parts.append(pd.concat([over, under], axis=1).max(axis=1))
    if not parts:
        return None
    ev = _aggregate(pd.concat(parts, axis=1).max(axis=1))
    return (_prob(ev), "outdoor temperature vs rated envelope", {})


def _s_fault_rollup(df):
    if "error_code" not in df:
        return None
    codes = df["error_code"].astype("string").str.strip().str.lower()
    ok = {"", "0", "00", "nan", "none", "-"}
    bad = (~codes.isin(ok) & codes.notna())
    frac = float(bad.mean())
    ev = float(np.clip(frac * 8, 0, 1))  # even a few abnormal codes matter
    return (_prob(ev), f"{int(bad.sum())} abnormal-code samples", {"abnormal_samples": int(bad.sum())})


def _s_leak_trend(df):
    if not _has(df, "subcool"):
        return None
    run = df[_active_mask(df) & df["subcool"].notna()]
    if _span_days(run["timestamp"]) < 2.0 or len(run) < 100:
        return None
    hourly = run.set_index("timestamp")["subcool"].resample("1h").median().dropna()
    if len(hourly) < 6:
        return None
    slope = _slope_per_day(hourly.index.to_series(), hourly)
    if slope is None:
        return None
    ev = float(np.clip((-slope - 0.2) / (1.0 - 0.2), 0, 1))
    return (_prob(ev), f"subcool trend {slope:.2f} K/day", {"slope_k_per_day": round(slope, 3)})


def _s_excess_defrost(df):
    if "mode" not in df:
        return None
    heating = df["mode"].isin(["heat", "defrost"])
    hh = float(heating.sum()) * _interval_min(df) / 60.0
    if hh < 1.0:
        return None  # no heating operation to assess
    flag = pd.Series(False, index=df.index)
    if "defrost" in df:
        flag = flag | df["defrost"].fillna(False).astype(bool)
    flag = flag | (df["mode"] == "defrost")
    rate = int((flag.astype(int).diff() == 1).sum()) / hh
    ev = float(np.clip((rate - 1.5) / (4.0 - 1.5), 0, 1))
    return (_prob(ev), f"{rate:.1f} defrosts/heating-hour", {"defrosts_per_hour": round(rate, 2)})


def _s_low_airflow(df):
    if not _has(df, "room_temp", "inlet_temp", "fan_speed"):
        return None
    run = df[_active_mask(df)]
    if len(run) < _MIN_ACTIVE:
        return None
    dt = (run["room_temp"] - run["inlet_temp"]).abs()
    ev = _aggregate(_ramp_low(dt, warn=6.0, fail=2.0))
    return (_prob(ev), f"median air delta-T {dt.median():.1f} K", {})


def _s_comm(df):
    ev = 0.0
    if "error_code" in df and df["error_code"].notna().any():
        codes = df["error_code"].astype("string").str.strip()
        comm = {"6600", "6602", "6603", "6606", "6607", "6608"}
        ev = max(ev, min(1.0, float(codes.isin(comm).mean()) * 8))
    ts = pd.to_datetime(df["timestamp"]).sort_values()
    if len(ts) > 10:
        dt = ts.diff().dt.total_seconds().dropna()
        med = dt.median()
        if med > 0:
            ev = max(ev, min(1.0, float((dt > 3 * med).mean()) * 10))
    return (_prob(ev), "comm error codes / data dropouts", {})


def _s_reversing(df):
    if not _has(df, "gas_pipe_temp", "room_temp", "mode"):
        return None
    run = df[_active_mask(df) & df["gas_pipe_temp"].notna()]
    if len(run) < _MIN_ACTIVE:
        return None
    m = 3.0
    cool, heat = run["mode"] == "cool", run["mode"] == "heat"
    wrong = ((cool & (run["gas_pipe_temp"] > run["room_temp"] + m)) |
             (heat & (run["gas_pipe_temp"] < run["room_temp"] - m)))
    ev = float(wrong.mean())
    return (_prob(ev), f"wrong-direction coil {ev*100:.0f}% of run time", {})


def _s_oil_return(df):
    if not _has(df, "comp_freq") or len(df) < _MIN_ACTIVE:
        return None
    im = _interval_min(df)
    freq = df["comp_freq"].fillna(0).to_numpy()
    low = (freq > 0) & (freq < 25)
    longest, i, n = 0, 0, len(low)
    while i < n:
        if low[i]:
            j, mx = i, 0.0
            while j < n and low[j]:
                mx = max(mx, freq[j]); j += 1
            if mx < 40:
                longest = max(longest, j - i)
            i = j
        else:
            i += 1
    hours = longest * im / 60.0
    ev = float(np.clip((hours - 2.0) / (6.0 - 2.0), 0, 1))
    return (_prob(ev), f"longest low-speed run {hours:.1f} h", {"low_speed_hours": round(hours, 1)})


def _s_part_load(df):
    if not _has(df, "comp_freq"):
        return None
    run = df[df["comp_freq"].fillna(0) > 0]
    if len(run) < _MIN_ACTIVE:
        return None
    fmin = float(run["comp_freq"].min())
    frac = float((run["comp_freq"] <= fmin + 3).mean())
    ev = float(np.clip((frac - 0.4) / (0.8 - 0.4), 0, 1))
    return (_prob(ev), f"{frac*100:.0f}% at minimum speed", {"frac_at_min": round(frac, 3)})


def _s_fan(df):
    if not _has(df, "fan_speed", "comp_freq"):
        return None
    run = df[df["comp_freq"].fillna(0) > 10]
    if len(run) < _MIN_ACTIVE:
        return None
    stalled = float((run["fan_speed"].fillna(0) <= 0).mean())
    ev = float(np.clip((stalled - 0.05) / (0.5 - 0.05), 0, 1))
    return (_prob(ev), f"fan stalled {stalled*100:.0f}% under load", {})


def _s_low_eff(df):
    if not _has(df, "power", "comp_freq"):
        return None
    run = df[(df["comp_freq"].fillna(0) > 10) & (df["power"].fillna(0) > 0.1)].copy()
    if _span_days(run["timestamp"]) < 2.0 or len(run) < 100:
        return None
    run["eff"] = run["comp_freq"] / run["power"]
    hourly = run.set_index("timestamp")["eff"].resample("1h").median().dropna()
    if len(hourly) < 6:
        return None
    slope = _slope_per_day(hourly.index.to_series(), hourly)
    base = float(hourly.iloc[:3].mean())
    if slope is None or base <= 0:
        return None
    frac = slope / base
    ev = float(np.clip((-frac - 0.03) / (0.15 - 0.03), 0, 1))
    return (_prob(ev), f"efficiency trend {frac*100:.1f}%/day", {})


def _sys_mode_conflict(df):
    iu = df[(df["unit_role"] == "IU") & df["mode"].notna()]
    if iu.empty:
        return None
    piv = iu.pivot_table(index="timestamp", columns="unit_id", values="mode", aggfunc="first")
    conflict = (piv == "cool").any(axis=1) & (piv == "heat").any(axis=1)
    ev = float(min(1.0, (conflict.mean() if len(conflict) else 0.0) * 4))
    return (_prob(ev), f"{int(conflict.sum())} simultaneous heat/cool timestamps", {})


SCORERS = {
    "R01_undercharge": _s_undercharge,
    "R02_overcharge": _s_overcharge,
    "R03_leak_trend": _s_leak_trend,
    "R04_high_discharge": _s_high_discharge,
    "R05_hp_trip_risk": _s_hp_trip,
    "R06_lp_trip_risk": _s_lp_trip,
    "R07_lev_fault": _s_lev_fault,
    "R08_short_cycling": _s_short_cycling,
    "R09_excess_defrost": _s_excess_defrost,
    "R10_dirty_condenser": _s_dirty_condenser,
    "R11_low_indoor_airflow": _s_low_airflow,
    "R12_evap_icing": _s_evap_icing,
    "R13_sensor_fault": _s_sensor_fault,
    "R14_comm_error": _s_comm,
    "R15_reversing_valve": _s_reversing,
    "R16_oil_return": _s_oil_return,
    "R17_high_current": _s_high_current,
    "R18_inverter_overheat": _s_inverter_overheat,
    "R20_part_load": _s_part_load,
    "R21_comfort_deviation": _s_comfort,
    "R22_fan_degradation": _s_fan,
    "R23_low_efficiency": _s_low_eff,
    "R24_ambient_limits": _s_ambient_limits,
    "R25_fault_rollup": _s_fault_rollup,
}

# system-scoped scorers receive the whole system's rows at once
SYSTEM_SCORERS = {
    "R19_mode_conflict": _sys_mode_conflict,
}


def score_system(df: pd.DataFrame) -> list[ModeProbability]:
    """Return a probability-of-presence for all 25 failure modes, ranked."""
    units = list(df.groupby(["system_id", "unit_id"], dropna=False))
    results: list[ModeProbability] = []

    for spec in CATALOG:
        # system-scoped modes see the whole system at once
        if spec.rule_id in SYSTEM_SCORERS:
            best, assessable = None, False
            for _sys, grp in df.groupby("system_id", dropna=False):
                out = SYSTEM_SCORERS[spec.rule_id](grp.sort_values("timestamp"))
                if out is None:
                    continue
                assessable = True
                if best is None or out[0] > best[0]:
                    best = (out[0], "*", out[1], out[2])
            if not assessable:
                results.append(ModeProbability(
                    spec.rule_id, spec.title, spec.category, None, "insufficient_data",
                    spec.default_severity.label,
                    rationale="required signals not present in this dataset"))
            else:
                results.append(ModeProbability(
                    spec.rule_id, spec.title, spec.category, round(best[0], 1), "assessed",
                    spec.default_severity.label, unit_id=best[1], rationale=best[2],
                    evidence=best[3]))
            continue

        scorer = SCORERS.get(spec.rule_id)
        if scorer is None:
            status = "not_implemented" if not spec.implemented else "insufficient_data"
            results.append(ModeProbability(
                spec.rule_id, spec.title, spec.category, None, status,
                spec.default_severity.label,
                rationale=("detector not yet implemented" if status == "not_implemented"
                           else "no scorer available")))
            continue

        best = None  # (prob, unit_id, rationale, evidence)
        assessable = False
        for (_sys, unit), grp in units:
            out = scorer(grp.sort_values("timestamp"))
            if out is None:
                continue
            assessable = True
            prob, rationale, ev = out
            if best is None or prob > best[0]:
                best = (prob, str(unit), rationale, ev)

        if not assessable:
            results.append(ModeProbability(
                spec.rule_id, spec.title, spec.category, None, "insufficient_data",
                spec.default_severity.label,
                rationale="required signals not present in this dataset"))
        else:
            results.append(ModeProbability(
                spec.rule_id, spec.title, spec.category, round(best[0], 1), "assessed",
                spec.default_severity.label, unit_id=best[1],
                rationale=best[2], evidence=best[3]))

    results.sort(key=lambda m: (m.probability is not None, m.probability or 0), reverse=True)
    return results


def probabilities_to_frame(scores: list[ModeProbability]) -> pd.DataFrame:
    rows = []
    for m in scores:
        rows.append({
            "rule_id": m.rule_id, "title": m.title, "category": m.category,
            "probability_%": m.probability, "status": m.status,
            "severity_if_present": m.severity_if_present, "unit_id": m.unit_id,
            "rationale": m.rationale,
        })
    return pd.DataFrame(rows)
