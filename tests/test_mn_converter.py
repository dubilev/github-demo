"""Regression tests for the Mitsubishi MN Converter parser + refrigerant model.

Uses a trimmed, serial-redacted real export committed under data/sample/.
"""

import os

import numpy as np
import pytest

from vrf_analyzer.ingest import load_csv
from vrf_analyzer.ingest.profiles import sniff_raw_profile
from vrf_analyzer.refrigerant import sat_temp_from_gauge
from vrf_analyzer.rules import assess

SAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "sample", "mn_converter_sample.CSV",
)


def test_sample_exists():
    assert os.path.exists(SAMPLE), "MN Converter sample fixture missing"


def test_autodetect_profile():
    prof = sniff_raw_profile(SAMPLE)
    assert prof is not None and prof.name == "mitsubishi_mn_converter"


def test_parse_units_and_schema():
    df = load_csv(SAMPLE)
    from vrf_analyzer.schema import ALL_COLUMNS
    assert list(df.columns) == ALL_COLUMNS
    units = set(df["unit_id"].unique())
    assert "OC-51" in units
    # six indoor units
    assert sum(1 for u in units if u.startswith("IC-")) == 6
    assert df.attrs["meta"]["ou_model"].startswith("PUMY")


def test_derived_cycle_fields_present_and_sane():
    df = load_csv(SAMPLE)
    ou = df[df["unit_role"] == "OU"]
    run = ou[ou["comp_freq"] > 0]
    assert len(run) > 0
    # pressures converted to kPa (hundreds-thousands range, not raw psi)
    assert run["high_pressure"].median() > 1500
    # derived saturation temps computed while running
    assert run["cond_temp"].notna().any()
    assert run["evap_temp"].notna().any()
    # condensing temp above evaporating temp
    assert run["cond_temp"].median() > run["evap_temp"].median()


def test_thermistor_mapping_th6_suction_th2_hic():
    # Per the PUMY-P manual: TH6=suction (cool, single digits), TH2=HIC (warmer).
    df = load_csv(SAMPLE)
    run = df[(df["unit_role"] == "OU") & (df["comp_freq"] > 0)]
    assert run["suction_temp"].median() < run["hic_pipe_temp"].median()
    # suction superheat from TH6 lands in a physically normal band, not ~23 K
    assert 0 < run["superheat"].median() < 15


def test_refrigerant_saturation_monotonic():
    # higher pressure -> higher saturation temperature
    lo = sat_temp_from_gauge(800, "R410A")
    hi = sat_temp_from_gauge(2500, "R410A")
    assert hi > lo


def test_detectors_run_on_real_sample():
    df = load_csv(SAMPLE)
    findings = assess(df)
    # should not raise and should return a list (content depends on the window)
    assert isinstance(findings, list)
    rule_ids = {f.rule_id for f in findings}
    # no detector error findings
    assert not any(f.title.startswith("[detector error]") for f in findings)
