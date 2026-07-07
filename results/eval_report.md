# Assay eval report

Documents: 32  |  doc-level accuracy (every field correct): 50.0%

## Per-field results

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
| line_items | 87.1% | 87.6% | f1 87.3% | 177 items |

## Routing

- Auto-accepted: 18.8%, review queue: 81.2%
- Silently wrong among auto-accepted: 16.7% (inv_004)
- Ambiguous docs routed to review: 2/3
- Repair retries attempted: 8, improved result: 0

## Performance

- Mean latency per doc: 2.72s (p95 3.27s), total wall time 87.2s
- Tokens per doc (prompt+completion): 1881.0
- Effective completion throughput: 167.0 tok/s (includes prefill and pipeline overhead)

## Cost per document

- Local (this machine): $0 marginal; electricity negligible
- Claude Haiku 4.5: $0.00370 (anthropic.com/pricing, est. Jul 2026)
- Claude Sonnet 4.5: $0.01110 (anthropic.com/pricing, est. Jul 2026)
- GPT-5 mini: $0.00127 (openai.com/api/pricing, est. Jul 2026)
- Gemini 2.5 Flash: $0.00156 (ai.google.dev/pricing, est. Jul 2026)
