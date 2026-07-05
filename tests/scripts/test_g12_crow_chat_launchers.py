from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_mutating_launchers_call_g12_crow_chat_gate() -> None:
    for rel in (
        "scripts/hapax-codex",
        "scripts/hapax-codex-headless",
        "scripts/hapax-claude",
        "scripts/hapax-claude-headless",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "shared.g12_crow_chat_gate" in text, rel
        assert "require_g12_crow_chat_attestation" in text, rel
