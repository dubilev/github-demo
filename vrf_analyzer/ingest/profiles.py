"""Format profiles: map a vendor CSV layout onto the canonical schema.

A Profile is a declarative description of one export format. Adapting the tool to
a new Mitsubishi export (MN Converter, AE-200/EW-50, MELANNEX, Diamond service
tool, ...) means adding one Profile here -- the rest of the pipeline is untouched.

When you share a real sample CSV, we add/adjust exactly one Profile: its
`column_map`, `datetime` handling, and how unit/system ids are derived.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd


@dataclass
class Profile:
    name: str
    description: str = ""
    # source CSV column name -> canonical signal/id name
    column_map: dict[str, str] = field(default_factory=dict)
    # source column(s) that hold the timestamp; joined with a space if multiple
    datetime_columns: list[str] = field(default_factory=lambda: ["timestamp"])
    datetime_format: Optional[str] = None  # None -> pandas infers
    # csv read options
    read_kwargs: dict = field(default_factory=dict)
    # optional post-processing hook (normalized df in, normalized df out)
    postprocess: Optional[Callable[[pd.DataFrame], pd.DataFrame]] = None
    # per-signal numeric scaling: canonical name -> multiplier
    scale: dict[str, float] = field(default_factory=dict)
    # how to detect whether this profile matches a given header set
    signature: list[str] = field(default_factory=list)

    def matches(self, columns: list[str]) -> bool:
        if not self.signature:
            return False
        cols = set(columns)
        return all(c in cols for c in self.signature)


def _parse_datetime(df: pd.DataFrame, profile: Profile) -> pd.Series:
    cols = [c for c in profile.datetime_columns if c in df.columns]
    if not cols:
        raise ValueError(
            f"profile '{profile.name}': none of datetime_columns "
            f"{profile.datetime_columns} found in CSV"
        )
    if len(cols) == 1:
        raw = df[cols[0]].astype(str)
    else:
        raw = df[cols].astype(str).agg(" ".join, axis=1)
    return pd.to_datetime(raw, format=profile.datetime_format, errors="coerce")


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------

# 1) The canonical/synthetic profile: CSV already uses normalized column names.
#    This is what the synthetic data generator emits and is the identity mapping.
CANONICAL = Profile(
    name="canonical",
    description="CSV already in normalized vrf-analyzer schema (identity map).",
    column_map={},  # identity
    datetime_columns=["timestamp"],
    signature=["timestamp", "system_id", "unit_id", "unit_role"],
)

# 2) A starter profile for a typical Mitsubishi Maintenance Tool / MN Converter
#    wide export. Column names below are PLACEHOLDERS to be corrected against a
#    real sample -- Mitsubishi exports vary by tool version and language locale.
MITSUBISHI_MN = Profile(
    name="mitsubishi_mn",
    description=(
        "Starter mapping for Mitsubishi Maintenance Tool / MN Converter wide "
        "exports. Column names are placeholders -- adjust to the real sample."
    ),
    column_map={
        "Date/Time": "timestamp",
        "Address": "unit_id",
        "System": "system_id",
        "Unit Type": "unit_role",
        "Mode": "mode",
        "Set Temp": "set_temp",
        "Room Temp": "room_temp",
        "Inlet Temp": "inlet_temp",
        "Outdoor Temp(TH7)": "outdoor_temp",
        "Liquid Temp": "liquid_pipe_temp",
        "Gas Temp": "gas_pipe_temp",
        "Discharge Temp(TH4)": "discharge_temp",
        "Suction Temp": "suction_temp",
        "Heatsink Temp(THHS)": "heatsink_temp",
        "High Pressure(63HS)": "high_pressure",
        "Low Pressure(63LS)": "low_pressure",
        "Comp Frequency": "comp_freq",
        "Comp Current": "comp_current",
        "LEV": "lev_pulse",
        "Fan Speed": "fan_speed",
        "Error Code": "error_code",
    },
    datetime_columns=["Date/Time"],
    signature=["Date/Time", "Address"],
)


PROFILES: dict[str, Profile] = {p.name: p for p in (CANONICAL, MITSUBISHI_MN)}


def get_profile(name: str) -> Profile:
    if name not in PROFILES:
        raise KeyError(
            f"unknown profile '{name}'. available: {sorted(PROFILES)}"
        )
    return PROFILES[name]


def detect_profile(columns: list[str]) -> Optional[Profile]:
    """Return the first built-in profile whose signature matches the header."""
    for profile in PROFILES.values():
        if profile.matches(columns):
            return profile
    return None
