from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import github_pr_status


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        capture_output: bool = False,
        text: bool = False,
        check: bool = False,
        timeout: int | None = None,
        **_: Any,
    ) -> subprocess.CompletedProcess:
        self.calls.append(list(cmd))
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/check-runs"):
            payload = {
                "check_runs": [
                    {
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "success",
                        "completed_at": "2026-07-05T15:00:00Z",
                    }
                ]
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/status"):
            payload = {
                "statuses": [
                    {
                        "context": "legacy-ci",
                        "state": "success",
                        "created_at": "2026-07-05T15:01:00Z",
                    }
                ]
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "api", "rate_limit"]:
            payload = {"resources": {"graphql": {"remaining": 0, "reset": 1893456000}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "api", "graphql"]:
            return subprocess.CompletedProcess(cmd, 0, '{"data":{}}', "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")


def test_rest_status_rollup_uses_check_runs_and_statuses(tmp_path: Path) -> None:
    runner = FakeRunner()

    rollup = github_pr_status.fetch_status_check_rollup_rest(
        "abc123",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        use_cache=False,
    )

    assert {item.get("name") or item.get("context") for item in rollup} == {
        "lint",
        "legacy-ci",
    }
    assert not any(call[:2] == ["gh", "pr"] for call in runner.calls)


def test_graphql_backoff_skips_graphql_when_remaining_is_low(tmp_path: Path) -> None:
    runner = FakeRunner()

    proc = github_pr_status.run_graphql_rate_aware(
        ["-f", "query=query { viewer { login } }"],
        repo_root=tmp_path,
        runner=runner,
        min_remaining=10,
    )

    assert proc.returncode == 75
    assert "github_graphql_remaining_below_threshold" in proc.stderr
    assert not any(call[:3] == ["gh", "api", "graphql"] for call in runner.calls)
