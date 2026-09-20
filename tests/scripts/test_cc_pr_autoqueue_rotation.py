"""Exercise timer rotation through listing, disk state, hydration and reconciliation."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
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
            if self.broken == "malformed_link":
                headers += "Link: truncated\r\n"
            return subprocess.CompletedProcess(cmd, 0, headers + "\r\n" + body, "")
        if cmd[:3] == ["gh", "api", "graphql"] and any("pullRequests(" in p for p in cmd):
            self.calls.append(cmd)
            offset = int(self._fields(cmd).get("cursor", "0"))
            rows = self.open_prs[offset : offset + 100]
            connection = {
                "totalCount": len(self.open_prs),
                "pageInfo": {
                    "hasNextPage": offset + 100 < len(self.open_prs),
                    "endCursor": str(offset + len(rows)),
                },
                "nodes": [
                    {
                        key: row[key]
                        for key in ("number", "headRefOid", "headRefName", "baseRefName")
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
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "pr", "view"]:
            self.calls.append(cmd)
            row = next(row for row in self.open_prs if str(row["number"]) == cmd[3])
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps({**row, "url": f"https://github.com/owner/repo/pull/{row['number']}"}),
                "",
            )
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
    assert [row["number"] for row in selected] == [6, 7]
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
