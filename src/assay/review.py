"""Human review queue CLI. Reads results/review_queue.jsonl, shows the
model's guesses with the failing rules, and captures accept / correct /
skip decisions into results/reviewed.jsonl."""

import json
from pathlib import Path

from .export import read_jsonl, write_jsonl

SCALAR_FIELDS = ("vendor", "invoice_number", "invoice_date", "due_date",
                 "currency", "subtotal", "tax", "total")


def _show(item: dict):
    print(f"\n=== {item['doc_id']}  (confidence {item['confidence']}) ===")
    inv = item.get("invoice")
    if inv is None:
        print("  extraction failed entirely")
    else:
        for f in SCALAR_FIELDS:
            print(f"  {f:>15}: {inv.get(f)}")
        print(f"  {'line_items':>15}: {len(inv.get('line_items', []))} rows")
        for li in inv.get("line_items", [])[:8]:
            print(f"        - {li['description'][:48]:<50} "
                  f"{li['quantity']:g} x {li['unit_price']} = {li['amount']}")
        if len(inv.get("line_items", [])) > 8:
            print(f"        ... {len(inv['line_items']) - 8} more")
    print("  why it is here:")
    for r in item.get("reasons", []) or ["confidence below threshold"]:
        print(f"    - {r}")


def _coerce(field: str, raw: str):
    if raw.lower() in ("null", "none", ""):
        return None
    if field in ("subtotal", "tax", "total"):
        return float(raw.replace(",", ""))
    return raw


def run_review(results_dir: Path, input_fn=input):
    queue_path = results_dir / "review_queue.jsonl"
    reviewed_path = results_dir / "reviewed.jsonl"
    queue = read_jsonl(queue_path)
    if not queue:
        print("Review queue is empty.")
        return

    already = {r["doc_id"] for r in read_jsonl(reviewed_path)}
    pending = [q for q in queue if q["doc_id"] not in already]
    print(f"{len(pending)} document(s) pending review "
          f"({len(already)} already reviewed).")

    reviewed = read_jsonl(reviewed_path)
    for item in pending:
        _show(item)
        while True:
            cmd = input_fn("\n[a]ccept  [c]orrect field=value  [s]kip  [q]uit > ").strip()
            if cmd == "q":
                write_jsonl(reviewed_path, reviewed)
                return
            if cmd == "s":
                break
            if cmd == "a":
                reviewed.append({**item, "review": "accepted", "corrections": {}})
                break
            if cmd.startswith("c "):
                try:
                    field, _, raw = cmd[2:].partition("=")
                    field = field.strip()
                    if field not in SCALAR_FIELDS:
                        print(f"unknown field '{field}' (one of {', '.join(SCALAR_FIELDS)})")
                        continue
                    value = _coerce(field, raw.strip())
                except ValueError:
                    print("could not parse value as a number")
                    continue
                inv = item.get("invoice") or {}
                corrections = {field: {"was": inv.get(field), "now": value}}
                inv[field] = value
                item["invoice"] = inv
                reviewed.append({**item, "review": "corrected",
                                 "corrections": corrections})
                break
            print("unrecognised command")
    write_jsonl(reviewed_path, reviewed)
    print(f"\nWrote {reviewed_path}")
