import json

from assay.generate import generate
from assay.ingest import ingest
from assay.schema import Invoice
from assay.validate import check_rules


def test_golden_set_properties(tmp_path):
    paths = generate(tmp_path, count=32, seed=42)
    assert len(paths) == 32
    truths = [json.loads((tmp_path / f"{p.stem}.truth.json").read_text())
              for p in paths]

    assert sum(t["ambiguous"] for t in truths) == 3
    assert any(t["invoice"]["tax"] is None for t in truths)
    assert any(t["invoice"]["due_date"] is None for t in truths)
    assert any(t["invoice"]["invoice_date"] is None for t in truths)
    assert len({t["template"] for t in truths}) == 5
    assert len({t["invoice"]["currency"] for t in truths}) >= 5

    for t in truths:
        errors = check_rules(Invoice.model_validate(t["invoice"]))
        assert errors == [], f"{t['doc_id']}: ground truth violates rules: {errors}"


def test_deterministic_bytes(tmp_path):
    a = generate(tmp_path / "a", count=6, seed=42)
    b = generate(tmp_path / "b", count=6, seed=42)
    for pa, pb in zip(a, b):
        assert pa.read_bytes() == pb.read_bytes()


def test_multipage_invoice_renders_two_pages(tmp_path):
    paths = generate(tmp_path, count=32, seed=42)
    doc = ingest(paths[7])
    assert len(doc.pages) == 2
    truth = json.loads((tmp_path / "inv_008.truth.json").read_text())
    assert len(truth["invoice"]["line_items"]) > 40


def test_ingest_preserves_key_content(tmp_path):
    paths = generate(tmp_path, count=6, seed=42)
    for p in paths:
        truth = json.loads((tmp_path / f"{p.stem}.truth.json").read_text())
        text = ingest(p).text
        assert truth["invoice"]["vendor"].split(" ")[0].lower() in text.lower()
        assert truth["invoice"]["invoice_number"] in text
