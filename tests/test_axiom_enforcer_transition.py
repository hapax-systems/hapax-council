"""OFF→ON transition coverage for runtime axiom output enforcement."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agents import briefing, digest
from shared import axiom_enforcer
from shared.axiom_pattern_checker import reload_patterns


@pytest.mark.parametrize(
    ("agent_id", "output_path"),
    [
        ("briefing", briefing.BRIEFING_FILE),
        ("digest", digest.DIGEST_MD_FILE),
    ],
)
def test_axiom_enforcer_env_off_then_on_for_agent_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    agent_id: str,
    output_path: Path,
) -> None:
    seeded_t0 = "I suggest you tell Alex that his communication needs work."
    audit_log = tmp_path / "audit.jsonl"
    quarantine_dir = tmp_path / "quarantine"

    # Defeat module-level _cached_patterns pollution from other tests
    # (e.g. test_output_enforcement.py patches load_patterns to return
    # synthetic pattern sets). Without this reload, CI ordering can leave
    # the cache populated with patterns that don't match seeded_t0,
    # causing check_output() to return [] and the off-mode assertion to
    # fail with audit_only=False.
    reload_patterns()

    with (
        patch("shared.axiom_enforcer.AUDIT_LOG", audit_log),
        patch("shared.axiom_enforcer.QUARANTINE_DIR", quarantine_dir),
    ):
        # block_enabled kwarg path is deterministic; env-var path was
        # subject to AXIOM_ENFORCE_BLOCK pollution (~30% flake rate
        # observed on alpha PRs #2113 + #2143). cc-task:
        # stabilize-axiom-enforcer-transition-flake.
        off_result = axiom_enforcer.enforce_output(
            seeded_t0, agent_id, output_path, block_enabled=False
        )
        on_result = axiom_enforcer.enforce_output(
            seeded_t0, agent_id, output_path, block_enabled=True
        )

    assert off_result.allowed is True
    assert off_result.audit_only is True
    assert on_result.allowed is False
    assert on_result.quarantine_path is not None
    assert on_result.quarantine_path.exists()
    assert agent_id in on_result.quarantine_path.name

    entries = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines()]
    assert [entry["agent_id"] for entry in entries] == [agent_id, agent_id]
    assert entries[0]["allowed"] is True
    assert entries[0]["audit_only"] is True
    assert entries[1]["allowed"] is False
    assert entries[1]["audit_only"] is False
