"""End-to-end and unit tests for the analysis pipeline."""

import os
import tempfile

import pandas as pd

from vrf_analyzer import synth
from vrf_analyzer.index import IndexStore
from vrf_analyzer.ingest import load_csv
from vrf_analyzer.rules import assess, coverage, findings_to_frame
from vrf_analyzer.report import summarize


def test_synth_shape_and_schema():
    df = synth.generate()
    from vrf_analyzer.schema import ALL_COLUMNS
    assert list(df.columns) == ALL_COLUMNS
    assert df["unit_id"].nunique() == 4  # 1 OU + 3 IU
    assert df["system_id"].nunique() == 1


def test_ingest_roundtrip_canonical():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s.csv")
        synth.write_csv(path)
        df = load_csv(path, profile="canonical")
        assert not df.empty
        assert df["timestamp"].is_monotonic_increasing or df["unit_id"].nunique() > 1


def test_index_build_and_read():
    df = synth.generate()
    with tempfile.TemporaryDirectory() as d:
        store = IndexStore(os.path.join(d, "idx")).build(df)
        assert store.exists()
        units = store.units()
        assert len(units) == 4
        back = store.read()
        assert len(back) == len(df)
        one = store.read(unit_id="OU-1")
        assert (one["unit_id"] == "OU-1").all()


def test_detectors_fire_on_injected_faults():
    df = synth.generate(inject_faults=True)
    findings = assess(df)
    rule_ids = {f.rule_id for f in findings}
    # injected faults should surface these detectors
    assert "R01_undercharge" in rule_ids
    assert "R04_high_discharge" in rule_ids
    assert "R21_comfort_deviation" in rule_ids
    assert "R25_fault_rollup" in rule_ids


def test_no_faults_is_quieter():
    faulted = assess(synth.generate(inject_faults=True))
    clean = assess(synth.generate(inject_faults=False))
    assert len(clean) < len(faulted)


def test_findings_frame_and_summary():
    findings = assess(synth.generate())
    frame = findings_to_frame(findings)
    assert set(["rule_id", "severity_label", "unit_id"]).issubset(frame.columns)
    s = summarize(findings)
    assert s["total_findings"] == len(findings)


def test_catalog_has_25_entries():
    cov = coverage()
    assert len(cov) == 25
    assert sum(1 for c in cov if c.implemented) >= 6
