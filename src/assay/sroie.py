"""SROIE 2019 (ICDAR scanned-receipt IE benchmark) as a real-data eval arm.

The dataset ships OCR line segments with pixel bounding boxes and four
ground-truth key fields per receipt: company, date, address, total.
The converter reconstructs a plain-text document from the segments (grouping
segments that share a visual line) and normalizes the ground truth into the
same *.truth.json shape the invoice golden set uses, so the eval harness can
score receipts with the identical machinery.

The dataset itself is not redistributed in this repo; scripts/fetch_sroie.py
downloads a pinned revision and calls convert_parquet()."""

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .dataset import DatasetSpec
from .normalize import parse_date


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str = Field(description="Store / business name printed at the top")
    date: str | None = Field(description="Receipt date, ISO YYYY-MM-DD; null if absent")
    address: str = Field(description="Store address as printed, joined on one line")
    total: float = Field(description="Final total paid")


SROIE_SYSTEM_PROMPT = """You are a receipt data extraction engine.
Extract the fields from the OCR text of a scanned retail receipt into JSON.
Rules:
- company is the store or business name printed at the top of the receipt, exactly as printed.
- date is the receipt date in ISO format YYYY-MM-DD. If no date is printed, use null.
- address is the store's full street address as printed, joined into one line.
- total is the final amount paid, a plain number without currency symbols or thousands separators.
- The OCR text may contain recognition errors; extract what is printed, do not correct it."""


def check_receipt_rules(rec: Receipt) -> list[str]:
    errors = []
    if not rec.company.strip():
        errors.append("company is empty")
    if not rec.address.strip():
        errors.append("address is empty")
    d = parse_date(rec.date)
    if rec.date and d is None:
        errors.append(f"date '{rec.date}' does not parse as a date")
    if d and not (2000 <= d.year <= 2035):
        errors.append(f"date year {d.year} is implausible")
    if rec.total <= 0:
        errors.append(f"total {rec.total} is not positive")
    return errors


def text_from_segments(words: list[str], bboxes: list[list[int]]) -> str:
    """Rebuild receipt text from OCR segments. Segments whose vertical center
    falls inside the current line's band are joined left-to-right with spaces;
    otherwise they start a new line. Receipts read strictly top-down, so only
    the previous line needs checking."""
    segs = sorted(zip(words, bboxes), key=lambda s: (s[1][1] + s[1][3], s[1][0]))
    lines: list[list[tuple[str, list[int]]]] = []
    for word, box in segs:
        cy = (box[1] + box[3]) / 2
        if lines:
            band_top = min(b[1] for _, b in lines[-1])
            band_bottom = max(b[3] for _, b in lines[-1])
            if band_top <= cy <= band_bottom:
                lines[-1].append((word, box))
                continue
        lines.append([(word, box)])
    out = []
    for line in lines:
        line.sort(key=lambda s: s[1][0])
        out.append(" ".join(w for w, _ in line))
    return "\n".join(out)


_MONEY_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def parse_total(raw: str) -> float | None:
    """SROIE truth totals appear as '9.00', 'RM9.00', 'RM 96.90', '$8.50'."""
    m = _MONEY_RE.search(raw or "")
    if not m:
        return None
    return float(m.group().replace(",", ""))


def normalize_truth(entities: dict) -> dict | None:
    """Map SROIE's entity strings to the receipt truth record. Dates become
    ISO when they parse (the model is asked for ISO, and the eval compares
    parsed dates anyway); totals become floats. Returns None only when the
    total has no digits at all, which does not occur in the test split."""
    total = parse_total(entities["total"])
    if total is None:
        return None
    d = parse_date(entities["date"])
    return {
        "company": entities["company"],
        "date": d.isoformat() if d else entities["date"],
        "address": entities["address"],
        "total": total,
    }


def convert_parquet(parquet_path: Path, out_dir: Path,
                    limit: int | None = None) -> int:
    """Read the pinned SROIE parquet and write <key>.txt + <key>.truth.json
    per receipt into out_dir. Requires pyarrow (the 'sroie' extra)."""
    import pyarrow.parquet as pq

    table = pq.ParquetFile(str(parquet_path)).read(
        columns=["key", "entities", "words", "bboxes"])
    rows = table.to_pylist()
    rows.sort(key=lambda r: r["key"])
    if limit:
        rows = rows[:limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for row in rows:
        truth = normalize_truth(row["entities"])
        if truth is None:
            continue
        text = text_from_segments(row["words"], row["bboxes"])
        (out_dir / f"{row['key']}.txt").write_text(text)
        (out_dir / f"{row['key']}.truth.json").write_text(json.dumps(
            {"receipt": truth, "source": "sroie2019-test"},
            indent=2, ensure_ascii=False))
        written += 1
    return written


def load_sroie(data_dir: Path) -> list[tuple[Path, dict]]:
    docs = []
    for txt in sorted(data_dir.glob("*.txt")):
        truth_path = txt.parent / f"{txt.stem}.truth.json"
        docs.append((txt, json.loads(truth_path.read_text())))
    return docs


SROIE_SPEC = DatasetSpec(
    name="sroie",
    doc_label="Receipt",
    model=Receipt,
    system_prompt=SROIE_SYSTEM_PROMPT,
    field_kinds={
        "company": "text",
        "date": "date",
        # SROIE annotations punctuate addresses ("NO 2 & 4, JALAN BAYU 4, ...")
        # while the OCR lines carry no commas, so exact punctuation is not
        # recoverable from the model's input; compare alphanumerics only.
        "address": "loose_text",
        "total": "money",
    },
    key_fields=("company", "date", "address", "total"),
    check_rules=check_receipt_rules,
    load=load_sroie,
    truth_key="receipt",
    has_line_items=False,
)
