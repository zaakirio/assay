"""Type-aware per-field comparison and corpus aggregation. Dates are compared
as parsed dates, money numerically with a cent tolerance, text after
whitespace/case normalization, and line items by fuzzy alignment on the
description so a one-row offset does not zero out the whole table."""

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .normalize import money_equal, norm_invoice_number, norm_text, parse_date

# Comparison kinds a dataset spec can assign to a field. Invoice fields keep
# their historical mapping via INVOICE_FIELD_KINDS.
INVOICE_FIELD_KINDS = {
    "vendor": "text",
    "invoice_number": "id",
    "invoice_date": "date",
    "due_date": "date",
    "currency": "currency",
    "subtotal": "money",
    "tax": "money",
    "total": "money",
}
SCALAR_FIELDS = tuple(INVOICE_FIELD_KINDS)
DESC_MATCH_THRESHOLD = 0.80
DESC_PAIR_THRESHOLD = 0.55


def _equal(kind: str, truth, pred) -> bool:
    if truth is None and pred is None:
        return True
    if kind == "date":
        t, p = parse_date(truth), parse_date(pred)
        return t is not None and t == p
    if kind == "money":
        return money_equal(truth, pred)
    if kind == "currency":
        return truth is not None and pred is not None and truth.upper() == pred.upper()
    if kind in ("id", "loose_text"):
        # Only the alphanumerics carry identity; separators and punctuation
        # vary between print layout, OCR, annotation, and model output.
        return norm_invoice_number(truth) == norm_invoice_number(pred)
    return norm_text(truth) == norm_text(pred)


@dataclass
class FieldTally:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    n_truth: int = 0
    errors: list[dict] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        d = self.tp + self.fp
        return self.tp / d if d else None

    @property
    def recall(self) -> float | None:
        d = self.tp + self.fn
        return self.tp / d if d else None

    @property
    def exact_match(self) -> float | None:
        return self.tp / self.n_truth if self.n_truth else None


def compare_scalars(doc_id: str, truth: dict, pred: dict | None,
                    tallies: dict[str, FieldTally],
                    field_kinds: dict[str, str] = INVOICE_FIELD_KINDS) -> dict[str, bool]:
    correct = {}
    for f, kind in field_kinds.items():
        t = truth.get(f)
        p = pred.get(f) if pred else None
        tally = tallies[f]
        if t is not None:
            tally.n_truth += 1
        ok = pred is not None and _equal(kind, t, p)
        correct[f] = ok
        if t is None and p is None:
            continue
        if ok:
            tally.tp += 1
        else:
            if p is not None:
                tally.fp += 1
            if t is not None:
                tally.fn += 1
            tally.errors.append({"doc_id": doc_id, "truth": t, "pred": p})
    return correct


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_text(a), norm_text(b)).ratio()


def align_line_items(truth_items: list[dict], pred_items: list[dict]) -> dict:
    """Greedy best-similarity pairing on description, then a pair counts as a
    true positive only if description matches closely and all three numbers
    agree."""
    pairs = []
    used_t, used_p = set(), set()
    candidates = sorted(
        ((_sim(t["description"], p["description"]), ti, pi)
         for ti, t in enumerate(truth_items)
         for pi, p in enumerate(pred_items)),
        key=lambda x: -x[0],
    )
    for sim, ti, pi in candidates:
        if sim < DESC_PAIR_THRESHOLD or ti in used_t or pi in used_p:
            continue
        used_t.add(ti)
        used_p.add(pi)
        pairs.append((sim, truth_items[ti], pred_items[pi]))

    tp = 0
    mismatches = []
    for sim, t, p in pairs:
        numbers_ok = (money_equal(t["quantity"], p["quantity"])
                      and money_equal(t["unit_price"], p["unit_price"])
                      and money_equal(t["amount"], p["amount"]))
        if sim >= DESC_MATCH_THRESHOLD and numbers_ok:
            tp += 1
        else:
            mismatches.append({"truth": t, "pred": p, "desc_sim": round(sim, 2)})
    return {
        "tp": tp,
        "fp": len(pred_items) - tp,
        "fn": len(truth_items) - tp,
        "mismatches": mismatches,
    }


def doc_correct(scalar_correct: dict[str, bool], li: dict) -> bool:
    return all(scalar_correct.values()) and li["fp"] == 0 and li["fn"] == 0


def prf(tp: int, fp: int, fn: int) -> tuple[float | None, float | None, float | None]:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    if p is None or r is None:
        f1 = None
    else:
        f1 = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f1
