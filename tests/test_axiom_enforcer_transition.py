"""OFF→ON transition coverage for runtime axiom output enforcement."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agents import briefing, digest
from shared import axiom_enforcer
from shared.axiom_pattern_checker import reload_patterns


@pytest.fixture(autouse=True)
def _reset_pattern_cache() -> None:
    """Clear the module-level pattern cache before each test.

    ``shared.axiom_pattern_checker`` caches the loaded pattern set in a
    module-level ``_cached_patterns`` global. Other test files
    (``tests/shared/test_axiom_pattern_checker.py``) seed that cache
    with fixture patterns via ``load_patterns(path=tmp_path/"...")``;
    when those run before this file in the same pytest process, the
    enforcer's ``check_output()`` reuses the test-fixture cache instead
    of the canonical ``axioms/enforcement-patterns.yaml``, producing
    zero violations on the seeded T0 string and tripping the
    ``audit_only is True`` assertion.

    Resetting the cache before each test forces ``load_patterns()`` to
    re-read the canonical file. cc-task:
    stabilize-axiom-enforcer-transition-flake.
    """
    reload_patterns()


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

    with (
        patch("shared.axiom_enforcer.AUDIT_LOG", audit_log),
        patch("shared.axiom_enforcer.QUARANTINE_DIR", quarantine_dir),
    ):
        # Pass block_enabled explicitly via kwarg instead of monkeypatching
        # AXIOM_ENFORCE_BLOCK env var. The kwarg path is deterministic; the
        # env-var path was subject to cross-test pollution (~30% flake rate
        # observed across alpha PRs #2113 + #2143). enforce_output() already
        # accepts block_enabled as a keyword override — this test now uses
        # that contract instead of relying on env-var ordering.
        # cc-task: stabilize-axiom-enforcer-transition-flake
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
