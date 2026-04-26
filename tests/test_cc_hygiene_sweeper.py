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
from unittest.mock import patch

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
        assigned_to="unassigned",
        claimed_at=None,
        created_at=_now(),
        updated_at=_now(),
    )
    note = parse_task_note(note_path)
    assert note is not None
    assert note.task_id == "cc-foo-bar"
    assert note.status == "offered"
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
