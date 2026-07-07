import json

from assay.evalrun import load_golden, run_eval
from assay.generate import generate
from conftest import FakeLLM


def test_eval_with_perfect_recorded_answers(tmp_path):
    golden = tmp_path / "golden"
    results = tmp_path / "results"
    generate(golden, count=6, seed=42)

    responses = [json.dumps(truth["invoice"]) for _, truth in load_golden(golden)]
    fake = FakeLLM(responses)

    summary = run_eval(golden, results, client=fake)

    assert summary["n_docs"] == 6
    assert summary["doc_accuracy"] == 1.0
    for f, t in summary["fields"].items():
        assert t["errors"] == [], f"{f}: {t['errors']}"
    assert summary["line_items"]["fp"] == 0
    assert summary["line_items"]["fn"] == 0
    assert summary["repairs"]["attempted"] == 0
    assert (results / "eval_report.md").exists()
    assert (results / "eval_report.json").exists()

    report = (results / "eval_report.md").read_text()
    assert "Per-field results" in report


def test_eval_scores_wrong_answers_and_queues_them(tmp_path):
    golden = tmp_path / "golden"
    results = tmp_path / "results"
    generate(golden, count=2, seed=42)

    docs = load_golden(golden)
    good = json.dumps(docs[0][1]["invoice"])
    wrong = dict(docs[1][1]["invoice"], total=1.0)
    fake = FakeLLM([good, json.dumps(wrong), json.dumps(wrong)])

    summary = run_eval(golden, results, client=fake)
    assert summary["doc_accuracy"] == 0.5
    assert summary["fields"]["total"]["exact_match"] == 0.5
    assert summary["routing"]["review_rate"] == 0.5
    assert summary["repairs"]["attempted"] == 1

    queue = (results / "review_queue.jsonl").read_text().strip().splitlines()
    assert len(queue) == 1
