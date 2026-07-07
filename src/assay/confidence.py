"""Confidence scoring and routing. The score is deliberately simple and
inspectable: three components a reviewer can reason about, not a learned
black box. Thresholds live here so tuning is one edit."""

from dataclasses import dataclass

from .dataset import INVOICE_SPEC, DatasetSpec
from .extract import Extraction

AUTO_ACCEPT_THRESHOLD = 0.85


@dataclass
class Scored:
    confidence: float
    rule_score: float
    self_check_score: float
    completeness: float
    route: str
    reasons: list[str]


def score(ext: Extraction, spec: DatasetSpec = INVOICE_SPEC) -> Scored:
    if ext.invoice is None:
        return Scored(0.0, 0.0, 0.0, 0.0, "review",
                      ["extraction failed schema validation twice"])

    rule_score = max(0.0, 1.0 - 0.5 * len(ext.rule_errors))
    self_check_score = max(0.0, 1.0 - 0.34 * len(ext.doubtful_fields))

    inv = ext.invoice
    present = sum(1 for f in spec.key_fields if getattr(inv, f) not in (None, ""))
    slots = len(spec.key_fields)
    if spec.has_line_items:
        present += 1 if inv.line_items else 0
        slots += 1
    completeness = present / slots

    confidence = round(
        0.55 * rule_score + 0.25 * self_check_score + 0.20 * completeness, 3
    )

    reasons = []
    reasons.extend(f"rule failed: {e}" for e in ext.rule_errors)
    reasons.extend(f"model doubts field: {f}" for f in ext.doubtful_fields)
    missing = [f for f in spec.key_fields if getattr(inv, f) in (None, "")]
    reasons.extend(f"missing key field: {f}" for f in missing)

    route = "auto" if confidence >= AUTO_ACCEPT_THRESHOLD else "review"
    return Scored(confidence, rule_score, self_check_score, completeness,
                  route, reasons)
