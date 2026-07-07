import json

from assay.export import read_jsonl, write_jsonl
from assay.review import run_review
from conftest import invoice_dict


def _queue_item(doc_id="inv_099"):
    return {
        "doc_id": doc_id,
        "route": "review",
        "confidence": 0.4,
        "reasons": ["rule failed: total mismatch"],
        "invoice": invoice_dict(total=99.99),
        "rule_errors": ["total mismatch"],
    }


def _scripted(inputs):
    it = iter(inputs)
    return lambda _prompt: next(it)


def test_accept_writes_reviewed(tmp_path):
    write_jsonl(tmp_path / "review_queue.jsonl", [_queue_item()])
    run_review(tmp_path, input_fn=_scripted(["a"]))
    reviewed = read_jsonl(tmp_path / "reviewed.jsonl")
    assert len(reviewed) == 1
    assert reviewed[0]["review"] == "accepted"


def test_correction_updates_field_and_records_history(tmp_path):
    write_jsonl(tmp_path / "review_queue.jsonl", [_queue_item()])
    run_review(tmp_path, input_fn=_scripted(["c total=73.78"]))
    reviewed = read_jsonl(tmp_path / "reviewed.jsonl")
    assert reviewed[0]["review"] == "corrected"
    assert reviewed[0]["invoice"]["total"] == 73.78
    assert reviewed[0]["corrections"]["total"] == {"was": 99.99, "now": 73.78}


def test_already_reviewed_docs_are_skipped(tmp_path):
    write_jsonl(tmp_path / "review_queue.jsonl",
                [_queue_item("inv_001"), _queue_item("inv_002")])
    write_jsonl(tmp_path / "reviewed.jsonl",
                [dict(_queue_item("inv_001"), review="accepted", corrections={})])
    run_review(tmp_path, input_fn=_scripted(["a"]))
    reviewed = read_jsonl(tmp_path / "reviewed.jsonl")
    assert {r["doc_id"] for r in reviewed} == {"inv_001", "inv_002"}
