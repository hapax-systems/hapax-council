"""Regression pins for the deferred ytb-SS3 continuity contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-05-11-ytb-ss3-long-arc-narrative-continuity-design.md"
)


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _frame_example() -> dict[str, object]:
    body = _body()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example LongArcContinuityFrame JSON block missing"
    return json.loads(match.group("payload"))


def test_spec_records_current_blockers_and_dependency_state() -> None:
    body = _body()

    for phrase in (
        "Status: deferred design / blocked execution",
        "`wsjf-008` is satisfied",
        "`ytb-SS2` is not complete",
        "`SS2_DONE` as a required hard gate",
        "no YouTube write",
    ):
        assert phrase in body


def test_continuity_boundaries_forbid_private_or_person_keyed_state() -> None:
    body = _body().lower()

    for phrase in (
        "no persistent state keyed by non-operator persons",
        "no raw qm5 text",
        "no durable memory of consent-sensitive facts about non-operator persons",
        "private sentinel phrases",
        "secret names",
        "no youtube writes",
    ):
        assert phrase in body


def test_allowed_state_is_limited_to_public_safe_summaries() -> None:
    body = _body().lower()

    for phrase in (
        "programme id",
        "autonomous narration triad ids",
        "ytb-ss2 cycle-level summaries",
        "aggregate chat or ambient statistics without viewer identity",
        "world-capability-surface references",
        "operator-authored public episode themes",
    ):
        assert phrase in body


def test_example_frame_fails_closed_until_ss2_is_done() -> None:
    frame = _frame_example()

    assert frame["schema_version"] == 1
    assert frame["status"] == "blocked"
    assert frame["required_gate"] == "SS2_DONE"
    assert frame["public_claim_allowed"] is False
    assert frame["youtube_writes_allowed"] is False
    assert "raw_qm5_text" in frame["forbidden_continuity"]
    assert "private_sentinel_phrase" in frame["forbidden_continuity"]
    assert "non_operator_person_key" in frame["forbidden_continuity"]
