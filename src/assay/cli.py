import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = Path(os.environ.get("ASSAY_GOLDEN_DIR", PROJECT_ROOT / "data" / "golden"))
SROIE_DIR = Path(os.environ.get("ASSAY_SROIE_DIR", PROJECT_ROOT / "data" / "sroie" / "golden"))
RESULTS_DIR = Path(os.environ.get("ASSAY_RESULTS_DIR", PROJECT_ROOT / "results"))


def main():
    ap = argparse.ArgumentParser(prog="assay",
                                 description="Invoice extraction pipeline with per-field evals")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="regenerate the golden dataset")
    g.add_argument("--count", type=int, default=32)
    g.add_argument("--seed", type=int, default=42)

    e = sub.add_parser("eval", help="run the pipeline over a dataset and score it")
    e.add_argument("--dataset", choices=("golden", "sroie"), default="golden",
                   help="golden = synthetic invoices; sroie = real SROIE 2019 receipts "
                        "(run scripts/fetch_sroie.py first)")
    e.add_argument("--limit", type=int, default=None)
    e.add_argument("--url", default=None, help="llama-server base URL (default http://127.0.0.1:8093/v1)")

    r = sub.add_parser("run", help="extract a single PDF and print the result")
    r.add_argument("pdf", type=Path)
    r.add_argument("--url", default=None)

    sub.add_parser("review", help="work through the review queue")

    args = ap.parse_args()

    if args.cmd == "generate":
        from .generate import generate
        paths = generate(GOLDEN_DIR, count=args.count, seed=args.seed)
        print(f"Wrote {len(paths)} invoices + truth JSON to {GOLDEN_DIR}")
        return

    if args.cmd == "eval":
        from .dataset import INVOICE_SPEC
        from .evalrun import run_eval
        from .llm import LLMClient
        if args.dataset == "sroie":
            from .sroie import SROIE_SPEC
            spec, data_dir, results_dir = SROIE_SPEC, SROIE_DIR, RESULTS_DIR / "sroie"
            if not any(data_dir.glob("*.txt")):
                sys.exit(f"No SROIE documents in {data_dir}. "
                         "Run: uv run --extra sroie python scripts/fetch_sroie.py")
        else:
            spec, data_dir, results_dir = INVOICE_SPEC, GOLDEN_DIR, RESULTS_DIR
        client = LLMClient(args.url) if args.url else LLMClient()
        summary = run_eval(data_dir, results_dir, client=client, limit=args.limit,
                           spec=spec)
        print(f"\nReports written to {results_dir}/eval_report.md and .json")
        print(f"Doc accuracy: {summary['doc_accuracy']:.1%}  "
              f"review rate: {summary['routing']['review_rate']:.1%}")
        return

    if args.cmd == "run":
        from .evalrun import run_document
        from .export import record
        from .extract import Extractor
        from .lf import build_tracer
        from .llm import LLMClient
        client = LLMClient(args.url) if args.url else LLMClient()
        _, ext, scored = run_document(Extractor(client), args.pdf, build_tracer())
        print(json.dumps(record(ext, scored), indent=2, ensure_ascii=False))
        return

    if args.cmd == "review":
        from .review import run_review
        run_review(RESULTS_DIR)
        return


if __name__ == "__main__":
    sys.exit(main())
