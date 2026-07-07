import json

from assay.extract import Extractor, _chunk_pages, MAX_PROMPT_CHARS
from assay.ingest import Document
from conftest import FakeLLM, invoice_dict


def _doc(text="Some invoice text", pages=None):
    return Document(doc_id="d1", path=None, pages=pages or [text])


def test_happy_path_single_call_plus_self_check():
    fake = FakeLLM([json.dumps(invoice_dict())])
    ext = Extractor(fake).extract(_doc())
    assert ext.invoice.total == 73.78
    assert ext.rule_errors == []
    assert not ext.repair_attempted
    assert len(fake.calls) == 2
    assert ext.prompt_tokens == 200


def test_repair_loop_fixes_rule_failure():
    bad = invoice_dict(total=99.99)
    fake = FakeLLM([json.dumps(bad), json.dumps(invoice_dict())])
    ext = Extractor(fake).extract(_doc())
    assert ext.repair_attempted and ext.repaired
    assert ext.first_pass_errors != []
    assert ext.rule_errors == []
    assert ext.invoice.total == 73.78
    repair_msg = fake.calls[1]["messages"][-1]["content"]
    assert "failed these checks" in repair_msg


def test_repair_keeps_first_result_if_retry_is_worse():
    bad = invoice_dict(total=99.99)
    worse = invoice_dict(total=99.99, currency="dollars", invoice_date="garbage")
    fake = FakeLLM([json.dumps(bad), json.dumps(worse)])
    ext = Extractor(fake).extract(_doc())
    assert ext.repair_attempted and not ext.repaired
    assert ext.invoice.total == 99.99


def test_repair_garbage_response_keeps_first_pass_state():
    bad = invoice_dict(total=99.99)
    fake = FakeLLM([json.dumps(bad), "not json"])
    ext = Extractor(fake).extract(_doc())
    assert ext.repair_attempted and not ext.repaired
    assert ext.invoice.total == 99.99
    assert not ext.schema_failed
    assert ext.rule_errors == ext.first_pass_errors
    assert not any(e.startswith("schema:") for e in ext.rule_errors)


def test_repair_parse_after_schema_failure_is_adopted():
    fake = FakeLLM(["not json at all", json.dumps(invoice_dict(total=99.99))])
    ext = Extractor(fake).extract(_doc())
    assert ext.repair_attempted and ext.repaired
    assert ext.invoice is not None
    assert ext.invoice.total == 99.99
    assert not ext.schema_failed
    assert any("total is 99.99" in e for e in ext.rule_errors)


def test_schema_garbage_marks_failure():
    fake = FakeLLM(["not json at all", "still not json"])
    ext = Extractor(fake).extract(_doc())
    assert ext.invoice is None
    assert ext.schema_failed


def test_multipage_chunks_and_merges_line_items():
    page = "Row of items\n" * 300
    doc = _doc(pages=[page, page])
    chunks = _chunk_pages(doc)
    assert len(chunks) == 2

    part1 = invoice_dict()
    part2 = invoice_dict(vendor="", invoice_date=None, line_items=[
        {"description": "Extra item from page 2", "quantity": 1.0,
         "unit_price": 5.0, "amount": 5.0}],
        subtotal=73.0, total=78.78)
    fake = FakeLLM([json.dumps(part1), json.dumps(part2)])
    ext = Extractor(fake).extract(doc)
    assert ext.chunks == 2
    assert len(ext.invoice.line_items) == 3
    assert ext.invoice.vendor == "Blue Mesa Packaging Co."
    assert ext.invoice.total == 78.78
    assert not ext.repair_attempted


def test_self_check_doubts_recorded():
    fake = FakeLLM([json.dumps(invoice_dict())], doubtful=["currency"])
    ext = Extractor(fake).extract(_doc())
    assert ext.doubtful_fields == ["currency"]


def test_chunk_boundary_respects_budget():
    doc = _doc(pages=["x" * 4000, "y" * 4000, "z" * 100])
    chunks = _chunk_pages(doc)
    assert all(len(c) <= MAX_PROMPT_CHARS + 100 for c in chunks)
