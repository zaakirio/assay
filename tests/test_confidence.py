from assay.confidence import AUTO_ACCEPT_THRESHOLD, score
from assay.extract import Extraction
from assay.schema import Invoice
from conftest import invoice_dict


def _ext(**kw) -> Extraction:
    base = dict(doc_id="d1", invoice=Invoice.model_validate(invoice_dict()),
                rule_errors=[], first_pass_errors=[])
    base.update(kw)
    return Extraction(**base)


def test_clean_extraction_auto_accepts():
    s = score(_ext())
    assert s.route == "auto"
    assert s.confidence >= AUTO_ACCEPT_THRESHOLD
    assert s.reasons == []


def test_rule_failure_routes_to_review():
    s = score(_ext(rule_errors=["total mismatch"]))
    assert s.route == "review"
    assert "rule failed: total mismatch" in s.reasons


def test_model_doubt_routes_to_review():
    s = score(_ext(doubtful_fields=["currency", "total"]))
    assert s.route == "review"
    assert s.self_check_score < 1.0


def test_missing_key_field_lowers_completeness():
    inv = Invoice.model_validate(invoice_dict(invoice_date=None, currency=None))
    s = score(_ext(invoice=inv))
    assert s.completeness < 1.0
    assert "missing key field: currency" in s.reasons


def test_schema_failure_is_zero_confidence_review():
    s = score(_ext(invoice=None, schema_failed=True))
    assert s.route == "review"
    assert s.confidence == 0.0
