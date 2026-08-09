"""CSV -> normalized DataFrame using a Profile."""

from __future__ import annotations

import glob
import os
from typing import Optional

import numpy as np
import pandas as pd

from ..schema import ALL_COLUMNS, SIGNALS, UnitRole
from .profiles import (
    Profile,
    _parse_datetime,
    detect_profile,
    get_profile,
    sniff_raw_profile,
)

# signals that are numeric (everything with a physical unit that isn't enum/bool/code)
_NUMERIC_SIGNALS = [
    name for name, unit in SIGNALS.items()
    if unit not in ("enum", "bool", "code")
]


def _normalize_unit_role(value) -> Optional[str]:
    if pd.isna(value):
        return None
    s = str(value).strip().lower()
    if s in ("ou", "outdoor", "oc", "condenser", "condensing"):
        return UnitRole.OUTDOOR.value
    if s in ("iu", "indoor", "ic", "fancoil", "fan coil"):
        return UnitRole.INDOOR.value
    # already canonical
    if s.upper() in (UnitRole.OUTDOOR.value, UnitRole.INDOOR.value):
        return s.upper()
    return value


def load_csv(
    path: str,
    profile: Optional[Profile | str] = None,
) -> pd.DataFrame:
    """Load one CSV into the normalized wide schema.

    If ``profile`` is None, auto-detect from the header. Raises if no profile
    matches -- pass one explicitly (or add one) in that case.
    """
    if isinstance(profile, str):
        profile = get_profile(profile)

    # reader-based profiles (complex layouts) short-circuit the generic path
    if profile is None:
        sniffed = sniff_raw_profile(path)
        if sniffed is not None:
            profile = sniffed
    if profile is not None and profile.reader is not None:
        df = profile.reader(path)
        df.attrs.setdefault("source_file", os.path.basename(path))
        df.attrs.setdefault("profile", profile.name)
        return df

    raw = pd.read_csv(path, **(profile.read_kwargs if profile else {}))
    raw.columns = [str(c).strip() for c in raw.columns]

    if profile is None:
        profile = detect_profile(list(raw.columns))
        if profile is None:
            raise ValueError(
                f"could not auto-detect a profile for {path!r}. "
                f"columns={list(raw.columns)[:12]}... "
                f"Pass profile=<name> or add a Profile."
            )

    df = pd.DataFrame()
    df["timestamp"] = _parse_datetime(raw, profile)

    # apply column map (identity if empty)
    if profile.column_map:
        for src, canonical in profile.column_map.items():
            if canonical == "timestamp":
                continue
            if src in raw.columns:
                df[canonical] = raw[src]
    else:
        for col in raw.columns:
            if col in ALL_COLUMNS:
                df[col] = raw[col]

    # ensure identity + all signal columns exist
    for col in ALL_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan

    # coerce types
    if "unit_role" in df:
        df["unit_role"] = df["unit_role"].map(_normalize_unit_role)
    for sig in _NUMERIC_SIGNALS:
        df[sig] = pd.to_numeric(df[sig], errors="coerce")
        if profile.scale.get(sig):
            df[sig] = df[sig] * profile.scale[sig]
    if "defrost" in df:
        df["defrost"] = _coerce_bool(df["defrost"])

    df["system_id"] = df["system_id"].astype("string")
    df["unit_id"] = df["unit_id"].astype("string")

    df = df[ALL_COLUMNS]
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    if profile.postprocess is not None:
        df = profile.postprocess(df)

    df.attrs["source_file"] = os.path.basename(path)
    df.attrs["profile"] = profile.name
    return df


def _coerce_bool(s: pd.Series) -> pd.Series:
    truthy = {"1", "true", "yes", "on", "y", "t"}
    return s.map(
        lambda v: (str(v).strip().lower() in truthy) if pd.notna(v) else False
    )


def load_dir(
    directory: str,
    pattern: str = "*.csv",
    profile: Optional[Profile | str] = None,
) -> pd.DataFrame:
    """Load and concatenate every CSV in a directory."""
    paths = sorted(glob.glob(os.path.join(directory, pattern)))
    if not paths:
        raise FileNotFoundError(f"no files matching {pattern!r} in {directory!r}")
    frames = [load_csv(p, profile=profile) for p in paths]
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["system_id", "unit_id", "timestamp"]).reset_index(drop=True)
