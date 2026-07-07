"""JSONL export of pipeline results: accepted docs to the ERP feed, the rest
to the review queue the `assay review` CLI consumes."""

import json
from dataclasses import asdict
from pathlib import Path

from .confidence import Scored
from .extract import Extraction


def record(ext: Extraction, scored: Scored) -> dict:
    return {
        "doc_id": ext.doc_id,
        "route": scored.route,
        "confidence": scored.confidence,
        "reasons": scored.reasons,
        "invoice": ext.invoice.model_dump() if ext.invoice else None,
        "rule_errors": ext.rule_errors,
        "repaired": ext.repaired,
        "repair_attempted": ext.repair_attempted,
        "doubtful_fields": ext.doubtful_fields,
        "chunks": ext.chunks,
        "prompt_tokens": ext.prompt_tokens,
        "completion_tokens": ext.completion_tokens,
        "latency_s": round(ext.latency_s, 2),
    }


def write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
