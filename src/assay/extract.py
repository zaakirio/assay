"""LLM extraction with constrained decoding, page-window chunking for long
documents, and a single validator-guided repair retry."""

import json
import time
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from .dataset import INVOICE_SPEC, DatasetSpec
from .ingest import Document
from .llm import LLMClient, LLMResult


def _self_check_schema(spec: DatasetSpec) -> dict:
    fields = list(spec.field_kinds)
    if spec.has_line_items:
        fields.append("line_items")
    return {
        "type": "object",
        "properties": {
            "doubtful_fields": {
                "type": "array",
                "items": {"type": "string", "enum": fields},
            }
        },
        "required": ["doubtful_fields"],
    }

# llama-server runs with --ctx-size 4096; leave room for the completion and
# chat-template overhead. ~3.5 chars/token is conservative for invoice text.
MAX_PROMPT_CHARS = 6000


@dataclass
class Extraction:
    doc_id: str
    # The extracted record; an Invoice for the golden set, a Receipt for
    # SROIE. The field keeps its original name for stability of the export
    # format and callers.
    invoice: BaseModel | None
    rule_errors: list[str]
    first_pass_errors: list[str]
    repaired: bool = False
    repair_attempted: bool = False
    schema_failed: bool = False
    doubtful_fields: list[str] = field(default_factory=list)
    chunks: int = 1
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0


def _chunk_pages(doc: Document) -> list[str]:
    if len(doc.text) <= MAX_PROMPT_CHARS:
        return [doc.text]
    chunks, current = [], ""
    for i, page in enumerate(doc.pages):
        tagged = f"--- page {i + 1} of {len(doc.pages)} ---\n{page}"
        if current and len(current) + len(tagged) > MAX_PROMPT_CHARS:
            chunks.append(current)
            current = tagged
        else:
            current = f"{current}\n\n{tagged}" if current else tagged
    if current:
        chunks.append(current)
    return chunks


class Extractor:
    def __init__(self, client: LLMClient, spec: DatasetSpec = INVOICE_SPEC):
        self.client = client
        self.spec = spec
        self.schema = spec.model.model_json_schema()
        self.self_check_schema = _self_check_schema(spec)

    def _call(self, messages: list[dict], ext: Extraction, schema: dict,
              max_tokens: int = 2048) -> LLMResult:
        res = self.client.chat(messages, json_schema=schema, max_tokens=max_tokens)
        ext.prompt_tokens += res.prompt_tokens
        ext.completion_tokens += res.completion_tokens
        return res

    def _extract_once(self, text: str, ext: Extraction,
                      prior_errors: list[str] | None = None) -> BaseModel | None:
        label = self.spec.doc_label
        messages = [
            {"role": "system", "content": self.spec.system_prompt},
            {"role": "user", "content": f"{label} text:\n\n{text}"},
        ]
        if prior_errors:
            messages.append({
                "role": "user",
                "content": (
                    "Your previous extraction failed these checks:\n- "
                    + "\n- ".join(prior_errors)
                    + f"\nRe-read the {label.lower()} text above and produce a corrected extraction."
                ),
            })
        res = self._call(messages, ext, self.schema)
        try:
            return self.spec.model.model_validate(json.loads(res.content))
        except (json.JSONDecodeError, ValidationError) as e:
            ext.schema_failed = True
            ext.rule_errors = [f"schema: {e}"]
            return None

    def _self_check(self, text: str, rec: BaseModel, ext: Extraction) -> list[str]:
        label = self.spec.doc_label
        messages = [
            {"role": "system", "content":
                f"You verify {label.lower()} extractions. Given the {label.lower()} text and an "
                "extracted JSON, list the field names whose extracted value is NOT "
                "clearly supported by the text (wrong, guessed, or ambiguous). "
                "Return an empty list if everything is supported."},
            {"role": "user", "content":
                f"{label} text:\n\n{text[:MAX_PROMPT_CHARS]}\n\n"
                f"Extraction:\n{rec.model_dump_json(indent=1)}"},
        ]
        try:
            res = self._call(messages, ext, self.self_check_schema, max_tokens=256)
            return sorted(set(json.loads(res.content).get("doubtful_fields", [])))
        except Exception:
            return ["self_check_failed"]

    def extract(self, doc: Document) -> Extraction:
        ext = Extraction(doc_id=doc.doc_id, invoice=None, rule_errors=[],
                         first_pass_errors=[])
        t0 = time.monotonic()
        chunks = _chunk_pages(doc)
        ext.chunks = len(chunks)

        parts = []
        for chunk in chunks:
            rec = self._extract_once(chunk, ext)
            if rec is not None:
                parts.append(rec)
        if not parts:
            invoice = None
        elif len(parts) > 1 and self.spec.merge:
            invoice = self.spec.merge(parts)
        else:
            invoice = parts[0]

        if invoice is not None:
            ext.rule_errors = self.spec.check_rules(invoice)
        ext.first_pass_errors = list(ext.rule_errors)

        if ext.rule_errors and len(chunks) == 1:
            ext.repair_attempted = True
            first_errors, first_schema_failed = ext.rule_errors, ext.schema_failed
            repaired = self._extract_once(chunks[0], ext, prior_errors=first_errors)
            if repaired is None:
                # A failed repair parse must not clobber the first pass's state.
                ext.rule_errors, ext.schema_failed = first_errors, first_schema_failed
            else:
                ext.schema_failed = False
                repaired_errors = self.spec.check_rules(repaired)
                # Any parsed invoice beats none; otherwise keep the retry only
                # if it strictly reduced rule failures.
                if invoice is None or len(repaired_errors) < len(first_errors):
                    invoice, ext.rule_errors = repaired, repaired_errors
                    ext.repaired = True
                else:
                    ext.rule_errors = first_errors

        ext.invoice = invoice
        if invoice is not None:
            ext.doubtful_fields = self._self_check(chunks[0], invoice, ext)
        ext.latency_s = time.monotonic() - t0
        return ext
