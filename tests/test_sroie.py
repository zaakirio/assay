import json

from assay.evalrun import run_eval
from assay.normalize import parse_date
from assay.sroie import (Receipt, SROIE_SPEC, check_receipt_rules, load_sroie,
                         normalize_truth, parse_total, text_from_segments)
from conftest import FakeLLM

# A hand-sized snippet in the shape of one SROIE parquet row (OCR line
# segments + pixel boxes + the four ground-truth entities), not dataset data.
SEGMENTS = {
    "words": [
        "OJC MARKETING SDN BHD",
        "NO 2 & 4, JALAN BAYU 4",
        "TAX INVOICE",
        "INVOICE NO",
        ": PEGIV-1030765",
        "DATE",
        ": 15/01/2019 11:05 AM",
        "TOTAL",
        "193.00",
    ],
    "bboxes": [
        [80, 119, 329, 140],
        [104, 163, 306, 182],
        [160, 205, 250, 225],
        [40, 240, 120, 258],
        [130, 241, 260, 259],   # same visual line as "INVOICE NO"
        [40, 265, 80, 283],
        [130, 266, 290, 284],   # same visual line as "DATE"
        [40, 320, 90, 338],
        [300, 320, 360, 338],   # same visual line as "TOTAL"
    ],
    "entities": {
        "company": "OJC MARKETING SDN BHD",
        "date": "15/01/2019",
        "address": "NO 2 & 4, JALAN BAYU 4, BANDAR SERI ALAM, 81750 MASAI, JOHOR",
        "total": "193.00",
    },
}


def test_segments_regroup_into_visual_lines():
    text = text_from_segments(SEGMENTS["words"], SEGMENTS["bboxes"])
    lines = text.splitlines()
    assert lines[0] == "OJC MARKETING SDN BHD"
    assert "INVOICE NO : PEGIV-1030765" in lines
    assert "DATE : 15/01/2019 11:05 AM" in lines
    assert "TOTAL 193.00" in lines
    assert len(lines) == 6


def test_parse_total_strips_currency_prefixes():
    assert parse_total("193.00") == 193.0
    assert parse_total("RM9.00") == 9.0
    assert parse_total("RM 96.90") == 96.9
    assert parse_total("$8.50") == 8.5
    assert parse_total("1,213.00") == 1213.0
    assert parse_total("no digits") is None


def test_sroie_date_variants_parse():
    assert parse_date("22 MAR 18") == parse_date("2018-03-22")
    assert parse_date("27/MAR/2018") == parse_date("2018-03-27")
    assert parse_date("28-FEB-2018") == parse_date("2018-02-28")
    assert parse_date("11/05/17") == parse_date("2017-05-11")


def test_normalize_truth_maps_entities_to_receipt_record():
    truth = normalize_truth(SEGMENTS["entities"])
    assert truth == {
        "company": "OJC MARKETING SDN BHD",
        "date": "2019-01-15",
        "address": "NO 2 & 4, JALAN BAYU 4, BANDAR SERI ALAM, 81750 MASAI, JOHOR",
        "total": 193.0,
    }


def test_receipt_rules():
    good = Receipt(company="X", date="2019-01-15", address="Y", total=1.0)
    assert check_receipt_rules(good) == []
    bad = Receipt(company=" ", date="not a date", address="", total=0.0)
    errors = check_receipt_rules(bad)
    assert len(errors) == 4


def _write_receipt(dir_, key, truth_overrides=None):
    truth = dict(normalize_truth(SEGMENTS["entities"]), **(truth_overrides or {}))
    (dir_ / f"{key}.txt").write_text(
        text_from_segments(SEGMENTS["words"], SEGMENTS["bboxes"]))
    (dir_ / f"{key}.truth.json").write_text(
        json.dumps({"receipt": truth, "source": "test"}))
    return truth


def test_sroie_eval_arm_end_to_end(tmp_path):
    data = tmp_path / "golden"
    results = tmp_path / "results"
    data.mkdir()
    t1 = _write_receipt(data, "X001")
    t2 = _write_receipt(data, "X002")

    docs = load_sroie(data)
    assert [p.stem for p, _ in docs] == ["X001", "X002"]

    # Perfect answer for doc 1; doc 2 gets a wrong total, printed date format,
    # and comma-less address to exercise the type-aware comparisons.
    good = dict(t1)
    wrong = dict(t2, total=1.0, date="15/01/2019",
                 address="NO 2 & 4 JALAN BAYU 4 BANDAR SERI ALAM 81750 MASAI JOHOR")
    fake = FakeLLM([json.dumps(good), json.dumps(wrong)])

    summary = run_eval(data, results, client=fake, spec=SROIE_SPEC)

    assert summary["dataset"] == "sroie"
    assert summary["n_docs"] == 2
    assert summary["doc_accuracy"] == 0.5
    assert summary["line_items"] is None
    assert summary["fields"]["total"]["exact_match"] == 0.5
    # Printed date and comma-less address still count as correct.
    assert summary["fields"]["date"]["exact_match"] == 1.0
    assert summary["fields"]["address"]["exact_match"] == 1.0
    report = (results / "eval_report.md").read_text()
    assert "line_items" not in report
    assert "(sroie)" in report
