# Assay eval report (sroie)

Documents: 50  |  doc-level accuracy (every field correct): 2.0%

## Per-field results

| Field | Precision | Recall | Exact match | Truth n |
|---|---|---|---|---|
| company | 60.0% | 60.0% | 60.0% | 50 |
| date | 59.6% | 56.0% | 56.0% | 50 |
| address | 4.0% | 4.0% | 4.0% | 50 |
| total | 86.0% | 86.0% | 86.0% | 50 |

## Routing

- Auto-accepted: 26.0%, review queue: 74.0%
- Silently wrong among auto-accepted: 100.0% (X51005268275, X51005268408, X51005301666, X51005337877, X51005361906, X51005442322, X51005442343, X51005442366, X51005444040, X51005444046, X51005447841, X51005568866, X51005568894)
- Ambiguous docs routed to review: 0/0
- Repair retries attempted: 0, improved result: 0

## Performance

- Mean latency per doc: 1.23s (p95 2.31s), total wall time 61.6s
- Tokens per doc (prompt+completion): 1108.0
- Effective completion throughput: 121.1 tok/s (includes prefill and pipeline overhead)

## Cost per document

- Local (this machine): $0 marginal; electricity negligible
- Claude Haiku 4.5: $0.00170 (anthropic.com/pricing, est. Jul 2026)
- Claude Sonnet 4.5: $0.00511 (anthropic.com/pricing, est. Jul 2026)
- GPT-5 mini: $0.00054 (openai.com/api/pricing, est. Jul 2026)
- Gemini 2.5 Flash: $0.00066 (ai.google.dev/pricing, est. Jul 2026)
