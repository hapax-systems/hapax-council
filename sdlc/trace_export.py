"""File-based Langfuse trace export for CI environments.

When ``LANGFUSE_EXPORT_FILE`` is set, traces are written to a JSONL file
instead of being sent over HTTP.  This is used in GitHub Actions where
the self-hosted Langfuse instance is unreachable.

Usage in CI::

    export LANGFUSE_EXPORT_FILE=/tmp/langfuse-traces.jsonl
    python -m scripts.sdlc_triage --issue-number 42
    # Traces are now in /tmp/langfuse-traces.jsonl

Import back into Langfuse later with::

    python scripts/import_langfuse_traces.py /tmp/langfuse-traces.jsonl
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

EXPORT_FILE = os.environ.get("LANGFUSE_EXPORT_FILE", "")


@dataclass
class TraceSpan:
    """A single span within a trace."""

    name: str
    trace_id: str
    span_id: str = ""
    parent_span_id: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    model: str = ""
    input_text: str = ""
    output_text: str = ""
    cost_usd: float = 0.0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.span_id:
            self.span_id = f"{self.trace_id}-{self.name}-{id(self)}"
        if not self.start_time:
            self.start_time = time.time()


def _write_span(span: TraceSpan) -> None:
    """Append a span to the export file."""
    if not EXPORT_FILE:
        return
    path = Path(EXPORT_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(span), default=str) + "\n")


class TraceContext:
    """Context manager for trace spans, with file export in CI."""

    def __init__(self, name: str, trace_id: str, **metadata: object) -> None:
        self.span = TraceSpan(
            name=name,
            trace_id=trace_id,
            metadata=dict(metadata),
        )

    def __enter__(self) -> TraceSpan:
        self.span.start_time = time.time()
        return self.span

    def __exit__(self, *_: object) -> None:
        self.span.end_time = time.time()
        _write_span(self.span)


def is_file_export() -> bool:
    """Return True if traces should go to a file (CI mode)."""
    return bool(EXPORT_FILE)
