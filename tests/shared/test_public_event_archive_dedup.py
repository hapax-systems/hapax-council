"""Archive-aware idempotency checks for public-event writers."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from agents.broadcast_boundary_public_event_producer import _load_event_ids as load_broadcast_ids
from agents.chronicle_high_salience_public_event_producer import (
    _load_event_ids as load_chronicle_ids,
)
from agents.governance_enforcement_public_event_producer import (
    _load_event_ids as load_governance_ids,
)
from agents.publish_orchestrator.orchestrator import (
    _load_public_event_ids as load_orchestrator_ids,
)
from agents.weblog_publish_public_event_producer import _load_event_ids as load_weblog_ids
from shared.conversion_broker import _load_public_event_ids as load_conversion_ids


def _line(event_id: str) -> str:
    return json.dumps({"event_id": event_id, "event_type": "fixture"}) + "\n"


def test_public_event_id_loaders_include_rotated_archives(tmp_path: Path) -> None:
    live_path = tmp_path / "events.jsonl"
    archive_dir = tmp_path / "archive"

    live_path.write_text(_line("live-id"), encoding="utf-8")
    archive_dir.mkdir()
    with gzip.open(
        archive_dir / "public-events.2026-06-12.jsonl.gz",
        "wt",
        encoding="utf-8",
    ) as fh:
        fh.write(_line("archived-id"))

    expected = {"archived-id", "live-id"}
    assert load_broadcast_ids(live_path) == expected
    assert load_chronicle_ids(live_path) == expected
    assert load_governance_ids(live_path) == expected
    assert load_weblog_ids(live_path) == expected
    assert load_orchestrator_ids(live_path) == expected
    assert load_conversion_ids(live_path) == expected
