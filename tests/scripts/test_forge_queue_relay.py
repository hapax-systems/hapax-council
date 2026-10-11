"""Tests for scripts/forge-queue-relay (S2 slice-2 item 3: shunt queue -> coord log).

The relay polls shunt /status + /metrics and the forge open-PR list plus per-head
``merge-queue`` commit-status rows, diffs them against persisted state, and emits
``forge.queue.*`` coord events through the sanctioned CLI subprocess path. These
tests inject the fetcher and the CLI runner; no live shadow is needed.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "forge-queue-relay"


def _load_relay() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("forge_queue_relay", str(SCRIPT))
    spec = importlib.util.spec_from_loader("forge_queue_relay", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["forge_queue_relay"] = module
    loader.exec_module(module)
    return module


fqr = _load_relay()


REPO = "forge-admin/shadow-ci-driver"
QUEUE_KEY = "forge-admin/shadow-ci-driver:main"
SHUNT_URL = "http://shunt.test:8901"
FORGE_URL = "http://forge.test:3000"

# Verbatim shapes captured from the live shadow (2026-10-06 poll).
LIVE_STATUS_IDLE = (
    '{"queues":[{"owner":"forge-admin","repo":"shadow-ci-driver","base":"main",'
    '"queue_depth":0,"active_batch":false,"active_batches":[],"pending_batches":[]}]}'
)

LIVE_METRICS = "\n".join(
    [
        "# HELP shunt_queue_depth Number of PRs known in the in-memory queue.",
        "# TYPE shunt_queue_depth gauge",
        "# HELP shunt_active_batch Whether a queue currently has a batch under gate test.",
        "# TYPE shunt_active_batch gauge",
        "# HELP shunt_batches_started_total Number of batches staged and sent to the gate.",
        "# TYPE shunt_batches_started_total counter",
        "# HELP shunt_pr_merges_total Number of pull requests landed through shunt's queue.",
        "# TYPE shunt_pr_merges_total counter",
        "# HELP shunt_bounces_total Number of pull requests bounced from the queue.",
        "# TYPE shunt_bounces_total counter",
        "# HELP shunt_staging_conflicts_total Number of staging merge conflicts detected.",
        "# TYPE shunt_staging_conflicts_total counter",
        "# HELP shunt_reconcile_errors_total Number of reconcile loop errors.",
        "# TYPE shunt_reconcile_errors_total counter",
        "# HELP shunt_gate_outcomes_total Number of terminal gate outcomes by result.",
        "# TYPE shunt_gate_outcomes_total counter",
        "# HELP shunt_time_in_queue_seconds Process-local time in queue.",
        "# TYPE shunt_time_in_queue_seconds histogram",
        'shunt_queue_depth{owner="forge-admin",repo="shadow-ci-driver",base="main"} 0',
        'shunt_active_batch{owner="forge-admin",repo="shadow-ci-driver",base="main"} 0',
        'shunt_queue_oldest_age_seconds{owner="forge-admin",repo="shadow-ci-driver",base="main"} 0',
        'shunt_batches_started_total{owner="forge-admin",repo="shadow-ci-driver",base="main"} 17',
        'shunt_pr_merges_total{owner="forge-admin",repo="shadow-ci-driver",base="main"} 14',
        'shunt_bounces_total{owner="forge-admin",repo="shadow-ci-driver",base="main"} 3',
        'shunt_staging_conflicts_total{owner="forge-admin",repo="shadow-ci-driver",base="main"} 0',
        'shunt_reconcile_errors_total{owner="forge-admin",repo="shadow-ci-driver",base="main"} 0',
        'shunt_gate_outcomes_total{owner="forge-admin",repo="shadow-ci-driver",base="main",outcome="failure"} 3',
        'shunt_gate_outcomes_total{owner="forge-admin",repo="shadow-ci-driver",base="main",outcome="success"} 14',
        'shunt_time_in_queue_seconds_bucket{owner="forge-admin",repo="shadow-ci-driver",base="main",outcome="bounced",le="60"} 3',
        'shunt_time_in_queue_seconds_bucket{owner="forge-admin",repo="shadow-ci-driver",base="main",outcome="bounced",le="+Inf"} 3',
        'shunt_time_in_queue_seconds_sum{owner="forge-admin",repo="shadow-ci-driver",base="main",outcome="bounced"} 41.5',
        'shunt_time_in_queue_seconds_count{owner="forge-admin",repo="shadow-ci-driver",base="main",outcome="bounced"} 3',
    ]
)

SHA_12A = "aaaaaaaaaa1100000000000000000000000000aa"
SHA_12B = "bbbbbbbbbb2200000000000000000000000000bb"
SHA_16 = "cccccccccc1600000000000000000000000000cc"


def metrics_text(**over: int) -> str:
    vals = {"depth": 0, "bounces": 3, "merges": 14, "batches": 17, "staging": 0, "reconcile": 0}
    vals.update(over)
    labels = 'owner="forge-admin",repo="shadow-ci-driver",base="main"'
    return "\n".join(
        [
            "# TYPE shunt_queue_depth gauge",
            f"shunt_queue_depth{{{labels}}} {vals['depth']}",
            "# TYPE shunt_active_batch gauge",
            f"shunt_active_batch{{{labels}}} 0",
            "# TYPE shunt_batches_started_total counter",
            f"shunt_batches_started_total{{{labels}}} {vals['batches']}",
            "# TYPE shunt_pr_merges_total counter",
            f"shunt_pr_merges_total{{{labels}}} {vals['merges']}",
            "# TYPE shunt_bounces_total counter",
            f"shunt_bounces_total{{{labels}}} {vals['bounces']}",
            "# TYPE shunt_staging_conflicts_total counter",
            f"shunt_staging_conflicts_total{{{labels}}} {vals['staging']}",
            "# TYPE shunt_reconcile_errors_total counter",
            f"shunt_reconcile_errors_total{{{labels}}} {vals['reconcile']}",
            f'shunt_gate_outcomes_total{{{labels},outcome="failure"}} 3',
            f'shunt_gate_outcomes_total{{{labels},outcome="success"}} 14',
        ]
    )


def status_text(
    *,
    depth: int = 0,
    active: list[list[int]] | None = None,
    pending: list[list[int]] | None = None,
    active_flag: Any = False,
) -> str:
    return json.dumps(
        {
            "queues": [
                {
                    "owner": "forge-admin",
                    "repo": "shadow-ci-driver",
                    "base": "main",
                    "queue_depth": depth,
                    "active_batch": active_flag,
                    "active_batches": active or [],
                    "pending_batches": pending or [],
                }
            ]
        }
    )


def open_prs(pr_to_sha: dict[int, str]) -> str:
    return json.dumps(
        [
            {"number": n, "state": "open", "head": {"sha": s}, "base": {"ref": "main"}}
            for n, s in sorted(pr_to_sha.items())
        ]
    )


def mq_row(row_id: int, state: str, *, description: str = "", target_url: str = "") -> dict:
    return {
        "id": row_id,
        "context": "merge-queue",
        "status": state,
        "description": description,
        "target_url": target_url,
        "created_at": "2026-10-06T00:00:00Z",
        "updated_at": "2026-10-06T00:00:00Z",
    }


class FakeRunner:
    """CLI runner recording argv; fails (rc 1) for event ids placed in fail_on."""

    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on or set()

    def __call__(self, cmd: list[str], cwd: str) -> tuple[int, str]:
        self.calls.append(list(cmd))
        eid = cmd[cmd.index("--event-id") + 1]
        if eid in self.fail_on:
            return 1, json.dumps({"error": "append_failed"})
        return 0, json.dumps(
            {"event_id": eid, "appended": True, "spooled": False, "sequence": 1, "duplicate": False}
        )


def emitted_ids(runner: FakeRunner) -> list[str]:
    return [c[c.index("--event-id") + 1] for c in runner.calls]


def event_types(events: list[dict]) -> list[str]:
    return [e["event_type"] for e in events]


def by_type(events: list[dict], event_type: str) -> dict:
    matches = [e for e in events if e["event_type"] == event_type]
    assert len(matches) == 1, f"expected exactly one {event_type}, got {event_types(events)}"
    return matches[0]


# ---------------------------------------------------------------- parsers


def test_parse_status_live_idle_shape() -> None:
    queues = fqr.parse_status(LIVE_STATUS_IDLE)
    assert len(queues) == 1
    q = queues[0]
    assert (q["owner"], q["repo"], q["base"]) == ("forge-admin", "shadow-ci-driver", "main")
    assert q["depth"] == 0
    assert q["queued_prs"] == []


def test_parse_status_flattens_active_and_pending_batches() -> None:
    text = status_text(active=[[3, 4]], pending=[[12]])
    assert fqr.parse_status(text)[0]["queued_prs"] == [3, 4, 12]
    # Some shunt builds carry the batch under active_batch as a list of lists.
    legacy = status_text(active_flag=[[2]], pending=[[12]])
    assert fqr.parse_status(legacy)[0]["queued_prs"] == [2, 12]


def test_parse_metrics_live_shape_and_label_filtering() -> None:
    m = fqr.parse_metrics(LIVE_METRICS)
    assert m.total("shunt_bounces_total") == 3
    assert m.total("shunt_pr_merges_total") == 14
    assert m.total("shunt_batches_started_total") == 17
    assert m.total("shunt_staging_conflicts_total") == 0
    assert m.total("shunt_reconcile_errors_total") == 0
    assert m.total("shunt_queue_depth") == 0
    assert m.value("shunt_gate_outcomes_total", outcome="failure") == 3
    assert m.value("shunt_gate_outcomes_total", outcome="success") == 14
    assert m.value("shunt_gate_outcomes_total", outcome="missing") is None


def test_relevant_status_rows_filters_context_and_epoch() -> None:
    rows = [
        mq_row(9000, "failure", description="old bounce, pre-snapshot"),
        mq_row(9100, "pending"),
        {"id": 9101, "context": "ci/lint", "status": "failure", "description": "other context"},
        mq_row(9102, "failure", description="merge queue: PR rejected"),
    ]
    got = fqr.relevant_status_rows(rows, max_id=9000)
    assert [r["id"] for r in got] == [9100, 9102]


# ---------------------------------------------------------------- derive


def derive(
    state: dict,
    status: str,
    metrics: str,
    pulls: str,
    statuses_for: Callable[[int, str], list[dict]] | None = None,
) -> tuple[list[dict], dict]:
    return fqr.derive_events(state, status, metrics, pulls, statuses_for or (lambda pr, sha: []))


def test_first_run_emits_exactly_one_baseline() -> None:
    events, new_state = derive({}, LIVE_STATUS_IDLE, metrics_text(), "[]")
    assert event_types(events) == ["forge.queue.baseline"]
    payload = events[0]["payload"]
    assert payload["queue_depth"] == 0
    assert payload["counters"]["shunt_bounces_total"] == 3
    q = new_state["queues"][QUEUE_KEY]
    assert q["baseline_done"] is True
    assert q["queued"] == {}


def test_first_run_baseline_covers_queued_prs_without_entry_events() -> None:
    events, new_state = derive(
        {}, status_text(depth=1, pending=[[12]]), metrics_text(), open_prs({12: SHA_12A})
    )
    assert event_types(events) == ["forge.queue.baseline"]
    assert events[0]["payload"]["queued"] == {"12": SHA_12A}
    assert new_state["queues"][QUEUE_KEY]["queued"] == {"12": SHA_12A}


def test_entry_event_carries_head_sha() -> None:
    _, state = derive({}, LIVE_STATUS_IDLE, metrics_text(), "[]")
    events, new_state = derive(
        state, status_text(depth=1, pending=[[12]]), metrics_text(), open_prs({12: SHA_12A})
    )
    entry = by_type(events, "forge.queue.entry")
    assert entry["payload"] == {"pr": 12, "head_sha": SHA_12A}
    assert new_state["queues"][QUEUE_KEY]["queued"] == {"12": SHA_12A}


def test_update_event_on_head_sha_change() -> None:
    _, state = derive(
        {}, status_text(depth=1, pending=[[12]]), metrics_text(), open_prs({12: SHA_12A})
    )
    events, new_state = derive(
        state, status_text(depth=1, pending=[[12]]), metrics_text(), open_prs({12: SHA_12B})
    )
    update = by_type(events, "forge.queue.update")
    assert update["payload"]["old_head_sha"] == SHA_12A
    assert update["payload"]["new_head_sha"] == SHA_12B
    assert new_state["queues"][QUEUE_KEY]["queued"] == {"12": SHA_12B}
    assert "forge.queue.entry" not in event_types(events)


def test_ejection_event_requires_and_carries_reason() -> None:
    _, state = derive(
        {}, status_text(depth=1, pending=[[12]]), metrics_text(), open_prs({12: SHA_12A})
    )
    rows = [
        mq_row(9000, "pending", description="enqueued"),
        mq_row(
            9101,
            "failure",
            description="merge queue: PR rejected",
            target_url="http://forge.test/staging/9101",
        ),
    ]
    events, new_state = derive(
        state, LIVE_STATUS_IDLE, metrics_text(bounces=4), "[]", statuses_for=lambda pr, sha: rows
    )
    ejection = by_type(events, "forge.queue.ejection")
    assert ejection["payload"]["pr"] == 12
    assert ejection["payload"]["reason"] == "merge queue: PR rejected"
    assert ejection["payload"]["evidence"]["status_row_id"] == 9101
    assert ejection["payload"]["evidence"]["target_url"] == "http://forge.test/staging/9101"
    assert ejection["payload"]["bounces"] == [3, 4]
    assert new_state["queues"][QUEUE_KEY]["queued"] == {}
    assert new_state["queues"][QUEUE_KEY]["status_row_max"]["12"] == 9101


def test_ejection_fallback_reason_when_description_empty() -> None:
    _, state = derive(
        {}, status_text(depth=1, pending=[[12]]), metrics_text(), open_prs({12: SHA_12A})
    )
    rows = [mq_row(9101, "failure")]
    events, _ = derive(
        state, LIVE_STATUS_IDLE, metrics_text(bounces=4), "[]", statuses_for=lambda pr, sha: rows
    )
    ejection = by_type(events, "forge.queue.ejection")
    reason = ejection["payload"]["reason"]
    assert isinstance(reason, str) and reason.strip()
    assert "3" in reason and "4" in reason  # derived from the bounce counter movement


def test_merge_event_on_success_row() -> None:
    _, state = derive(
        {}, status_text(depth=1, pending=[[12]]), metrics_text(), open_prs({12: SHA_12A})
    )
    rows = [mq_row(9202, "success", target_url="http://forge.test/staging/9202")]
    events, new_state = derive(
        state, LIVE_STATUS_IDLE, metrics_text(merges=15), "[]", statuses_for=lambda pr, sha: rows
    )
    merge = by_type(events, "forge.queue.merge")
    assert merge["payload"]["evidence"]["status_row_id"] == 9202
    assert merge["payload"]["merges"] == [14, 15]
    assert new_state["queues"][QUEUE_KEY]["queued"] == {}


def test_departure_without_carrier_watches_then_depart_unknown_never_success() -> None:
    _, state = derive(
        {}, status_text(depth=1, pending=[[12]]), metrics_text(), open_prs({12: SHA_12A})
    )
    # R3: a departure with no verified carrier is never recorded as a merge/success.
    events, state = derive(state, LIVE_STATUS_IDLE, metrics_text(), "[]")
    assert events == []
    assert state["queues"][QUEUE_KEY]["watch"]["12"]["remaining"] == 2

    events, state = derive(state, LIVE_STATUS_IDLE, metrics_text(), "[]")
    assert events == []
    assert state["queues"][QUEUE_KEY]["watch"]["12"]["remaining"] == 1

    events, state = derive(state, LIVE_STATUS_IDLE, metrics_text(), "[]")
    assert event_types(events) == ["forge.queue.depart_unknown"]
    assert events[0]["payload"]["pr"] == 12
    assert "watch" not in state["queues"][QUEUE_KEY] or state["queues"][QUEUE_KEY]["watch"] == {}


def test_departure_with_counter_movement_but_no_carrier_is_not_merge() -> None:
    # Another PR's merge moved the merges counter; this departed PR has no own
    # merge-queue success row, so the relay must never claim a merge for it (R3).
    _, state = derive(
        {}, status_text(depth=1, pending=[[12]]), metrics_text(), open_prs({12: SHA_12A})
    )
    events, state = derive(state, LIVE_STATUS_IDLE, metrics_text(merges=15), "[]")
    assert events == []
    events, state = derive(state, LIVE_STATUS_IDLE, metrics_text(merges=15), "[]")
    assert events == []
    events, _ = derive(state, LIVE_STATUS_IDLE, metrics_text(merges=15), "[]")
    assert event_types(events) == ["forge.queue.depart_unknown"]


def test_late_carrier_upgrades_watch_to_ejection() -> None:
    _, state = derive(
        {}, status_text(depth=1, pending=[[12]]), metrics_text(), open_prs({12: SHA_12A})
    )
    events, state = derive(state, LIVE_STATUS_IDLE, metrics_text(bounces=4), "[]")
    assert events == []
    rows = [mq_row(9101, "failure", description="merge queue: PR rejected")]
    events, state = derive(
        state, LIVE_STATUS_IDLE, metrics_text(bounces=4), "[]", statuses_for=lambda pr, sha: rows
    )
    ejection = by_type(events, "forge.queue.ejection")
    assert ejection["payload"]["late"] is True
    assert ejection["payload"]["reason"] == "merge queue: PR rejected"
    assert state["queues"][QUEUE_KEY]["watch"] == {}


def test_identical_snapshots_emit_nothing() -> None:
    _, state = derive({}, LIVE_STATUS_IDLE, metrics_text(), "[]")
    events, _ = derive(state, LIVE_STATUS_IDLE, metrics_text(), "[]")
    assert events == []


def test_batch_event_on_batches_started_increase() -> None:
    _, state = derive({}, LIVE_STATUS_IDLE, metrics_text(), "[]")
    events, _ = derive(
        state,
        status_text(depth=2, active=[[12, 16]]),
        metrics_text(batches=18),
        open_prs({12: SHA_12A, 16: SHA_16}),
    )
    batch = by_type(events, "forge.queue.batch")
    assert batch["payload"]["batches_started"] == [17, 18]
    assert event_types(events).count("forge.queue.entry") == 2


def test_error_event_on_reconcile_increase() -> None:
    _, state = derive({}, LIVE_STATUS_IDLE, metrics_text(), "[]")
    events, _ = derive(state, LIVE_STATUS_IDLE, metrics_text(reconcile=1), "[]")
    error = by_type(events, "forge.queue.error")
    assert error["payload"]["counters"]["shunt_reconcile_errors_total"] == [0, 1]


def test_counter_reset_rebaseline_no_error_noise() -> None:
    # Shunt counters are per-process: a restart resets them to zero.
    _, state = derive({}, LIVE_STATUS_IDLE, metrics_text(), "[]")
    events, new_state = derive(
        state,
        LIVE_STATUS_IDLE,
        metrics_text(bounces=0, merges=0, batches=0),
        "[]",
    )
    assert event_types(events) == ["forge.queue.baseline"]
    assert events[0]["payload"]["restarted"] is True
    assert new_state["queues"][QUEUE_KEY]["counters"]["shunt_bounces_total"] == 0


def test_deterministic_event_ids_across_rederivations() -> None:
    _, state = derive(
        {}, status_text(depth=1, pending=[[12]]), metrics_text(), open_prs({12: SHA_12A})
    )
    rows = [mq_row(9101, "failure", description="merge queue: PR rejected")]
    args = (state, LIVE_STATUS_IDLE, metrics_text(bounces=4), "[]", lambda pr, sha: rows)
    first, _ = derive(*args)
    second, _ = derive(*args)
    assert [e["event_id"] for e in first] == [e["event_id"] for e in second]
    ejection = by_type(first, "forge.queue.ejection")
    assert "12" in ejection["event_id"] and "9101" in ejection["event_id"]


def test_subject_and_actor_shape() -> None:
    events, _ = derive({}, LIVE_STATUS_IDLE, metrics_text(), "[]")
    assert events[0]["subject"] == REPO
    _, state = derive(
        {}, status_text(depth=1, pending=[[12]]), metrics_text(), open_prs({12: SHA_12A})
    )
    events, _ = derive(
        state,
        LIVE_STATUS_IDLE,
        metrics_text(bounces=4),
        "[]",
        statuses_for=lambda pr, sha: [
            mq_row(9101, "failure", description="merge queue: PR rejected")
        ],
    )
    assert by_type(events, "forge.queue.ejection")["subject"] == f"{REPO}#12"


# ---------------------------------------------------------------- emit / run_once


def test_build_emit_command_uses_sanctioned_cli_shape() -> None:
    event = {
        "event_type": "forge.queue.baseline",
        "event_id": "fqr:baseline:x",
        "subject": REPO,
        "payload": {"queue_depth": 0},
    }
    cmd = fqr.build_emit_command(event, python_exe="/usr/bin/python3")
    assert cmd[:4] == ["/usr/bin/python3", "-m", "shared.coord_event_log", "append"]
    flags = {cmd[i]: cmd[i + 1] for i in range(4, len(cmd) - 1, 2)}
    assert flags["--event-type"] == "forge.queue.baseline"
    assert flags["--event-id"] == "fqr:baseline:x"
    assert flags["--subject"] == REPO
    assert flags["--actor"] == fqr.ACTOR
    assert flags["--origin"] == "forge-queue-relay"
    assert json.loads(flags["--payload"]) == {"queue_depth": 0}
    assert "--fail-open" in cmd


def test_emit_event_accepts_appended_spooled_and_duplicate() -> None:
    event = {"event_type": "forge.queue.baseline", "event_id": "e1", "subject": REPO, "payload": {}}
    for receipt in (
        {"appended": True, "spooled": False, "duplicate": False},
        {"appended": False, "spooled": True, "duplicate": False},
        {"appended": True, "spooled": False, "duplicate": True},
    ):
        assert fqr.emit_event(event, lambda cmd, cwd: (0, json.dumps(receipt)))
    assert not fqr.emit_event(event, lambda cmd, cwd: (1, json.dumps({"error": "append_failed"})))
    assert not fqr.emit_event(event, lambda cmd, cwd: (0, "not json"))


def make_fetch(
    status: str, metrics: str, pulls: str, statuses_by_sha: dict[str, list[dict]] | None = None
) -> Callable[[str], str]:
    statuses_by_sha = statuses_by_sha or {}

    def fetch(url: str) -> str:
        if url == f"{SHUNT_URL}/status":
            return status
        if url == f"{SHUNT_URL}/metrics":
            return metrics
        if url.startswith(f"{FORGE_URL}/api/v1/repos/{REPO}/pulls"):
            return pulls
        if "/statuses" in url:
            sha = url.split("/")[-2]
            return json.dumps(statuses_by_sha.get(sha, []))
        raise AssertionError(f"unexpected url {url}")

    return fetch


def run_once(
    state_path: Path,
    status: str,
    metrics: str,
    pulls: str,
    statuses_by_sha: dict[str, list[dict]] | None = None,
    runner: FakeRunner | None = None,
    dry_run: bool = False,
    fetch: Callable[[str], str] | None = None,
) -> tuple[int, list[dict], FakeRunner]:
    runner = runner or FakeRunner()
    rc, emitted = fqr.run_once(
        shunt_url=SHUNT_URL,
        forge_url=FORGE_URL,
        repo=REPO,
        state_path=state_path,
        fetch=fetch or make_fetch(status, metrics, pulls, statuses_by_sha),
        runner=runner,
        dry_run=dry_run,
    )
    return rc, emitted, runner


def test_run_once_end_to_end_baseline(tmp_path: Path) -> None:
    rc, emitted, runner = run_once(tmp_path / "state.json", LIVE_STATUS_IDLE, metrics_text(), "[]")
    assert rc == 0
    assert event_types(emitted) == ["forge.queue.baseline"]
    assert len(runner.calls) == 1
    assert (tmp_path / "state.json").exists()


def test_run_once_fetch_failure_no_emit_no_state_next_action(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(url: str) -> str:
        raise fqr.FetchError(f"connection refused for {url}")

    rc, emitted, runner = run_once(
        tmp_path / "state.json", LIVE_STATUS_IDLE, metrics_text(), "[]", fetch=broken
    )
    assert rc == 2
    assert emitted == []
    assert runner.calls == []
    assert not (tmp_path / "state.json").exists()
    err = capsys.readouterr().err
    assert "Next action" in err


def test_run_once_repo_mismatch_is_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = json.dumps(
        {
            "queues": [
                {
                    "owner": "forge-admin",
                    "repo": "other-repo",
                    "base": "main",
                    "queue_depth": 0,
                    "active_batch": False,
                    "active_batches": [],
                    "pending_batches": [],
                }
            ]
        }
    )
    rc, emitted, runner = run_once(tmp_path / "state.json", other, metrics_text(), "[]")
    assert rc == 2
    assert emitted == []
    assert runner.calls == []
    assert "Next action" in capsys.readouterr().err


def test_run_once_dry_run_emits_nothing_and_does_not_advance(tmp_path: Path) -> None:
    rc, emitted, runner = run_once(
        tmp_path / "state.json", LIVE_STATUS_IDLE, metrics_text(), "[]", dry_run=True
    )
    assert rc == 0
    assert event_types(emitted) == ["forge.queue.baseline"]
    assert runner.calls == []
    assert not (tmp_path / "state.json").exists()


def test_failed_emit_does_not_advance_state_and_redelivery_same_ids(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    rc, _, runner = run_once(state_path, LIVE_STATUS_IDLE, metrics_text(), "[]")
    assert rc == 0
    baseline_id = emitted_ids(runner)[0]

    # Next run derives entry(12) + batch(18); the batch emit fails.
    rc, derived, _ = run_once(
        state_path,
        status_text(depth=1, pending=[[12]]),
        metrics_text(batches=18),
        open_prs({12: SHA_12A}),
        dry_run=True,
    )
    assert rc == 0 and len(derived) == 2
    fail_runner = FakeRunner(fail_on={derived[1]["event_id"]})
    rc, emitted, runner2 = run_once(
        state_path,
        status_text(depth=1, pending=[[12]]),
        metrics_text(batches=18),
        open_prs({12: SHA_12A}),
        runner=fail_runner,
    )
    assert rc == 3
    assert not any(e["event_type"] == "forge.queue.baseline" for e in emitted)
    # State was not advanced: the queue entry is still unseen on the next run.
    assert json.loads(state_path.read_text())["queues"][QUEUE_KEY]["queued"] == {}

    ok_runner = FakeRunner()
    rc, emitted, runner3 = run_once(
        state_path,
        status_text(depth=1, pending=[[12]]),
        metrics_text(batches=18),
        open_prs({12: SHA_12A}),
        runner=ok_runner,
    )
    assert rc == 0
    assert emitted_ids(runner3) == emitted_ids(runner2)
    assert baseline_id not in emitted_ids(runner3)
    assert json.loads(state_path.read_text())["queues"][QUEUE_KEY]["queued"] == {"12": SHA_12A}


def test_state_roundtrip_and_default_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "schema": 1,
        "queues": {
            QUEUE_KEY: {
                "baseline_done": True,
                "queued": {},
                "counters": {},
                "status_row_max": {},
                "watch": {},
            }
        },
    }
    path = tmp_path / "state.json"
    fqr.save_state(path, state)
    assert fqr.load_state(path) == state
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    assert fqr.default_state_path() == tmp_path / "coord" / "forge-queue-relay-state.json"
    monkeypatch.delenv("HAPAX_COORD_DIR")
    assert fqr.default_state_path() == Path.home() / ".cache" / "hapax" / "coord" / (
        "forge-queue-relay-state.json"
    )


def test_forge_headers_only_for_forge_urls() -> None:
    token = "t-never-printed"
    assert fqr.forge_headers(FORGE_URL, f"{FORGE_URL}/api/v1/repos/x/y/pulls", token) == {
        "Authorization": f"token {token}"
    }
    assert fqr.forge_headers(FORGE_URL, f"{SHUNT_URL}/status", token) == {}
    assert fqr.forge_headers(FORGE_URL, f"{FORGE_URL}/api/v1/repos/x/y/pulls", "") == {}


def test_main_end_to_end_with_fakes(tmp_path: Path) -> None:
    runner = FakeRunner()
    rc = fqr.main(
        [
            "--once",
            "--shunt-url",
            SHUNT_URL,
            "--forge-url",
            FORGE_URL,
            "--repo",
            REPO,
            "--state-path",
            str(tmp_path / "state.json"),
        ],
        fetch=make_fetch(LIVE_STATUS_IDLE, metrics_text(), "[]"),
        runner=runner,
    )
    assert rc == 0
    assert len(runner.calls) == 1
    assert (tmp_path / "state.json").exists()


def test_main_dry_run_prints_derived_events(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = fqr.main(
        [
            "--once",
            "--dry-run",
            "--shunt-url",
            SHUNT_URL,
            "--forge-url",
            FORGE_URL,
            "--repo",
            REPO,
            "--state-path",
            str(tmp_path / "state.json"),
        ],
        fetch=make_fetch(LIVE_STATUS_IDLE, metrics_text(), "[]"),
        runner=FakeRunner(),
    )
    assert rc == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1
    printed = json.loads(lines[0])
    assert printed["event_type"] == "forge.queue.baseline"
    assert not (tmp_path / "state.json").exists()


def test_relay_units_are_parked_and_never_auto_enabled() -> None:
    """Merging must install nothing live. hapax-post-merge-deploy `enable --now`s a new timer
    that carries `Hapax-Auto-Enable: true` (or no marker), which would start a two-minute relay
    writing shadow queue events into the production coord log. Enabling stays the seat act of
    forge-s2-merge-queue-shadow-live-20261010."""
    import re

    parked = re.compile(r"(?mi)^[#;][ \t]*Hapax-Parked:[ \t]*(?:true|yes|1)[ \t]*$")
    auto_enable = re.compile(r"(?mi)^[#;][ \t]*Hapax-Auto-Enable:[ \t]*(?:true|yes|1)[ \t]*$")
    for unit in ("forge-queue-relay.service", "forge-queue-relay.timer"):
        text = (REPO_ROOT / "systemd" / "units" / unit).read_text(encoding="utf-8")
        assert parked.search(text), unit
        assert not auto_enable.search(text), unit
