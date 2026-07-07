"""The eval harness: run the full pipeline over the golden set, score every
field against ground truth, and emit a markdown + JSON report. This is the
artifact a customer signs off on before anything touches their ERP."""

import json
import statistics
import time
from pathlib import Path

from . import export
from .confidence import score
from .cost import cloud_cost_per_doc
from .dataset import INVOICE_SPEC, DatasetSpec, load_golden  # noqa: F401 (re-export)
from .extract import Extractor
from .ingest import ingest
from .lf import build_tracer, span
from .llm import LLMClient
from .metrics import (FieldTally, align_line_items, compare_scalars,
                      doc_correct, prf)


def run_document(extractor: Extractor, pdf: Path, tracer=None):
    """One document through the pipeline, as one Langfuse trace when enabled."""
    with span(tracer, name=pdf.stem) as root:
        with span(root, "ingest") as s:
            doc = ingest(pdf)
            if s:
                s.update(output={"pages": len(doc.pages), "chars": len(doc.text)})
        with span(root, "extract") as s:
            ext = extractor.extract(doc)
            if s:
                if ext.repair_attempted:
                    s.create_event(name="repair", metadata={"improved": ext.repaired})
                s.update(
                    metadata={
                        "chunks": ext.chunks,
                        "prompt_tokens": ext.prompt_tokens,
                        "completion_tokens": ext.completion_tokens,
                        "schema_failed": ext.schema_failed,
                    },
                    output={
                        "rule_errors": ext.rule_errors,
                        "doubtful_fields": ext.doubtful_fields,
                    },
                )
        with span(root, "confidence") as s:
            scored = score(ext, extractor.spec)
            if s:
                s.update(output={"confidence": scored.confidence, "route": scored.route})
        if root:
            root.update(
                metadata={
                    "prompt_tokens": ext.prompt_tokens,
                    "completion_tokens": ext.completion_tokens,
                    "latency_s": round(ext.latency_s, 3),
                },
                output={"route": scored.route, "confidence": scored.confidence},
            )
    return doc, ext, scored


def run_eval(golden_dir: Path, results_dir: Path, client: LLMClient | None = None,
             limit: int | None = None, tracer=None,
             spec: DatasetSpec = INVOICE_SPEC) -> dict:
    client = client or LLMClient()
    tracer = tracer if tracer is not None else build_tracer()
    extractor = Extractor(client, spec)
    docs = spec.load(golden_dir)
    if limit:
        docs = docs[:limit]

    tallies = {f: FieldTally() for f in spec.field_kinds}
    li_tp = li_fp = li_fn = 0
    rows, doc_results = [], []
    t_start = time.monotonic()

    for pdf, truth in docs:
        doc, ext, scored = run_document(extractor, pdf, tracer)
        pred = ext.invoice.model_dump() if ext.invoice else None
        truth_rec = truth[spec.truth_key]
        scalar_ok = compare_scalars(doc.doc_id, truth_rec, pred, tallies,
                                    spec.field_kinds)
        if spec.has_line_items:
            li = align_line_items(
                truth_rec["line_items"],
                pred["line_items"] if pred else [],
            )
        else:
            li = {"tp": 0, "fp": 0, "fn": 0, "mismatches": []}
        li_tp += li["tp"]
        li_fp += li["fp"]
        li_fn += li["fn"]
        all_ok = doc_correct(scalar_ok, li)

        row = export.record(ext, scored)
        rows.append(row)
        doc_results.append({
            **row,
            "truth_route": truth.get("expected_route"),
            "ambiguous": truth.get("ambiguous", False),
            "fields_correct": scalar_ok,
            "line_items": {k: li[k] for k in ("tp", "fp", "fn")},
            "doc_correct": all_ok,
        })
        wrong = [f for f, ok in scalar_ok.items() if not ok]
        status = "OK " if all_ok else "ERR"
        print(f"[{status}] {doc.doc_id} route={scored.route} conf={scored.confidence} "
              f"wrong={wrong or '-'} li_fp={li['fp']} li_fn={li['fn']} "
              f"{ext.latency_s:.1f}s")

    wall_s = time.monotonic() - t_start
    n = len(doc_results)
    accepted = [d for d in doc_results if d["route"] == "auto"]
    queued = [d for d in doc_results if d["route"] == "review"]
    silent_wrong = [d for d in accepted
                    if not all(d["fields_correct"].values())
                    or d["line_items"]["fp"] or d["line_items"]["fn"]]
    ambiguous_caught = [d for d in queued if d["ambiguous"]]
    n_ambiguous = sum(1 for d in doc_results if d["ambiguous"])

    prompt_toks = sum(d["prompt_tokens"] for d in doc_results)
    completion_toks = sum(d["completion_tokens"] for d in doc_results)
    latencies = [d["latency_s"] for d in doc_results]

    li_p, li_r, li_f1 = prf(li_tp, li_fp, li_fn)
    summary = {
        "dataset": spec.name,
        "n_docs": n,
        "doc_accuracy": round(sum(d["doc_correct"] for d in doc_results) / n, 4),
        "fields": {
            f: {
                "precision": _r(t.precision),
                "recall": _r(t.recall),
                "exact_match": _r(t.exact_match),
                "n_truth": t.n_truth,
                "errors": t.errors,
            }
            for f, t in tallies.items()
        },
        "line_items": {
            "precision": _r(li_p), "recall": _r(li_r), "f1": _r(li_f1),
            "tp": li_tp, "fp": li_fp, "fn": li_fn,
        } if spec.has_line_items else None,
        "routing": {
            "review_rate": round(len(queued) / n, 4),
            "auto_accept_rate": round(len(accepted) / n, 4),
            "silent_wrong_docs": [d["doc_id"] for d in silent_wrong],
            "silent_wrong_rate_of_accepted": round(len(silent_wrong) / len(accepted), 4) if accepted else None,
            "ambiguous_docs_caught": f"{len(ambiguous_caught)}/{n_ambiguous}",
        },
        "repairs": {
            "attempted": sum(d["repair_attempted"] for d in doc_results),
            "improved": sum(d["repaired"] for d in doc_results),
        },
        "perf": {
            "wall_s_total": round(wall_s, 1),
            "latency_s_mean": round(statistics.mean(latencies), 2),
            "latency_s_p95": round(sorted(latencies)[int(0.95 * (n - 1))], 2),
            "prompt_tokens_total": prompt_toks,
            "completion_tokens_total": completion_toks,
            "tokens_per_doc_mean": round((prompt_toks + completion_toks) / n, 1),
            "completion_tok_s_incl_prefill": round(completion_toks / wall_s, 1),
        },
        "cost": {
            "local": "electricity negligible; see perf for throughput",
            "cloud_estimates_per_doc": cloud_cost_per_doc(
                prompt_toks / n, completion_toks / n),
        },
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    export.write_jsonl(results_dir / "accepted.jsonl",
                       [r for r in rows if r["route"] == "auto"])
    export.write_jsonl(results_dir / "review_queue.jsonl",
                       [r for r in rows if r["route"] == "review"])
    (results_dir / "eval_report.json").write_text(
        json.dumps({"summary": summary, "docs": doc_results}, indent=2,
                   ensure_ascii=False))
    (results_dir / "eval_report.md").write_text(render_markdown(summary))
    return summary


def _r(v: float | None) -> float | None:
    return round(v, 4) if v is not None else None


def _pct(v: float | None) -> str:
    return f"{100 * v:.1f}%" if v is not None else "n/a"


def render_markdown(s: dict) -> str:
    lines = [
        f"# Assay eval report ({s.get('dataset', 'golden')})",
        "",
        f"Documents: {s['n_docs']}  |  doc-level accuracy (every field correct): "
        f"{_pct(s['doc_accuracy'])}",
        "",
        "## Per-field results",
        "",
        "| Field | Precision | Recall | Exact match | Truth n |",
        "|---|---|---|---|---|",
    ]
    for f, t in s["fields"].items():
        lines.append(f"| {f} | {_pct(t['precision'])} | {_pct(t['recall'])} | "
                     f"{_pct(t['exact_match'])} | {t['n_truth']} |")
    li = s["line_items"]
    if li is not None:
        lines.append(f"| line_items | {_pct(li['precision'])} | {_pct(li['recall'])} | "
                     f"f1 {_pct(li['f1'])} | {li['tp'] + li['fn']} items |")
    r = s["routing"]
    p = s["perf"]
    lines += [
        "",
        "## Routing",
        "",
        f"- Auto-accepted: {_pct(r['auto_accept_rate'])}, review queue: {_pct(r['review_rate'])}",
        f"- Silently wrong among auto-accepted: {_pct(r['silent_wrong_rate_of_accepted'])} "
        f"({', '.join(r['silent_wrong_docs']) or 'none'})",
        f"- Ambiguous docs routed to review: {r['ambiguous_docs_caught']}",
        f"- Repair retries attempted: {s['repairs']['attempted']}, improved result: {s['repairs']['improved']}",
        "",
        "## Performance",
        "",
        f"- Mean latency per doc: {p['latency_s_mean']}s (p95 {p['latency_s_p95']}s), "
        f"total wall time {p['wall_s_total']}s",
        f"- Tokens per doc (prompt+completion): {p['tokens_per_doc_mean']}",
        f"- Effective completion throughput: {p['completion_tok_s_incl_prefill']} tok/s "
        "(includes prefill and pipeline overhead)",
        "",
        "## Cost per document",
        "",
        "- Local (this machine): $0 marginal; electricity negligible",
    ]
    for name, c in s["cost"]["cloud_estimates_per_doc"].items():
        lines.append(f"- {name}: ${c['usd_per_doc']:.5f} ({c['source']})")
    lines.append("")
    return "\n".join(lines)
