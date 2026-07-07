import json

from assay.llm import LLMResult


class FakeLLM:
    """Stands in for llama-server. Extraction calls pop from a queue of
    recorded responses; self-check calls (recognised by their schema) return
    a canned doubtful-fields list."""

    def __init__(self, extraction_responses: list[str], doubtful: list[str] | None = None):
        self.queue = list(extraction_responses)
        self.doubtful = doubtful or []
        self.calls: list[dict] = []

    def chat(self, messages, json_schema=None, max_tokens=2048, temperature=0.0):
        self.calls.append({"messages": messages, "schema": json_schema})
        if json_schema and "doubtful_fields" in json_schema.get("properties", {}):
            content = json.dumps({"doubtful_fields": self.doubtful})
        else:
            content = self.queue.pop(0)
        return LLMResult(content=content, prompt_tokens=100, completion_tokens=50)


def invoice_dict(**overrides) -> dict:
    base = {
        "vendor": "Blue Mesa Packaging Co.",
        "invoice_number": "INV-00123",
        "invoice_date": "2026-03-04",
        "due_date": "2026-04-03",
        "currency": "USD",
        "line_items": [
            {"description": "Pallet wrap, 500mm x 300m", "quantity": 4.0,
             "unit_price": 12.50, "amount": 50.00},
            {"description": "Nitrile gloves, size L (box 100)", "quantity": 2.0,
             "unit_price": 9.00, "amount": 18.00},
        ],
        "subtotal": 68.00,
        "tax": 5.78,
        "total": 73.78,
    }
    base.update(overrides)
    return base
