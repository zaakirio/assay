"""Optional Langfuse tracing. build_tracer returns None unless the LANGFUSE_*
keys are set and the langfuse package (the `obs` extra) is installed; a None
tracer makes every span() a no-op, so the pipeline is unchanged by default."""

import logging
import os
from contextlib import contextmanager

log = logging.getLogger("assay")


def build_tracer():
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    try:
        from langfuse import Langfuse
    except ImportError:
        log.warning(
            "LANGFUSE_PUBLIC_KEY/SECRET_KEY are set but the langfuse package "
            "is not installed; install with `uv sync --extra obs`"
        )
        return None
    return Langfuse()


@contextmanager
def span(parent, name: str, **kwargs):
    """Child span under a Langfuse client or span; yields None when parent is None."""
    if parent is None:
        yield None
        return
    s = parent.start_observation(name=name, **kwargs)
    try:
        yield s
    finally:
        s.end()
