"""Core types for the rules engine."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Optional

import pandas as pd


class Severity(IntEnum):
    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @property
    def label(self) -> str:
        return self.name.title()


@dataclass
class Finding:
    """One detected issue on one unit over one time window."""

    rule_id: str
    title: str
    severity: Severity
    system_id: str
    unit_id: str
    start: Optional[pd.Timestamp] = None
    end: Optional[pd.Timestamp] = None
    message: str = ""
    recommendation: str = ""
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = int(self.severity)
        d["severity_label"] = self.severity.label
        d["start"] = None if self.start is None else pd.Timestamp(self.start).isoformat()
        d["end"] = None if self.end is None else pd.Timestamp(self.end).isoformat()
        return d


@dataclass
class RuleSpec:
    """Catalog entry describing an issue detector (one of the 'top 25')."""

    rule_id: str
    title: str
    category: str
    description: str
    signals: list[str]
    default_severity: Severity = Severity.MEDIUM
    implemented: bool = False


class Detector:
    """Base class. A detector inspects one unit's time series and yields Findings.

    Subclasses set ``spec`` and implement ``run``. Detectors are pure: given a
    per-unit DataFrame (normalized schema, sorted by timestamp) they return a
    list of Findings and never mutate the input.
    """

    spec: RuleSpec

    #: "unit" detectors see one unit's rows; "system" detectors see a whole
    #: refrigerant system (all its units) for cross-unit checks.
    scope: str = "unit"

    #: default tunables; overridable per-instance via constructor
    params: dict = {}

    def __init__(self, **overrides):
        self.params = {**self.__class__.params, **overrides}

    # helpers -------------------------------------------------------------
    def _finding(self, df: pd.DataFrame, **kwargs) -> Finding:
        sys_id = str(df["system_id"].iloc[0]) if len(df) else "?"
        unit_id = str(df["unit_id"].iloc[0]) if len(df) else "?"
        kwargs.setdefault("rule_id", self.spec.rule_id)
        kwargs.setdefault("title", self.spec.title)
        kwargs.setdefault("severity", self.spec.default_severity)
        kwargs.setdefault("system_id", sys_id)
        kwargs.setdefault("unit_id", unit_id)
        return Finding(**kwargs)

    def run(self, df: pd.DataFrame) -> list[Finding]:  # pragma: no cover - abstract
        raise NotImplementedError
