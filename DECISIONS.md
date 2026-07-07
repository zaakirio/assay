# Decisions

Short record of the non-obvious choices; the README carries the full argument.

## One Pydantic model as the contract

`schema.Invoice` generates the constrained-decoding JSON schema, backs validation, and defines the eval fields.
Alternative (separate schema per stage) was rejected because drift between extractor and scorer is exactly the bug an eval harness exists to prevent.

## Constrained decoding over parse-and-repair

llama.cpp's `response_format: json_schema` compiles the schema into a GBNF grammar.
Result on the real run: zero structural failures, so the eval measures semantics only.
Cost: the grammar cannot reject semantically wrong strings (see inv_028, address extracted as invoice number), so validation still earns its keep.

## Repair loop capped at one retry

Measured result with a 1.2B: 8 retries, 0 improvements.
More retries would multiply latency for nothing on this model; the counter stays in the report so a stronger backend can prove the loop pays.

## Confidence is a transparent weighted sum

0.55 rules + 0.25 self-check + 0.20 key-field completeness, threshold 0.85.
A learned or calibrated score would be better ML and worse operations: reviewers need to read why a doc is queued, and the CTO needs a one-line dial.
The threshold sweep in the README is the evidence for the 0.85 default on this model.

## Self-check kept despite noise

It drives the review rate to 81% on the 1.2B, but the sweep shows it is also what holds silent errors to 1 in 6 accepted docs.
Removing it optimizes the demo and pessimizes the product.

## Type-aware metrics, greedy line-item alignment

Dates compare as parsed dates, money numerically at 1 cent, invoice numbers after separator stripping.
Line items pair greedily by description similarity (threshold 0.55 to pair, 0.80 plus numeric agreement to count as correct).
Positional comparison was rejected: one inserted row would cascade into N failures and misstate the model's real error.

## Synthetic golden data, deterministic seed

Real invoices carry real supplier data; a portfolio repo gets none of it.
The generator (reportlab, seed 42, byte-identical PDFs across runs) encodes the mess on purpose: 5 templates, 7 currencies, 6 date formats, label typos, missing fields, multi-page, handwritten-style notes, 3 designed ambiguities.
Ground truth is emitted by the same code that renders the PDF, so labels cannot be wrong.

## Chunk-merge strategy (known weak point)

Multi-page docs are extracted per page-window; header fields take the first non-null, totals the last non-null, line items concatenate.
The real run showed this is the biggest engineering (non-model) failure source; the planned fix is recomputing totals from merged items and repairing chunked docs too.

## Provider-agnostic client, local reference run

Everything speaks `/v1/chat/completions`, so `--url` swaps in any backend (cloud or bigger local model) and the same eval re-scores it.
The measured numbers come from a small local model because it is the cheapest honest baseline; the swap-and-remeasure loop is the point of the project.

## Two eval arms behind one dataset spec

`dataset.DatasetSpec` carries everything arm-specific (Pydantic model, prompt, per-field comparison kinds, key fields, rules, loader, chunk merge), and the extractor, confidence scorer, and eval harness all read from it.
Alternative (a parallel SROIE code path) was rejected for the same reason as separate per-stage schemas: two scoring paths would eventually disagree, and the point of the real arm is comparability with the synthetic one.

## SROIE 2019 via a pinned mirror, never redistributed

The real-data arm uses the `jsdnrs/ICDAR2019-SROIE` Hugging Face mirror (CC-BY-4.0), pinned to revision `bffe40c2` so the bytes cannot drift; `scripts/fetch_sroie.py` downloads and converts on demand and `data/sroie/` is gitignored.
The converter regroups the OCR segments into visual lines using their bounding boxes, normalizes truth dates to ISO, and parses truth totals to floats ("RM 96.90" -> 96.9).

## Address compared on alphanumerics only

SROIE address annotations are comma-punctuated but the provided OCR text has no commas, so exact punctuation is unrecoverable from the model's input.
Comparing alphanumerics (case- and punctuation-insensitive) scores the model on content it can actually produce; the remaining 4% exact match on the reference run is dominated by annotation fragments that are absent from the OCR input entirely (41 of 50 receipts), a measured property of the benchmark.
