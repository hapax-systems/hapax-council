"""CLI tests for ``scripts/hapax-merge-queue-lineage``."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-merge-queue-lineage"


def _load_lineage_module() -> ModuleType:
    name = "hapax_merge_queue_lineage_script"
    if name in sys.modules:
        return sys.modules[name]
    loader = SourceFileLoader(name, str(SCRIPT))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def test_collect_from_json_fixtures_writes_ledger_and_summary(tmp_path: Path) -> None:
    runs_json = tmp_path / "runs.json"
    prs_json = tmp_path / "prs.json"
    ledger = tmp_path / "merge-queue-lineage.jsonl"
    summary = tmp_path / "merge-queue-summary.json"
    vault_root = tmp_path / "hapax-cc-tasks"
    active = vault_root / "active"
    active.mkdir(parents=True)
    (active / "demo-task.md").write_text(
        """---
type: cc-task
task_id: demo-task
status: claimed
pr: 3450
assigned_to: cx-demo
---

# Demo
""",
        encoding="utf-8",
    )

    runs_json.write_text(
        json.dumps(
            [
                {
                    "databaseId": 42,
                    "attempt": 1,
                    "conclusion": "success",
                    "createdAt": "2026-05-18T21:44:24Z",
                    "event": "merge_group",
                    "headBranch": (
                        "gh-readonly-queue/main/pr-3450-0375eb0ea2b70e9c964e9f209c3127f237d7044b"
                    ),
                    "headSha": "ef27e40690b1dcdee3296810cb5ea8e0312b7de3",
                    "startedAt": "2026-05-18T21:44:24Z",
                    "status": "completed",
                    "updatedAt": "2026-05-18T22:00:50Z",
                    "workflowName": "CI",
                    "jobs": [
                        {
                            "name": "test-full-shard (1/4)",
                            "status": "completed",
                            "conclusion": "success",
                            "startedAt": "2026-05-18T21:45:00Z",
                            "completedAt": "2026-05-18T21:58:00Z",
                            "steps": [],
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    prs_json.write_text(
        json.dumps(
            [
                {
                    "number": 3450,
                    "headRefOid": "0375eb0ea2b70e9c964e9f209c3127f237d7044b",
                    "state": "OPEN",
                    "mergedAt": None,
                    "mergeStateStatus": "CLEAN",
                    "autoMergeRequest": None,
                    "isDraft": False,
                    "body": "## Summary\ncc-task: demo-task\n\n## Test plan\n- [x] tests\n",
                    "statusCheckRollup": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(SCRIPT),
            "collect",
            "--runs-json",
            str(runs_json),
            "--prs-json",
            str(prs_json),
            "--ledger-path",
            str(ledger),
            "--summary-path",
            str(summary),
            "--vault-root",
            str(vault_root),
            "--max-records",
            "5",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "wrote 1 record" in result.stdout
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["event"] == "merge_queue_lineage"
    assert record["pr_number"] == 3450
    summary_data = json.loads(summary.read_text(encoding="utf-8"))
    assert summary_data["event"] == "merge_queue_summary"
    assert summary_data["latest_run_id"] == 42
    assert summary_data["latest_bottleneck"]["kind"] == "branch_protection_check_mapping"
    assert any(
        reason["source"] == "cc_task_note" and "status is claimed" in reason["reason"]
        for reason in summary_data["current_queue_hold_reasons"]
    )


def test_fetch_prs_uses_rest_status_shape(tmp_path: Path, monkeypatch: Any) -> None:
    lineage = _load_lineage_module()

    class RestRunner:
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
            if cmd[:5] != ["gh", "api", "--method", "GET", "-H"]:
                return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

            path = cmd[6]
            if path == "repos/hapax-systems/hapax-council/pulls":
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps(
                        [
                            {
                                "number": 3450,
                                "node_id": "PR_kw",
                                "title": "PR 3450",
                                "body": "body",
                                "head": {"ref": "feat/lineage", "sha": "sha-3450"},
                                "draft": False,
                                "state": "open",
                                "merged": False,
                                "merged_at": None,
                                "updated_at": "2026-05-18T22:00:00Z",
                                "html_url": (
                                    "https://github.com/hapax-systems/hapax-council/pull/3450"
                                ),
                                "mergeable_state": "clean",
                                "auto_merge": None,
                                "changed_files": 1,
                                "labels": [],
                            }
                        ]
                    ),
                    "",
                )
            if path == "repos/hapax-systems/hapax-council/pulls/3450":
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps(
                        {
                            "number": 3450,
                            "node_id": "PR_kw",
                            "title": "PR 3450",
                            "body": "body",
                            "head": {"ref": "feat/lineage", "sha": "sha-3450"},
                            "draft": False,
                            "state": "open",
                            "merged": False,
                            "merged_at": None,
                            "updated_at": "2026-05-18T22:00:00Z",
                            "html_url": (
                                "https://github.com/hapax-systems/hapax-council/pull/3450"
                            ),
                            "mergeable_state": "clean",
                            "auto_merge": None,
                            "changed_files": 1,
                            "labels": [],
                        }
                    ),
                    "",
                )
            if path == "repos/hapax-systems/hapax-council/commits/sha-3450/check-runs":
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps(
                        {
                            "check_runs": [
                                {
                                    "name": "test",
                                    "status": "completed",
                                    "conclusion": "success",
                                }
                            ]
                        }
                    ),
                    "",
                )
            if path == "repos/hapax-systems/hapax-council/commits/sha-3450/status":
                return subprocess.CompletedProcess(cmd, 0, json.dumps({"statuses": []}), "")
            return subprocess.CompletedProcess(cmd, 1, "", f"unexpected path {path}")

    runner = RestRunner()
    monkeypatch.setattr(lineage.subprocess, "run", runner)

    rows, unhydrated = lineage.fetch_prs(limit=100, repo=None, pr_numbers={3450})

    # Gaps come back separately: a synthetic row inside `rows` would be a fabricated
    # measurement, since this list feeds every lineage record as real PR status.
    assert unhydrated == []
    assert len(rows) == 1
    assert rows[0]["state"] == "OPEN"
    assert rows[0]["mergedAt"] is None
    assert rows[0]["updatedAt"] == "2026-05-18T22:00:00Z"
    assert rows[0]["url"] == "https://github.com/hapax-systems/hapax-council/pull/3450"
    assert rows[0]["statusCheckRollup"][0]["name"] == "test"
    assert rows[0]["statusCheckRollup"][0]["conclusion"] == "SUCCESS"
    assert not any(call[:2] == ["gh", "pr"] for call in runner.calls)


def test_hydration_uses_the_chosen_transport_and_records_what_it_could_not_reach(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Executes the branch the enumeration test could only bless statically.

    codex was right that naming `fetch_prs` as routed in a source-level list does not show that
    it *routes*. Two behaviours are asserted here by running it: on a GraphQL-routed cycle with
    REST healthy, per-PR hydration goes over GraphQL rather than back onto the pool the routing
    chose to spare; and with REST measured empty, the PR is recorded as a gap rather than
    fetched or silently dropped.
    """
    lineage = _load_lineage_module()

    def runner_for(*, core: int, graphql: int, calls: list[list[str]]) -> Any:
        def run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
            calls.append(list(cmd))
            if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
                head = (
                    "HTTP/2.0 200 OK\r\nX-Ratelimit-Limit: 5000\r\n"
                    f"X-Ratelimit-Remaining: {core}\r\nX-Ratelimit-Reset: 1893456000\r\n"
                    "X-Ratelimit-Resource: core\r\n"
                )
                payload = {
                    "resources": {
                        "core": {"remaining": core, "limit": 5000, "reset": 1893456000},
                        "graphql": {"remaining": graphql, "limit": 5000, "reset": 1893456000},
                    }
                }
                return subprocess.CompletedProcess(cmd, 0, f"{head}\r\n{json.dumps(payload)}", "")
            if cmd[:3] == ["gh", "pr", "list"]:
                return subprocess.CompletedProcess(cmd, 0, "[]", "")
            if cmd[:3] == ["gh", "pr", "view"]:
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps(
                        {
                            "number": 4242,
                            "url": "https://github.com/hapax-systems/hapax-council/pull/4242",
                            "state": "MERGED",
                            "title": "t",
                            "headRefName": "b",
                            "headRefOid": "sha",
                            "statusCheckRollup": [],
                        }
                    ),
                    "",
                )
            return subprocess.CompletedProcess(cmd, 1, "", "unexpected")

        return run

    monkeypatch.setattr(lineage, "REPO_ROOT", tmp_path)

    # GraphQL chosen because it is roomier; REST healthy. Hydration must not touch REST.
    calls: list[list[str]] = []
    monkeypatch.setattr(lineage.subprocess, "run", runner_for(core=1000, graphql=4900, calls=calls))
    rows, unhydrated = lineage.fetch_prs(limit=10, repo=None, pr_numbers={4242})
    assert [r["number"] for r in rows] == [4242]
    assert unhydrated == []
    assert not any(len(c) > 6 and str(c[6]).startswith("repos/") for c in calls), (
        f"per-PR hydration must follow the cycle's transport: {calls}"
    )

    # REST measured EMPTY and GraphQL healthy — the case the GraphQL hydrator exists for.
    #
    # This assertion previously read `unhydrated == [4242]`, which ENCODED the bug: the
    # hydrator required `not rest_blocked`, so it refused GraphQL in exactly the situation it
    # was built for and recorded a gap instead. All three review families caught the inversion;
    # the test had blessed it. A gap is correct only when nothing eligible remains.
    calls = []
    monkeypatch.setattr(lineage.subprocess, "run", runner_for(core=0, graphql=4900, calls=calls))
    rows, unhydrated = lineage.fetch_prs(limit=10, repo=None, pr_numbers={4242})
    assert [r["number"] for r in rows] == [4242], (
        "an exhausted REST pool is the reason to USE the GraphQL hydrator, not to skip it"
    )
    assert unhydrated == []
    assert not any(len(c) > 6 and str(c[6]).startswith("repos/") for c in calls)


def test_a_gap_is_recorded_only_when_nothing_eligible_remains(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """The converse, and the reason the fix is not simply "always try GraphQL".

    A gap is the right answer when the chosen transport fails AND the other pool is measured
    empty. It is the wrong answer whenever an eligible pool is left untried — which is what the
    inverted guard produced.
    """
    lineage = _load_lineage_module()
    monkeypatch.setattr(lineage, "REPO_ROOT", tmp_path)

    def both_unusable(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            head = (
                "HTTP/2.0 200 OK\r\nX-Ratelimit-Limit: 5000\r\n"
                "X-Ratelimit-Remaining: 0\r\nX-Ratelimit-Reset: 1893456000\r\n"
                "X-Ratelimit-Resource: core\r\n"
            )
            payload = {
                "resources": {
                    "core": {"remaining": 0, "limit": 5000, "reset": 1893456000},
                    "graphql": {"remaining": 4900, "limit": 5000, "reset": 1893456000},
                }
            }
            return subprocess.CompletedProcess(cmd, 0, f"{head}\r\n{json.dumps(payload)}", "")
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        # GraphQL hydration fails; REST is measured empty, so nothing eligible remains.
        return subprocess.CompletedProcess(cmd, 1, "", "boom")

    monkeypatch.setattr(lineage.subprocess, "run", both_unusable)
    rows, unhydrated = lineage.fetch_prs(limit=10, repo=None, pr_numbers={4242})

    assert rows == []
    assert [g["reason"] for g in unhydrated] == ["graphql_failed_rest_blocked"], (
        "the gap must name WHY nothing was eligible, not merely that a row is missing"
    )


def test_fetch_prs_fails_closed_when_open_pr_snapshot_is_indeterminate(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    lineage = _load_lineage_module()

    class IndeterminateRunner:
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
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
                return subprocess.CompletedProcess(cmd, 1, "", "rate limit")
            return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

    monkeypatch.setattr(lineage.subprocess, "run", IndeterminateRunner())
    monkeypatch.setattr(lineage, "REPO_ROOT", tmp_path)

    # The invariant is fail-closed with an actionable message, not one exact wording. The
    # listing is now routed, so an indeterminate REST result arrives as `RestListingFailed`
    # rather than a bare SubprocessError, and the operator text comes from the shared formatter
    # — "via REST" was never the load-bearing part.
    try:
        lineage.fetch_prs(limit=100, repo=None, pr_numbers=set())
    except RuntimeError as exc:
        assert "open PR query indeterminate" in str(exc)
        assert "Next action" in str(exc), f"a fail-closed refusal must name a next action: {exc}"
    else:
        raise AssertionError("fetch_prs must not return a false-empty open PR set")


def test_a_raised_rest_hydration_failure_records_a_gap_instead_of_aborting_collection(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """A REST hydration that RAISES must produce the gap, not abort the run.

    Found by two review families. The gap path handled a `None` return and nothing else, so a
    timeout or an unrunnable `gh` propagated out of `fetch_prs` and killed `collect` **before the
    unhydrated receipt was written** — leaving lineage output silently stale, which is the exact
    outcome the receipt exists to prevent. The GraphQL hydrator had already been normalised; this
    REST fallback sat outside any handler, so the boundary was fixed on one side only.

    The existing tests could not see it: every one drives failure through a nonzero
    `CompletedProcess`, which is a RETURN. None of them raises.
    """
    lineage = _load_lineage_module()
    monkeypatch.setattr(lineage, "REPO_ROOT", tmp_path)

    def rest_healthy_then_gh_vanishes(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            head = (
                "HTTP/2.0 200 OK\r\nX-Ratelimit-Limit: 5000\r\n"
                "X-Ratelimit-Remaining: 4000\r\nX-Ratelimit-Reset: 1893456000\r\n"
                "X-Ratelimit-Resource: core\r\n"
            )
            payload = {
                "resources": {
                    "core": {"remaining": 4000, "limit": 5000, "reset": 1893456000},
                    "graphql": {"remaining": 10, "limit": 5000, "reset": 1893456000},
                }
            }
            return subprocess.CompletedProcess(cmd, 0, f"{head}\r\n{json.dumps(payload)}", "")
        # Only the PER-PR hydration call fails to execute. The listing must succeed, or the run
        # refuses earlier for an unrelated reason and this test would pass without exercising the
        # hydration boundary at all.
        if any("pulls/4242" in str(part) for part in cmd):
            raise FileNotFoundError(2, "No such file or directory: 'gh'")
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        return subprocess.CompletedProcess(cmd, 0, "[]", "")

    monkeypatch.setattr(lineage.subprocess, "run", rest_healthy_then_gh_vanishes)

    rows, unhydrated = lineage.fetch_prs(limit=10, repo=None, pr_numbers={4242})

    assert rows == []
    assert [g["reason"] for g in unhydrated] == ["rest_query_unavailable"], (
        "a raised REST failure must be recorded as a gap that names why, not propagated; "
        f"got {unhydrated}"
    )


# Use the real github_pr_status hydrator so malformed identities cannot bypass gap receipts.


@pytest.mark.parametrize(
    "change",
    [
        *[{"number": number} for number in (None, "", "4242", 0, -1, True, 4242.0, 4243)],
        {"url": "https://github.com/other/repo/pull/4242"},
        {"url": None},
        {"headRefOid": ""},
    ],
)
def test_invalid_hydration_identity_reaches_fetch_and_collect_gap_receipt(
    tmp_path: Path, monkeypatch: Any, change: dict[str, Any]
) -> None:
    import github_pr_status

    lineage = _load_lineage_module()
    monkeypatch.setattr(lineage, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        lineage,
        "list_open_pr_statuses",
        lambda **_: ([], github_pr_status.ListingRoute("graphql", True, "REST below floor")),
    )

    def wrong_identity(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        assert cmd[:3] == ["gh", "pr", "view"], "blocked REST must not be used"
        return subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps(
                {
                    "number": 4242,
                    "url": "https://github.com/owner/repo/pull/4242",
                    "headRefOid": "a" * 40,
                    "statusCheckRollup": [],
                    **change,
                }
            ),
            "",
        )

    monkeypatch.setattr(lineage.subprocess, "run", wrong_identity)
    rows, gaps = lineage.fetch_prs(limit=10, repo="owner/repo", pr_numbers={4242})
    assert rows == []
    assert gaps == [{"number": 4242, "reason": "graphql_failed_rest_blocked"}]
    runs = tmp_path / "runs.json"
    runs.write_text(
        json.dumps(
            [
                {
                    "databaseId": 42,
                    "event": "merge_group",
                    "status": "completed",
                    "conclusion": "success",
                    "headBranch": "gh-readonly-queue/main/pr-4242-" + "a" * 40,
                    "headSha": "b" * 40,
                }
            ]
        )
    )
    summary = tmp_path / "summary.json"
    assert (
        lineage.main(
            [
                "collect",
                "--repo",
                "owner/repo",
                "--runs-json",
                str(runs),
                "--ledger-path",
                str(tmp_path / "ledger.jsonl"),
                "--summary-path",
                str(summary),
                "--vault-root",
                str(tmp_path / "vault"),
            ]
        )
        == 0
    )
    receipt = json.loads(summary.read_text())
    assert receipt["hydration_complete"] is False
    assert receipt["unhydrated_prs"] == gaps
