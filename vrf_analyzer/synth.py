"""Generate synthetic-but-realistic VRF logs with injected faults.

Used to drive the prototype end-to-end until a real Mitsubishi CSV is supplied.
The output is already in the normalized schema (profile='canonical'), so it round
-trips through the whole ingest -> index -> assess pipeline. Deterministic given
a seed so runs and tests are reproducible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import ALL_COLUMNS, UnitRole, Mode


def _base_series(rng, n, mean, amp, noise, period=96):
    t = np.arange(n)
    daily = amp * np.sin(2 * np.pi * t / period)
    return mean + daily + rng.normal(0, noise, n)


def generate(
    seed: int = 7,
    days: int = 3,
    interval_min: int = 15,
    inject_faults: bool = True,
) -> pd.DataFrame:
    """Return a normalized DataFrame for one system with 1 OU + 3 IUs."""
    rng = np.random.default_rng(seed)
    n = int(days * 24 * 60 / interval_min)
    start = pd.Timestamp("2026-01-06 00:00:00")
    ts = pd.date_range(start, periods=n, freq=f"{interval_min}min")
    period = int(24 * 60 / interval_min)

    frames = []
    system_id = "SYS-1"

    # --- Outdoor unit ----------------------------------------------------
    ou = _blank(ts, system_id, "OU-1", UnitRole.OUTDOOR)
    ou["outdoor_temp"] = _base_series(rng, n, 5.0, 6.0, 0.6, period)
    ou["mode"] = Mode.COOL.value
    ou["comp_freq"] = np.clip(_base_series(rng, n, 60, 25, 4, period), 0, 120)
    ou["comp_current"] = ou["comp_freq"] * 0.12 + rng.normal(0, 0.3, n)
    ou["high_pressure"] = _base_series(rng, n, 2800, 200, 30, period)
    ou["low_pressure"] = _base_series(rng, n, 900, 80, 15, period)
    ou["discharge_temp"] = _base_series(rng, n, 78, 8, 1.5, period)
    ou["suction_temp"] = _base_series(rng, n, 8, 3, 0.8, period)
    ou["heatsink_temp"] = _base_series(rng, n, 55, 10, 2, period)
    ou["subcool"] = np.clip(_base_series(rng, n, 6.0, 1.5, 0.4, period), 0, None)
    ou["superheat"] = np.clip(_base_series(rng, n, 6.0, 1.5, 0.4, period), 0, None)
    ou["error_code"] = "0"

    # --- Indoor units ----------------------------------------------------
    ius = []
    for i in range(1, 4):
        iu = _blank(ts, system_id, f"IU-{i}", UnitRole.INDOOR)
        iu["mode"] = Mode.COOL.value
        iu["set_temp"] = 24.0
        iu["room_temp"] = _base_series(rng, n, 24.0, 1.0, 0.3, period)
        iu["inlet_temp"] = iu["room_temp"] + rng.normal(0, 0.2, n)
        iu["liquid_pipe_temp"] = _base_series(rng, n, 12, 2, 0.5, period)
        iu["gas_pipe_temp"] = _base_series(rng, n, 10, 2, 0.5, period)
        iu["lev_pulse"] = np.clip(_base_series(rng, n, 250, 60, 15, period), 0, 480)
        iu["fan_speed"] = _base_series(rng, n, 900, 120, 20, period)
        iu["capacity_demand"] = np.clip(_base_series(rng, n, 55, 25, 5, period), 0, 100)
        iu["error_code"] = "0"
        ius.append(iu)

    if inject_faults:
        # Fault A: undercharge on the system -> low subcool + high superheat (last day)
        lo = n - period
        ou.loc[lo:, "subcool"] = np.clip(ou.loc[lo:, "subcool"] - 5.5, 0, None)
        ou.loc[lo:, "superheat"] = ou.loc[lo:, "superheat"] + 12.0
        # Fault B: high discharge temp spike block
        hi0, hi1 = period, period + 8
        ou.loc[hi0:hi1, "discharge_temp"] = 118.0

        # Fault C: IU-1 comfort deviation (room runs hot vs setpoint)
        seg = ius[0].loc[period // 2:, "set_temp"] + 3.5
        ius[0].loc[period // 2:, "room_temp"] = seg + rng.normal(0, 0.25, len(seg))

        # Fault D: IU-2 short-cycling compressor-side proxy via error + gas sensor flatline
        ius[1].loc[:, "gas_pipe_temp"] = 10.0  # flatlined sensor

        # Fault E: IU-3 error codes burst
        ius[2].loc[period: period + 6, "error_code"] = "6607"

    frames = [ou] + ius
    df = pd.concat(frames, ignore_index=True)
    return df[ALL_COLUMNS].sort_values(["unit_id", "timestamp"]).reset_index(drop=True)


def _blank(ts, system_id, unit_id, role) -> pd.DataFrame:
    df = pd.DataFrame({c: np.nan for c in ALL_COLUMNS}, index=range(len(ts)))
    df["timestamp"] = ts
    df["system_id"] = system_id
    df["unit_id"] = unit_id
    df["unit_role"] = role.value
    df["defrost"] = False
    return df


def write_csv(path: str, **kwargs) -> str:
    df = generate(**kwargs)
    df.to_csv(path, index=False)
    return path
