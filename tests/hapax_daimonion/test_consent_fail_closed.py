"""Regression pins for BETA-FINDING-K: consent-gate fail-closed behavior.

PR #756 (queue 024 Phase 0) caught a live ``interpersonal_transparency``
axiom violation: a malformed contract file (``contract--2026-03-23.yaml``
with ``parties: [operator, ""]`` and ``scope: []``) raised from
``ConsentRegistry.load_all()``; the caller in ``init_pipeline.py``
silently caught the exception, set ``_precomputed_consent_reader`` to
``None``, and ``conversation_pipeline._handle_tool_calls`` then fell
through without filtering. Tool results reached the LLM unfiltered —
a direct axiom-88 violation.

The fix is two-tiered:

1. ``init_pipeline.precompute_pipeline_deps`` raises on
   ``ConsentGatedReader.create()`` failure so the daemon refuses to
   start rather than degrading silently.
2. ``conversation_pipeline._handle_tool_calls`` redacts the tool
   result if the reader is ``None`` at runtime (belt-and-suspenders
   for any future regression that re-introduces the silent catch),
   and redacts on filter exception as well.

These tests pin both behaviors.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_init_pipeline_raises_on_reader_construction_failure() -> None:
    """``precompute_pipeline_deps`` must NOT silently catch a
    ConsentGatedReader construction error. The daemon should refuse
    to start so the operator sees the malformed-contract failure
    instead of a silent axiom violation.
    """
    from agents.hapax_daimonion import init_pipeline

    fake_daemon = MagicMock()
    fake_daemon.cfg.tools_enabled = False
    # Block every downstream branch except the consent reader section —
    # the test only cares about the consent-init fail-closed behavior.
    with (
        patch(
            "agents.hapax_daimonion.tool_definitions.build_registry",
            return_value=MagicMock(),
        ),
        patch(
            "agents._consent_reader.ConsentGatedReader.create",
            side_effect=RuntimeError("malformed contract"),
        ),
        pytest.raises(RuntimeError, match="malformed contract"),
    ):
        init_pipeline.precompute_pipeline_deps(fake_daemon)


def test_handle_tool_calls_redacts_when_consent_reader_is_none() -> None:
    """The runtime path in ``_handle_tool_calls`` must redact the
    tool result (not pass it through) if the reader is ``None`` for
    any reason. Defense in depth for BETA-FINDING-K.
    """
    from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline

    source = _load_conversation_pipeline_source()

    # The conversation_pipeline module is ~2 kLoC with many dependency
    # imports that make instantiating a full ConversationPipeline in a
    # unit test non-trivial. Instead of running the whole turn, pin
    # the fail-closed branch at the source level: the guard must be
    # present, must redact on ``None``, and must not fall through.
    guard_start = "if self._consent_reader is None:"
    guard_idx = source.find(guard_start)
    assert guard_idx >= 0, "conversation_pipeline must guard against _consent_reader being None"
    block = source[guard_idx : guard_idx + 600]
    assert "consent_gate_unavailable" in block, (
        "None-reader branch must redact with a consent_gate_unavailable error, "
        "not pass the tool result through unfiltered"
    )
    assert ConversationPipeline is not None  # import smoke check


def test_handle_tool_calls_redacts_on_filter_exception() -> None:
    """``filter_tool_result`` raising must redact the tool result,
    not pass the raw result through. Source-level pin matching the
    None-reader test pattern.
    """
    source = _load_conversation_pipeline_source()
    except_idx = source.find("Consent filtering raised for")
    assert except_idx >= 0, (
        "conversation_pipeline must log a warning when filter_tool_result raises"
    )
    tail = source[except_idx : except_idx + 400]
    assert "consent_filter_failed" in tail, (
        "filter-exception branch must redact with consent_filter_failed, not "
        "pass the raw result through unfiltered"
    )


def test_malformed_consent_contract_file_is_absent() -> None:
    """Regression pin: ``contract--2026-03-23.yaml`` was the specific
    file that triggered the live axiom violation on 2026-04-13. It
    was deleted in the BETA-FINDING-K fix. A future committer adding
    a similarly malformed file would re-trigger the violation; this
    test pins the absence.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    malformed = repo_root / "axioms" / "contracts" / "contract--2026-03-23.yaml"
    assert not malformed.exists(), (
        "contract--2026-03-23.yaml was deleted in the BETA-FINDING-K fix "
        "because it had parties: [operator, ''] and scope: [] which raises "
        "from ConsentRegistry.load_all. If you need to restore a contract "
        "for the same date, give it a non-empty party and scope."
    )


def _load_conversation_pipeline_source() -> str:
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "agents"
        / "hapax_daimonion"
        / "conversation_pipeline.py"
    )
    return path.read_text(encoding="utf-8")


def test_json_import_still_present_in_conversation_pipeline() -> None:
    """The redacted payload uses ``json.dumps`` — pin the import so a
    future cleanup sweep doesn't accidentally delete it and turn the
    fail-closed branch into a NameError (which would crash the turn
    rather than redacting, still correct but noisy).
    """
    source = _load_conversation_pipeline_source()
    assert "import json" in source, (
        "conversation_pipeline.py must import json for the consent fail-closed redacted payload"
    )
