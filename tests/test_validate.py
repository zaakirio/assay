from assay.schema import Invoice
from assay.validate import check_rules
from conftest import invoice_dict


def test_clean_invoice_passes():
    assert check_rules(Invoice.model_validate(invoice_dict())) == []


def test_totals_mismatch_flagged():
    errors = check_rules(Invoice.model_validate(invoice_dict(total=99.99)))
    assert any("total is 99.99" in e for e in errors)


def test_line_sum_vs_subtotal_flagged():
    errors = check_rules(Invoice.model_validate(invoice_dict(subtotal=70.00, total=75.78)))
    assert any("sum to 68.0 but subtotal is 70.0" in e for e in errors)


def test_unparseable_date_flagged():
    errors = check_rules(Invoice.model_validate(invoice_dict(invoice_date="3rd of maybe")))
    assert any("does not parse" in e for e in errors)


def test_due_before_issue_flagged():
    errors = check_rules(Invoice.model_validate(invoice_dict(due_date="2026-01-01")))
    assert any("before invoice_date" in e for e in errors)


def test_non_iso_currency_flagged():
    errors = check_rules(Invoice.model_validate(invoice_dict(currency="dollars")))
    assert any("ISO 4217" in e for e in errors)


def test_missing_optionals_ok():
    inv = Invoice.model_validate(invoice_dict(due_date=None, tax=None,
                                              subtotal=None, total=68.00))
    assert check_rules(inv) == []


def test_line_item_arithmetic_flagged():
    d = invoice_dict()
    d["line_items"][0]["amount"] = 51.00
    d["subtotal"] = 69.00
    d["total"] = 74.78
    errors = check_rules(Invoice.model_validate(d))
    assert any("4 x 12.5 != 51" in e for e in errors)
