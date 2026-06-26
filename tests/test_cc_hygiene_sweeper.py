"""Tests for the cc-hygiene sweeper (PR1 of the task-list hygiene plan).

Per project convention, no shared conftest fixtures — each test builds
its own vault + relay tree under ``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest  # noqa: TC002 (used at runtime in fixture type hint)

# Ensure the script-side package is importable in tests.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _load_sweeper_module() -> ModuleType:
    """Load `scripts/cc-hygiene-sweeper.py` despite its hyphenated filename."""
    if "cc_hygiene_sweeper" in sys.modules:
        return sys.modules["cc_hygiene_sweeper"]
    path = _SCRIPTS / "cc-hygiene-sweeper.py"
    spec = importlib.util.spec_from_file_location("cc_hygiene_sweeper", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["cc_hygiene_sweeper"] = module
    spec.loader.exec_module(module)
    return module


from cc_hygiene import events as events_mod  # noqa: E402
from cc_hygiene.checks import (  # noqa: E402
    OFFERED_STALE_DAYS,
    RELAY_STALE_MIN,
    STALE_IN_PROGRESS_HOURS,
    WIP_LIMIT,
    check_duplicate_claim,
    check_ghost_claimed,
    check_offered_staleness,
    check_orphan_pr,
    check_refusal_pipeline_dormancy,
    check_relay_yaml_staleness,
    check_stale_in_progress,
    check_wip_limit,
    parse_task_note,
)
from cc_hygiene.events import append_events  # noqa: E402
from cc_hygiene.models import HygieneEvent, TaskNote  # noqa: E402
from cc_hygiene.state import write_state  # noqa: E402

# ----------------------------------------------------------------------------
# fixtures (inline per project convention — no shared conftest)
# ----------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 4, 26, 12, 0, tzinfo=UTC)


def _write_note(dirpath: Path, task_id: str, **frontmatter: Any) -> Path:
    """Write a vault cc-task note with given frontmatter."""
    fm: dict[str, Any] = {
        "type": "cc-task",
        "task_id": task_id,
        "title": f"test task {task_id}",
        **frontmatter,
    }
    body_lines = ["---"]
    for key, value in fm.items():
        if value is None:
            body_lines.append(f"{key}: null")
        elif isinstance(value, datetime):
            body_lines.append(f"{key}: {value.isoformat()}")
        elif isinstance(value, list):
            body_lines.append(f"{key}: {value}")
        else:
            body_lines.append(f"{key}: {value}")
    body_lines.append("---")
    body_lines.append("")
    body_lines.append("# body")
    path = dirpath / f"{task_id}-test.md"
    path.write_text("\n".join(body_lines), encoding="utf-8")
    return path


def _write_relay(relay_dir: Path, role: str, payload: dict[str, Any]) -> Path:
    import yaml

    relay_dir.mkdir(parents=True, exist_ok=True)
    path = relay_dir / f"{role}.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


# ----------------------------------------------------------------------------
# parse_task_note
# ----------------------------------------------------------------------------


def test_parse_task_note_happy_path(tmp_path: Path) -> None:
    note_path = _write_note(
        tmp_path,
        "cc-foo-bar",
        status="offered",
        automation_status="FULL_AUTO",
        assigned_to="unassigned",
        claimed_at=None,
        created_at=_now(),
        updated_at=_now(),
    )
    note = parse_task_note(note_path)
    assert note is not None
    assert note.task_id == "cc-foo-bar"
    assert note.status == "offered"
    assert note.automation_status == "FULL_AUTO"
    assert note.assigned_to == "unassigned"
    assert note.claimed_at is None


def test_parse_task_note_returns_none_on_non_cctask(tmp_path: Path) -> None:
    p = tmp_path / "random.md"
    p.write_text("---\ntype: not-a-task\n---\nbody\n", encoding="utf-8")
    assert parse_task_note(p) is None


def test_parse_task_note_returns_none_on_missing_frontmatter(tmp_path: Path) -> None:
    p = tmp_path / "bad.md"
    p.write_text("just markdown, no frontmatter\n", encoding="utf-8")
    assert parse_task_note(p) is None


# ----------------------------------------------------------------------------
# check_ghost_claimed (§2.2) — sanity-check anchor
# ----------------------------------------------------------------------------


def test_ghost_claimed_unassigned_fires(tmp_path: Path) -> None:
    note = TaskNote(
        path="x",
        task_id="cc-1",
        status="claimed",
        assigned_to="unassigned",
        claimed_at=None,
    )
    events = check_ghost_claimed([note], now=_now())
    assert len(events) == 1
    assert events[0].check_id == "ghost_claimed"
    assert events[0].severity == "violation"


def test_ghost_claimed_null_claimed_at_fires(tmp_path: Path) -> None:
    note = TaskNote(
        path="x",
        task_id="cc-2",
        status="claimed",
        assigned_to="alpha",
        claimed_at=None,
    )
    events = check_ghost_claimed([note], now=_now())
    assert len(events) == 1


def test_ghost_claimed_legitimate_claim_does_not_fire() -> None:
    note = TaskNote(
        path="x",
        task_id="cc-3",
        status="claimed",
        assigned_to="alpha",
        claimed_at=_now(),
    )
    events = check_ghost_claimed([note], now=_now())
    assert events == []


# ----------------------------------------------------------------------------
# check_stale_in_progress (§2.1)
# ----------------------------------------------------------------------------


def test_stale_in_progress_old_updated_at_fires(tmp_path: Path) -> None:
    now = _now()
    note = TaskNote(
        path="x",
        task_id="cc-stale",
        status="in_progress",
        assigned_to="alpha",
        updated_at=now - timedelta(hours=STALE_IN_PROGRESS_HOURS + 1),
    )
    # _git_log_count_since shells out to git; mock it to return 0.
    with (
        patch("cc_hygiene.checks._git_log_count_since", return_value=0),
        patch("cc_hygiene.checks._gh_pr_view_updated", return_value=None),
    ):
        events = check_stale_in_progress([note], tmp_path, now=now)
    assert len(events) == 1
    assert events[0].check_id == "stale_in_progress"


def test_stale_in_progress_recent_commit_suppresses(tmp_path: Path) -> None:
    now = _now()
    note = TaskNote(
        path="x",
        task_id="cc-stale-but-active",
        status="in_progress",
        assigned_to="alpha",
        branch="alpha/work",
        updated_at=now - timedelta(hours=STALE_IN_PROGRESS_HOURS + 1),
    )
    with patch("cc_hygiene.checks._git_log_count_since", return_value=3):
        events = check_stale_in_progress([note], tmp_path, now=now)
    assert events == []


def test_stale_in_progress_skips_non_in_progress() -> None:
    note = TaskNote(
        path="x",
        task_id="cc-offered",
        status="offered",
        assigned_to="unassigned",
    )
    events = check_stale_in_progress([note], Path("."), now=_now())
    assert events == []


# ----------------------------------------------------------------------------
# check_duplicate_claim (§2.3)
# ----------------------------------------------------------------------------


def test_duplicate_claim_same_task_within_window_fires() -> None:
    now = _now()
    payloads = {
        "alpha": {"current_claim": {"task_id": "cc-shared", "claimed_at": now.isoformat()}},
        "beta": {
            "current_claim": {
                "task_id": "cc-shared",
                "claimed_at": (now - timedelta(minutes=2)).isoformat(),
            }
        },
    }
    events = check_duplicate_claim(payloads, now=now)
    assert len(events) == 1
    assert events[0].check_id == "duplicate_claim"
    assert events[0].severity == "violation"


def test_duplicate_claim_outside_window_suppresses() -> None:
    now = _now()
    payloads = {
        "alpha": {
            "current_claim": {
                "task_id": "cc-shared",
                "claimed_at": (now - timedelta(hours=2)).isoformat(),
            }
        },
        "beta": {"current_claim": {"task_id": "cc-shared", "claimed_at": now.isoformat()}},
    }
    events = check_duplicate_claim(payloads, now=now)
    assert events == []


def test_duplicate_claim_distinct_tasks_no_event() -> None:
    now = _now()
    payloads = {
        "alpha": {"current_claim": {"task_id": "cc-A", "claimed_at": now.isoformat()}},
        "beta": {"current_claim": {"task_id": "cc-B", "claimed_at": now.isoformat()}},
    }
    assert check_duplicate_claim(payloads, now=now) == []


# ----------------------------------------------------------------------------
# check_orphan_pr (§2.4)
# ----------------------------------------------------------------------------


def test_orphan_pr_old_unlinked_fires(tmp_path: Path) -> None:
    now = _now()
    notes = [
        TaskNote(path="x", task_id="cc-other", status="offered", assigned_to=None, pr=999),
    ]
    fake_prs = [
        {
            "number": 1234,
            "headRefName": "alpha/whatever",
            "createdAt": (now - timedelta(hours=4)).isoformat(),
            "updatedAt": (now - timedelta(hours=2)).isoformat(),
        }
    ]
    with patch("cc_hygiene.checks._gh_pr_list", return_value=fake_prs):
        events = check_orphan_pr(notes, tmp_path, now=now)
    assert len(events) == 1
    assert events[0].metadata["pr"] == "1234"


def test_orphan_pr_linked_pr_suppresses(tmp_path: Path) -> None:
    now = _now()
    notes = [TaskNote(path="x", task_id="cc-A", status="in_progress", pr=1234)]
    fake_prs = [
        {
            "number": 1234,
            "headRefName": "alpha/whatever",
            "createdAt": (now - timedelta(hours=4)).isoformat(),
        }
    ]
    with patch("cc_hygiene.checks._gh_pr_list", return_value=fake_prs):
        events = check_orphan_pr(notes, tmp_path, now=now)
    assert events == []


def test_orphan_pr_secondary_linked_pr_suppresses(tmp_path: Path) -> None:
    now = _now()
    notes = [
        TaskNote(
            path="x",
            task_id="cc-A",
            status="pr_open",
            pr=4091,
            linked_prs=(4091, 4092),
        )
    ]
    fake_prs = [
        {
            "number": 4092,
            "headRefName": "alpha/abstention-witness-class-20260611",
            "createdAt": (now - timedelta(hours=4)).isoformat(),
        }
    ]
    with patch("cc_hygiene.checks._gh_pr_list", return_value=fake_prs):
        events = check_orphan_pr(notes, tmp_path, now=now)
    assert events == []


def test_parse_task_note_collects_secondary_pr_links(tmp_path: Path) -> None:
    note_path = _write_note(
        tmp_path,
        "cc-A",
        status="pr_open",
        pr=4091,
        pr_secondary=4092,
    )

    note = parse_task_note(note_path)

    assert note is not None
    assert note.pr == 4091
    assert note.linked_prs == (4091, 4092)


def test_orphan_pr_linked_by_closed_task_suppresses(tmp_path: Path) -> None:
    # Regression for P0 incident orphan_pr:4111 (count 215): a task is
    # routinely closed (moved to closed/) the moment its PR opens, well before
    # the PR merges. The orphan check must treat a PR linked by a CLOSED task
    # as linked, or every such PR is mislabeled an orphan and fires a recurring
    # 5-min notification storm for the PR's whole open lifetime.
    now = _now()
    closed_notes = [TaskNote(path="x", task_id="cc-done", status="done", pr=4111)]
    fake_prs = [
        {
            "number": 4111,
            "headRefName": "cx-blue/trainyard-b1-admission-feed-20260612",
            "createdAt": (now - timedelta(hours=4)).isoformat(),
        }
    ]
    with patch("cc_hygiene.checks._gh_pr_list", return_value=fake_prs):
        events = check_orphan_pr([], tmp_path, closed_notes=closed_notes, now=now)
    assert events == []


def test_orphan_pr_unlinked_still_fires_with_closed_notes(tmp_path: Path) -> None:
    # The closed-note link set must not suppress a genuinely orphan PR: a PR
    # that no task (active or closed) links is still a real orphan signal.
    now = _now()
    closed_notes = [TaskNote(path="x", task_id="cc-done", status="done", pr=4111)]
    fake_prs = [
        {
            "number": 5555,
            "headRefName": "alpha/untracked",
            "createdAt": (now - timedelta(hours=4)).isoformat(),
        }
    ]
    with patch("cc_hygiene.checks._gh_pr_list", return_value=fake_prs):
        events = check_orphan_pr([], tmp_path, closed_notes=closed_notes, now=now)
    assert len(events) == 1
    assert events[0].metadata["pr"] == "5555"


def test_orphan_pr_too_young_suppresses(tmp_path: Path) -> None:
    now = _now()
    fake_prs = [
        {
            "number": 1234,
            "headRefName": "x",
            "createdAt": (now - timedelta(minutes=10)).isoformat(),
        }
    ]
    with patch("cc_hygiene.checks._gh_pr_list", return_value=fake_prs):
        events = check_orphan_pr([], tmp_path, now=now)
    assert events == []


# ----------------------------------------------------------------------------
# check_relay_yaml_staleness (§2.5)
# ----------------------------------------------------------------------------


def test_relay_stale_fires_when_old() -> None:
    now = _now()
    payloads = {
        "alpha": {"updated": (now - timedelta(minutes=RELAY_STALE_MIN + 5)).isoformat()},
    }
    events = check_relay_yaml_staleness(payloads, now=now)
    assert len(events) == 1
    assert events[0].session == "alpha"
    assert events[0].severity == "warning"


def test_relay_stale_fresh_yaml_no_event() -> None:
    now = _now()
    payloads = {"alpha": {"updated": (now - timedelta(minutes=2)).isoformat()}}
    events = check_relay_yaml_staleness(payloads, now=now)
    assert events == []


def test_relay_stale_missing_timestamp_emits_info() -> None:
    payloads = {"alpha": {"role": "alpha"}}
    events = check_relay_yaml_staleness(payloads, now=_now())
    assert len(events) == 1
    assert events[0].severity == "info"


def test_relay_stale_skips_retired_session_with_flat_status() -> None:
    """Retired / wound-down sessions are correctly silent — their
    staleness is the steady state, not a hygiene event. Operator-
    reported regression 2026-05-01: cx-amber yaml flagged 90min stale
    after codex retirement."""

    now = _now()
    payloads = {
        "cx-amber": {
            "status": "idle_wound_down",
            "updated": (now - timedelta(minutes=RELAY_STALE_MIN + 60)).isoformat(),
        },
    }
    events = check_relay_yaml_staleness(payloads, now=now)
    assert events == []


def test_relay_stale_skips_retired_session_with_nested_session_status() -> None:
    """Some yamls carry the retirement marker as a multi-line scalar
    on ``session_status``: ``"RETIRED legacy delta relay; superseded by ..."``.
    The check must match the leading word of normalized text."""

    now = _now()
    payloads = {
        "delta": {
            "session_status": "RETIRED legacy delta relay; superseded by cx-* lanes",
            "updated": (now - timedelta(hours=24)).isoformat(),
        },
    }
    events = check_relay_yaml_staleness(payloads, now=now)
    assert events == []


def test_relay_stale_skips_retired_with_nested_dict_status() -> None:
    """A nested ``session_status: {status: RETIRED, ...}`` shape is
    also recognized."""

    now = _now()
    payloads = {
        "epsilon": {
            "session_status": {"status": "retired", "ts": now.isoformat()},
            "updated": (now - timedelta(hours=12)).isoformat(),
        },
    }
    events = check_relay_yaml_staleness(payloads, now=now)
    assert events == []


def test_relay_stale_skips_wind_down_idle_variant() -> None:
    """Empirical regression: post-codex cx-blue / cx-green carry the
    word-swapped spelling ``wind_down_idle`` (vs ``idle_wound_down``
    for cx-amber). The recognizer must treat both as retired."""

    now = _now()
    payloads = {
        "cx-blue": {
            "status": "wind_down_idle",
            "updated": (now - timedelta(minutes=RELAY_STALE_MIN + 100)).isoformat(),
        },
        "cx-green": {
            "status": "wind_down_idle",
            "updated": (now - timedelta(hours=2)).isoformat(),
        },
    }
    events = check_relay_yaml_staleness(payloads, now=now)
    assert events == [], (
        "wind_down_idle is the spelling cx-blue / cx-green actually carry — "
        "must be recognized as retired alongside idle_wound_down"
    )


def test_relay_stale_skips_winding_down_progressive_variant() -> None:
    """`winding_down` is the progressive form some lanes use mid-handoff."""

    now = _now()
    payloads = {
        "cx-foo": {
            "status": "winding_down",
            "updated": (now - timedelta(hours=1)).isoformat(),
        },
    }
    events = check_relay_yaml_staleness(payloads, now=now)
    assert events == []


def test_relay_stale_active_session_still_fires_when_old() -> None:
    """An ``active`` session whose updated timestamp is past the
    threshold still emits the warning — the retired-session bypass
    must not silence live lanes."""

    now = _now()
    payloads = {
        "alpha": {
            "status": "active",
            "updated": (now - timedelta(minutes=RELAY_STALE_MIN + 5)).isoformat(),
        },
    }
    events = check_relay_yaml_staleness(payloads, now=now)
    assert len(events) == 1
    assert events[0].session == "alpha"


# ----------------------------------------------------------------------------
# check_wip_limit (§2.6)
# ----------------------------------------------------------------------------


def test_wip_limit_exceeded_fires() -> None:
    notes = [
        TaskNote(path=f"x{i}", task_id=f"cc-{i}", status="in_progress", assigned_to="alpha")
        for i in range(WIP_LIMIT + 1)
    ]
    events = check_wip_limit(notes, now=_now())
    assert len(events) == 1
    assert events[0].metadata["in_progress_count"] == str(WIP_LIMIT + 1)


def test_wip_limit_at_threshold_no_event() -> None:
    notes = [
        TaskNote(path=f"x{i}", task_id=f"cc-{i}", status="in_progress", assigned_to="alpha")
        for i in range(WIP_LIMIT)
    ]
    assert check_wip_limit(notes, now=_now()) == []


def test_wip_limit_unassigned_ignored() -> None:
    notes = [
        TaskNote(path=f"x{i}", task_id=f"cc-{i}", status="in_progress", assigned_to="unassigned")
        for i in range(WIP_LIMIT + 5)
    ]
    assert check_wip_limit(notes, now=_now()) == []


# ----------------------------------------------------------------------------
# check_offered_staleness (§2.7)
# ----------------------------------------------------------------------------


def test_offered_staleness_old_offered_fires() -> None:
    now = _now()
    note = TaskNote(
        path="x",
        task_id="cc-old",
        status="offered",
        assigned_to="unassigned",
        created_at=now - timedelta(days=OFFERED_STALE_DAYS + 1),
        updated_at=now - timedelta(days=OFFERED_STALE_DAYS + 1),
    )
    events = check_offered_staleness([note], now=now)
    assert len(events) == 1


def test_offered_staleness_recently_updated_no_event() -> None:
    now = _now()
    note = TaskNote(
        path="x",
        task_id="cc-touched",
        status="offered",
        assigned_to="unassigned",
        created_at=now - timedelta(days=OFFERED_STALE_DAYS + 1),
        updated_at=now - timedelta(days=1),
    )
    assert check_offered_staleness([note], now=now) == []


def test_offered_staleness_young_no_event() -> None:
    now = _now()
    note = TaskNote(
        path="x",
        task_id="cc-young",
        status="offered",
        assigned_to="unassigned",
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
    )
    assert check_offered_staleness([note], now=now) == []


# ----------------------------------------------------------------------------
# check_refusal_pipeline_dormancy (§2.8)
# ----------------------------------------------------------------------------


def test_refusal_dormancy_no_refused_fires() -> None:
    events = check_refusal_pipeline_dormancy([], now=_now())
    assert len(events) == 1
    assert events[0].check_id == "refusal_dormancy"


def test_refusal_dormancy_recent_refused_no_event() -> None:
    now = _now()
    note = TaskNote(
        path="x",
        task_id="cc-refused",
        status="refused",
        updated_at=now - timedelta(days=1),
    )
    assert check_refusal_pipeline_dormancy([note], now=now) == []


def test_refusal_dormancy_recent_canonical_refused_no_event() -> None:
    now = _now()
    note = TaskNote(
        path="x",
        task_id="cc-refused-done",
        status="done",
        automation_status="REFUSED",
        updated_at=now - timedelta(days=1),
    )
    assert check_refusal_pipeline_dormancy([note], now=now) == []


def test_refusal_dormancy_only_old_refused_fires() -> None:
    now = _now()
    note = TaskNote(
        path="x",
        task_id="cc-refused-old",
        status="refused",
        updated_at=now - timedelta(days=30),
    )
    events = check_refusal_pipeline_dormancy([note], now=now)
    assert len(events) == 1


# ----------------------------------------------------------------------------
# state writer
# ----------------------------------------------------------------------------


def test_write_state_atomic_and_valid_json(tmp_path: Path) -> None:
    from cc_hygiene.models import CheckSummary, HygieneState

    state = HygieneState(
        sweep_timestamp=_now(),
        sweep_duration_ms=42,
        sessions=[],
        check_summaries=[CheckSummary(check_id="ghost_claimed", fired=0)],
        events=[],
    )
    out = tmp_path / "state.json"
    write_state(state, path=out)
    payload = json.loads(out.read_text())
    assert payload["schema_version"] == 1
    assert payload["sweep_duration_ms"] == 42
    assert payload["killswitch_active"] is False


# ----------------------------------------------------------------------------
# event log writer
# ----------------------------------------------------------------------------


def test_append_events_creates_header_and_block(tmp_path: Path) -> None:
    log = tmp_path / "cc-hygiene-events.md"
    event = HygieneEvent(
        timestamp=_now(),
        check_id="ghost_claimed",
        severity="violation",
        task_id="cc-foo",
        message="ghost claim detected",
    )
    append_events([event], _now(), path=log)
    text = log.read_text()
    assert "# cc-hygiene event log" in text
    assert "## sweep" in text
    assert "ghost_claimed" in text
    assert "ghost claim detected" in text


def test_append_events_appends_not_overwrites(tmp_path: Path) -> None:
    log = tmp_path / "log.md"
    event_a = HygieneEvent(
        timestamp=_now(), check_id="ghost_claimed", severity="violation", message="a"
    )
    event_b = HygieneEvent(timestamp=_now(), check_id="orphan_pr", severity="warning", message="b")
    append_events([event_a], _now(), path=log)
    append_events([event_b], _now(), path=log)
    text = log.read_text()
    # Two sweep heading lines (header has the literal phrase in its prose,
    # but only sweep headings start with "## sweep " followed by an ISO-8601 ts).
    sweep_headings = [line for line in text.splitlines() if line.startswith("## sweep 2")]
    assert len(sweep_headings) == 2
    assert "message: a" in text
    assert "message: b" in text


def test_append_events_with_no_events_still_appends_heartbeat(tmp_path: Path) -> None:
    log = tmp_path / "heartbeat.md"
    append_events([], _now(), path=log, killswitch_active=True)
    text = log.read_text()
    assert "## sweep" in text
    assert "killswitch_active: true" in text
    assert "events: []" in text


# ----------------------------------------------------------------------------
# size-capped rotation + relocation (reform Phase-0 housekeeping)
# ----------------------------------------------------------------------------


def test_default_log_path_relocated_out_of_dashboard() -> None:
    # The canonical log must NOT live inside the Obsidian _dashboard/ dir
    # (a 100MB+ markdown there chokes Obsidian) and must sit under ~/.cache/hapax.
    parts = events_mod.DEFAULT_EVENT_LOG_PATH.parts
    assert "_dashboard" not in parts
    assert ".cache" in parts and "hapax" in parts


def test_event_log_max_bytes_default_is_positive_int() -> None:
    assert isinstance(events_mod.EVENT_LOG_MAX_BYTES, int)
    assert events_mod.EVENT_LOG_MAX_BYTES > 0


def test_rotation_moves_oversized_log_to_archive(tmp_path: Path) -> None:
    log = tmp_path / "cc-hygiene-events.md"
    old_content = "# cc-hygiene event log\n\n" + ("x" * 400)
    log.write_text(old_content, encoding="utf-8")

    event = HygieneEvent(
        timestamp=_now(), check_id="ghost_claimed", severity="violation", message="post-rotate"
    )
    append_events([event], _now(), path=log, max_bytes=100)

    # the active log is fresh: header + the new block only; old bulk is gone
    text = log.read_text()
    assert text.startswith("# cc-hygiene event log")
    assert "post-rotate" in text
    assert "x" * 400 not in text

    # the old log was moved whole into an archive/ sibling, byte-for-byte
    archived = list((tmp_path / "archive").glob("*.md"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == old_content


def test_no_rotation_when_under_cap(tmp_path: Path) -> None:
    log = tmp_path / "cc-hygiene-events.md"
    ev = HygieneEvent(timestamp=_now(), check_id="orphan_pr", severity="warning", message="m")
    append_events([ev], _now(), path=log, max_bytes=10_000_000)
    append_events([ev], _now(), path=log, max_bytes=10_000_000)
    assert not (tmp_path / "archive").exists()
    sweep_headings = [ln for ln in log.read_text().splitlines() if ln.startswith("## sweep 2")]
    assert len(sweep_headings) == 2


def test_rotation_disabled_when_cap_zero(tmp_path: Path) -> None:
    log = tmp_path / "cc-hygiene-events.md"
    log.write_text("# cc-hygiene event log\n\n" + ("y" * 500), encoding="utf-8")
    ev = HygieneEvent(timestamp=_now(), check_id="orphan_pr", severity="warning", message="m")
    append_events([ev], _now(), path=log, max_bytes=0)
    assert not (tmp_path / "archive").exists()
    assert "y" * 500 in log.read_text()  # appended in place, old content preserved


def test_rotation_uses_module_default_cap_when_unspecified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # With no explicit max_bytes, a file at/over the (current) module default rotates.
    monkeypatch.setattr(events_mod, "EVENT_LOG_MAX_BYTES", 100)
    log = tmp_path / "cc-hygiene-events.md"
    log.write_text("# cc-hygiene event log\n\n" + ("z" * 400), encoding="utf-8")
    ev = HygieneEvent(timestamp=_now(), check_id="orphan_pr", severity="warning", message="m")
    append_events([ev], _now(), path=log)
    assert (tmp_path / "archive").is_dir()
    assert "z" * 400 not in log.read_text()


# ----------------------------------------------------------------------------
# vault-link integrity (reform Phase-0 housekeeping #3)
# ----------------------------------------------------------------------------


def _vault_with_request(tmp_path: Path, req_id: str, *, subdir: str = "active") -> Path:
    """Synthetic vault root holding one request note under hapax-requests/."""
    req_dir = tmp_path / "20-projects" / "hapax-requests" / subdir
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / f"{req_id}.md").write_text("# req\n", encoding="utf-8")
    return tmp_path


def test_vault_link_integrity_flags_dangling_request(tmp_path: Path) -> None:
    from cc_hygiene.checks import check_vault_link_integrity

    vault = _vault_with_request(tmp_path, "REQ-exists")
    note = TaskNote(
        path=str(tmp_path / "t.md"),
        task_id="cc-x",
        status="in_progress",
        assigned_to="beta",
        parent_request="REQ-missing",
    )
    out = check_vault_link_integrity([note], vault_root=vault)
    assert len(out) == 1
    assert out[0].check_id == "vault_link_integrity"
    assert out[0].severity == "warning"
    assert out[0].task_id == "cc-x"
    assert out[0].session == "beta"
    assert out[0].metadata["field"] == "parent_request"
    assert out[0].metadata["target"] == "REQ-missing"


def test_vault_link_integrity_ok_when_request_resolves(tmp_path: Path) -> None:
    from cc_hygiene.checks import check_vault_link_integrity

    vault = _vault_with_request(tmp_path, "REQ-exists")
    note = TaskNote(
        path=str(tmp_path / "t.md"),
        task_id="cc-x",
        status="claimed",
        parent_request="REQ-exists",
    )
    assert check_vault_link_integrity([note], vault_root=vault) == []


def test_vault_link_integrity_resolves_request_in_closed(tmp_path: Path) -> None:
    from cc_hygiene.checks import check_vault_link_integrity

    vault = _vault_with_request(tmp_path, "REQ-old", subdir="closed")
    note = TaskNote(
        path=str(tmp_path / "t.md"),
        task_id="cc-x",
        status="claimed",
        parent_request="REQ-old",
    )
    assert check_vault_link_integrity([note], vault_root=vault) == []


def test_vault_link_integrity_flags_dangling_spec_path(tmp_path: Path) -> None:
    from cc_hygiene.checks import check_vault_link_integrity

    note = TaskNote(
        path=str(tmp_path / "t.md"),
        task_id="cc-x",
        status="claimed",
        parent_spec=str(tmp_path / "30-areas" / "nope.md"),
    )
    out = check_vault_link_integrity([note], vault_root=tmp_path)
    assert len(out) == 1
    assert out[0].metadata["field"] == "parent_spec"


def test_vault_link_integrity_ok_when_spec_path_exists(tmp_path: Path) -> None:
    from cc_hygiene.checks import check_vault_link_integrity

    spec = tmp_path / "30-areas" / "design.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("# design\n", encoding="utf-8")
    note = TaskNote(
        path=str(tmp_path / "t.md"),
        task_id="cc-x",
        status="claimed",
        parent_spec=str(spec),
    )
    assert check_vault_link_integrity([note], vault_root=tmp_path) == []


def test_vault_link_integrity_skips_null_pointers(tmp_path: Path) -> None:
    from cc_hygiene.checks import check_vault_link_integrity

    n1 = TaskNote(path=str(tmp_path / "a.md"), task_id="cc-a", status="claimed")
    n2 = TaskNote(
        path=str(tmp_path / "b.md"),
        task_id="cc-b",
        status="claimed",
        parent_request="null",
        parent_spec="~",
        parent_plan="",
    )
    assert check_vault_link_integrity([n1, n2], vault_root=tmp_path) == []


# Real vault data stores parent_* links in many forms: bare id, id+`.md`,
# vault-relative path, repo-relative path, `~`-prefixed path, absolute path.
# A resolver that only handles bare ids false-positives on ~70% of live notes
# (measured 146/230 parent_request FPs) — noise that violates executive_function.
# These pin the multi-form/multi-root resolution that keeps the signal clean.


def test_vault_link_integrity_resolves_request_id_with_md_suffix(tmp_path: Path) -> None:
    from cc_hygiene.checks import check_vault_link_integrity

    vault = _vault_with_request(tmp_path, "REQ-exists")
    note = TaskNote(
        path=str(tmp_path / "t.md"),
        task_id="cc-x",
        status="claimed",
        parent_request="REQ-exists.md",
    )
    assert check_vault_link_integrity([note], vault_root=vault) == []


def test_vault_link_integrity_resolves_vault_relative_request_path(tmp_path: Path) -> None:
    from cc_hygiene.checks import check_vault_link_integrity

    vault = _vault_with_request(tmp_path, "REQ-exists")
    note = TaskNote(
        path=str(tmp_path / "t.md"),
        task_id="cc-x",
        status="claimed",
        parent_request="20-projects/hapax-requests/active/REQ-exists.md",
    )
    assert check_vault_link_integrity([note], vault_root=vault) == []


def test_vault_link_integrity_resolves_repo_relative_spec(tmp_path: Path) -> None:
    from cc_hygiene.checks import check_vault_link_integrity

    repo = tmp_path / "repo"
    spec = repo / "docs" / "superpowers" / "specs" / "design.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# design\n", encoding="utf-8")
    note = TaskNote(
        path=str(tmp_path / "t.md"),
        task_id="cc-x",
        status="claimed",
        parent_spec="docs/superpowers/specs/design.md",
    )
    assert check_vault_link_integrity([note], vault_root=tmp_path, repo_root=repo) == []


def test_vault_link_integrity_expands_tilde_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cc_hygiene.checks import check_vault_link_integrity

    monkeypatch.setenv("HOME", str(tmp_path))
    spec = tmp_path / "Documents" / "Personal" / "30-areas" / "hapax" / "s.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# spec\n", encoding="utf-8")
    note = TaskNote(
        path=str(tmp_path / "t.md"),
        task_id="cc-x",
        status="claimed",
        parent_spec="~/Documents/Personal/30-areas/hapax/s.md",
    )
    assert check_vault_link_integrity([note], vault_root=tmp_path / "Documents" / "Personal") == []


def test_vault_link_integrity_flags_truncated_request_id(tmp_path: Path) -> None:
    """A truncated id that is only a *prefix* of a real filename does not resolve —
    it is flagged for repair (no prefix matching, which would be ambiguous)."""
    from cc_hygiene.checks import check_vault_link_integrity

    vault = _vault_with_request(tmp_path, "REQ-20260511154500-livestream-layout-identity")
    note = TaskNote(
        path=str(tmp_path / "t.md"),
        task_id="cc-x",
        status="claimed",
        parent_request="REQ-20260511154500",
    )
    out = check_vault_link_integrity([note], vault_root=vault)
    assert len(out) == 1
    assert out[0].metadata["field"] == "parent_request"


def test_parse_task_note_reads_parent_request(tmp_path: Path) -> None:
    p = _write_note(tmp_path, "cc-x", status="claimed", parent_request="REQ-abc")
    note = parse_task_note(p)
    assert note is not None
    assert note.parent_request == "REQ-abc"


# ----------------------------------------------------------------------------
# relay loader
# ----------------------------------------------------------------------------


def test_load_relay_payloads_skips_codex_sidecar_yamls(tmp_path: Path) -> None:
    sweeper = _load_sweeper_module()
    relay = tmp_path / "relay"
    _write_relay(relay, "cx-blue", {"session": "cx-blue", "updated": _now().isoformat()})
    _write_relay(
        relay,
        "cx-blue-wsjf-007-audit",
        {"session": "cx-blue", "status": "completed"},
    )
    _write_relay(
        relay,
        "cx-green-coordination",
        {"session": "cx-green", "status": "active-coordination"},
    )

    payloads = sweeper._load_relay_payloads(relay)

    assert "cx-blue" in payloads
    assert "cx-blue-wsjf-007-audit" not in payloads
    assert "cx-green-coordination" not in payloads


def test_load_relay_payloads_skips_retired_relays(tmp_path: Path) -> None:
    sweeper = _load_sweeper_module()
    relay = tmp_path / "relay"
    _write_relay(relay, "alpha", {"session": "alpha", "role": "SUPERSEDED"})
    _write_relay(relay, "beta", {"session": "beta", "session_status": "RETIRING soon"})
    _write_relay(relay, "cx-amber", {"session": "cx-amber", "status": "RETIRED"})
    _write_relay(relay, "cx-blue", {"session": "cx-blue", "updated": _now().isoformat()})

    payloads = sweeper._load_relay_payloads(relay)

    assert "alpha" not in payloads
    assert "beta" not in payloads
    assert "cx-amber" not in payloads
    assert "cx-blue" in payloads


def test_load_relay_payloads_accepts_codex_status_yamls(tmp_path: Path) -> None:
    """Codex lanes write canonical status relays as ``cx-foo-status.yaml``.

    The loader must index those under the lane role, not the literal
    ``cx-foo-status`` stem, and still reject sidecars whose payload identity
    does not match the filename.
    """
    sweeper = _load_sweeper_module()
    relay = tmp_path / "relay"
    _write_relay(
        relay,
        "cx-p0-status",
        {
            "role": "cx-p0",
            "lane": "cx-p0",
            "timestamp": _now().isoformat(),
            "status": "blocked",
        },
    )
    _write_relay(
        relay,
        "cx-blue-status",
        {
            "role": "cx-other",
            "lane": "cx-other",
            "timestamp": _now().isoformat(),
            "status": "blocked",
        },
    )

    payloads = sweeper._load_relay_payloads(relay)

    assert "cx-p0" in payloads
    assert "cx-p0-status" not in payloads
    assert "cx-blue" not in payloads


def test_load_relay_payloads_keeps_status_relay_when_plain_relay_exists(tmp_path: Path) -> None:
    """If both Codex relay shapes exist, the status relay is authoritative."""
    sweeper = _load_sweeper_module()
    relay = tmp_path / "relay"
    _write_relay(
        relay,
        "cx-p0-status",
        {
            "role": "cx-p0",
            "lane": "cx-p0",
            "timestamp": _now().isoformat(),
            "status": "blocked",
        },
    )
    _write_relay(
        relay,
        "cx-p0",
        {
            "session": "cx-p0",
            "updated": (_now() - timedelta(hours=2)).isoformat(),
            "status": "active",
        },
    )

    payloads = sweeper._load_relay_payloads(relay)

    assert payloads["cx-p0"]["role"] == "cx-p0"
    assert "session" not in payloads["cx-p0"]


def test_reap_dead_lanes_retires_status_and_plain_codex_relay_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Duplicate Codex relay shapes for one lane should trigger one retire."""
    sweeper = _load_sweeper_module()
    relay = tmp_path / "relay"
    _write_relay(
        relay,
        "cx-p0-status",
        {
            "role": "cx-p0",
            "lane": "cx-p0",
            "timestamp": (_now() - timedelta(hours=2)).isoformat(),
            "status": "blocked",
        },
    )
    _write_relay(
        relay,
        "cx-p0",
        {
            "session": "cx-p0",
            "updated": (_now() - timedelta(hours=2)).isoformat(),
            "status": "active",
        },
    )
    retire_calls: list[list[str]] = []

    def fake_has_live_process(role: str) -> bool:
        return role != "cx-p0"

    def fake_retire(args: list[str], **_: Any) -> object:
        retire_calls.append(args)
        return object()

    monkeypatch.setattr(sweeper, "_lane_has_live_process", fake_has_live_process)
    monkeypatch.setattr(sweeper.subprocess, "run", fake_retire)

    reaped = sweeper.reap_dead_lanes(relay)

    assert reaped == ["cx-p0"]
    assert [call[1] for call in retire_calls] == ["cx-p0"]


# ----------------------------------------------------------------------------
# end-to-end: run_sweep + killswitch
# ----------------------------------------------------------------------------


def _build_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    (vault / "closed").mkdir(parents=True)
    (vault / "_dashboard").mkdir(parents=True)
    return vault


def test_run_sweep_finds_ghost_claimed(tmp_path: Path) -> None:
    run_sweep = _load_sweeper_module().run_sweep

    vault = _build_vault(tmp_path)
    _write_note(
        vault / "active",
        "cc-ghost",
        status="claimed",
        assigned_to="unassigned",
        claimed_at=None,
    )
    relay = tmp_path / "relay"
    state = run_sweep(vault_root=vault, relay_root=relay, repo_root=tmp_path, now=_now())
    ghost_events = [e for e in state.events if e.check_id == "ghost_claimed"]
    assert len(ghost_events) == 1


def test_run_sweep_reaps_dead_codex_status_relay_before_stale_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression pin for the ``relay_yaml_stale @cx-p0`` storm.

    A dead Codex lane with only ``cx-p0-status.yaml`` must be retired before
    ``check_relay_yaml_staleness`` runs, otherwise every 5-minute sweep emits
    the same stale relay event forever.
    """
    sweeper = _load_sweeper_module()
    vault = _build_vault(tmp_path)
    relay = tmp_path / "relay"
    relay_path = _write_relay(
        relay,
        "cx-p0-status",
        {
            "role": "cx-p0",
            "lane": "cx-p0",
            "timestamp": (_now() - timedelta(hours=2)).isoformat(),
            "status": "blocked",
        },
    )
    retire_calls: list[list[str]] = []

    def fake_has_live_process(role: str) -> bool:
        return role != "cx-p0"

    def fake_retire(args: list[str], **_: Any) -> object:
        retire_calls.append(args)
        relay_path.write_text(
            relay_path.read_text(encoding="utf-8")
            + "\nstatus: retired\nretired_reason: test reaper\n",
            encoding="utf-8",
        )
        return object()

    monkeypatch.setattr(sweeper, "_lane_has_live_process", fake_has_live_process)
    monkeypatch.setattr(sweeper.subprocess, "run", fake_retire)
    with patch("cc_hygiene.checks._gh_pr_list", return_value=[]):
        state = sweeper.run_sweep(
            vault_root=vault,
            relay_root=relay,
            repo_root=tmp_path,
            now=_now(),
        )

    assert retire_calls
    assert retire_calls[0][1] == "cx-p0"
    assert "status: retired" in relay_path.read_text(encoding="utf-8")
    assert not any(
        event.check_id == "relay_yaml_stale" and event.session == "cx-p0" for event in state.events
    )


def test_main_killswitch_writes_no_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    main = _load_sweeper_module().main

    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.md"
    monkeypatch.setenv("HAPAX_CC_HYGIENE_OFF", "1")
    rc = main(
        [
            "--state-path",
            str(state_path),
            "--event-log-path",
            str(log_path),
            "--vault-root",
            str(tmp_path / "missing-vault"),
            "--relay-root",
            str(tmp_path / "missing-relay"),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    payload = json.loads(state_path.read_text())
    assert payload["killswitch_active"] is True
    assert payload["events"] == []


# ----------------------------------------------------------------------------
# CLI smoke tests
# ----------------------------------------------------------------------------


def test_main_runs_clean_on_empty_world(tmp_path: Path) -> None:
    main = _load_sweeper_module().main

    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.md"
    rc = main(
        [
            "--state-path",
            str(state_path),
            "--event-log-path",
            str(log_path),
            "--vault-root",
            str(tmp_path / "missing-vault"),
            "--relay-root",
            str(tmp_path / "missing-relay"),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    payload = json.loads(state_path.read_text())
    # Empty world still emits the refusal-dormancy info event.
    assert payload["killswitch_active"] is False
    assert any(e["check_id"] == "refusal_dormancy" for e in payload["events"])


# ----------------------------------------------------------------------------
# main() ghost-claim self-heal (effect-based auto-action wiring)
# ----------------------------------------------------------------------------


def _main_args(tmp_path: Path, vault: Path) -> list[str]:
    """CLI args for a writing sweep with side-effecting surfaces disabled."""
    return [
        "--vault-root",
        str(vault),
        "--relay-root",
        str(tmp_path / "relay"),
        "--repo-root",
        str(tmp_path),
        "--state-path",
        str(tmp_path / "state.json"),
        "--event-log-path",
        str(tmp_path / "log.md"),
        "--no-ntfy",
        "--no-dashboard",
    ]


def test_main_auto_reverts_ghost_claimed(tmp_path: Path) -> None:
    """A ghost-claimed note (status: claimed, assigned but claimed_at=null) is
    self-healed back to `offered` in one sweep — the effect-based repair that
    stops the violation re-firing (P0 incident 2026-06-13, 39x storm)."""
    sweeper = _load_sweeper_module()
    vault = _build_vault(tmp_path)
    note_path = _write_note(
        vault / "active",
        "cc-ghost",
        status="claimed",
        assigned_to="epsilon",
        claimed_at=None,
    )
    with patch("cc_hygiene.checks._gh_pr_list", return_value=[]):
        rc = sweeper.main(_main_args(tmp_path, vault))
    assert rc == 0
    healed = parse_task_note(note_path)
    assert healed is not None
    assert healed.status == "offered"
    assert healed.assigned_to == "unassigned"
    assert healed.claimed_at is None


def test_main_ghost_claim_does_not_recur_after_heal(tmp_path: Path) -> None:
    """Storm-stop canary: sweep 1 detects + heals; sweep 2 finds NO ghost event."""
    sweeper = _load_sweeper_module()
    vault = _build_vault(tmp_path)
    _write_note(
        vault / "active",
        "cc-ghost",
        status="claimed",
        assigned_to="epsilon",
        claimed_at=None,
    )
    args = _main_args(tmp_path, vault)
    with patch("cc_hygiene.checks._gh_pr_list", return_value=[]):
        assert sweeper.main(args) == 0
        assert sweeper.main(args) == 0
    payload = json.loads((tmp_path / "state.json").read_text())
    assert not any(e["check_id"] == "ghost_claimed" for e in payload["events"])


def test_main_no_actions_flag_preserves_ghost(tmp_path: Path) -> None:
    """--no-actions keeps the sweeper observational (no auto-revert) for diagnosis."""
    sweeper = _load_sweeper_module()
    vault = _build_vault(tmp_path)
    note_path = _write_note(
        vault / "active",
        "cc-ghost",
        status="claimed",
        assigned_to="epsilon",
        claimed_at=None,
    )
    with patch("cc_hygiene.checks._gh_pr_list", return_value=[]):
        rc = sweeper.main(_main_args(tmp_path, vault) + ["--no-actions"])
    assert rc == 0
    same = parse_task_note(note_path)
    assert same is not None
    assert same.status == "claimed"
    assert same.assigned_to == "epsilon"


def test_main_does_not_touch_healthy_claim(tmp_path: Path) -> None:
    """No-op canary (parent-spec watch-list #2): a legitimately claimed task
    (assigned + claimed_at) is never reverted by the self-heal."""
    sweeper = _load_sweeper_module()
    vault = _build_vault(tmp_path)
    note_path = _write_note(
        vault / "active",
        "cc-healthy",
        status="claimed",
        assigned_to="alpha",
        claimed_at=_now(),
    )
    with patch("cc_hygiene.checks._gh_pr_list", return_value=[]):
        rc = sweeper.main(_main_args(tmp_path, vault))
    assert rc == 0
    same = parse_task_note(note_path)
    assert same is not None
    assert same.status == "claimed"
    assert same.assigned_to == "alpha"
    assert same.claimed_at is not None


# ----------------------------------------------------------------------------
# main() ghost-claim self-heal — notification suppression (post-#4140 recurrence)
# ----------------------------------------------------------------------------


def _main_args_with_ntfy(tmp_path: Path, vault: Path) -> list[str]:
    """CLI args for a writing sweep with ntfy ENABLED (tmp throttle/state).

    Unlike ``_main_args`` (which sets ``--no-ntfy``), this exercises the
    dispatch path so tests can assert whether a ghost pages the operator.
    """
    return [
        "--vault-root",
        str(vault),
        "--relay-root",
        str(tmp_path / "relay"),
        "--repo-root",
        str(tmp_path),
        "--state-path",
        str(tmp_path / "state.json"),
        "--event-log-path",
        str(tmp_path / "log.md"),
        "--throttle-path",
        str(tmp_path / "throttle.json"),
        "--no-dashboard",
    ]


def test_main_does_not_page_for_self_healed_ghost(tmp_path: Path) -> None:
    """Post-#4140 recurrence fix: a ghost-claimed note self-healed in THIS sweep
    must NOT dispatch an ntfy alert.

    #4140 wired the heal (storm stops re-firing) but left ``dispatch_alerts``
    running over the un-filtered sweep events, so the FIRST detection still sent
    a ``violation`` ntfy -> ``p0-incident-intake`` minted a fresh P0 task for
    every transient ghost (one per task_id; observed 2026-06-15/16, ledger
    fingerprints ``...segprep-s2-compo`` et al.). The heal already remediated the
    violation; paging the operator (and minting a task) for an auto-fixed
    transient is noise. Detection stays in the event log (asserted below), so
    this is severity-routing, not detection-avoidance."""
    sweeper = _load_sweeper_module()
    vault = _build_vault(tmp_path)
    note_path = _write_note(
        vault / "active",
        "cc-ghost",
        status="claimed",
        assigned_to="alpha",
        claimed_at=None,
    )
    sender = MagicMock(return_value=True)
    with (
        patch("cc_hygiene.checks._gh_pr_list", return_value=[]),
        patch("cc_hygiene.ntfy._default_sender", return_value=sender),
    ):
        rc = sweeper.main(_main_args_with_ntfy(tmp_path, vault))
    assert rc == 0
    # Healed on disk...
    healed = parse_task_note(note_path)
    assert healed is not None
    assert healed.status == "offered"
    # ...and NOT paged (this is the regression #4140 left open).
    assert sender.call_count == 0
    # Detection is still durably recorded — no detection-avoidance.
    assert "ghost_claimed" in (tmp_path / "log.md").read_text()


def test_main_still_pages_unhealed_ghost_under_no_actions(tmp_path: Path) -> None:
    """Contrast / over-suppression guard: with ``--no-actions`` the ghost is NOT
    healed, so the violation persists and MUST still page. Suppression is keyed
    strictly to a *successful* heal, never to the mere presence of a ghost."""
    sweeper = _load_sweeper_module()
    vault = _build_vault(tmp_path)
    note_path = _write_note(
        vault / "active",
        "cc-ghost",
        status="claimed",
        assigned_to="alpha",
        claimed_at=None,
    )
    sender = MagicMock(return_value=True)
    with (
        patch("cc_hygiene.checks._gh_pr_list", return_value=[]),
        patch("cc_hygiene.ntfy._default_sender", return_value=sender),
    ):
        rc = sweeper.main(_main_args_with_ntfy(tmp_path, vault) + ["--no-actions"])
    assert rc == 0
    # Not healed (observational mode)...
    same = parse_task_note(note_path)
    assert same is not None
    assert same.status == "claimed"
    # ...so the live violation still pages.
    assert sender.call_count == 1
