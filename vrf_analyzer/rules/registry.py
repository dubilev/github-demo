"""Registry + engine: run detectors over an indexed dataset."""

from __future__ import annotations

import pandas as pd

from .base import Detector, Finding
from .catalog import CATALOG, CATALOG_BY_ID, RuleSpec
from .detectors import IMPLEMENTED_DETECTORS

# rule_id -> Detector class
REGISTRY: dict[str, type[Detector]] = {d.spec.rule_id: d for d in IMPLEMENTED_DETECTORS}

# mark catalog coverage
for _rid, _det in REGISTRY.items():
    CATALOG_BY_ID[_rid].implemented = True


def coverage() -> list[RuleSpec]:
    """Full catalog with up-to-date implemented flags."""
    return CATALOG


def build_detectors(overrides: dict | None = None) -> list[Detector]:
    """Instantiate all implemented detectors. ``overrides`` maps rule_id->params."""
    overrides = overrides or {}
    return [cls(**overrides.get(rid, {})) for rid, cls in REGISTRY.items()]


def assess_unit(df: pd.DataFrame, detectors: list[Detector] | None = None) -> list[Finding]:
    """Run detectors over one unit's readings."""
    if df.empty:
        return []
    detectors = detectors or build_detectors()
    findings: list[Finding] = []
    for det in detectors:
        try:
            findings.extend(det.run(df))
        except Exception as exc:  # a broken detector must not sink the run
            findings_err = Finding(
                rule_id=det.spec.rule_id,
                title=f"[detector error] {det.spec.title}",
                severity=det.spec.default_severity,
                system_id=str(df["system_id"].iloc[0]),
                unit_id=str(df["unit_id"].iloc[0]),
                message=f"detector raised: {exc!r}",
            )
            findings.append(findings_err)
    return findings


def assess(df: pd.DataFrame, detectors: list[Detector] | None = None) -> list[Finding]:
    """Run detectors over a normalized frame.

    Unit-scoped detectors run per (system, unit); system-scoped detectors run
    once per system with all its units' rows.
    """
    detectors = detectors or build_detectors()
    unit_dets = [d for d in detectors if getattr(d, "scope", "unit") != "system"]
    sys_dets = [d for d in detectors if getattr(d, "scope", "unit") == "system"]
    out: list[Finding] = []
    for (_sys, _unit), grp in df.groupby(["system_id", "unit_id"], dropna=False):
        out.extend(assess_unit(grp.sort_values("timestamp"), unit_dets))
    for _sys, grp in df.groupby("system_id", dropna=False):
        for det in sys_dets:
            try:
                out.extend(det.run(grp.sort_values("timestamp")))
            except Exception as exc:
                out.append(Finding(
                    rule_id=det.spec.rule_id,
                    title=f"[detector error] {det.spec.title}",
                    severity=det.spec.default_severity,
                    system_id=str(grp["system_id"].iloc[0]), unit_id="*",
                    message=f"detector raised: {exc!r}"))
    out.sort(key=lambda f: int(f.severity), reverse=True)
    return out


def findings_to_frame(findings: list[Finding]) -> pd.DataFrame:
    if not findings:
        return pd.DataFrame(columns=[
            "rule_id", "title", "severity", "severity_label",
            "system_id", "unit_id", "start", "end", "message", "recommendation",
        ])
    return pd.DataFrame([f.to_dict() for f in findings])
