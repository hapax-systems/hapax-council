"""Contract tests for AVSDLC witness tactic requirements."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_CASE = REPO_ROOT / "docs" / "methodology" / "avsdlc-authority-case.md"
VISUAL_CONTRACT = REPO_ROOT / "docs" / "methodology" / "avsdlc-visual-evidence-contract.md"
AUDIO_CONTRACT = REPO_ROOT / "docs" / "methodology" / "avsdlc-audio-evidence-contract.md"


def _body(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _plain(path: Path) -> str:
    return " ".join(_body(path).split())


def test_visual_contract_requires_multipov_duration_witness_tactics() -> None:
    body = _plain(VISUAL_CONTRACT)

    assert "#### Universal Witness Tactics Requirement" in body
    assert "every visual witness" in body
    assert "at least two independent POVs" in body
    assert "audience-facing or user-facing" in body
    assert "producer-facing, diagnostic, upstream, or geometry-alternate" in body
    assert "Duration window" in body
    assert "repeated samples over time, not a single frame" in body
    assert "omitted POV or shortened duration window" in body


def test_audio_contract_requires_route_measurement_output_duration_povs() -> None:
    body = _plain(AUDIO_CONTRACT)

    assert "#### Audio Witness Tactics Requirement" in body
    assert "every audio witness" in body
    assert "Route/config POV" in body
    assert "Measurement POV" in body
    assert "Audible/output POV" in body
    assert "Broadcast-path work must include the egress or monitor feed" in body
    assert "Duration window" in body
    assert "before, during, and after the event" in body


def test_authority_case_blocks_release_without_witness_tactics() -> None:
    body = _plain(AUTHORITY_CASE)

    assert "**Witness tactics:** every visual, audio, or audiovisual evidence item" in body
    assert "At least two independent POVs are required" in body
    assert "single-POV evidence is acceptable only when the dossier proves" in body
    assert "Witness tactics omit required POV coverage" in body
    assert "a witness tactics declaration in the dossier" in body
    assert "cross-modal POV coverage" in body
    assert "collected over a declared duration window" in body
