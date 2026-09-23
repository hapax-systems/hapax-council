"""Exercise timer rotation through listing, disk state, hydration and reconciliation."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from math import ceil
from pathlib import Path
from typing import Any

import pytest

from tests.test_cc_pr_autoqueue import _FakeRunner, _pr, autoqueue


class RotationRunner(_FakeRunner):
    def __init__(self, count: int, transport: str = "rest") -> None:
        super().__init__()
        self.open_prs = [_pr(number=number) for number in range(count, 0, -1)]
        self.transport = transport
        self.broken: str | None = None
        self.fail_graphql_listing = False
        self.first_page_count_delta = 0
        self.listing_returncode = 0
        self.fail_hydration: set[int] = set()

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            self.calls.append(cmd)
            payload = {
                "resources": {
                    pool: {"remaining": remaining, "limit": 5000, "reset": 1893456000}
                    for pool, remaining in (
                        ("core", 5000 if self.transport == "rest" else 0),
                        ("graphql", 5000),
                    )
                }
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if "--include" in cmd and "repos/owner/repo/pulls" in cmd:
            self.calls.append(cmd)
            page = int(self._fields(cmd)["page"])
            rows = self.open_prs[(page - 1) * 100 : page * 100]
            headers = "HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n"
            if page * 100 < len(self.open_prs):
                headers += f'Link: <https://api.github.com/repos/owner/repo/pulls?page={page + 1}>; rel="next"\r\n'
            body = json.dumps([self._rest_pr(row) for row in rows])
            if self.broken == "missing_marker":
                return subprocess.CompletedProcess(cmd, 0, body, "")
            if self.broken == "headers_absent":
                # Keep the body separator so deleting the envelope guard cannot
                # hide behind an unrelated tuple-unpacking or JSON parse failure.
                headers = ""
            if self.broken == "malformed_link":
                headers += "Link: truncated\r\n"
            return subprocess.CompletedProcess(
                cmd,
                self.listing_returncode,
                headers.rstrip("\r\n") + "\r\n\r\n" + body,
                "listing failed" if self.listing_returncode else "",
            )
        if cmd[:3] == ["gh", "api", "graphql"] and any("pullRequests(" in p for p in cmd):
            self.calls.append(cmd)
            if self.fail_graphql_listing:
                return subprocess.CompletedProcess(cmd, 1, "", "GraphQL unavailable")
            offset = int(self._fields(cmd).get("cursor", "0"))
            rows = self.open_prs[offset : offset + 100]
            connection = {
                "totalCount": len(self.open_prs)
                + (self.first_page_count_delta if offset == 0 else 0),
                "pageInfo": {
                    "hasNextPage": offset + 100 < len(self.open_prs),
                    "endCursor": str(offset + len(rows)),
                },
                "nodes": [
                    {
                        **{
                            key: row[key]
                            for key in ("number", "headRefOid", "headRefName", "baseRefName")
                        },
                        "autoMergeRequest": row.get("autoMergeRequest"),
                    }
                    for row in rows
                ],
            }
            if self.broken == "missing_marker":
                connection.pop("pageInfo")
            elif self.broken == "truncated":
                connection["totalCount"] += 1
            elif self.broken == "duplicate":
                connection["nodes"].append(connection["nodes"][0])
            elif self.broken == "errors":
                return subprocess.CompletedProcess(cmd, 0, '{"errors":[{"message":"timeout"}]}', "")
            elif self.broken == "malformed_link":
                return subprocess.CompletedProcess(cmd, 1, "", "GraphQL unavailable")
            payload = {
                "data": {
                    "repository": {"pullRequests": connection, "defaultBranchRef": {"name": "main"}}
                }
            }
            return subprocess.CompletedProcess(
                cmd,
                self.listing_returncode,
                json.dumps(payload),
                "listing failed" if self.listing_returncode else "",
            )
        if cmd[:3] == ["gh", "pr", "view"]:
            self.calls.append(cmd)
            if int(cmd[3]) in self.fail_hydration:
                return subprocess.CompletedProcess(cmd, 1, "", "persistent hydration failure")
            row = next(row for row in self.open_prs if str(row["number"]) == cmd[3])
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps({**row, "url": f"https://github.com/owner/repo/pull/{row['number']}"}),
                "",
            )
        if any(f"repos/owner/repo/pulls/{number}/files" in cmd for number in self.fail_hydration):
            self.calls.append(cmd)
            # A files command error can become a normal fail-closed partial row;
            # a timeout exercises the REST hydration exception boundary instead.
            raise subprocess.TimeoutExpired(cmd, 45)
        return super().__call__(cmd, **kwargs)

    def hydrated_numbers(self) -> set[int]:
        numbers = set()
        for cmd in self.calls:
            if cmd[:3] == ["gh", "pr", "view"]:
                numbers.add(int(cmd[3]))
            for arg in cmd:
                match = re.fullmatch(r"repos/owner/repo/pulls/(\d+)(?:/files|/reviews)?", arg)
                if match:
                    numbers.add(int(match[1]))
        return numbers


def tick(
    tmp_path: Path,
    runner: RotationRunner,
    *,
    limit: int = 5,
    module: Any = autoqueue,
    apply: bool = True,
) -> dict:
    return module.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=tmp_path / "tasks",
        runner=runner,
        apply=apply,
        limit=limit,
        rotation_state_path=tmp_path / "examined.json",
        lineage_ledger_path=None,
        quarantine_path=tmp_path / "quarantine.json",
        admission_governor_path=tmp_path / "governor.yaml",
    )


def examined(report: dict) -> list[int]:
    assert not report.get("skipped"), report
    return [decision["pr"] for decision in report["decisions"]]


@pytest.mark.parametrize("transport", ["rest", "graphql"])
def test_autoqueue_disjoint_ticks_cover_estate_and_repeat_oldest(
    tmp_path: Path, transport: str
) -> None:
    runner = RotationRunner(25, transport)
    windows = []
    for _ in range(5):
        runner.calls.clear()
        report = tick(tmp_path, runner)
        window = examined(report)
        assert len(window) == 5
        assert runner.hydrated_numbers() == set(window)
        assert report["open_pr_count"] == report["storm_mode"]["open_pr_count"] == 25
        assert report["examined_pr_count"] == 5
        assert not set(window).intersection(number for previous in windows for number in previous)
        windows.append(window)
    assert windows == [list(range(start, start + 5)) for start in range(1, 26, 5)]
    assert examined(tick(tmp_path, runner)) == windows[0]


def test_autoqueue_never_examined_precedes_previous_tick_and_new_pr(tmp_path: Path) -> None:
    runner = RotationRunner(12)
    assert examined(tick(tmp_path, runner)) == [1, 2, 3, 4, 5]
    runner.open_prs.append(_pr(number=80))
    assert examined(tick(tmp_path, runner)) == [6, 7, 8, 9, 10]
    assert examined(tick(tmp_path, runner)) == [11, 12, 80, 1, 2]


def test_autoqueue_all_79_prs_reached_within_16_ticks(tmp_path: Path) -> None:
    runner = RotationRunner(79)
    visited = []
    for _ in range(16):
        visited.extend(examined(tick(tmp_path, runner)))
    assert visited[:79] == list(range(1, 80))
    assert visited[79:] == [1]


@pytest.mark.parametrize("transport", ["rest", "graphql"])
def test_autoqueue_explicitly_complete_empty_estate_is_quiet(
    tmp_path: Path, transport: str
) -> None:
    runner = RotationRunner(0, transport)
    report = tick(tmp_path, runner)
    assert examined(report) == []
    assert report["open_pr_count"] == report["examined_pr_count"] == 0
    assert not runner.hydrated_numbers()


def test_autoqueue_closed_prs_are_pruned_and_repositories_are_isolated(tmp_path: Path) -> None:
    runner = RotationRunner(10)
    tick(tmp_path, runner)
    runner.open_prs = [row for row in runner.open_prs if row["number"] > 5]
    assert examined(tick(tmp_path, runner)) == [6, 7, 8, 9, 10]
    state_path = tmp_path / "examined.json"
    state = json.loads(state_path.read_text())
    assert set(state["repositories"]["owner/repo"]) == {"6", "7", "8", "9", "10"}
    selected = autoqueue._select_pr_window(
        runner.open_prs, repo="other/repo", limit=2, state_path=state_path, persist=True
    )
    assert [row["number"] for row in selected.rotation_rows] == [6, 7]
    assert (
        json.loads(state_path.read_text())["repositories"]["owner/repo"]
        == state["repositories"]["owner/repo"]
    )


def test_autoqueue_rotation_survives_module_restart(tmp_path: Path) -> None:
    assert examined(tick(tmp_path, RotationRunner(15))) == [1, 2, 3, 4, 5]
    state = json.loads((tmp_path / "examined.json").read_text())
    assert set(state["repositories"]["owner/repo"]) == {"1", "2", "3", "4", "5"}
    module_name = "cc_pr_autoqueue_rotation_restart"
    spec = importlib.util.spec_from_file_location(module_name, autoqueue.__file__)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        assert examined(tick(tmp_path, RotationRunner(15), module=module)) == [6, 7, 8, 9, 10]
    finally:
        sys.modules.pop(module_name)
    assert examined(tick(tmp_path, RotationRunner(15))) == [11, 12, 13, 14, 15]


@pytest.mark.parametrize("transport", ["rest", "graphql"])
def test_autoqueue_lists_every_page_before_hydrating_a_bounded_window(
    tmp_path: Path, transport: str
) -> None:
    runner = RotationRunner(203, transport)
    report = tick(tmp_path, runner)
    assert report["open_pr_count"] == 203
    assert examined(report) == [1, 2, 3, 4, 5]
    assert runner.hydrated_numbers() == {1, 2, 3, 4, 5}


@pytest.mark.parametrize(
    "transport,broken",
    [
        ("rest", "missing_marker"),
        ("rest", "malformed_link"),
        ("graphql", "missing_marker"),
        ("graphql", "truncated"),
        ("graphql", "duplicate"),
        ("graphql", "errors"),
    ],
)
def test_autoqueue_indeterminate_listing_refuses_before_reconciliation(
    tmp_path: Path, transport: str, broken: str
) -> None:
    runner = RotationRunner(79, transport)
    runner.broken = broken
    report = tick(tmp_path, runner)
    assert report["skipped"] is True
    assert report["reason"].startswith("open_pr_scan_indeterminate:")
    assert report["decisions"] == report["mutations"] == []
    assert runner.hydrated_numbers() == set()
    assert not (tmp_path / "examined.json").exists()


def assert_listing_refused_without_advancing(
    tmp_path: Path, runner: RotationRunner, previous_state: bytes
) -> None:
    report = tick(tmp_path, runner)
    assert report.get("skipped") is True
    assert report["decisions"] == report["mutations"] == []
    assert not runner.hydrated_numbers()
    assert (tmp_path / "examined.json").read_bytes() == previous_state


def test_autoqueue_rest_rows_without_pagination_headers_refuse(tmp_path: Path) -> None:
    runner = RotationRunner(79)
    runner.fail_graphql_listing = True
    assert examined(tick(tmp_path, runner)) == [1, 2, 3, 4, 5]
    previous_state = (tmp_path / "examined.json").read_bytes()
    runner.calls.clear()
    # Valid rows, but neither an HTTP envelope nor Link/end-of-pagination evidence.
    runner.broken = "headers_absent"
    assert_listing_refused_without_advancing(tmp_path, runner, previous_state)
    listing_calls = [cmd for cmd in runner.calls if "repos/owner/repo/pulls" in cmd]
    assert [runner._fields(cmd)["page"] for cmd in listing_calls] == ["1"]


@pytest.mark.parametrize("first_page_count_delta", [-1, 1], ids=["increases", "decreases"])
def test_autoqueue_open_pr_count_changes_between_pages_refuse(
    tmp_path: Path, first_page_count_delta: int
) -> None:
    runner = RotationRunner(101, "graphql")
    assert examined(tick(tmp_path, runner)) == [1, 2, 3, 4, 5]
    previous_state = (tmp_path / "examined.json").read_bytes()
    runner.calls.clear()
    # Page one's count differs; the terminal count still matches the 101 rows.
    # Removing the change guard must not get caught by the final-count guard.
    runner.first_page_count_delta = first_page_count_delta
    assert_listing_refused_without_advancing(tmp_path, runner, previous_state)
    listing_calls = [cmd for cmd in runner.calls if any("pullRequests(" in arg for arg in cmd)]
    assert [runner._fields(cmd).get("cursor") for cmd in listing_calls] == [None, "100"]


@pytest.mark.parametrize("transport", ["rest", "graphql"])
def test_autoqueue_failed_listing_with_parseable_stdout_refuses(
    tmp_path: Path, transport: str
) -> None:
    runner = RotationRunner(79, transport)
    runner.fail_graphql_listing = transport == "rest"
    assert examined(tick(tmp_path, runner)) == [1, 2, 3, 4, 5]
    previous_state = (tmp_path / "examined.json").read_bytes()
    runner.calls.clear()
    # A failed gh command can leave valid-looking stdout. Its exit status must
    # independently veto reconciliation, without relying on a parsing failure.
    runner.listing_returncode = 1
    assert_listing_refused_without_advancing(tmp_path, runner, previous_state)


def test_autoqueue_dry_run_previews_without_advancing(tmp_path: Path) -> None:
    runner = RotationRunner(10)
    assert examined(tick(tmp_path, runner, apply=False)) == [1, 2, 3, 4, 5]
    assert not (tmp_path / "examined.json").exists()
    tick(tmp_path, runner)
    before = (tmp_path / "examined.json").read_bytes()
    assert examined(tick(tmp_path, runner, apply=False)) == [6, 7, 8, 9, 10]
    assert (tmp_path / "examined.json").read_bytes() == before


def test_autoqueue_corrupt_state_refuses_without_hydration(tmp_path: Path) -> None:
    (tmp_path / "examined.json").write_text("{broken")
    runner = RotationRunner(10)
    report = tick(tmp_path, runner)
    assert report["reason"] == "open_pr_scan_indeterminate:rotation_state_unavailable_or_invalid"
    assert report["decisions"] == report["mutations"] == []
    assert not runner.hydrated_numbers()


def test_autoqueue_equal_tick_times_still_rotate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return cls(2026, 9, 20, tzinfo=UTC)

    monkeypatch.setattr(autoqueue, "datetime", FrozenDateTime)
    runner = RotationRunner(10)
    assert examined(tick(tmp_path, runner)) == [1, 2, 3, 4, 5]
    assert examined(tick(tmp_path, runner)) == [6, 7, 8, 9, 10]
    assert examined(tick(tmp_path, runner)) == [1, 2, 3, 4, 5]
    assert examined(tick(tmp_path, runner)) == [6, 7, 8, 9, 10]


def test_autoqueue_cli_uses_persistent_rotation_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    state_path = tmp_path / "examined.json"
    monkeypatch.setattr(autoqueue, "DEFAULT_ROTATION_STATE_PATH", state_path)
    monkeypatch.setattr(autoqueue.subprocess, "run", RotationRunner(10))
    args = [
        "--repo",
        "owner/repo",
        "--repo-root",
        str(tmp_path),
        "--vault-root",
        str(tmp_path / "tasks"),
        "--apply",
        "--limit",
        "5",
        "--no-write-report",
        "--lineage-ledger-path",
        str(tmp_path / "lineage.jsonl"),
    ]
    for expected in ([1, 2, 3, 4, 5], [6, 7, 8, 9, 10]):
        assert autoqueue.main(args) == 0
        assert examined(json.loads(capsys.readouterr().out)) == expected
    assert autoqueue.DEFAULT_REPORT_PATH.parent == Path.home() / ".cache/hapax/orchestration"


@pytest.mark.parametrize("limit", [0, -1])
def test_autoqueue_rejects_nonpositive_tick_limit(tmp_path: Path, limit: int) -> None:
    with pytest.raises(ValueError, match="limit must be positive"):
        tick(tmp_path, RotationRunner(10), limit=limit)


@pytest.mark.parametrize("transport", ["rest", "graphql"])
@pytest.mark.parametrize("count,limit", [(10, 5), (6, 1)])
def test_autoqueue_repeated_hydration_failure_cannot_starve_healthy_prs(
    tmp_path: Path, transport: str, count: int, limit: int
) -> None:
    # A single-slot window must also progress; merely continuing peers cannot fix it.
    runner = RotationRunner(count, transport)
    runner.fail_hydration = {1}
    healthy = set(range(2, count + 1))
    first_sweep_ticks = ceil((count + 1) / limit)  # One immediate retry, then fair rotation.
    for sweep_ticks in (first_sweep_ticks, ceil(count / limit), ceil(count / limit)):
        reconciled = set()
        for _ in range(sweep_ticks):
            runner.calls.clear()
            report = tick(tmp_path, runner, limit=limit)
            window = examined(report)
            reconciled.update(window)
            assert len(runner.hydrated_numbers()) <= limit
            assert 1 not in window
            assert report["examined_pr_count"] == len(window)
            assert report["open_pr_count"] == count
            state = json.loads((tmp_path / "examined.json").read_text())
            assert "1" not in state["repositories"]["owner/repo"]
            failure = report["hydration_failures"][0]
            assert failure["pr"] == 1
            assert failure["reason"]
            assert failure["next_action"]
            assert failure["attempted_this_tick"] == (1 in runner.hydrated_numbers())
            assert (
                failure["consecutive_failures"]
                == state["hydration_failures"]["owner/repo"]["1"]["consecutive_failures"]
            )
        assert reconciled == healthy
    assert failure["consecutive_failures"] >= 4  # Failed PR keeps returning, never vanishes.


@pytest.mark.parametrize("transport", ["rest", "graphql"])
def test_autoqueue_failed_hydration_keeps_old_timestamp_and_continues_peers(
    tmp_path: Path, transport: str
) -> None:
    runner = RotationRunner(5, transport)
    tick(tmp_path, runner)
    state_path = tmp_path / "examined.json"
    before = json.loads(state_path.read_text())["repositories"]["owner/repo"]
    runner.fail_hydration = {1}
    report = tick(tmp_path, runner)
    assert examined(report) == [2, 3, 4, 5]
    after = json.loads(state_path.read_text())["repositories"]["owner/repo"]
    assert after["1"] == before["1"]
    assert all(after[str(number)] > before[str(number)] for number in range(2, 6))
    assert report["hydration_failures"][0]["consecutive_failures"] == 1


def test_autoqueue_interrupted_reconciliation_acknowledges_only_completed_prs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = RotationRunner(3, "graphql")
    tick(tmp_path, runner)
    state_path = tmp_path / "examined.json"
    before = json.loads(state_path.read_text())["repositories"]["owner/repo"]
    original = autoqueue.set_autoqueue_admission_status

    def interrupt(decision: Any, **kwargs: Any) -> Any:
        if decision.pr.number == 2:
            raise RuntimeError("interrupted reconciliation")
        return original(decision, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(autoqueue, "set_autoqueue_admission_status", interrupt)
        with pytest.raises(RuntimeError, match="interrupted reconciliation"):
            tick(tmp_path, runner)
    after = json.loads(state_path.read_text())["repositories"]["owner/repo"]
    assert after["1"] > before["1"]
    assert after["2"] == before["2"]
    assert after["3"] == before["3"]  # Hydrated/selected, but never reconciled.
    assert examined(tick(tmp_path, runner, limit=1)) == [2]


def test_autoqueue_retry_policy_and_pending_failure_survive_restart_and_recovery(
    tmp_path: Path,
) -> None:
    for attempts in (1, 2):
        runner = RotationRunner(3, "graphql")  # Fresh caller, same disk state.
        runner.fail_hydration = {1}
        report = tick(tmp_path, runner, limit=1)
        assert examined(report) == []
        assert runner.hydrated_numbers() == {1}
        failure = report["hydration_failures"][0]
        assert failure["consecutive_failures"] == attempts
        assert failure["retry_policy"] == ("next_tick" if attempts == 1 else "fair_rotation")
    runner = RotationRunner(3, "graphql")
    for number in (2, 3):
        report = tick(tmp_path, runner, limit=1)
        assert examined(report) == [number]
        assert report["hydration_failures"][0]["pr"] == 1
        assert report["hydration_failures"][0]["attempted_this_tick"] is False
    assert examined(report := tick(tmp_path, runner, limit=1)) == [1]
    assert report["hydration_failures"] == []
    state = json.loads((tmp_path / "examined.json").read_text())
    assert state["hydration_failures"]["owner/repo"] == {}
    assert "1" in state["repositories"]["owner/repo"]
    for _ in range(2):
        tick(tmp_path, runner, limit=1)
    runner.fail_hydration = {1}
    report = tick(tmp_path, runner, limit=1)
    assert report["hydration_failures"][0]["consecutive_failures"] == 1
    assert report["hydration_failures"][0]["retry_policy"] == "next_tick"


def test_autoqueue_failed_hydration_dry_run_does_not_persist_retry_state(tmp_path: Path) -> None:
    runner = RotationRunner(3, "graphql")
    runner.fail_hydration = {1}
    report = tick(tmp_path, runner, apply=False)
    assert examined(report) == [2, 3]
    assert report["hydration_failures"][0]["consecutive_failures"] == 1
    state_path = tmp_path / "examined.json"
    assert not state_path.exists()
    tick(tmp_path, runner)
    before = state_path.read_bytes()
    tick(tmp_path, runner, apply=False)
    assert state_path.read_bytes() == before


@pytest.mark.parametrize("bad_identity", ["missing", "mismatch"])
def test_autoqueue_unusable_hydrated_identity_is_a_visible_per_pr_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_identity: str
) -> None:
    original = autoqueue._hydrate_open_prs

    def hydrate(raw: Any, route: Any, **kwargs: Any) -> Any:
        prs, route = original(raw, route, **kwargs)
        if raw[0]["number"] == 1:
            prs = [] if bad_identity == "missing" else [autoqueue.replace(prs[0], number=99)]
        return prs, route

    monkeypatch.setattr(autoqueue, "_hydrate_open_prs", hydrate)
    report = tick(tmp_path, RotationRunner(3, "graphql"))
    assert examined(report) == [2, 3]
    assert report["hydration_failures"][0]["reason"] == "selected_pr_hydration_identity_invalid"
    assert set(
        json.loads((tmp_path / "examined.json").read_text())["repositories"]["owner/repo"]
    ) == {"2", "3"}


@pytest.mark.parametrize(
    "field,value", [("consecutive_failures", 0), ("consecutive_failures", True), ("reason", None)]
)
def test_autoqueue_corrupt_retry_state_refuses_without_hydration(
    tmp_path: Path, field: str, value: Any
) -> None:
    runner = RotationRunner(3, "graphql")
    runner.fail_hydration = {1}
    tick(tmp_path, runner)
    state_path = tmp_path / "examined.json"
    state = json.loads(state_path.read_text())
    state["hydration_failures"]["owner/repo"]["1"][field] = value
    state_path.write_text(json.dumps(state))
    previous = state_path.read_bytes()
    runner.calls.clear()
    report = tick(tmp_path, runner)
    assert report["reason"] == "open_pr_scan_indeterminate:rotation_state_unavailable_or_invalid"
    assert report["decisions"] == report["mutations"] == []
    assert not runner.hydrated_numbers()
    assert state_path.read_bytes() == previous


def _admission_status(
    state: str,
    *,
    age_minutes: float,
    description: str = "cc-pr-autoqueue admitted: queue",
) -> dict[str, Any]:
    created = datetime.now(UTC) - timedelta(minutes=age_minutes)
    return {
        "context": autoqueue.AUTOQUEUE_ADMISSION_CONTEXT,
        "state": state,
        "description": description,
        "created_at": created.isoformat(),
    }


def _status_posts(runner: RotationRunner, sha: str) -> list[list[str]]:
    return [
        cmd
        for cmd in runner.calls
        if cmd[:4] == ["gh", "api", "-X", "POST"] and f"repos/owner/repo/statuses/{sha}" in cmd
    ]


MUST_INCLUDE_STATE_NAME = "examined.json.must-include.json"


def test_autoqueue_queued_pr_proof_refreshed_within_one_reconcile(tmp_path: Path) -> None:
    # R1 control-flow proof: a queued PR at proof age 16 min receives a status
    # POST inside ONE reconcile call, without full hydration.
    runner = RotationRunner(25)
    runner.queued_prs = {13}
    runner.head_statuses["sha-13"] = [_admission_status("success", age_minutes=16)]
    report = tick(tmp_path, runner)
    assert not report.get("skipped"), report
    assert _status_posts(runner, "sha-13")
    assert 13 not in runner.hydrated_numbers()
    assert 13 not in examined(report)
    assert len(examined(report)) == 4  # Window stays 5 wide: 1 must + 4 rotation.
    state = json.loads((tmp_path / "examined.json").read_text())
    assert "13" in state["repositories"]["owner/repo"]  # Rotation ack stamped.
    assert report["must_include"]["refreshed"] == [13]


def test_autoqueue_armed_pr_is_must_include(tmp_path: Path) -> None:
    # R2: auto-merge-armed PRs (pre-queue gap) refresh even when not queued.
    runner = RotationRunner(25)
    runner.open_prs[6]["autoMergeRequest"] = {"mergeMethod": "SQUASH"}  # PR #19
    runner.head_statuses["sha-19"] = [_admission_status("success", age_minutes=16)]
    report = tick(tmp_path, runner)
    assert _status_posts(runner, "sha-19")
    assert 19 not in runner.hydrated_numbers()
    assert 19 not in examined(report)


def test_autoqueue_fresh_must_include_proof_not_reposted(tmp_path: Path) -> None:
    # R4: the refresh margin is one tick, not TTL/2 — a 2-minute-old proof is
    # left alone, and no POST is spent on it.
    runner = RotationRunner(25)
    runner.queued_prs = {13}
    runner.head_statuses["sha-13"] = [_admission_status("success", age_minutes=2)]
    report = tick(tmp_path, runner)
    assert not _status_posts(runner, "sha-13")
    assert report["must_include"]["ok"] == [13]
    state = json.loads((tmp_path / "examined.json").read_text())
    assert "13" in state["repositories"]["owner/repo"]


def test_autoqueue_must_include_cap_overflow_and_post_cap(tmp_path: Path) -> None:
    # R5: cap, not dominance. 12 must-include PRs at limit 5: 8 served by the
    # guarantee, 4 POSTs per tick, 2 rotation slots preserved, overflow reported.
    runner = RotationRunner(25)
    runner.queued_prs = set(range(1, 13))
    for number in range(1, 13):
        runner.head_statuses[f"sha-{number}"] = [_admission_status("success", age_minutes=16)]
    report = tick(tmp_path, runner)
    must_include = report["must_include"]
    assert must_include["refreshed"] == [1, 2, 3, 4]
    assert [
        number
        for number in range(1, 13)
        if must_include["deferred"].get(str(number)) == "deferred_post_cap"
    ] == [5, 6, 7, 8]
    assert must_include["overflow"] == [9, 10, 11, 12]
    assert len(examined(report)) == 2
    assert runner.hydrated_numbers() == {9, 10}  # Overflow rows may win rotation slots.


def test_autoqueue_indeterminate_queue_snapshot_refreshes_persisted_set(
    tmp_path: Path,
) -> None:
    # R3: an indeterminate merge-queue probe runs a refresh-only pass for the
    # persisted last-known set, then skips the cycle as before.
    runner = RotationRunner(25)
    runner.queued_prs = {7}
    runner.head_statuses["sha-7"] = [_admission_status("success", age_minutes=16)]
    tick(tmp_path, runner)
    assert (tmp_path / MUST_INCLUDE_STATE_NAME).exists()
    runner.merge_queue_stdout = "not-json"
    runner.calls.clear()
    report = tick(tmp_path, runner)
    assert report["skipped"] is True
    assert report["reason"] == "merge_queue_state_indeterminate"
    assert _status_posts(runner, "sha-7")
    assert not runner.hydrated_numbers()
    assert not any(
        "repos/owner/repo/pulls" in arg or "pullRequests(" in arg
        for cmd in runner.calls
        for arg in cmd
    )
    assert report["must_include"]["refreshed"] == [7]


def test_autoqueue_expired_persisted_must_include_entry_is_dropped(tmp_path: Path) -> None:
    # R3: the persisted set lives no longer than the proof TTL it protects.
    runner = RotationRunner(25)
    runner.queued_prs = {7}
    runner.head_statuses["sha-7"] = [_admission_status("success", age_minutes=16)]
    tick(tmp_path, runner)
    state_path = tmp_path / MUST_INCLUDE_STATE_NAME
    state = json.loads(state_path.read_text())
    entry = state["repositories"]["owner/repo"]["7"]
    entry["last_seen_at"] = (datetime.now(UTC) - timedelta(minutes=45)).isoformat()
    state_path.write_text(json.dumps(state))
    runner.merge_queue_stdout = "not-json"
    runner.calls.clear()
    report = tick(tmp_path, runner)
    assert report["skipped"] is True
    assert report["must_include"]["ok"] == []
    assert not _status_posts(runner, "sha-7")


def test_autoqueue_dequeued_pr_gets_one_shot_full_exam(tmp_path: Path) -> None:
    # R6: a PR that left the merge queue (still open) gets exactly one full
    # exam, not a permanent must-include seat.
    runner = RotationRunner(25)
    runner.queued_prs = {9}
    runner.head_statuses["sha-9"] = [_admission_status("success", age_minutes=16)]
    tick(tmp_path, runner)
    # Queued: served by the cheap refresh path, not a full exam/hydration.
    assert 9 not in runner.hydrated_numbers()
    runner.queued_prs = set()
    report = tick(tmp_path, runner)
    assert 9 in examined(report)
    assert 9 in runner.hydrated_numbers()
    assert report["must_include"]["dequeued_followup"] == [9]
    report = tick(tmp_path, runner)
    assert 9 not in examined(report)


def test_autoqueue_armed_pr_persisted_keeps_refresh_not_repeated_full_exams(
    tmp_path: Path,
) -> None:
    # R2 vs R6: an armed, never-queued PR that lands in the persisted
    # must-include set keeps the cheap refresh path — armed is not dequeued,
    # so the R6 one-shot must not re-fire on alternate ticks.
    runner = RotationRunner(25)
    runner.open_prs[6]["autoMergeRequest"] = {"mergeMethod": "SQUASH"}  # PR #19
    runner.head_statuses["sha-19"] = [_admission_status("success", age_minutes=16)]
    tick(tmp_path, runner)
    for _ in range(2):
        runner.calls.clear()
        report = tick(tmp_path, runner)
        assert 19 not in runner.hydrated_numbers()
        assert 19 not in examined(report)
        assert report["must_include"]["refreshed"] == [19]
    state = json.loads((tmp_path / MUST_INCLUDE_STATE_NAME).read_text())
    assert "19" in state["repositories"]["owner/repo"]
    assert report["must_include"]["dequeued_followup"] == []


def test_autoqueue_dequeued_then_rearmed_pr_keeps_refresh_path(tmp_path: Path) -> None:
    # A dequeued PR that re-arms (auto-merge request still on) is an R2
    # refresh seat until it re-queues; the R6 one-shot full exam belongs to
    # rows that left the queue unarmed.
    runner = RotationRunner(25)
    runner.queued_prs = {9}
    runner.head_statuses["sha-9"] = [_admission_status("success", age_minutes=16)]
    tick(tmp_path, runner)
    runner.queued_prs = set()
    runner.open_prs[16]["autoMergeRequest"] = {"mergeMethod": "SQUASH"}  # PR #9
    report = tick(tmp_path, runner)
    assert 9 not in runner.hydrated_numbers()
    assert 9 not in examined(report)
    assert report["must_include"]["refreshed"] == [9]
    assert report["must_include"]["dequeued_followup"] == []


def test_autoqueue_starved_must_include_pr_alerts_after_two_ticks(tmp_path: Path) -> None:
    # R7: two consecutive ticks without a successful status write raise the
    # starved flag on the persisted counters.
    runner = RotationRunner(25)
    runner.queued_prs = {5}
    runner.head_statuses["sha-5"] = [_admission_status("success", age_minutes=16)]
    runner.fail_status_posts = True
    report = tick(tmp_path, runner)
    assert report["must_include"]["starved"] == []
    report = tick(tmp_path, runner)
    assert report["must_include"]["starved"] == [5]
    state = json.loads((tmp_path / MUST_INCLUDE_STATE_NAME).read_text())
    assert state["repositories"]["owner/repo"]["5"]["consecutive_failures"] == 2


def test_autoqueue_non_success_must_include_status_is_not_reposted(tmp_path: Path) -> None:
    # Only successful proofs are refreshed; anything else needs the full path.
    runner = RotationRunner(25)
    runner.queued_prs = {13}
    runner.head_statuses["sha-13"] = [
        _admission_status("failure", age_minutes=16, description="cc-pr-autoqueue blocked: x")
    ]
    report = tick(tmp_path, runner)
    assert not _status_posts(runner, "sha-13")
    assert report["must_include"]["deferred"]["13"].startswith("existing_status_not_success")


def test_autoqueue_one_shot_path_fetches_must_include_beyond_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # T01 #12: the one-shot API path must not silently drop merge-queued PRs
    # when the estate exceeds the limit slice.
    runner = RotationRunner(25)
    runner.queued_prs = {20}
    original_listing = autoqueue.list_open_pr_statuses

    def sliced_listing(**kwargs: Any) -> Any:
        raw, route = original_listing(**kwargs)
        return raw[: kwargs["limit"]], route

    monkeypatch.setattr(autoqueue, "list_open_pr_statuses", sliced_listing)
    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=tmp_path / "tasks",
        runner=runner,
        apply=False,
        limit=5,
        rotation_state_path=None,
        lineage_ledger_path=None,
        quarantine_path=tmp_path / "quarantine.json",
        admission_governor_path=tmp_path / "governor.yaml",
    )
    assert 20 in examined(report)


def test_autoqueue_post_cap_rotation_serves_next_slice_next_tick(tmp_path: Path) -> None:
    # Post-cap starvation refutation: rows served past the POST cap (deferred)
    # and rows overflowed entirely keep their head-of-queue priority, while the
    # rows that DID get their proof rotate to the tail. Tick 2 must therefore
    # serve exactly the deferred slice, not re-serve tick 1's posted rows.
    runner = RotationRunner(25)
    runner.queued_prs = set(range(1, 13))
    for number in range(1, 13):
        runner.head_statuses[f"sha-{number}"] = [_admission_status("success", age_minutes=16)]
    report = tick(tmp_path, runner)
    assert report["must_include"]["refreshed"] == [1, 2, 3, 4]
    report = tick(tmp_path, runner)
    must_include = report["must_include"]
    assert must_include["refreshed"] == [5, 6, 7, 8]  # Tick 1's deferred_post_cap slice.
    assert must_include["overflow"] == [3, 4, 9, 10]  # Previously served rows rotated to the tail.
    covered = set(range(1, 5)) | set(must_include["refreshed"])
    for _ in range(4):
        covered.update(tick(tmp_path, runner)["must_include"]["refreshed"])
    assert covered == set(range(1, 13))  # No queued PR can starve behind the caps.


def test_autoqueue_dequeued_followup_overflow_stays_in_state(tmp_path: Path) -> None:
    # A dequeued follow-up that overflows the window (no full exam this tick)
    # must stay in the persisted set for its one-shot exam on a later tick;
    # only a served exam retires it.
    runner = RotationRunner(25)
    runner.queued_prs = set(range(1, 11))  # 11 and 12 just left the queue.
    now = datetime.now(UTC)
    state_path = tmp_path / MUST_INCLUDE_STATE_NAME
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repositories": {
                    "owner/repo": {
                        str(number): {
                            "head_sha": f"sha-{number}",
                            "last_seen_at": now.isoformat(),
                            "consecutive_failures": 0,
                        }
                        for number in range(1, 13)
                    }
                },
            }
        )
    )
    report = tick(tmp_path, runner)
    assert 11 not in examined(report) and 12 not in examined(report)
    persisted = json.loads(state_path.read_text())["repositories"]["owner/repo"]
    assert set(persisted) == {str(number) for number in range(1, 13)}
    assert persisted["11"]["consecutive_failures"] == 1  # Overflow counts as an unserved tick.


def test_autoqueue_must_include_killswitch_restores_plain_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # HAPAX_AUTOQUEUE_MUST_INCLUDE_OFF=1: no must seats, no refresh path, no
    # persisted must-include state — the rotation behaves exactly as pre-R1.
    monkeypatch.setenv("HAPAX_AUTOQUEUE_MUST_INCLUDE_OFF", "1")
    runner = RotationRunner(25)
    runner.queued_prs = {13}
    runner.head_statuses["sha-13"] = [_admission_status("success", age_minutes=16)]
    report = tick(tmp_path, runner)
    assert examined(report) == [1, 2, 3, 4, 5]
    assert report["queued_prs"] == []
    assert not _status_posts(runner, "sha-13")
    assert 13 not in runner.hydrated_numbers()
    must_include = report["must_include"]
    assert must_include["refreshed"] == must_include["ok"] == must_include["starved"] == []
    assert must_include["deferred"] == {} and must_include["overflow"] == []
    assert not (tmp_path / MUST_INCLUDE_STATE_NAME).exists()
    assert examined(tick(tmp_path, runner)) == [6, 7, 8, 9, 10]


def test_autoqueue_must_include_without_head_sha_is_a_visible_failure(tmp_path: Path) -> None:
    runner = RotationRunner(25)
    runner.queued_prs = {13}
    runner.open_prs[12].pop("headRefOid")
    report = tick(tmp_path, runner)
    assert report["must_include"]["deferred"]["13"] == "missing_head_sha"
    assert not _status_posts(runner, "sha-13")
    assert 13 not in runner.hydrated_numbers()
    assert len(examined(report)) == 4


def test_autoqueue_must_include_without_existing_status_is_a_visible_failure(
    tmp_path: Path,
) -> None:
    runner = RotationRunner(25)
    runner.queued_prs = {13}
    report = tick(tmp_path, runner)
    assert report["must_include"]["deferred"]["13"] == "no_existing_admission_status"
    assert not _status_posts(runner, "sha-13")


class _StatusReadFailsRunner(RotationRunner):
    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if (
            cmd[:2] == ["gh", "api"]
            and len(cmd) == 3
            and "/commits/" in cmd[2]
            and cmd[2].endswith("/statuses")
        ):
            self.calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 1, "", "status read failed")
        return super().__call__(cmd, **kwargs)


def test_autoqueue_failed_status_read_counts_toward_starvation(tmp_path: Path) -> None:
    runner = _StatusReadFailsRunner(25)
    runner.queued_prs = {13}
    report = tick(tmp_path, runner)
    assert (
        report["must_include"]["deferred"]["13"] == "admission_status_read_failed:query_failed:rc=1"
    )
    assert report["must_include"]["starved"] == []
    report = tick(tmp_path, runner)
    assert report["must_include"]["starved"] == [13]


def test_autoqueue_refresh_defers_write_when_rest_pool_below_floor(tmp_path: Path) -> None:
    runner = RotationRunner(25)
    runner.head_statuses["sha-13"] = [_admission_status("success", age_minutes=16)]
    result = autoqueue._refresh_must_include_proof(
        13,
        "sha-13",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        now=datetime.now(UTC),
        apply=True,
        route=autoqueue.ListingRoute(
            transport="rest", rest_blocked=True, reason="core_below_floor"
        ),
    )
    assert result["pr"] == 13 and result["ok"] is False
    assert result["message"].startswith("admission status write deferred")
    # "rate limit" wording files it as a transport-window deferral, not a PR verdict.
    assert "rate limit" in result["message"]
    assert not _status_posts(runner, "sha-13")


def test_autoqueue_refresh_dry_run_previews_without_posting(tmp_path: Path) -> None:
    runner = RotationRunner(25)
    runner.queued_prs = {13}
    runner.head_statuses["sha-13"] = [_admission_status("success", age_minutes=16)]
    report = tick(tmp_path, runner, apply=False)
    must_include = report["must_include"]
    assert must_include["ok"] == [13]
    assert must_include["refreshed"] == []
    assert must_include["deferred"] == {}
    assert not _status_posts(runner, "sha-13")
    assert not (tmp_path / MUST_INCLUDE_STATE_NAME).exists()
    preview = autoqueue._refresh_must_include_proof(
        13,
        "sha-13",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        now=datetime.now(UTC),
        apply=False,
        route=None,
    )
    assert preview == {"pr": 13, "ok": True, "message": "stale_would_refresh", "posted": False}


def test_autoqueue_queued_number_absent_from_listing_is_ignored(tmp_path: Path) -> None:
    # A queued number with no listing row is silently out of the window: no
    # refresh, no failure counter, no crash — the listing is the liveness truth.
    runner = RotationRunner(25)
    runner.queued_prs = {13, 999}
    runner.head_statuses["sha-13"] = [_admission_status("success", age_minutes=16)]
    report = tick(tmp_path, runner)
    assert not report.get("skipped"), report
    assert report["must_include"]["refreshed"] == [13]
    assert "999" not in json.dumps(report["must_include"])
    assert 999 not in examined(report)
    state = json.loads((tmp_path / MUST_INCLUDE_STATE_NAME).read_text())
    assert set(state["repositories"]["owner/repo"]) == {"13"}
    # A phantom queued number must not inflate the reserve floor and widen the
    # window: at limit 3, one live must row leaves exactly two rotation seats.
    assert examined(tick(tmp_path, runner, limit=3)) == [5, 6]
