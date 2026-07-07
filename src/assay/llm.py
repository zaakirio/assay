"""Minimal OpenAI-compatible chat client for llama.cpp's llama-server.
Structured output goes through response_format json_schema, which llama.cpp
compiles to a GBNF grammar (constrained decoding), so the model cannot emit
structurally invalid JSON."""

import os
from dataclasses import dataclass

import httpx

DEFAULT_BASE_URL = os.environ.get("ASSAY_LLM_URL", "http://127.0.0.1:8093/v1")


@dataclass
class LLMResult:
    content: str
    prompt_tokens: int
    completion_tokens: int


class LLMClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(timeout=timeout)

    def chat(self, messages: list[dict], json_schema: dict | None = None,
             max_tokens: int = 2048, temperature: float = 0.0) -> LLMResult:
        body: dict = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "extraction", "schema": json_schema},
            }
        r = self._http.post(f"{self.base_url}/chat/completions", json=body)
        r.raise_for_status()
        data = r.json()
        usage = data.get("usage", {})
        return LLMResult(
            content=data["choices"][0]["message"]["content"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
