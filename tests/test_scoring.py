"""Tests for the failure-mode probability scoring."""

import os

import numpy as np
import pandas as pd

from vrf_analyzer import synth
from vrf_analyzer.ingest import load_csv
from vrf_analyzer.scoring import score_system, probabilities_to_frame

SAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "sample", "mn_converter_sample.CSV",
)


def test_scores_cover_all_25_modes():
    scores = score_system(synth.generate())
    assert len(scores) == 25
    ids = {s.rule_id for s in scores}
    assert len(ids) == 25


def test_probabilities_are_bounded_and_ranked():
    scores = score_system(synth.generate())
    probs = [s.probability for s in scores if s.probability is not None]
    assert probs, "expected at least some assessed modes"
    assert all(1.0 <= p <= 97.0 for p in probs)
    # assessed modes come first, sorted descending
    assessed = [s.probability for s in scores if s.status == "assessed"]
    assert assessed == sorted(assessed, reverse=True)


def test_unassessable_modes_have_no_probability():
    scores = score_system(synth.generate())
    for s in scores:
        if s.status != "assessed":
            assert s.probability is None


def test_real_sample_ranks_undercharge_highly():
    scores = score_system(load_csv(SAMPLE))
    by_id = {s.rule_id: s for s in scores}
    uc = by_id["R01_undercharge"]
    assert uc.status == "assessed"
    # low subcool present -> should clearly beat a healthy axis like HP trip
    assert uc.probability > by_id["R05_hp_trip_risk"].probability
    # comfort needs setpoints which the OM export lacks
    assert by_id["R21_comfort_deviation"].status == "insufficient_data"


def test_frame_shape():
    fr = probabilities_to_frame(score_system(synth.generate()))
    assert {"probability_%", "status", "rule_id", "rationale"} <= set(fr.columns)
