"""Concrete detectors for a subset of the catalog.

Six issues are implemented end-to-end for the prototype; the remaining catalog
entries are wired but not yet live (shown as 'planned' coverage in the UI).
Each detector is small, pure, and tunable via ``params`` so thresholds can be
calibrated against real data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Detector, Finding, Severity
from .catalog import CATALOG_BY_ID


def _has(df: pd.DataFrame, *cols: str) -> bool:
    """True if all columns exist and have at least one non-null value."""
    return all(c in df.columns and df[c].notna().any() for c in cols)


def _contiguous_windows(mask: pd.Series, timestamps: pd.Series, min_len: int):
    """Yield (start_ts, end_ts, count) for runs of True at least min_len long."""
    m = mask.to_numpy()
    if not m.any():
        return
    idx = np.flatnonzero(np.diff(np.concatenate(([0], m.view(np.int8), [0]))))
    for start, end in zip(idx[::2], idx[1::2]):
        if end - start >= min_len:
            yield timestamps.iloc[start], timestamps.iloc[end - 1], int(end - start)


def _active_mask(df: pd.DataFrame) -> pd.Series:
    """Rows where the unit is actually operating (so signals should be dynamic).

    OU: compressor running. IU: mode not off. Falls back to 'all rows' when
    neither signal is available.
    """
    active = pd.Series(False, index=df.index)
    have_signal = False
    if "comp_freq" in df and df["comp_freq"].notna().any():
        active = active | (df["comp_freq"].fillna(0) > 0)
        have_signal = True
    if "mode" in df and df["mode"].notna().any():
        active = active | (~df["mode"].isin(["off", None]) & df["mode"].notna())
        have_signal = True
    return active if have_signal else pd.Series(True, index=df.index)


class RefrigerantUndercharge(Detector):
    """Chronic low-subcool / high-superheat -> undercharge.

    Reported as ONE aggregated finding per unit with a duty-cycle metric, rather
    than one per contiguous window, because undercharge is a persistent state.
    Uses the reported subcool target (SCm) when present for stronger evidence.
    """

    spec = CATALOG_BY_ID["R01_undercharge"]
    params = {
        "min_subcool_k": 2.0,
        "max_superheat_k": 12.0,
        "min_duty": 0.15,        # fraction of running time in the fault state
        "min_running_samples": 30,
    }

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if not _has(df, "subcool", "superheat"):
            return []
        p = self.params
        run = df[_active_mask(df) & df["subcool"].notna() & df["superheat"].notna()]
        if len(run) < p["min_running_samples"]:
            return []
        mask = (run["subcool"] < p["min_subcool_k"]) & (
            run["superheat"] > p["max_superheat_k"]
        )
        duty = float(mask.mean())
        if duty < p["min_duty"]:
            return []
        bad = run[mask]
        avg_sc = float(bad["subcool"].mean())
        avg_sh = float(bad["superheat"].mean())
        target = (
            float(run["subcool_target"].dropna().median())
            if _has(run, "subcool_target") else None
        )
        sev = Severity.HIGH if duty >= 0.4 else Severity.MEDIUM
        tgt_txt = f" vs {target:.0f} K target" if target is not None else ""
        return [self._finding(
            df, start=bad["timestamp"].min(), end=bad["timestamp"].max(),
            severity=sev,
            message=(
                f"Undercharge signature during {duty*100:.0f}% of run time: "
                f"subcool avg {avg_sc:.1f} K{tgt_txt} with superheat avg "
                f"{avg_sh:.1f} K."
            ),
            recommendation=(
                "Check for a refrigerant leak and verify charge against "
                "commissioning data; inspect service ports, flare joints, and "
                "the subcool sensor before adding refrigerant."
            ),
            metrics={
                "duty_fraction": round(duty, 3),
                "avg_subcool_k": round(avg_sc, 2),
                "target_subcool_k": None if target is None else round(target, 1),
                "avg_superheat_k": round(avg_sh, 2),
                "running_samples": int(len(run)),
                "fault_samples": int(len(bad)),
            },
        )]


class HighDischargeTemp(Detector):
    spec = CATALOG_BY_ID["R04_high_discharge"]
    params = {"limit_c": 110.0, "critical_c": 120.0, "min_samples": 3}

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if not _has(df, "discharge_temp"):
            return []
        p = self.params
        mask = df["discharge_temp"] > p["limit_c"]
        out: list[Finding] = []
        for start, end, n in _contiguous_windows(mask, df["timestamp"], p["min_samples"]):
            win = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
            peak = float(win["discharge_temp"].max())
            sev = Severity.CRITICAL if peak > p["critical_c"] else Severity.HIGH
            out.append(self._finding(
                df, start=start, end=end, severity=sev,
                message=(
                    f"Discharge temp exceeded {p['limit_c']:.0f} C for {n} samples "
                    f"(peak {peak:.1f} C)."
                ),
                recommendation=(
                    "Verify charge and superheat, check LEV operation and for "
                    "restricted refrigerant flow; inspect compressor cooling."
                ),
                metrics={"peak_c": round(peak, 1), "samples": n},
            ))
        return out


class CompressorShortCycling(Detector):
    spec = CATALOG_BY_ID["R08_short_cycling"]
    params = {"on_freq_hz": 5.0, "max_cycles_per_hour": 6, "min_hours": 1.0}

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if not _has(df, "comp_freq"):
            return []
        p = self.params
        ts = pd.to_datetime(df["timestamp"])
        span_h = (ts.iloc[-1] - ts.iloc[0]).total_seconds() / 3600.0 if len(df) > 1 else 0
        if span_h < p["min_hours"]:
            return []
        on = (df["comp_freq"].fillna(0) > p["on_freq_hz"]).astype(int)
        starts = int(((on.diff() == 1).sum()))  # off->on transitions
        cph = starts / span_h if span_h else 0
        if cph <= p["max_cycles_per_hour"]:
            return []
        return [self._finding(
            df, start=ts.iloc[0], end=ts.iloc[-1],
            message=(
                f"Compressor started {starts} times over {span_h:.1f} h "
                f"({cph:.1f} cycles/h)."
            ),
            recommendation=(
                "Check for oversizing, thermostat/setpoint hunting, low load, "
                "or refrigerant charge issues causing protective cut-outs."
            ),
            metrics={"cycles_per_hour": round(cph, 1), "starts": starts},
        )]


class ComfortDeviation(Detector):
    spec = CATALOG_BY_ID["R21_comfort_deviation"]
    params = {"tolerance_c": 2.5, "min_samples": 12}

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if not _has(df, "room_temp", "set_temp"):
            return []
        p = self.params
        active = df["set_temp"].notna() & df["room_temp"].notna()
        err = (df["room_temp"] - df["set_temp"]).where(active)
        mask = err.abs() > p["tolerance_c"]
        mask = mask.fillna(False)
        out: list[Finding] = []
        for start, end, n in _contiguous_windows(mask, df["timestamp"], p["min_samples"]):
            win = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
            avg_err = float((win["room_temp"] - win["set_temp"]).mean())
            direction = "above" if avg_err > 0 else "below"
            out.append(self._finding(
                df, start=start, end=end,
                message=(
                    f"Room temp held {abs(avg_err):.1f} C {direction} setpoint "
                    f"for {n} samples."
                ),
                recommendation=(
                    "Check capacity vs. load, airflow, sensor placement, and "
                    "whether the unit is reaching demand under these conditions."
                ),
                metrics={"avg_error_c": round(avg_err, 2), "samples": n},
            ))
        return out


class ThermistorFault(Detector):
    """Out-of-range or flatlined thermistors.

    Flatline is only evaluated while the unit is *active* (so a satisfied,
    stable zone is not mistaken for a stuck sensor) and excludes room-air
    temperature, which legitimately holds steady. Findings are aggregated to one
    per sensor per failure mode.
    """

    spec = CATALOG_BY_ID["R13_sensor_fault"]
    params = {
        "flatline_samples": 60,          # identical-value run length (while active)
        "min_c": -45.0, "max_c": 140.0,  # plausible pipe/refrigerant sensor range
        # sensors eligible for flatline detection (room-air excluded on purpose)
        "flatline_sensors": ["liquid_pipe_temp", "gas_pipe_temp",
                             "discharge_temp", "suction_temp"],
        # sensors checked for out-of-range
        "range_sensors": ["room_temp", "liquid_pipe_temp", "gas_pipe_temp",
                          "discharge_temp", "suction_temp", "outdoor_temp"],
    }

    def run(self, df: pd.DataFrame) -> list[Finding]:
        out: list[Finding] = []
        p = self.params
        active = _active_mask(df)

        for sig in p["range_sensors"]:
            if not _has(df, sig):
                continue
            s = df[sig]
            oor = ((s < p["min_c"]) | (s > p["max_c"])).fillna(False)
            if oor.any():
                sub = df[oor]
                out.append(self._finding(
                    df, start=sub["timestamp"].min(), end=sub["timestamp"].max(),
                    severity=Severity.MEDIUM,
                    message=(f"Sensor '{sig}' out of plausible range "
                             f"({int(oor.sum())} samples, "
                             f"min {s[oor].min():.1f} / max {s[oor].max():.1f} C)."),
                    recommendation=f"Inspect/replace the '{sig}' thermistor and wiring.",
                    metrics={"sensor": sig, "samples": int(oor.sum())},
                ))

        for sig in p["flatline_sensors"]:
            if not _has(df, sig):
                continue
            s = df[sig].where(active)
            # identical consecutive values *within active operation*
            same = (s.diff() == 0) & active
            longest = 0
            total = 0
            for _s, _e, n in _contiguous_windows(same.fillna(False), df["timestamp"],
                                                 p["flatline_samples"]):
                longest = max(longest, n)
                total += n
            if longest:
                out.append(self._finding(
                    df, severity=Severity.LOW,
                    message=(f"Sensor '{sig}' flatlined while running "
                             f"(longest {longest} consecutive identical readings)."),
                    recommendation=f"Verify the '{sig}' sensor is reporting live data.",
                    metrics={"sensor": sig, "longest_run": longest,
                             "total_flatlined": total},
                ))
        return out


class HighPressureTripRisk(Detector):
    """High side approaching the high-pressure cutout (R410A ~4.15 MPa)."""

    spec = CATALOG_BY_ID["R05_hp_trip_risk"]
    # gauge kPa; R410A HP switch ~4.15 MPa abs -> ~4050 kPa gauge. Warn at 90%.
    params = {"warn_kpa": 3650.0, "critical_kpa": 3950.0, "min_samples": 3}

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if not _has(df, "high_pressure"):
            return []
        p = self.params
        mask = (df["high_pressure"] > p["warn_kpa"]).fillna(False)
        out: list[Finding] = []
        for start, end, n in _contiguous_windows(mask, df["timestamp"], p["min_samples"]):
            win = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
            peak = float(win["high_pressure"].max())
            sev = Severity.CRITICAL if peak > p["critical_kpa"] else Severity.HIGH
            out.append(self._finding(
                df, start=start, end=end, severity=sev,
                message=(f"High pressure elevated for {n} samples "
                         f"(peak {peak:.0f} kPa / {peak/6.895:.0f} psi)."),
                recommendation=("Check condenser airflow/fouling, outdoor fan, "
                                "ambient limits, and for overcharge."),
                metrics={"peak_kpa": round(peak, 0), "samples": n},
            ))
        return out


class LowPressureTripRisk(Detector):
    """Low side approaching the low-pressure cutout."""

    spec = CATALOG_BY_ID["R06_lp_trip_risk"]
    # gauge kPa; warn below ~350 kPa gauge (~51 psi) while running.
    params = {"warn_kpa": 350.0, "critical_kpa": 250.0, "min_samples": 3}

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if not _has(df, "low_pressure"):
            return []
        p = self.params
        run = _active_mask(df)
        mask = ((df["low_pressure"] < p["warn_kpa"]) & run).fillna(False)
        out: list[Finding] = []
        for start, end, n in _contiguous_windows(mask, df["timestamp"], p["min_samples"]):
            win = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
            low = float(win["low_pressure"].min())
            sev = Severity.CRITICAL if low < p["critical_kpa"] else Severity.MEDIUM
            out.append(self._finding(
                df, start=start, end=end, severity=sev,
                message=(f"Low pressure depressed for {n} samples "
                         f"(min {low:.0f} kPa / {low/6.895:.0f} psi)."),
                recommendation=("Check for low charge, restricted refrigerant "
                                "flow, low indoor airflow, or a stuck expansion valve."),
                metrics={"min_kpa": round(low, 0), "samples": n},
            ))
        return out


class LEVFault(Detector):
    """Expansion valve not controlling: pinned at a travel limit while the zone's
    superheat stays abnormal. Reported per indoor unit as an aggregated finding.
    """

    spec = CATALOG_BY_ID["R07_lev_fault"]
    params = {
        "max_rail": 470, "min_open": 70,
        "high_superheat_k": 15.0, "low_superheat_k": 1.0,
        "min_duty": 0.2, "min_active_samples": 30,
    }

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if not _has(df, "lev_pulse", "superheat"):
            return []
        p = self.params
        act = _active_mask(df) & df["lev_pulse"].notna() & df["superheat"].notna()
        run = df[act]
        if len(run) < p["min_active_samples"]:
            return []
        starved = (run["lev_pulse"] >= p["max_rail"]) & (
            run["superheat"] > p["high_superheat_k"])
        flooding = (run["lev_pulse"] <= p["min_open"]) & (
            run["superheat"] < p["low_superheat_k"])
        for label, mask in (("maxed open with high superheat (zone underfed)", starved),
                            ("nearly closed with low superheat (zone flooded)", flooding)):
            duty = float(mask.mean())
            if duty >= p["min_duty"]:
                bad = run[mask]
                return [self._finding(
                    df, start=bad["timestamp"].min(), end=bad["timestamp"].max(),
                    severity=Severity.MEDIUM,
                    message=(f"Expansion valve {label} during {duty*100:.0f}% of "
                             f"run time (avg superheat {bad['superheat'].mean():.1f} K)."),
                    recommendation=("Inspect the LEV coil/connector and valve "
                                    "operation; verify the superheat sensor."),
                    metrics={"duty_fraction": round(duty, 3),
                             "avg_superheat_k": round(float(bad["superheat"].mean()), 2)},
                )]
        return []


class DirtyCondenser(Detector):
    """Elevated condensing approach (cond_temp - ambient) in cooling -> a fouled
    or airflow-restricted outdoor coil.
    """

    spec = CATALOG_BY_ID["R10_dirty_condenser"]
    params = {"max_approach_k": 15.0, "min_samples": 15}

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if not _has(df, "cond_temp", "outdoor_temp"):
            return []
        p = self.params
        cooling = _active_mask(df) & (df.get("mode") == "cool")
        approach = (df["cond_temp"] - df["outdoor_temp"]).where(cooling)
        mask = (approach > p["max_approach_k"]).fillna(False)
        out: list[Finding] = []
        for start, end, n in _contiguous_windows(mask, df["timestamp"], p["min_samples"]):
            win_ap = approach[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
            out.append(self._finding(
                df, start=start, end=end, severity=Severity.MEDIUM,
                message=(f"Condensing approach elevated (avg {win_ap.mean():.1f} K "
                         f"above ambient) for {n} samples."),
                recommendation=("Clean the outdoor coil, check the outdoor fan and "
                                "for airflow obstructions/recirculation."),
                metrics={"avg_approach_k": round(float(win_ap.mean()), 2), "samples": n},
            ))
        return out


class EvaporatorIcing(Detector):
    """Evaporating temperature below freezing during cooling -> coil frosting /
    low-load or low-airflow risk. Aggregated to one finding per unit.
    """

    spec = CATALOG_BY_ID["R12_evap_icing"]
    params = {"evap_limit_c": -3.0, "min_samples": 10}

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if not _has(df, "evap_temp"):
            return []
        p = self.params
        cooling = _active_mask(df)
        if _has(df, "mode"):
            cooling = cooling & (df["mode"] == "cool")
        mask = ((df["evap_temp"] < p["evap_limit_c"]) & cooling).fillna(False)
        episodes = list(_contiguous_windows(mask, df["timestamp"], p["min_samples"]))
        if not episodes:
            return []
        total = sum(n for _, _, n in episodes)
        coldest = float(df["evap_temp"][mask].min())
        return [self._finding(
            df, start=episodes[0][0], end=episodes[-1][1], severity=Severity.MEDIUM,
            message=(f"Evaporating temp below {p['evap_limit_c']:.0f} C in "
                     f"{len(episodes)} episodes ({total} samples, coldest "
                     f"{coldest:.1f} C) - coil frosting/low-load risk."),
            recommendation=("Check indoor airflow/filters, load matching, and for "
                            "low charge or a restricted expansion valve."),
            metrics={"episodes": len(episodes), "total_samples": total,
                     "coldest_evap_c": round(coldest, 1)},
        )]


class HighCompressorCurrent(Detector):
    """Compressor current abnormally high for its running frequency, relative to
    the unit's own current/frequency envelope.
    """

    spec = CATALOG_BY_ID["R17_high_current"]
    params = {"ratio_factor": 1.35, "min_freq_hz": 5.0,
              "min_current_a": 2.0, "min_duty": 0.1, "min_samples": 30}

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if not _has(df, "comp_current", "comp_freq"):
            return []
        p = self.params
        run = df[(df["comp_freq"] > p["min_freq_hz"])
                 & (df["comp_current"] > p["min_current_a"])]
        if len(run) < p["min_samples"]:
            return []
        ratio = run["comp_current"] / run["comp_freq"]
        baseline = float(ratio.median())
        mask = ratio > p["ratio_factor"] * baseline
        duty = float(mask.mean())
        if duty < p["min_duty"]:
            return []
        bad = run[mask]
        return [self._finding(
            df, start=bad["timestamp"].min(), end=bad["timestamp"].max(),
            severity=Severity.HIGH,
            message=(f"Compressor current high for its frequency during "
                     f"{duty*100:.0f}% of run time (ratio > {p['ratio_factor']:.2f}x "
                     f"the {baseline:.2f} A/Hz baseline)."),
            recommendation=("Check compressor mechanical load, voltage imbalance, "
                            "and for liquid floodback or high head pressure."),
            metrics={"duty_fraction": round(duty, 3),
                     "baseline_a_per_hz": round(baseline, 3)},
        )]


class InverterOverheat(Detector):
    """Inverter/heatsink temperature (THHS) approaching its protection limit."""

    spec = CATALOG_BY_ID["R18_inverter_overheat"]
    params = {"limit_c": 90.0, "critical_c": 100.0, "min_samples": 3}

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if not _has(df, "heatsink_temp"):
            return []
        p = self.params
        mask = (df["heatsink_temp"] > p["limit_c"]).fillna(False)
        out: list[Finding] = []
        for start, end, n in _contiguous_windows(mask, df["timestamp"], p["min_samples"]):
            win = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
            peak = float(win["heatsink_temp"].max())
            sev = Severity.CRITICAL if peak > p["critical_c"] else Severity.HIGH
            out.append(self._finding(
                df, start=start, end=end, severity=sev,
                message=f"Heatsink temp exceeded {p['limit_c']:.0f} C (peak {peak:.1f} C).",
                recommendation=("Check outdoor airflow/heatsink cooling, ambient "
                                "limits, and inverter fan."),
                metrics={"peak_c": round(peak, 1), "samples": n},
            ))
        return out


class FaultCodeRollup(Detector):
    spec = CATALOG_BY_ID["R25_fault_rollup"]
    params = {"ok_values": {"", "0", "00", "nan", "none", "-"}}

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if "error_code" not in df.columns:
            return []
        codes = df["error_code"].astype("string").str.strip().str.lower()
        bad = ~codes.isin(self.params["ok_values"]) & codes.notna()
        if not bad.any():
            return []
        sub = df[bad]
        counts = sub["error_code"].astype("string").value_counts()
        top = ", ".join(f"{code} x{n}" for code, n in counts.head(5).items())
        return [self._finding(
            df, start=sub["timestamp"].min(), end=sub["timestamp"].max(),
            severity=Severity.INFO if len(sub) < 3 else Severity.MEDIUM,
            message=f"{int(bad.sum())} abnormal-code samples. Top: {top}.",
            recommendation="Cross-reference codes with the Mitsubishi service manual.",
            metrics={"total": int(bad.sum()),
                     "codes": {str(k): int(v) for k, v in counts.head(10).items()}},
        )]


IMPLEMENTED_DETECTORS = [
    RefrigerantUndercharge,
    HighDischargeTemp,
    HighPressureTripRisk,
    LowPressureTripRisk,
    LEVFault,
    DirtyCondenser,
    EvaporatorIcing,
    HighCompressorCurrent,
    InverterOverheat,
    CompressorShortCycling,
    ComfortDeviation,
    ThermistorFault,
    FaultCodeRollup,
]
