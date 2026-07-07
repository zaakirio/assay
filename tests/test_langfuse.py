import json

import pytest

from assay.evalrun import load_golden, run_document, run_eval
from assay.extract import Extractor
from assay.generate import generate
from assay.lf import build_tracer, span
from conftest import FakeLLM


class SpySpan:
    def __init__(self, name, **kwargs):
        self.name = name
        self.kwargs = kwargs
        self.children = []
        self.events = []
        self.updates = []
        self.ended = False

    def start_observation(self, name, **kwargs):
        child = SpySpan(name, **kwargs)
        self.children.append(child)
        return child

    def update(self, **kwargs):
        self.updates.append(kwargs)
        return self

    def create_event(self, name, **kwargs):
        self.events.append((name, kwargs))

    def end(self):
        self.ended = True


class SpyTracer:
    def __init__(self):
        self.traces = []

    def start_observation(self, name, **kwargs):
        trace = SpySpan(name, **kwargs)
        self.traces.append(trace)
        return trace


def test_run_document_emits_one_trace_with_pipeline_stages(tmp_path):
    golden = tmp_path / "golden"
    generate(golden, count=1, seed=42)
    pdf, truth = load_golden(golden)[0]
    fake = FakeLLM([json.dumps(truth["invoice"])])
    tracer = SpyTracer()

    doc, ext, scored = run_document(Extractor(fake), pdf, tracer)

    assert len(tracer.traces) == 1
    trace = tracer.traces[0]
    assert trace.name == pdf.stem
    assert [c.name for c in trace.children] == ["ingest", "extract", "confidence"]
    assert trace.ended
    assert all(c.ended for c in trace.children)

    extract_span = trace.children[1]
    meta = extract_span.updates[-1]["metadata"]
    assert meta["prompt_tokens"] == ext.prompt_tokens
    assert meta["completion_tokens"] == ext.completion_tokens
    assert meta["chunks"] == 1

    conf_out = trace.children[2].updates[-1]["output"]
    assert conf_out["route"] == scored.route
    assert conf_out["confidence"] == scored.confidence
    assert trace.updates[-1]["output"]["route"] == scored.route


def test_repair_attempt_recorded_as_event(tmp_path):
    golden = tmp_path / "golden"
    generate(golden, count=1, seed=42)
    pdf, truth = load_golden(golden)[0]
    broken = dict(truth["invoice"], total=1.0)
    fake = FakeLLM([json.dumps(broken), json.dumps(broken)])
    tracer = SpyTracer()

    _, ext, _ = run_document(Extractor(fake), pdf, tracer)

    assert ext.repair_attempted
    extract_span = tracer.traces[0].children[1]
    assert ("repair", {"metadata": {"improved": False}}) in extract_span.events


def test_run_eval_traces_every_document(tmp_path):
    golden = tmp_path / "golden"
    generate(golden, count=2, seed=42)
    responses = [json.dumps(truth["invoice"]) for _, truth in load_golden(golden)]
    fake = FakeLLM(responses)
    tracer = SpyTracer()

    summary = run_eval(golden, tmp_path / "results", client=fake, tracer=tracer)

    assert summary["n_docs"] == 2
    assert [t.name for t in tracer.traces] == ["inv_001", "inv_002"]


def test_span_is_noop_without_tracer():
    with span(None, "anything") as s:
        assert s is None


def test_build_tracer_requires_env(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert build_tracer() is None


def test_build_tracer_requires_package(monkeypatch):
    import importlib.util

    if importlib.util.find_spec("langfuse") is not None:
        pytest.skip("langfuse is installed; the ImportError path is not reachable")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    assert build_tracer() is None
