"""Dataset specs: everything the pipeline and the eval harness need to know
about one document type in one place (schema, prompt, field types, rules,
loader), so adding a dataset cannot silently disagree with how it is scored."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from .schema import Invoice
from .validate import check_rules

INVOICE_SYSTEM_PROMPT = """You are an invoice data extraction engine.
Extract the fields from the invoice text into JSON.
Rules:
- Copy vendor name and invoice number exactly as printed.
- Dates must be ISO format YYYY-MM-DD. If a printed date is ambiguous or absent, use null.
- currency is the ISO 4217 code (USD, EUR, GBP, JPY, AUD, CHF, NZD, ...). Infer from the symbol and vendor country if no code is printed; use null only if it cannot be determined.
- Numbers are plain numbers without currency symbols or thousands separators.
- Include every line item. amount is the line total.
- subtotal is the pre-tax sum, tax is the tax amount, total is the grand total payable.
- Use null for any optional field not present in the document."""


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    doc_label: str                      # "Invoice" / "Receipt", used in prompts
    model: type[BaseModel]
    system_prompt: str
    field_kinds: dict[str, str]         # scalar field -> comparison kind (metrics.py)
    key_fields: tuple[str, ...]         # completeness component of confidence
    check_rules: Callable[[BaseModel], list[str]]
    load: Callable[[Path], list[tuple[Path, dict]]]
    truth_key: str                      # key of the record inside *.truth.json
    has_line_items: bool
    merge: Callable[[list[BaseModel]], BaseModel] | None = None  # multi-chunk merge


def load_golden(golden_dir: Path) -> list[tuple[Path, dict]]:
    docs = []
    for pdf in sorted(golden_dir.glob("*.pdf")):
        truth_path = pdf.parent / f"{pdf.stem}.truth.json"
        docs.append((pdf, json.loads(truth_path.read_text())))
    return docs


def merge_invoices(parts: list[Invoice]) -> Invoice:
    first = parts[0]
    data = first.model_dump()
    for p in parts[1:]:
        data["line_items"].extend(it.model_dump() for it in p.line_items)
    # Header fields: first non-null wins. Totals print on the last page, so
    # the last non-null wins there.
    for f in ("vendor", "invoice_number", "invoice_date", "due_date", "currency"):
        for p in parts:
            v = getattr(p, f)
            if v:
                data[f] = v
                break
    for f in ("subtotal", "tax", "total"):
        for p in reversed(parts):
            v = getattr(p, f)
            if v is not None:
                data[f] = v
                break
    return Invoice.model_validate(data)


INVOICE_SPEC = DatasetSpec(
    name="golden",
    doc_label="Invoice",
    model=Invoice,
    system_prompt=INVOICE_SYSTEM_PROMPT,
    field_kinds={
        "vendor": "text",
        "invoice_number": "id",
        "invoice_date": "date",
        "due_date": "date",
        "currency": "currency",
        "subtotal": "money",
        "tax": "money",
        "total": "money",
    },
    key_fields=("vendor", "invoice_number", "invoice_date", "currency", "total"),
    check_rules=check_rules,
    load=load_golden,
    truth_key="invoice",
    has_line_items=True,
    merge=merge_invoices,
)
