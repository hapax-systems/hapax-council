"""Alpha continuation retirement handoff pin (2026-04-14).

Pins existence + required sections of the continuation retirement
handoff doc so it can't be silently renamed or pruned. Modeled on
tests/test_retirement_handoff_pin.py from the prior marathon
retirement.
"""

from __future__ import annotations

from pathlib import Path

HANDOFF_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "superpowers"
    / "handoff"
    / "2026-04-14-alpha-continuation-retirement.md"
)

REQUIRED_SECTIONS: tuple[str, ...] = (
    "## Start state",
    "## What shipped this continuation",
    "## Beta drops this continuation",
    "## Delta drops this continuation",
    "## LRR state at retirement",
    "## Recommended next pickup",
    "## Known carry-overs",
    "## Hardware milestone pending",
    "## Final sanity checks",
)


class TestContinuationRetirementHandoff:
    def test_handoff_file_exists(self) -> None:
        assert HANDOFF_PATH.is_file(), f"Continuation retirement handoff missing at {HANDOFF_PATH}."

    def test_handoff_has_required_sections(self) -> None:
        body = HANDOFF_PATH.read_text(encoding="utf-8")
        missing = [s for s in REQUIRED_SECTIONS if s not in body]
        assert not missing, f"Continuation retirement handoff missing sections: {missing}"

    def test_handoff_documents_all_three_merged_prs(self) -> None:
        body = HANDOFF_PATH.read_text(encoding="utf-8")
        assert "#797" in body
        assert "#798" in body
        assert "#799" in body

    def test_handoff_cites_lrr_completed_phases(self) -> None:
        body = HANDOFF_PATH.read_text(encoding="utf-8")
        assert "`[0, 1, 2, 9]`" in body or "[0,1,2,9]" in body

    def test_handoff_links_to_prior_retirement_handoff(self) -> None:
        """The prior marathon retirement handoff is cited for continuity."""
        body = HANDOFF_PATH.read_text(encoding="utf-8")
        assert "marathon retirement" in body.lower()
        assert "2026-04-14" in body
