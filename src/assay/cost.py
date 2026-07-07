"""Cost model. Local cost is measured (wall time on this machine, electricity
treated as negligible). Cloud figures are vendor list prices per million
tokens as published around July 2026; they are ESTIMATES for comparison, not
quotes, and should be re-checked before any procurement decision."""

CLOUD_PRICES_PER_MTOK = {
    # name: (input $/MTok, output $/MTok, source note)
    "Claude Haiku 4.5": (1.00, 5.00, "anthropic.com/pricing, est. Jul 2026"),
    "Claude Sonnet 4.5": (3.00, 15.00, "anthropic.com/pricing, est. Jul 2026"),
    "GPT-5 mini": (0.25, 2.00, "openai.com/api/pricing, est. Jul 2026"),
    "Gemini 2.5 Flash": (0.30, 2.50, "ai.google.dev/pricing, est. Jul 2026"),
}


def cloud_cost_per_doc(prompt_tokens: float, completion_tokens: float) -> dict:
    out = {}
    for name, (pin, pout, source) in CLOUD_PRICES_PER_MTOK.items():
        cost = (prompt_tokens * pin + completion_tokens * pout) / 1_000_000
        out[name] = {"usd_per_doc": round(cost, 6), "source": source}
    return out
