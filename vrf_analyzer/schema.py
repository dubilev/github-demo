"""Canonical (normalized) schema for VRF telemetry.

Every vendor CSV format is mapped onto these signal names and units so that the
indexing and rules layers never have to know which tool produced the file.

One normalized row = one timestamp for one physical unit (an outdoor unit OU or
an indoor unit IU). Real Mitsubishi exports are wide (one row per timestamp with
many columns), so keeping the normalized form wide keeps the mapping trivial.
"""

from __future__ import annotations

from enum import Enum


class UnitRole(str, Enum):
    OUTDOOR = "OU"  # outdoor / condensing unit
    INDOOR = "IU"   # indoor / fan-coil unit


class Mode(str, Enum):
    OFF = "off"
    COOL = "cool"
    HEAT = "heat"
    DRY = "dry"
    FAN = "fan"
    DEFROST = "defrost"
    AUTO = "auto"


# --- Identity columns present on every normalized row -----------------------
ID_COLUMNS = [
    "timestamp",    # tz-aware or naive pandas datetime
    "system_id",    # refrigerant system / OU group identifier
    "unit_id",      # unique unit address within the system
    "unit_role",    # UnitRole value
]

# --- Canonical signal columns  (name -> unit) -------------------------------
# Not every row has every signal; IU rows and OU rows populate different subsets.
SIGNALS: dict[str, str] = {
    # operating state
    "mode": "enum",
    "defrost": "bool",
    "error_code": "code",
    # temperatures (degC)
    "set_temp": "degC",
    "room_temp": "degC",           # IU return-air / room temperature
    "inlet_temp": "degC",          # IU coil inlet air
    "outdoor_temp": "degC",        # OU ambient (TH7)
    "liquid_pipe_temp": "degC",
    "gas_pipe_temp": "degC",
    "discharge_temp": "degC",      # compressor discharge (TH4)
    "suction_temp": "degC",
    "heatsink_temp": "degC",       # inverter heatsink (THHS)
    "cond_temp": "degC",           # condensing temperature (saturated, from HP)
    "evap_temp": "degC",           # evaporating temperature (saturated, from LP)
    # derived refrigerant health
    "subcool": "K",                # condenser subcooling
    "superheat": "K",              # evaporator/suction superheat
    # pressures (kPa gauge)
    "high_pressure": "kPa",        # 63HS
    "low_pressure": "kPa",         # 63LS
    # compressor / electrical
    "comp_freq": "Hz",
    "comp_current": "A",
    "power": "kW",
    # valves / airflow
    "lev_pulse": "pulse",          # linear expansion valve opening
    "fan_speed": "rpm",
    "capacity_demand": "pct",      # requested capacity 0-100
}

ALL_COLUMNS = ID_COLUMNS + list(SIGNALS.keys())


def empty_columns() -> list[str]:
    """Return the full ordered list of normalized columns."""
    return list(ALL_COLUMNS)
