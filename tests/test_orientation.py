"""Tests for the orientation collector — deterministic assembly of per-domain state."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from logos.data.orientation import (
    OrientationState,
    SprintSummary,
    collect_orientation,
)
from logos.data.session_inference import SessionContext
from logos.data.vault_goals import VaultGoal


def _goal(
    id: str = "g1",
    domain: str = "research",
    status: str = "active",
    priority: str = "P1",
    stale: bool = False,
    progress: float | None = None,
) -> VaultGoal:
    return VaultGoal(
        id=id,
        title=f"Goal {id}",
        domain=domain,
        status=status,
        priority=priority,
        started_at=None,
        target_date=None,
        sprint_measures=[],
        depends_on=[],
        tags=[],
        file_path=Path(f"/vault/{id}.md"),
        last_modified=datetime.now(UTC),
        stale=stale,
        progress=progress,
        obsidian_uri=f"obsidian://open?vault=Personal&file={id}",
    )


def _session(
    last_domain: str = "research",
    absence: float = 0.5,
    boundary: bool = False,
) -> SessionContext:
    return SessionContext(
        last_active_domain=last_domain,
        absence_hours=absence,
        session_boundary=boundary,
        domain_recency={"research": 1.0, "studio": 2.0},
    )


_PATCH_PREFIX = "logos.data.orientation"

# Default mocks that every test applies.
_DEFAULT_PATCHES = {
    f"{_PATCH_PREFIX}._load_domain_registry": lambda: {
        "research": {"staleness_days": 7, "apis": {"sprint": "/api/sprint"}, "telemetry": {}},
        "studio": {"staleness_days": 14, "apis": {}, "telemetry": {}},
    },
    f"{_PATCH_PREFIX}.collect_vault_goals": lambda **kw: [],
    f"{_PATCH_PREFIX}.infer_session": lambda **kw: _session(),
    f"{_PATCH_PREFIX}._get_sprint_summary": lambda: None,
    f"{_PATCH_PREFIX}._sprint_measure_statuses": lambda: {},
    f"{_PATCH_PREFIX}._get_stimmung_stance": lambda: "nominal",
    f"{_PATCH_PREFIX}._get_briefing": lambda: (None, None),
    f"{_PATCH_PREFIX}._get_health_summary": lambda: ("ok", 0),
}


def _apply_patches(overrides: dict | None = None):
    """Return a list of started mock patchers."""
    targets = {**_DEFAULT_PATCHES, **(overrides or {})}
    patchers = []
    for target, side_effect in targets.items():
        p = patch(target, side_effect=side_effect)
        patchers.append(p)
    return patchers


def _run_with(overrides: dict | None = None) -> OrientationState:
    patchers = _apply_patches(overrides)
    for p in patchers:
        p.start()
    try:
        return collect_orientation()
    finally:
        for p in patchers:
            p.stop()


class TestBasicAssembly:
    def test_single_domain_one_goal(self):
        result = _run_with(
            {
                f"{_PATCH_PREFIX}._load_domain_registry": lambda: {
                    "research": {
                        "staleness_days": 7,
                        "apis": {"sprint": "/api/sprint"},
                        "telemetry": {},
                    },
                },
                f"{_PATCH_PREFIX}.collect_vault_goals": lambda **kw: [
                    _goal("g1", "research", "active", "P1"),
                ],
            }
        )
        assert isinstance(result, OrientationState)
        assert len(result.domains) == 1
        ds = result.domains[0]
        assert ds.domain == "research"
        assert ds.goal_count == 1
        assert ds.top_goal is not None
        assert ds.top_goal.id == "g1"


class TestDomainSorting:
    def test_sorted_by_recency(self):
        result = _run_with(
            {
                f"{_PATCH_PREFIX}.infer_session": lambda **kw: SessionContext(
                    last_active_domain="studio",
                    absence_hours=0.5,
                    session_boundary=False,
                    domain_recency={"studio": 0.5, "research": 3.0},
                ),
            }
        )
        assert len(result.domains) == 2
        assert result.domains[0].domain == "studio"
        assert result.domains[1].domain == "research"

    def test_blocked_domain_ranks_highest(self):
        result = _run_with(
            {
                f"{_PATCH_PREFIX}.infer_session": lambda **kw: SessionContext(
                    last_active_domain="studio",
                    absence_hours=0.5,
                    session_boundary=False,
                    domain_recency={"studio": 0.5, "research": 3.0},
                ),
                f"{_PATCH_PREFIX}._get_sprint_summary": lambda: SprintSummary(
                    current_sprint=1,
                    measures_completed=2,
                    measures_total=5,
                    blocking_gate="G1",
                ),
                f"{_PATCH_PREFIX}.collect_vault_goals": lambda **kw: [
                    _goal("g1", "research", "active", "P0"),
                ],
            }
        )
        assert result.domains[0].domain == "research"
        assert result.domains[0].health == "blocked"

    def test_stale_p0_ranks_high(self):
        result = _run_with(
            {
                f"{_PATCH_PREFIX}.infer_session": lambda **kw: SessionContext(
                    last_active_domain="studio",
                    absence_hours=0.5,
                    session_boundary=False,
                    domain_recency={"studio": 0.5, "research": 3.0},
                ),
                f"{_PATCH_PREFIX}.collect_vault_goals": lambda **kw: [
                    _goal("g1", "research", "active", "P0", stale=True),
                ],
            }
        )
        assert result.domains[0].domain == "research"


class TestNarrative:
    def test_no_narrative_steady_state(self):
        result = _run_with(
            {
                f"{_PATCH_PREFIX}.infer_session": lambda **kw: SessionContext(
                    last_active_domain="research",
                    absence_hours=0.5,
                    session_boundary=False,
                    domain_recency={"research": 1.0},
                ),
            }
        )
        assert result.narrative is None


class TestEmptyRegistry:
    def test_empty_registry_returns_empty_domains(self):
        result = _run_with(
            {
                f"{_PATCH_PREFIX}._load_domain_registry": lambda: {},
            }
        )
        assert result.domains == []


import pytest

from logos.data import orientation as orient


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_get_sprint_summary_non_dict_returns_none(tmp_path, payload, kind, monkeypatch):
    """Pin _get_sprint_summary against non-dict JSON. The chained
    data.get() calls inside (OSError, JSONDecodeError) catch let
    AttributeError escape on non-dict roots."""
    sprint_path = tmp_path / "sprint.json"
    sprint_path.write_text(payload)
    with patch("logos.data.orientation.Path") as MockPath:
        MockPath.return_value = sprint_path
        result = orient._get_sprint_summary()
    assert result is None, f"non-dict root={kind} must yield None"


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_sprint_measure_statuses_non_dict_returns_empty(tmp_path, payload, kind):
    """Pin _sprint_measure_statuses against non-dict JSON."""
    sprint_path = tmp_path / "sprint.json"
    sprint_path.write_text(payload)
    with patch("logos.data.orientation.Path") as MockPath:
        MockPath.return_value = sprint_path
        result = orient._sprint_measure_statuses()
    assert result == {}, f"non-dict root={kind} must yield empty dict"


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_get_stimmung_stance_non_dict_returns_nominal(tmp_path, payload, kind):
    """Pin _get_stimmung_stance against non-dict JSON."""
    stimmung_path = tmp_path / "stimmung.json"
    stimmung_path.write_text(payload)
    with patch("logos.data.orientation.Path") as MockPath:
        MockPath.return_value = stimmung_path
        result = orient._get_stimmung_stance()
    assert result == "nominal", f"non-dict root={kind} must yield default"
