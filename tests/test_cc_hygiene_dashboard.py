"""Tests for cc-hygiene dashboard renderer (PR5 surface B).

Per project convention, no shared conftest fixtures — each test builds its
own dashboard + state under ``tmp_path``. The renderer NEVER touches the
operator's live vault during tests; everything is fixture-scoped.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Make the script-side package importable.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cc_hygiene.dashboard import (  # noqa: E402
    SENTINEL_END,
    SENTINEL_START,
    render_block,
    update_dashboard,
)
from cc_hygiene.events import append_events  # noqa: E402
from cc_hygiene.models import (  # noqa: E402
    CheckSummary,
    HygieneEvent,
    HygieneState,
    SessionState,
)


def _now() -> datetime:
    return datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)


def _build_state(*, sessions: list[SessionState] | None = None) -> HygieneState:
    return HygieneState(
        sweep_timestamp=_now(),
        sweep_duration_ms=42,
        sessions=sessions
        or [
            SessionState(role="alpha", current_claim="cc-alpha-task", in_progress_count=1),
            SessionState(role="beta", current_claim=None, in_progress_count=0),
            SessionState(role="delta", current_claim=None, in_progress_count=2),
            SessionState(role="epsilon", current_claim=None, in_progress_count=0),
        ],
        check_summaries=[
            CheckSummary(check_id="ghost_claimed", fired=2),
            CheckSummary(check_id="duplicate_claim", fired=0),
            CheckSummary(check_id="stale_in_progress", fired=0),
            CheckSummary(check_id="orphan_pr", fired=0),
            CheckSummary(check_id="relay_yaml_stale", fired=0),
            CheckSummary(check_id="wip_limit", fired=0),
            CheckSummary(check_id="offered_stale", fired=0),
            CheckSummary(check_id="refusal_dormancy", fired=0),
        ],
        events=[],
    )


def _build_event_log(path: Path, events: list[HygieneEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    append_events(events, _now(), path=path)


# ----------------------------------------------------------------------------
# render_block — pure formatting
# ----------------------------------------------------------------------------


def test_render_block_has_sentinels(tmp_path: Path) -> None:
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    active = tmp_path / "active"
    active.mkdir()
    block = render_block(state, event_log_path=event_log, vault_active=active, now=_now())
    assert block.startswith(SENTINEL_START)
    assert block.rstrip().endswith(SENTINEL_END)


def test_render_block_includes_three_sections(tmp_path: Path) -> None:
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    active = tmp_path / "active"
    active.mkdir()
    block = render_block(state, event_log_path=event_log, vault_active=active, now=_now())
    assert "## Live Sessions" in block
    assert "## Recent Hygiene Events" in block
    assert "## Counters" in block


def test_render_block_lists_all_four_roles(tmp_path: Path) -> None:
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    active = tmp_path / "active"
    active.mkdir()
    block = render_block(state, event_log_path=event_log, vault_active=active, now=_now())
    for role in ("alpha", "beta", "delta", "epsilon"):
        assert f"| {role} |" in block


def test_render_block_includes_current_claim(tmp_path: Path) -> None:
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    active = tmp_path / "active"
    active.mkdir()
    block = render_block(state, event_log_path=event_log, vault_active=active, now=_now())
    assert "cc-alpha-task" in block


def test_render_block_uses_native_markdown_tables(tmp_path: Path) -> None:
    """Acceptance criterion: native markdown only, no Dataview-only constructs."""
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    active = tmp_path / "active"
    active.mkdir()
    block = render_block(state, event_log_path=event_log, vault_active=active, now=_now())
    assert "```dataview" not in block
    # standard pipe-row markdown tables present
    assert block.count("|") > 30
    assert "|------|" in block or "|-----|" in block or "|---|" in block


def test_render_block_event_tail_renders(tmp_path: Path) -> None:
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    events = [
        HygieneEvent(
            timestamp=_now(),
            check_id="duplicate_claim",
            severity="violation",
            task_id="cc-task-DUPE",
            message="claimed twice",
        )
    ]
    _build_event_log(event_log, events)
    active = tmp_path / "active"
    active.mkdir()
    block = render_block(state, event_log_path=event_log, vault_active=active, now=_now())
    assert "duplicate_claim" in block
    assert "cc-task-DUPE" in block


def test_render_block_counters_uses_vault_active_dir(tmp_path: Path) -> None:
    """Status counts come from parsing vault active/ — fixture vault."""
    active = tmp_path / "active"
    active.mkdir()
    (active / "cc-1.md").write_text(
        '---\ntype: cc-task\ntask_id: "cc-1"\nstatus: "offered"\n---\nbody\n',
        encoding="utf-8",
    )
    (active / "cc-2.md").write_text(
        '---\ntype: cc-task\ntask_id: "cc-2"\nstatus: "in_progress"\n'
        'assigned_to: "alpha"\n---\nbody\n',
        encoding="utf-8",
    )
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    block = render_block(state, event_log_path=event_log, vault_active=active, now=_now())
    # Counter row ordering: offered | claimed | in_progress | pr_open | done | other
    # We expect 1 offered + 1 in_progress
    assert "| 1 | 0 | 1 | 0 | 0 | 0 |" in block


# ----------------------------------------------------------------------------
# update_dashboard — additive sentinel block
# ----------------------------------------------------------------------------


_EXISTING_DASHBOARD = """# CC — Active Tasks

> All Claude Code work currently in flight, across every session.

## In progress (by role)

```dataview
TABLE WITHOUT ID
  file.link as "Task",
  assigned_to as "Role"
FROM "20-projects/hapax-cc-tasks/active"
WHERE type = "cc-task" AND status = "in_progress"
SORT priority DESC, wsjf DESC
```

## Operator hand-edited section

A note from the operator that must be preserved.
"""


def test_update_dashboard_creates_block_when_sentinels_absent(tmp_path: Path) -> None:
    dashboard = tmp_path / "cc-active.md"
    dashboard.write_text(_EXISTING_DASHBOARD, encoding="utf-8")
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    active = tmp_path / "active"
    active.mkdir()

    update_dashboard(
        state,
        dashboard_path=dashboard,
        event_log_path=event_log,
        vault_active=active,
        now=_now(),
    )

    out = dashboard.read_text(encoding="utf-8")
    # Existing content preserved verbatim
    assert "## In progress (by role)" in out
    assert "```dataview" in out
    assert "## Operator hand-edited section" in out
    assert "A note from the operator that must be preserved." in out
    # New block appended
    assert SENTINEL_START in out
    assert SENTINEL_END in out
    assert "## Live Sessions" in out


def test_update_dashboard_replaces_block_in_place(tmp_path: Path) -> None:
    dashboard = tmp_path / "cc-active.md"
    initial = (
        _EXISTING_DASHBOARD
        + "\n"
        + SENTINEL_START
        + "\n\n## Live Sessions\n\nold content\n\n"
        + SENTINEL_END
        + "\n"
        + "## After-block operator section\n\nMore preserved content.\n"
    )
    dashboard.write_text(initial, encoding="utf-8")
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    active = tmp_path / "active"
    active.mkdir()

    update_dashboard(
        state,
        dashboard_path=dashboard,
        event_log_path=event_log,
        vault_active=active,
        now=_now(),
    )

    out = dashboard.read_text(encoding="utf-8")
    # Pre-block preserved
    assert "## In progress (by role)" in out
    assert "```dataview" in out
    assert "## Operator hand-edited section" in out
    # Post-block preserved
    assert "## After-block operator section" in out
    assert "More preserved content." in out
    # Old generated content gone, new generated content present
    assert "old content" not in out
    assert "## Live Sessions" in out
    # Exactly one sentinel pair (no duplication on subsequent rewrites)
    assert out.count(SENTINEL_START) == 1
    assert out.count(SENTINEL_END) == 1


def test_update_dashboard_idempotent_across_runs(tmp_path: Path) -> None:
    """Two consecutive sweeps must leave the dashboard structurally stable."""
    dashboard = tmp_path / "cc-active.md"
    dashboard.write_text(_EXISTING_DASHBOARD, encoding="utf-8")
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    active = tmp_path / "active"
    active.mkdir()

    update_dashboard(
        state,
        dashboard_path=dashboard,
        event_log_path=event_log,
        vault_active=active,
        now=_now(),
    )
    first = dashboard.read_text(encoding="utf-8")
    update_dashboard(
        state,
        dashboard_path=dashboard,
        event_log_path=event_log,
        vault_active=active,
        now=_now(),
    )
    second = dashboard.read_text(encoding="utf-8")
    assert first == second
    assert second.count(SENTINEL_START) == 1
    assert second.count(SENTINEL_END) == 1


def test_update_dashboard_creates_file_if_absent(tmp_path: Path) -> None:
    dashboard = tmp_path / "missing-cc-active.md"
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    active = tmp_path / "active"
    active.mkdir()

    update_dashboard(
        state,
        dashboard_path=dashboard,
        event_log_path=event_log,
        vault_active=active,
        now=_now(),
    )
    assert dashboard.exists()
    out = dashboard.read_text(encoding="utf-8")
    assert SENTINEL_START in out
    assert SENTINEL_END in out


def test_update_dashboard_killswitch_no_op(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("HAPAX_CC_HYGIENE_OFF", "1")
    dashboard = tmp_path / "cc-active.md"
    dashboard.write_text(_EXISTING_DASHBOARD, encoding="utf-8")
    original = dashboard.read_text(encoding="utf-8")
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    active = tmp_path / "active"
    active.mkdir()

    update_dashboard(
        state,
        dashboard_path=dashboard,
        event_log_path=event_log,
        vault_active=active,
        now=_now(),
    )
    assert dashboard.read_text(encoding="utf-8") == original


def test_update_dashboard_handles_only_one_sentinel(tmp_path: Path) -> None:
    """Mismatched sentinels: do not corrupt — append a fresh block."""
    dashboard = tmp_path / "cc-active.md"
    dashboard.write_text(
        _EXISTING_DASHBOARD + "\n" + SENTINEL_START + "\n\norphan content with no end\n",
        encoding="utf-8",
    )
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    active = tmp_path / "active"
    active.mkdir()

    update_dashboard(
        state,
        dashboard_path=dashboard,
        event_log_path=event_log,
        vault_active=active,
        now=_now(),
    )
    out = dashboard.read_text(encoding="utf-8")
    # Original content preserved (we refused to corrupt)
    assert "orphan content with no end" in out
    assert "## Operator hand-edited section" in out
    # Fresh block appended
    assert SENTINEL_END in out
    assert "## Live Sessions" in out


def test_update_dashboard_preserves_pre_existing_dataview(tmp_path: Path) -> None:
    """The acceptance criterion: existing Dataview tables are NOT mutated."""
    dashboard = tmp_path / "cc-active.md"
    dashboard.write_text(_EXISTING_DASHBOARD, encoding="utf-8")
    state = _build_state()
    event_log = tmp_path / "cc-hygiene-events.md"
    active = tmp_path / "active"
    active.mkdir()

    update_dashboard(
        state,
        dashboard_path=dashboard,
        event_log_path=event_log,
        vault_active=active,
        now=_now(),
    )
    out = dashboard.read_text(encoding="utf-8")
    # original Dataview block preserved verbatim (text-equality)
    assert '```dataview\nTABLE WITHOUT ID\n  file.link as "Task",\n  assigned_to as "Role"' in out
