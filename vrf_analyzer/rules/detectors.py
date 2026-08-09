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


class RefrigerantUndercharge(Detector):
    spec = CATALOG_BY_ID["R01_undercharge"]
    params = {"min_subcool_k": 2.0, "max_superheat_k": 12.0, "min_samples": 6}

    def run(self, df: pd.DataFrame) -> list[Finding]:
        if not _has(df, "subcool", "superheat"):
            return []
        p = self.params
        mask = (df["subcool"] < p["min_subcool_k"]) & (
            df["superheat"] > p["max_superheat_k"]
        )
        out: list[Finding] = []
        for start, end, n in _contiguous_windows(mask, df["timestamp"], p["min_samples"]):
            win = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
            out.append(self._finding(
                df, start=start, end=end,
                message=(
                    f"Low subcool (avg {win['subcool'].mean():.1f} K) with high "
                    f"superheat (avg {win['superheat'].mean():.1f} K) over {n} samples."
                ),
                recommendation=(
                    "Check for refrigerant leak and verify charge against "
                    "commissioning data; inspect service ports and flare joints."
                ),
                metrics={
                    "avg_subcool_k": round(float(win["subcool"].mean()), 2),
                    "avg_superheat_k": round(float(win["superheat"].mean()), 2),
                    "samples": n,
                },
            ))
        return out


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
    spec = CATALOG_BY_ID["R13_sensor_fault"]
    params = {
        "flatline_samples": 30,   # identical value run length
        "min_c": -40.0, "max_c": 140.0,  # plausible range for pipe/room sensors
        "sensors": ["room_temp", "liquid_pipe_temp", "gas_pipe_temp",
                    "discharge_temp", "suction_temp"],
    }

    def run(self, df: pd.DataFrame) -> list[Finding]:
        out: list[Finding] = []
        p = self.params
        for sig in p["sensors"]:
            if not _has(df, sig):
                continue
            s = df[sig]
            # out-of-range
            oor = ((s < p["min_c"]) | (s > p["max_c"])).fillna(False)
            for start, end, n in _contiguous_windows(oor, df["timestamp"], 1):
                out.append(self._finding(
                    df, start=start, end=end, severity=Severity.MEDIUM,
                    message=f"Sensor '{sig}' out of plausible range for {n} samples.",
                    recommendation=f"Inspect/replace the '{sig}' thermistor and wiring.",
                    metrics={"sensor": sig, "samples": n},
                ))
            # flatline (no change over many samples while unit is not off)
            same = (s.diff().fillna(1) == 0)
            for start, end, n in _contiguous_windows(same, df["timestamp"], p["flatline_samples"]):
                out.append(self._finding(
                    df, start=start, end=end, severity=Severity.LOW,
                    message=f"Sensor '{sig}' flatlined ({n} identical readings).",
                    recommendation=f"Verify the '{sig}' sensor is reporting live data.",
                    metrics={"sensor": sig, "samples": n},
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
    CompressorShortCycling,
    ComfortDeviation,
    ThermistorFault,
    FaultCodeRollup,
]
