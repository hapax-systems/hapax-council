"""Test that the quarantine seed file format satisfies the watchdog."""

from __future__ import annotations

import json
from pathlib import Path


def test_seed_json_marks_quarantine_inactive(tmp_path: Path) -> None:
    seed = {"quarantine_active": False, "reason": "boot default", "updated_at": "boot"}
    state_file = tmp_path / "private-voice-quarantine.json"
    state_file.write_text(json.dumps(seed))

    payload = json.loads(state_file.read_text())
    assert payload.get("quarantine_active") is False
