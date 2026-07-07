"""Regression test against a verbatim response recorded from llama-server
running LFM2.5-1.2B with constrained decoding, so the parse path is exercised
with real model output without needing the server."""

import json
from pathlib import Path

from assay.extract import Extractor
from assay.ingest import Document
from assay.validate import check_rules
from conftest import FakeLLM

FIXTURE = Path(__file__).parent / "fixtures" / "inv_001.recorded.json"


def test_real_recorded_response_parses_and_passes_rules():
    fake = FakeLLM([FIXTURE.read_text()])
    ext = Extractor(fake).extract(
        Document(doc_id="inv_001", path=None, pages=["(recorded run)"]))
    assert ext.invoice is not None
    assert ext.invoice.vendor == "Northwind Fastener Supply Ltd"
    assert ext.invoice.currency == "GBP"
    assert check_rules(ext.invoice) == []
    assert json.loads(FIXTURE.read_text())["total"] == ext.invoice.total
