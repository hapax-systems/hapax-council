"""Alpha marathon retirement handoff regression pin.

Pins the existence + required sections of the 2026-04-14 alpha marathon
retirement handoff doc. The next alpha session reads this handoff after
relay onboarding; if the file is moved, renamed, or accidentally pruned,
this test fails so the pickup procedure stays intact.

The pin is lightweight (exists + has required sections) rather than
content-exact so routine edits don't force test updates.
"""

from __future__ import annotations

from pathlib import Path

HANDOFF_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "superpowers"
    / "handoff"
    / "2026-04-14-alpha-marathon-retirement.md"
)

REQUIRED_SECTIONS: tuple[str, ...] = (
    "## What happened",
    "## PR manifest",
    "## LRR epic state at retirement",
    "## Known blockers carried forward",
    "## Beta drops queued",
    "## Hardware milestone pending",
    "## Operator decisions recorded this session",
    "## Recommended Phase 2 pickup procedure",
)


class TestAlphaMarathonRetirementHandoff:
    def test_handoff_file_exists(self) -> None:
        assert HANDOFF_PATH.is_file(), (
            f"Alpha marathon retirement handoff missing at {HANDOFF_PATH}. "
            "The next alpha session depends on this file for Phase 2 pickup."
        )

    def test_handoff_has_required_sections(self) -> None:
        body = HANDOFF_PATH.read_text(encoding="utf-8")
        missing = [s for s in REQUIRED_SECTIONS if s not in body]
        assert not missing, f"Handoff missing required sections: {missing}"

    def test_handoff_cites_phase_1_close_handoff(self) -> None:
        body = HANDOFF_PATH.read_text(encoding="utf-8")
        assert "2026-04-14-lrr-phase-1-complete.md" in body, (
            "Retirement handoff must cite the Phase 1 close handoff "
            "so the next session has a complete pickup chain."
        )

    def test_handoff_pins_lrr_state_fields(self) -> None:
        body = HANDOFF_PATH.read_text(encoding="utf-8")
        assert "`current_phase`" in body and "`completed_phases`" in body, (
            "Retirement handoff must document the LRR state fields the "
            "next session will check when claiming Phase 2."
        )
