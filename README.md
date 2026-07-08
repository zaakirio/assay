<p align="center"><img src="assets/banner.svg" alt="" width="100%"></p>

# Assay

An invoice extraction pipeline where every number below was measured, not promised.
Assay extracts structured invoice data from PDFs with an LLM behind any OpenAI-compatible endpoint, validates it against business rules, scores its own confidence, and routes anything uncertain to a human review queue instead of letting it silently reach the ERP.
Its centerpiece is a per-field eval harness that tells you, before go-live, exactly which fields you can trust and which you cannot.
The harness runs on two arms: real scanned receipts from the SROIE 2019 benchmark, and a synthetic invoice set designed as a controlled stress test.

This document is written the way I would brief a customer CTO at the end of a discovery sprint.

## The problem

Your accounts-payable team receives supplier invoices as PDFs from dozens of vendors.
Every vendor has a different layout, date format, currency convention, and level of care.
Someone re-keys vendor, invoice number, dates, line items, tax, and totals into the ERP.
The two failure modes that actually cost money are not "the tool is slow": they are a wrong total posted silently, and a duplicate payment because an invoice number was mis-keyed.

So the bar for automation is not "usually right".
It is: know per field how often you are right, and when you are not sure, say so and route to a human.

## Architecture

```
 PDF ──> ingest ──> extract ──────────> validate ──> confidence ──> route ──> export
         pypdf      local LLM           Pydantic +    schema-valid   ├─ auto-accept ──> accepted.jsonl (ERP feed)
         layout     constrained         business      + rule-pass    └─ review ───────> review_queue.jsonl
         mode       decoding via        rules         + model                              │
                    JSON schema            │          self-check                     assay review (human CLI)
                    (llama.cpp GBNF)       │                                               │
                            ▲              │ validator errors                        reviewed.jsonl
                            └── repair ────┘ (one retry)
```

Each stage is a separate testable module.
The extraction schema is a single Pydantic model; the same model derives the JSON schema that llama.cpp compiles into a decoding grammar, drives validation, and defines the eval fields.
On a rule failure the pipeline retries once, feeding the validator errors back to the model, and reports how often that helped.

## What we measured

Two eval arms, one harness.
The real-data arm is SROIE 2019, the ICDAR scanned-receipt benchmark: real receipts, provided OCR text, independent human annotations (see its section below).
The synthetic arm is the controlled stress-test instrument: 32 generated invoices that plant ambiguity, typos, and contradictions on purpose, with ground truth emitted by the same code that renders the PDFs, so specific failure classes are guaranteed to be covered.
Both roles matter: real data grounds the numbers in documents nobody designed, and synthetic data guarantees coverage of edge cases a sampled real dataset cannot promise to contain.

All numbers below are reference runs with a deliberately small local model.
The pipeline itself is provider-agnostic: everything speaks `/v1/chat/completions`, so pointing `--url` at a cloud frontier model re-scores that backend with the same harness.

### Synthetic arm: 32 invoices, controlled stress test

Setup: LFM2.5-1.2B-Instruct Q4_K_M served by llama.cpp (`llama-server`, Metal, `--ctx-size 4096`) on an Apple M4 Pro, 24 GB.
Golden set: 32 synthetic invoices (seed 42) across 5 layout templates, 7 currencies, 6 date formats, with label typos, handwritten-style annotations, missing fields, 2 multi-page invoices, and 3 deliberately ambiguous documents.
Run date: 2026-07-07. Full outputs in `results/`.
Reproduce with `uv run assay eval`.

Headline: doc-level accuracy (every field correct) was 50.0%.
A 1.2B model is not good enough to run this unattended, and the harness proves it with per-field granularity.

| Field | Precision | Recall | Exact match | Truth n |
|---|---|---|---|---|
| vendor | 96.9% | 96.9% | 96.9% | 32 |
| invoice_number | 96.9% | 96.9% | 96.9% | 32 |
| invoice_date | 90.6% | 93.5% | 93.5% | 31 |
| due_date | 100.0% | 100.0% | 100.0% | 24 |
| currency | 93.8% | 93.8% | 93.8% | 32 |
| subtotal | 87.5% | 90.3% | 90.3% | 31 |
| tax | 73.3% | 81.5% | 81.5% | 27 |
| total | 90.6% | 90.6% | 90.6% | 32 |
| line_items | 87.1% | 87.6% | F1 87.3% | 177 items |

Comparison is type-aware: dates are compared as parsed dates regardless of printed format, money numerically with a 1-cent tolerance, invoice numbers after separator stripping, and line items by fuzzy description alignment so an offset row does not zero out the whole table.

### Routing: the number that matters most

At the shipped confidence threshold (0.85):

- 18.8% of documents auto-accepted, 81.2% routed to review.
- Of the auto-accepted documents, exactly 1 of 6 was wrong (inv_004, wrong currency; see failure analysis).
- 2 of the 3 deliberately ambiguous documents were caught and routed to review.
- Repair retries: 8 attempted, 0 produced a better result.

The threshold is an explicit business dial, and the eval measures the tradeoff on this model:

| Threshold | Auto-accepted | Silently wrong among accepted |
|---|---|---|
| 0.75 | 22/32 (69%) | 6 docs |
| 0.80 | 16/32 (50%) | 4 docs |
| 0.85 | 6/32 (19%) | 1 doc |

With this model you can have volume or safety, not both.
That conclusion is exactly the evidence you need to justify a bigger model: rerun `assay eval` with a different backend and watch this table move.

## Failure analysis (synthetic arm)

Every failure below is from `results/eval_report.json`; nothing is hypothetical.

1. Tax is the weakest field (73.3% precision), and mostly for a semantic reason, not an arithmetic one.
When no tax is printed, the model outputs `0.0` instead of `null` (inv_007, inv_025), and once it invented a tax and a matching total (inv_032: total 1337.78 vs the printed 1310.33).
Null-versus-zero is a classic small-model schema-semantics failure; a stricter prompt contract plus a post-rule ("tax must appear in the text") would catch most of it.

2. Date component transposition.
On numeric formats the model swapped day and month: inv_017 printed 10.06.2026 and extracted 2026-10-06, inv_028 printed 09/02/2026 and extracted 2026-09-02.
Both dates are individually plausible, so only cross-checks (due_date minus invoice_date should be a standard net term) or a locale hint from the vendor address can catch this.
This is the highest-risk residual error class because it survives all current rules.

3. Multi-page documents break the naive chunk-merge (inv_008, inv_020, the two 2-page invoices).
Per-chunk extraction then merge produced subtotals from partial item lists (inv_008: 1787.85 vs truth 8989.85) and missed or duplicated line items (inv_020: 8 wrong items).
Both were routed to review (confidence 0.28 and 0.20), so nothing silent, but the fix is real: extract line items per page and totals only from the final page, then recompute totals from items instead of trusting either chunk.
The repair loop also currently skips chunked documents, so they never get a second chance.

4. Currency inference fails exactly where a human would need context.
inv_004 prints only "$" on an Australian vendor; the model said USD, and this was the one silently wrong auto-accept in the whole run.
inv_010 printed a literal € sign and the model still said USD.
The designed ambiguity (inv_004) argues for a rule: symbol-only currencies never auto-accept.
The € miss is plain model weakness; a bigger model fixes it.

5. Hallucination under absence.
inv_012 prints no invoice date at all; the model produced 2024-05-20 from nothing.
The self-check flagged it (routed to review), which is the system working, but it shows why "no date printed" must not be an auto-accept path.

6. Field confusion: inv_028 extracted the vendor's street address as the invoice number.
Constrained decoding guarantees a syntactically valid string, and this is the tradeoff: the grammar cannot know the string is semantically wrong.
A format prior on invoice numbers (regex over observed vendor formats) would catch it cheaply.

7. The repair loop does not pay for itself at 1.2B: 8 retries, 0 improvements.
The model repeats roughly the same extraction when shown its own validation errors.
Kept in the pipeline because the mechanism is right and measured, but the data says feedback-driven repair needs a model that can actually use feedback.

8. One copy typo: inv_023 extracted "Reddfern & Gale Stationers" for "Redfern & Gale Stationers".
Exact-match scoring counts it wrong, which is correct for an ERP key; vendor-master fuzzy matching belongs in the export stage in production.

What a stronger model buys: classes 2, 4 (€ case), 5, 6, and 8 are model-capability errors, and class 7 becomes useful instead of dead weight.
Class 3 is an engineering fix independent of model size.
Class 1 is half prompt contract, half rule.

## Real-data arm: SROIE 2019 receipts

Synthetic data proves the machinery; real data proves the claim.
The second arm runs the same pipeline and the same per-field harness over [SROIE 2019](https://rrc.cvc.uab.es/?ch=13) (ICDAR 2019 Robust Reading Challenge on Scanned Receipts OCR and Information Extraction, task 3): real retail receipts with provided OCR text and four annotated key fields per receipt (company, date, address, total).
The dataset is not redistributed in this repo.
`scripts/fetch_sroie.py` downloads a pinned revision of the CC-BY-4.0 [`jsdnrs/ICDAR2019-SROIE`](https://huggingface.co/datasets/jsdnrs/ICDAR2019-SROIE) mirror on Hugging Face and converts the OCR line segments (grouped back into visual lines via their bounding boxes) plus ground truth into assay's document and truth format, with a receipt schema variant.

Reference run: same deliberately small local model and machine as the synthetic arm (LFM2.5-1.2B Q4_K_M, llama.cpp, M4 Pro), first 50 receipts of the 361-receipt test split ordered by key, run 2026-07-07.
Full outputs in `results/sroie/`.
Reproduce:

```bash
uv run --extra sroie python scripts/fetch_sroie.py
uv run assay eval --dataset sroie --limit 50
```

Headline: doc-level accuracy (all four fields correct) was 2.0%, against 50.0% on the synthetic invoices.
Real documents are dramatically harder than designed ones, and exposing that gap before go-live is exactly what this arm is for.

| Field | Precision | Recall | Exact match | Truth n |
|---|---|---|---|---|
| company | 60.0% | 60.0% | 60.0% | 50 |
| date | 59.6% | 56.0% | 56.0% | 50 |
| address | 4.0% | 4.0% | 4.0% | 50 |
| total | 86.0% | 86.0% | 86.0% | 50 |

Comparison is type-aware here too: dates as parsed dates, totals numerically with a 1-cent tolerance, and addresses on alphanumerics only (case and punctuation ignored), because the annotations punctuate addresses with commas that the OCR input never contains.
Constrained decoding again held: zero schema failures across the run.

What the failures actually are:

1. Address (4.0%) is mostly a data-ceiling story, and the harness quantifies it: on 41 of the 50 receipts at least one fragment of the annotated address never appears in the provided OCR text at all (the annotations were made from the receipt images; the OCR misses lines like "JALAN BAYU 4", and the annotation itself sometimes carries typos like "B1750" for the printed "81750").
The achievable ceiling on this slice is therefore 18% for any model reading this input.
Within reach of that ceiling the model adds its own failures: it paraphrases and reorders instead of copying ("2 & 4 Bandar Seri Alam, 81750 Masai" for "NO 2 & 4, JALAN BAYU 4, ...").

2. Date (56.0%) repeats the exact transposition class the synthetic arm predicted: 9 of the 22 date errors are day/month swaps ("02/01/2019" extracted as 2019-02-01).
The synthetic stress test flagged this failure mode before any real document was scored, which is the clearest demonstration of why both arms exist.

3. Company (60.0%) fails by picking the wrong header line: the cashier's name "TAN CHAY YEE" over the business name printed below it, or a truncation ("SECURE PARKING" for "SECURE PARKING CORPORATION S/B").

4. Total (86.0%) fails by selecting a nearby plausible amount (a rounding line, or tax-exclusive versus paid), not by arithmetic.

Routing on real data is the sobering result: 26.0% of receipts auto-accepted, and every single auto-accepted receipt had at least one wrong field, almost always the address.
The confidence score has components for rule failures, model self-doubt, and completeness, but no component can know that the annotation is not recoverable from the input, and no business rule can cross-check a free-text address.
The operational conclusion: on real receipts with this model, automation is total-and-date triage at best, the address field must never be an auto-accept criterion, and the per-field report is what tells you that before you promise otherwise.

## Cost per document

Measured on the synthetic reference run: mean 1,881 tokens per document (1,426 prompt + 455 completion), mean latency 2.72 s/doc, p95 3.27 s, 87.2 s wall for 32 documents, effective completion throughput 167 tok/s including prefill.

| Backend | Cost per doc | Cost per 10k docs/month |
|---|---|---|
| Local LFM2.5-1.2B on M4 Pro (measured) | $0 marginal, 2.72 s/doc | ~7.6 machine-hours, electricity negligible |
| GPT-5 mini (estimate) | $0.00127 | ~$13 |
| Gemini 2.5 Flash (estimate) | $0.00156 | ~$16 |
| Claude Haiku 4.5 (estimate) | $0.00370 | ~$37 |
| Claude Sonnet 4.5 (estimate) | $0.01110 | ~$111 |

Cloud rows use vendor list prices per MTok as published around July 2026 applied to the measured token counts.
They are estimates for comparison, not quotes; re-check prices before any procurement decision.
The takeaway: at these volumes, cloud inference cost is a rounding error next to one mis-posted invoice.
The argument for local is data residency and control, not dollars.

## Technical decisions

One Pydantic model is the single source of truth: it generates the JSON schema for constrained decoding, drives validation, and defines the eval fields, so the extractor, validator, and scorer cannot drift apart.

Constrained decoding (llama.cpp compiles the JSON schema to a GBNF grammar) instead of parse-and-pray: zero schema failures across the run, which converts "did it emit JSON" from a metric into a non-issue and leaves the eval measuring what matters, semantic correctness.

Confidence is a transparent weighted sum of three inspectable components (business-rule score, model self-check, key-field completeness), not a learned score.
A reviewer can read exactly why a document is in their queue, and the threshold is one line to change.

Eval comparison is type-aware because exact string match would systematically lie: it would punish `18/01/2026` vs `2026-01-18` (same date) and reward `2026-09-02` vs `09/02/2026` printed with the other convention (wrong date).

Line items are aligned greedily by description similarity before comparing numbers, so one hallucinated row costs one false positive rather than cascading through a positional comparison.

Two datasets with two distinct jobs, not a synthetic stand-in for missing real data.
The synthetic golden set is generated deterministically (`uv run assay generate`, seed 42) and models the mess deliberately: typo'd labels, 6 date formats, symbol-only currencies, missing fields, multi-page spillover, handwritten-style annotations, and 3 documents that are ambiguous to a careful human.
A sampled real dataset cannot guarantee coverage of any of those classes; a generator can, and its ground truth is emitted by the same code that renders the PDF so labels cannot be wrong.
The real arm (SROIE 2019) then checks the pipeline against documents and annotations nobody designed, including annotation noise the synthetic arm cannot simulate.
One dataset spec object per arm (schema, prompt, field comparison types, rules, loader) feeds the identical harness, so the two arms cannot drift apart in how they are scored.

The self-check stays despite being noisy on a 1.2B (it is the main reason the review rate is 81%): the threshold sweep shows it is also what keeps silent errors at 1 in 6 accepted docs.
Trading review volume against silent errors is the customer's call to make with the table above, not a default I should bury.

## What production hardening would add

Scanned and photographed invoices: this pipeline reads born-digital PDF text layers; production needs an OCR stage (or a vision model) in front of ingest, and the eval harness already measures whatever ingest feeds it.

Permissions and audit: per-user review queues, approval limits by amount, an immutable audit log of who accepted or corrected what, and redaction of bank details from logs.

Idempotency and CDC: dedup on (vendor, invoice_number, total) before export, change-data-capture into the ERP instead of file drops, and replay-safe exports.

Freshness and drift: new vendors mean new layouts; production needs a weekly eval on a rotating labeled sample, per-vendor accuracy tracking, and alerting when a field's exact-match drops.

Feedback loop: reviewed corrections (`reviewed.jsonl`) are the labeled data for the next eval round and for few-shot prompt examples per vendor; the file format is already the truth format.

## Running it

```bash
uv sync
uv run pytest                 # 51 tests, model-free

# point the pipeline at any OpenAI-compatible endpoint...
export ASSAY_LLM_URL=https://api.openai.com/v1   # or any compatible base URL
export ASSAY_LLM_KEY=sk-...                      # sent as a Bearer token
export ASSAY_LLM_MODEL=gpt-5-mini                # model name, if the endpoint needs one

# ...or serve a model locally (the reference-run setup; no key or model name needed)
/path/to/llama-server -m LFM2.5-1.2B-Instruct-Uncensored-Q4_K_M.gguf \
  --port 8093 --jinja -ngl 99 --ctx-size 4096

uv run assay generate         # regenerate the synthetic golden set (deterministic, seed 42)
uv run assay eval             # synthetic arm: full pipeline + report -> results/

uv run --extra sroie python scripts/fetch_sroie.py   # download + convert SROIE 2019 (~216 MB, pinned revision)
uv run assay eval --dataset sroie --limit 50         # real-data arm -> results/sroie/

uv run assay run data/golden/inv_001.pdf   # single document, prints JSON
uv run assay review           # work the review queue in the terminal
```

`ASSAY_LLM_URL` or `--url` points the pipeline at any OpenAI-compatible endpoint.
`ASSAY_LLM_KEY` adds a Bearer token for keyed APIs and `ASSAY_LLM_MODEL` sets the model name in the request body; a local llama-server needs neither.
`ASSAY_GOLDEN_DIR` and `ASSAY_RESULTS_DIR` override where the golden set is read from and where reports and queues are written (defaults: `data/golden/` and `results/` in the repo).

### Docker

```bash
docker build -t assay .
docker run --rm assay --help
docker run --rm -v "$PWD/out:/work/results" \
  -e ASSAY_LLM_URL=http://host.docker.internal:8093/v1 \
  assay eval
```

The image is a runnable CLI (multi-stage uv build, `python:3.11-slim` runtime, non-root user) with the golden set baked in at `/app/data/golden` and results written to the `/work` volume.
To regenerate data inside the container, point `ASSAY_GOLDEN_DIR` somewhere writable, e.g. `-e ASSAY_GOLDEN_DIR=/work/golden`.

### Langfuse tracing

Assay can emit one Langfuse trace per document as it moves through the pipeline: an `ingest` span (pages, characters), an `extract` span (chunks, tokens, rule errors, doubtful fields, with any repair retry attached as an event), and a `confidence` span (score and routing decision).
That gives you a per-document, per-stage view of an eval run in the Langfuse UI without reading the JSON report.

It is off by default and strictly optional: the SDK lives in the `obs` extra, the import is guarded, and with the env vars unset the pipeline runs exactly as before.

```bash
uv sync --extra obs
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=http://127.0.0.1:3000   # optional; defaults to Langfuse Cloud
uv run assay eval
```

Works with Langfuse Cloud or self-hosted Langfuse; only the env vars differ.

## Layout

```
src/assay/
  cli.py         # argparse entry point (generate / eval / run / review)
  schema.py      # the invoice Pydantic contract
  dataset.py     # dataset specs: schema + prompt + field types + rules + loader per arm
  sroie.py       # SROIE 2019 arm: receipt schema, converter, dataset spec
  generate.py    # synthetic golden dataset generator (PDFs + truth JSON)
  ingest.py      # pdf/txt -> layout-preserving text
  llm.py         # OpenAI-compatible client (llama.cpp json_schema)
  extract.py     # chunking, constrained extraction, repair loop, self-check
  validate.py    # invoice business rules
  confidence.py  # scoring + routing threshold
  metrics.py     # type-aware per-field comparison, line-item alignment
  evalrun.py     # the eval harness
  review.py      # human review CLI
  export.py      # JSONL in/out
  cost.py        # measured local vs estimated cloud
  lf.py          # optional Langfuse tracing (obs extra)
scripts/
  fetch_sroie.py # download pinned SROIE 2019 mirror + convert (not redistributed)
data/golden/     # 32 synthetic invoices + ground truth (committed)
data/sroie/      # real receipts, downloaded on demand (gitignored)
results/         # synthetic-arm reports + queues from the real run
results/sroie/   # real-data-arm reports from the real run
tests/           # offline; FakeLLM + one recorded real response
```

See `DECISIONS.md` for the short version of every non-obvious choice.
