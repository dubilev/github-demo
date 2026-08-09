"""Unit tests for individual detectors using crafted per-unit frames."""

import numpy as np
import pandas as pd

from vrf_analyzer.schema import ALL_COLUMNS, UnitRole
from vrf_analyzer.rules.base import Severity
from vrf_analyzer.rules.detectors import (
    LEVFault, DirtyCondenser, EvaporatorIcing,
    HighCompressorCurrent, InverterOverheat,
    RefrigerantUndercharge, RefrigerantOvercharge, AmbientLimits,
    PartLoadOversizing, OilReturnProblem, ReversingValveFault,
    ModeConflict, RefrigerantLeakTrend,
)


def _frame(n=120, role=UnitRole.OUTDOOR, unit_id="OC-1", **signals):
    df = pd.DataFrame({c: np.nan for c in ALL_COLUMNS}, index=range(n))
    df["timestamp"] = pd.date_range("2026-01-01", periods=n, freq="1min")
    df["system_id"] = "SYS-1"
    df["unit_id"] = unit_id
    df["unit_role"] = role.value
    df["mode"] = "cool"
    df["comp_freq"] = 40.0  # running (used by _active_mask)
    for k, v in signals.items():
        df[k] = v
    return df


def test_evaporator_icing_fires_and_is_quiet():
    cold = _frame(evap_temp=np.r_[np.full(40, -6.0), np.full(80, 3.0)])
    f = EvaporatorIcing().run(cold)
    assert len(f) == 1 and f[0].metrics["coldest_evap_c"] <= -3
    warm = _frame(evap_temp=np.full(120, 4.0))
    assert EvaporatorIcing().run(warm) == []


def test_dirty_condenser_fires_on_high_approach():
    df = _frame(outdoor_temp=30.0, cond_temp=np.r_[np.full(30, 55.0), np.full(90, 37.0)])
    f = DirtyCondenser().run(df)
    assert len(f) == 1 and f[0].metrics["avg_approach_k"] > 15
    healthy = _frame(outdoor_temp=30.0, cond_temp=37.0)
    assert DirtyCondenser().run(healthy) == []


def test_inverter_overheat_severity():
    df = _frame(heatsink_temp=np.r_[np.full(10, 105.0), np.full(110, 60.0)])
    f = InverterOverheat().run(df)
    assert len(f) == 1 and f[0].severity.label == "Critical"
    assert InverterOverheat().run(_frame(heatsink_temp=70.0)) == []


def test_high_compressor_current_fires():
    freq = np.full(120, 40.0)
    cur = np.full(120, 40 * 0.5)          # baseline 0.5 A/Hz
    cur[:40] = 40 * 0.9                    # spike to 0.9 A/Hz for a third of the run
    df = _frame(comp_freq=freq, comp_current=cur)
    f = HighCompressorCurrent().run(df)
    assert len(f) == 1
    normal = _frame(comp_freq=freq, comp_current=np.full(120, 40 * 0.5))
    assert HighCompressorCurrent().run(normal) == []


def test_undercharge_vrf_logic_severity():
    # low subcool + NORMAL superheat -> Medium "verify charge" (LEV logic)
    mild = _frame(subcool=1.0, superheat=6.0)
    f = RefrigerantUndercharge().run(mild)
    assert len(f) == 1 and f[0].severity == Severity.MEDIUM
    # low subcool + HIGH superheat -> High undercharge (LEV saturated)
    severe = _frame(subcool=1.0, superheat=22.0)
    f2 = RefrigerantUndercharge().run(severe)
    assert len(f2) == 1 and f2[0].severity == Severity.HIGH
    # healthy subcool -> nothing
    assert RefrigerantUndercharge().run(_frame(subcool=6.0, superheat=6.0)) == []


def test_ambient_limits_fires_outside_cooling_range():
    df = _frame(outdoor_temp=np.r_[np.full(20, 50.0), np.full(100, 35.0)])
    df["mode"] = "cool"
    f = AmbientLimits().run(df)
    assert len(f) == 1 and f[0].metrics["max_c"] >= 46
    inrange = _frame(outdoor_temp=35.0)
    inrange["mode"] = "cool"
    assert AmbientLimits().run(inrange) == []


def test_overcharge_fires_on_high_subcool():
    df = _frame(subcool=15.0, high_pressure=3600.0)
    f = RefrigerantOvercharge().run(df)
    assert len(f) == 1
    assert RefrigerantOvercharge().run(_frame(subcool=6.0)) == []


def test_part_load_oversizing():
    df = _frame(comp_freq=np.full(120, 20.0))   # pinned at minimum
    f = PartLoadOversizing().run(df)
    assert len(f) == 1 and f[0].metrics["frac_at_min"] >= 0.6
    varied = _frame(comp_freq=np.linspace(20, 70, 120))
    assert PartLoadOversizing().run(varied) == []


def test_oil_return_long_low_speed():
    # 4 h at 20 Hz (1-min samples), never reaching oil-return speed
    df = _frame(n=240, comp_freq=np.full(240, 20.0))
    f = OilReturnProblem().run(df)
    assert len(f) == 1 and f[0].metrics["longest_low_speed_hours"] >= 3


def test_reversing_valve_wrong_direction():
    iu = _frame(role=UnitRole.INDOOR, unit_id="IC-1",
                gas_pipe_temp=np.full(120, 30.0), room_temp=np.full(120, 22.0))
    iu["mode"] = "cool"  # coil hotter than room while cooling -> fault
    f = ReversingValveFault().run(iu)
    assert len(f) == 1


def test_mode_conflict_system_scope():
    a = _frame(role=UnitRole.INDOOR, unit_id="IC-1"); a["mode"] = "cool"
    b = _frame(role=UnitRole.INDOOR, unit_id="IC-2"); b["mode"] = "heat"
    sysdf = pd.concat([a, b], ignore_index=True)
    f = ModeConflict().run(sysdf)
    assert len(f) == 1 and f[0].metrics["conflict_samples"] > 0


def test_leak_trend_declining_subcool():
    n = 3 * 24 * 4  # 3 days at 15-min cadence
    df = _frame(n=n, subcool=np.linspace(8.0, 2.0, n))
    df["timestamp"] = pd.date_range("2026-01-01", periods=n, freq="15min")
    f = RefrigerantLeakTrend().run(df)
    assert len(f) == 1 and f[0].metrics["slope_k_per_day"] < 0


def test_lev_fault_underfed_zone():
    iu = _frame(role=UnitRole.INDOOR, unit_id="IC-1",
                lev_pulse=np.full(120, 480.0), superheat=np.full(120, 20.0))
    f = LEVFault().run(iu)
    assert len(f) == 1 and "underfed" in f[0].message
    # healthy: mid-travel valve, normal superheat
    ok = _frame(role=UnitRole.INDOOR, unit_id="IC-1",
                lev_pulse=np.full(120, 200.0), superheat=np.full(120, 5.0))
    assert LEVFault().run(ok) == []
