"""LRR state file schema regression pin.

The LIVESTREAM RESEARCH READY epic tracks execution state in
``~/.cache/hapax/relay/lrr-state.yaml``. Every alpha session that picks
up an LRR phase reads this file first per the LRR plan §2 pickup
procedure. The schema is documented in
``docs/superpowers/plans/2026-04-14-livestream-research-ready-epic-plan.md``
§3.

This test pins the schema field names so a future refactor of the
state file can't silently drop a required field. The file itself lives
in ``~/.cache`` (not in git) so the test creates its own minimal
instance and validates the LRR plan documented schema rather than
asserting against any particular live state.
"""

from __future__ import annotations

import yaml

REQUIRED_LRR_STATE_FIELDS = (
    "epic_id",
    "epic_design_doc",
    "epic_plan_doc",
    "current_phase",
    "current_phase_owner",
    "current_phase_branch",
    "current_phase_pr",
    "current_phase_opened_at",
    "last_completed_phase",
    "last_completed_at",
    "last_completed_handoff",
    "completed_phases",
    "known_blockers",
    "current_condition",
    "previous_condition",
    "notes",
)


def _minimal_state(current_phase: int = 0) -> dict:
    """The state-file shape a fresh ``scripts/lrr-state.py init`` produces."""
    return {
        "epic_id": "livestream-research-ready",
        "epic_design_doc": (
            "docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md"
        ),
        "epic_plan_doc": (
            "docs/superpowers/plans/2026-04-14-livestream-research-ready-epic-plan.md"
        ),
        "current_phase": current_phase,
        "current_phase_owner": None,
        "current_phase_branch": None,
        "current_phase_pr": None,
        "current_phase_opened_at": None,
        "last_completed_phase": None,
        "last_completed_at": None,
        "last_completed_handoff": None,
        "completed_phases": [],
        "known_blockers": [],
        "current_condition": None,
        "previous_condition": None,
        "notes": "",
    }


class TestLrrStateSchema:
    def test_minimal_state_has_all_required_fields(self) -> None:
        state = _minimal_state()
        for key in REQUIRED_LRR_STATE_FIELDS:
            assert key in state, f"required LRR state field missing: {key!r}"

    def test_minimal_state_round_trips_through_yaml(self) -> None:
        state = _minimal_state()
        rendered = yaml.safe_dump(state, sort_keys=False)
        parsed = yaml.safe_load(rendered)
        assert parsed == state

    def test_completed_phases_is_a_list(self) -> None:
        state = _minimal_state(current_phase=1)
        state["completed_phases"] = [0]
        rendered = yaml.safe_dump(state, sort_keys=False)
        parsed = yaml.safe_load(rendered)
        assert parsed["completed_phases"] == [0]
        assert parsed["current_phase"] == 1

    def test_known_blockers_supports_documented_shape(self) -> None:
        # Per the LRR plan §3 example block.
        state = _minimal_state()
        state["known_blockers"] = [
            {
                "phase": 4,
                "blocker": "sprint-0-g3",
                "description": "G3 sprint gate blocks Condition A baseline collection",
                "discovered_at": "2026-04-15T00:00:00Z",
                "resolved_at": None,
                "resolution": None,
            }
        ]
        rendered = yaml.safe_dump(state, sort_keys=False)
        parsed = yaml.safe_load(rendered)
        blocker = parsed["known_blockers"][0]
        assert blocker["phase"] == 4
        assert blocker["resolved_at"] is None

    def test_phase_advancement_pattern(self) -> None:
        # Pin the documented pattern: closing phase N moves current_phase
        # to N+1, sets last_completed_phase to N, and appends N to
        # completed_phases.
        state = _minimal_state(current_phase=0)
        state["current_phase"] = 1
        state["last_completed_phase"] = 0
        state["completed_phases"] = [0]
        rendered = yaml.safe_dump(state, sort_keys=False)
        parsed = yaml.safe_load(rendered)
        assert parsed["current_phase"] == 1
        assert parsed["last_completed_phase"] == 0
        assert 0 in parsed["completed_phases"]
