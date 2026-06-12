"""Pins for the platform session contract v1 spec."""

from __future__ import annotations

from pathlib import Path

from shared.platform_session_contract import CONTRACT_EVENT_KINDS

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "docs" / "specs" / "platform-session-contract-v1-20260612.md"


def test_platform_session_contract_spec_covers_required_sections() -> None:
    body = SPEC.read_text(encoding="utf-8")

    for heading in (
        "## Scope",
        "## Lifecycle",
        "## Event Stream",
        "## Control Channel",
        "## MCP Surface",
        "## Adapter Shims",
        "## Conformance Fixtures",
        "## Honest Rejection",
    ):
        assert heading in body


def test_spec_pins_closed_event_kind_enum() -> None:
    body = SPEC.read_text(encoding="utf-8")

    for kind in CONTRACT_EVENT_KINDS:
        assert f"`{kind}`" in body
    assert "`thought_blob`" not in body


def test_spec_enumerates_codex_divergences_and_shims() -> None:
    body = SPEC.read_text(encoding="utf-8")

    for phrase in (
        "FIFO carrying Claude stdin-json",
        "Codex tmux-buffer text",
        "role resolution",
        "dispatch flags",
        "output formats",
        "relay-exclusion visibility",
    ):
        assert phrase in body
