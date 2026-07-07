from assay.metrics import (FieldTally, align_line_items, compare_scalars,
                           SCALAR_FIELDS)
from assay.normalize import parse_date


def _tallies():
    return {f: FieldTally() for f in SCALAR_FIELDS}


def test_date_formats_normalize():
    assert parse_date("18/01/2026") == parse_date("2026-01-18")
    assert parse_date("18.01.2026") == parse_date("18 Jan 2026")
    assert parse_date("March 4, 2026") == parse_date("2026-03-04")
    assert parse_date("not a date") is None


def test_scalar_comparison_type_aware():
    truth = {"vendor": "Blue Mesa Packaging Co.", "invoice_number": "INV-00123",
             "invoice_date": "2026-01-18", "due_date": None, "currency": "USD",
             "subtotal": 68.0, "tax": 5.78, "total": 73.78}
    pred = {"vendor": "BLUE MESA PACKAGING CO.", "invoice_number": "INV 00123",
            "invoice_date": "18/01/2026", "due_date": None, "currency": "usd",
            "subtotal": 68.004, "tax": 5.78, "total": 73.78}
    tallies = _tallies()
    correct = compare_scalars("d1", truth, pred, tallies)
    assert all(correct.values())
    assert tallies["invoice_date"].tp == 1


def test_null_pred_is_false_negative_not_false_positive():
    truth = {"vendor": "X", "invoice_number": "1", "invoice_date": "2026-01-18",
             "due_date": None, "currency": "USD", "subtotal": None, "tax": None,
             "total": 10.0}
    pred = dict(truth, invoice_date=None)
    tallies = _tallies()
    compare_scalars("d1", truth, pred, tallies)
    t = tallies["invoice_date"]
    assert (t.tp, t.fp, t.fn) == (0, 0, 1)


def test_hallucinated_value_is_false_positive():
    truth = {"vendor": "X", "invoice_number": "1", "invoice_date": None,
             "due_date": None, "currency": "USD", "subtotal": None, "tax": None,
             "total": 10.0}
    pred = dict(truth, invoice_date="2026-05-05")
    tallies = _tallies()
    compare_scalars("d1", truth, pred, tallies)
    t = tallies["invoice_date"]
    assert (t.tp, t.fp, t.fn) == (0, 1, 0)
    assert t.exact_match is None


def test_line_items_fuzzy_alignment_tolerates_typos_and_order():
    truth = [
        {"description": "Pallet wrap, 500mm x 300m", "quantity": 4, "unit_price": 12.5, "amount": 50.0},
        {"description": "Nitrile gloves, size L (box 100)", "quantity": 2, "unit_price": 9.0, "amount": 18.0},
    ]
    pred = [
        {"description": "Nitrile gloves size L (box 100)", "quantity": 2, "unit_price": 9.0, "amount": 18.0},
        {"description": "Pallet wrap, 500mm x 300m", "quantity": 4, "unit_price": 12.5, "amount": 50.0},
    ]
    r = align_line_items(truth, pred)
    assert (r["tp"], r["fp"], r["fn"]) == (2, 0, 0)


def test_line_items_wrong_number_is_not_a_match():
    truth = [{"description": "Pallet wrap", "quantity": 4, "unit_price": 12.5, "amount": 50.0}]
    pred = [{"description": "Pallet wrap", "quantity": 4, "unit_price": 12.5, "amount": 55.0}]
    r = align_line_items(truth, pred)
    assert (r["tp"], r["fp"], r["fn"]) == (0, 1, 1)
    assert r["mismatches"][0]["desc_sim"] == 1.0


def test_line_items_missing_and_extra():
    truth = [
        {"description": "Item A", "quantity": 1, "unit_price": 1.0, "amount": 1.0},
        {"description": "Item B", "quantity": 1, "unit_price": 2.0, "amount": 2.0},
    ]
    pred = [
        {"description": "Item A", "quantity": 1, "unit_price": 1.0, "amount": 1.0},
        {"description": "Completely different thing", "quantity": 9, "unit_price": 9.0, "amount": 81.0},
    ]
    r = align_line_items(truth, pred)
    assert (r["tp"], r["fp"], r["fn"]) == (1, 1, 1)
