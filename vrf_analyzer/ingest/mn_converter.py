"""Parser for Mitsubishi MN Converter service exports (CMS-MNG-E family).

These files are outdoor-unit-centric: after a metadata preamble, each row is one
timestamp holding the full OU refrigerant-cycle plus a repeating 4-column block
(TH1, TH2, TH3, IC S) for every indoor unit. Column names repeat between the OU
and the IU blocks, so parsing is driven by the *ownership* row (which unit each
column belongs to) rather than by name alone.

Layout (0-based line numbers):
  0        : capture metadata (dates, MN Converter model, unit/record counts)
  1        : outdoor unit info (Adres, Attr:OC, Modl, Serial, Capa, ...)
  2..N     : indoor unit info rows (Attr:IC)
  N+1      : ownership row  -> OC(051) / IC(001) per column
  N+2      : column-name header
  N+3..    : data rows

Output: normalized long form (one row per timestamp per unit), with derived
condensing/evaporating temperatures and suction superheat computed from the
reported pressures using the configured refrigerant.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ..refrigerant import psi_gauge_to_kpa_gauge, sat_temp_from_gauge
from ..schema import ALL_COLUMNS, Mode, UnitRole

# OU column name (as it appears in the header) -> canonical signal
_OU_MAP = {
    "TH2": "suction_temp",       # accumulator/suction gas temp
    "TH3": "liquid_pipe_temp",   # outdoor coil liquid temp
    "TH4": "discharge_temp",     # compressor discharge
    "TH7": "outdoor_temp",       # ambient
    "TH8": "heatsink_temp",      # inverter/HIC heatsink (tentative)
    "63HS": "high_pressure",     # high side (psi gauge -> kPa)
    "63LS": "low_pressure",      # low side  (psi gauge -> kPa)
    "W(comp)": "power",          # compressor watts -> kW
    "I(comp)(A)": "comp_current",
    "F/Hz": "comp_freq",
    "FAN": "fan_speed",
    "SC": "subcool",
    # NOTE: SCm (subcool target) is a dummy/placeholder in these exports and is
    # intentionally NOT mapped.
    "Demand(%)": "capacity_demand",
    "OPERATION MODE": "mode",
    "State": "error_code",       # 'Ordinary'/'Stop'/... -> normalized below
}

# IU per-unit block: header name -> canonical signal
_IU_MAP = {
    "TH1": "room_temp",          # return-air / intake
    "TH2": "liquid_pipe_temp",
    "TH3": "gas_pipe_temp",
    "IC S": "mode",              # 'Cool ON'/'Cool OFF'/'Stop' -> mode + active
}

_MODE_MAP = {
    "cooling": Mode.COOL.value, "cool": Mode.COOL.value,
    "heating": Mode.HEAT.value, "heat": Mode.HEAT.value,
    "dry": Mode.DRY.value, "fan": Mode.FAN.value,
    "defrost": Mode.DEFROST.value, "stop": Mode.OFF.value, "off": Mode.OFF.value,
}
_NORMAL_STATES = {"ordinary", "stop", "warm up", "warmup", "defrost",
                  "preparing", "restart", "", "nan"}


def _find_header_lines(lines: list[str]) -> tuple[int, int]:
    """Return (ownership_line_idx, header_line_idx)."""
    for i, ln in enumerate(lines):
        cells = [c.strip() for c in ln.split(",")]
        if cells[:2] == ["Date", "Time"]:
            return i - 1, i
    raise ValueError("could not locate the 'Date,Time,...' header row")


def _meta(lines: list[str]) -> dict:
    m = {}
    first = lines[0]
    for key in ("StrtDate", "StrtTime", "EndDate", "EndTime", "Cycle", "Units", "Records"):
        mt = re.search(rf"{key}\s*:\s*([^\s,]+)", first)
        if mt:
            m[key] = mt.group(1)
    ou = re.search(r"Adres:(\d+),\s*Attr:OC[^,]*,\s*Modl:([^,]+)", lines[1])
    if ou:
        m["ou_address"] = ou.group(1)
        m["ou_model"] = ou.group(2).strip()
    return m


def _mode_from(text) -> str:
    if not isinstance(text, str):
        return np.nan
    t = text.strip().lower()
    for key, val in _MODE_MAP.items():
        if key in t:
            return val
    return np.nan


def read_mn_converter(path: str, refrigerant: str = "R410A") -> pd.DataFrame:
    with open(path, encoding="latin-1") as fh:
        lines = [ln.rstrip("\r\n") for ln in fh]

    own_idx, hdr_idx = _find_header_lines(lines)
    owners = [c.strip() for c in lines[own_idx].split(",")]
    headers = [c.strip() for c in lines[hdr_idx].split(",")]
    meta = _meta(lines)

    data = pd.read_csv(path, skiprows=hdr_idx + 1, header=None,
                       encoding="latin-1", names=list(range(len(headers))))

    ts = pd.to_datetime(
        data[0].astype(str).str.strip() + " " + data[1].astype(str).str.strip(),
        format="%m/%d/%Y %H:%M:%S", errors="coerce",
    )

    system_id = f"OU-{meta.get('ou_address', '00')}"

    def _col(owner_prefix: str, name: str):
        for i, (o, h) in enumerate(zip(owners, headers)):
            if o.startswith(owner_prefix) and h == name:
                return data[i]
        return None

    frames: list[pd.DataFrame] = []

    # --- outdoor unit ----------------------------------------------------
    ou = _blank(ts, system_id, f"OC-{meta.get('ou_address', '00')}", UnitRole.OUTDOOR)
    for src, canonical in _OU_MAP.items():
        col = _col("OC", src)
        if col is None:
            continue
        if canonical == "mode":
            ou["mode"] = col.map(_mode_from)
        elif canonical == "error_code":
            state = col.astype(str).str.strip()
            ou["error_code"] = np.where(
                state.str.lower().isin(_NORMAL_STATES), "0", state
            )
        else:
            ou[canonical] = pd.to_numeric(col, errors="coerce")

    # unit conversions
    if ou["high_pressure"].notna().any():
        ou["high_pressure"] = psi_gauge_to_kpa_gauge(ou["high_pressure"])
    if ou["low_pressure"].notna().any():
        ou["low_pressure"] = psi_gauge_to_kpa_gauge(ou["low_pressure"])
    if ou["power"].notna().any():
        ou["power"] = ou["power"] / 1000.0  # W -> kW

    # derived cycle temps + superheat, only while the compressor runs
    running = ou["comp_freq"].fillna(0) > 0
    ou["cond_temp"] = np.where(
        running, sat_temp_from_gauge(ou["high_pressure"], refrigerant), np.nan)
    ou["evap_temp"] = np.where(
        running, sat_temp_from_gauge(ou["low_pressure"], refrigerant), np.nan)
    ou["superheat"] = np.where(
        running, ou["suction_temp"] - ou["evap_temp"], np.nan)
    # keep reported subcool only while running; mask idle noise
    ou["subcool"] = ou["subcool"].where(running)
    frames.append(ou)

    # --- indoor units ----------------------------------------------------
    # The OU section carries per-indoor arrays LEV{k}/SC{k}/SCm{k}, indexed by
    # the indoor unit's position (1-based) in address order. LEV{k} is the
    # zone's expansion-valve opening; SC{k}/SCm{k} are subcool actual/target
    # (often unreported -- all zero -- in OM exports, so mapped only if nonzero).
    ic_owners = sorted({o for o in owners if o.startswith("IC")})
    evap = ou["evap_temp"].to_numpy()
    for k, owner in enumerate(ic_owners, start=1):
        addr = re.search(r"IC\((\d+)\)", owner)
        unit_id = f"IC-{addr.group(1)}" if addr else owner
        iu = _blank(ts, system_id, unit_id, UnitRole.INDOOR)
        state_col = None
        for src, canonical in _IU_MAP.items():
            # locate the column with this exact owner label + header name
            col = None
            for i, (o, h) in enumerate(zip(owners, headers)):
                if o == owner and h == src:
                    col = data[i]
                    break
            if col is None:
                continue
            if canonical == "mode":
                state_col = col.astype(str).str.strip()
                iu["mode"] = state_col.map(_mode_from)
            else:
                iu[canonical] = pd.to_numeric(col, errors="coerce")

        # per-zone expansion valve (from the OU LEV{k} array)
        lev = _col("OC", f"LEV{k}")
        if lev is not None:
            iu["lev_pulse"] = pd.to_numeric(lev, errors="coerce")
        # per-zone subcool array, only if actually populated (SCm is a dummy
        # placeholder in these exports and is intentionally ignored).
        sc_k = _col("OC", f"SC{k}")
        if sc_k is not None and pd.to_numeric(sc_k, errors="coerce").abs().sum() > 0:
            iu["subcool"] = pd.to_numeric(sc_k, errors="coerce")

        # mask indoor pipe temps to active periods (state contains 'ON')
        active = (
            state_col.str.upper().str.contains("ON", na=False)
            if state_col is not None
            else pd.Series(True, index=iu.index)
        )
        for sig in ("liquid_pipe_temp", "gas_pipe_temp"):
            iu[sig] = iu[sig].where(active)
        # per-zone suction superheat = indoor gas-pipe temp - system evap temp
        iu["superheat"] = np.where(
            active.to_numpy() & ~np.isnan(evap),
            iu["gas_pipe_temp"].to_numpy() - evap,
            np.nan,
        )
        frames.append(iu)

    df = pd.concat(frames, ignore_index=True)
    df = df[ALL_COLUMNS].dropna(subset=["timestamp"])
    df = df.sort_values(["unit_id", "timestamp"]).reset_index(drop=True)
    df.attrs["profile"] = "mitsubishi_mn_converter"
    df.attrs["meta"] = meta
    df.attrs["refrigerant"] = refrigerant
    return df


def _blank(ts, system_id, unit_id, role) -> pd.DataFrame:
    out = pd.DataFrame({c: np.nan for c in ALL_COLUMNS}, index=range(len(ts)))
    out["timestamp"] = ts.values
    out["system_id"] = system_id
    out["unit_id"] = unit_id
    out["unit_role"] = role.value
    out["defrost"] = False
    return out
