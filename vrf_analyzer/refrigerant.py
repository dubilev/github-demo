"""Refrigerant pressure-temperature saturation helpers.

Mitsubishi service logs report raw pressures (63HS/63LS). To diagnose the
refrigerant cycle we need the corresponding saturated condensing/evaporating
temperatures. This module provides a compact saturation table per refrigerant
and interpolates T_sat from an absolute pressure.

Values are approximate bubble-point saturation data, adequate for the ~1 K
tolerances the detectors use. Add refrigerants as needed.
"""

from __future__ import annotations

import numpy as np

PSI_TO_KPA = 6.894757
ATM_KPA = 101.325

# refrigerant -> (temp_degC array, absolute-pressure kPa array), ascending
_SAT_TABLES: dict[str, tuple[list[float], list[float]]] = {
    # R410A saturation (bubble point), approximate
    "R410A": (
        [-30, -20, -10, 0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70],
        [269, 400, 573, 799, 934, 1088, 1259, 1450, 1663, 1900, 2162,
         2452, 2771, 3122, 3506, 3926, 4384, 4884],
    ),
    # R32 saturation (bubble point), approximate
    "R32": (
        [-30, -20, -10, 0, 10, 20, 30, 40, 50, 60, 70],
        [270, 401, 574, 813, 1107, 1470, 1912, 2443, 3074, 3818, 4688],
    ),
}


def sat_temp(p_abs_kpa: float | np.ndarray, refrigerant: str = "R410A"):
    """Saturated temperature (degC) for an absolute pressure (kPa)."""
    if refrigerant not in _SAT_TABLES:
        raise KeyError(f"no saturation table for {refrigerant!r}")
    temps, pres = _SAT_TABLES[refrigerant]
    # np.interp needs ascending x (pressure); temps ascend with pressure too
    return np.interp(p_abs_kpa, pres, temps, left=temps[0], right=temps[-1])


def psi_gauge_to_kpa_gauge(psi_gauge):
    return np.asarray(psi_gauge, dtype=float) * PSI_TO_KPA


def sat_temp_from_gauge(p_gauge_kpa, refrigerant: str = "R410A"):
    """T_sat from a *gauge* pressure in kPa."""
    return sat_temp(np.asarray(p_gauge_kpa, dtype=float) + ATM_KPA, refrigerant)
