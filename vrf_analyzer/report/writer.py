"""Turn findings into serializable reports and summaries."""

from __future__ import annotations

import json
from collections import Counter

from ..rules.base import Finding, Severity


def summarize(findings: list[Finding]) -> dict:
    by_sev = Counter(f.severity.label for f in findings)
    by_rule = Counter(f.rule_id for f in findings)
    by_unit = Counter(f.unit_id for f in findings)
    return {
        "total_findings": len(findings),
        "by_severity": dict(by_sev),
        "by_rule": dict(by_rule),
        "by_unit": dict(by_unit),
        "max_severity": (
            max(findings, key=lambda f: int(f.severity)).severity.label
            if findings else None
        ),
    }


def write_json(findings: list[Finding], path: str) -> str:
    payload = {
        "summary": summarize(findings),
        "findings": [f.to_dict() for f in findings],
    }
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    return path
