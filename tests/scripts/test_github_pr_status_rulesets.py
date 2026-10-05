"""Load-balance the rulesets read across REST and GraphQL (the real consumer).

Task github-rest-hourly-budget-exhausted-by-estate-20261004 (operator: "graphql and rest are
supposed to be lb"). cc-pr-autoqueue's `fetch_merge_queue_merge_method` was REST-only, so a
REST-core exhaustion (measured 2026-10-04 at 01:55Z while GraphQL sat at 4993/5000) 403'd the
rulesets fetch and no PR could arm. It now routes the read through `choose_transport`
(authoritative HEADER headroom, both directions), diverting BEFORE the call and holding with a
reason only when BOTH pools are measured below floor.

These tests drive the routing with real ``gh api -i rate_limit`` HEADER values through the REAL
``choose_transport`` (not a static mock of it) and exercise the REAL ``_rulesets_graphql`` -- so
the routing is shown to follow headroom, the GraphQL error returns are covered, and the
GraphQL->REST fallback (and its conservative floor) is pinned end to end.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pytest


def _load_autoqueue():
    if "cc_pr_autoqueue" in sys.modules:
        return sys.modules["cc_pr_autoqueue"]
    spec = importlib.util.spec_from_file_location(
        "cc_pr_autoqueue", _SCRIPTS / "cc-pr-autoqueue.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["cc_pr_autoqueue"] = module
    spec.loader.exec_module(module)
    return module


autoqueue = _load_autoqueue()

_RULESET_NAME = autoqueue.AUTOQUEUE_MERGE_QUEUE_RULESET_NAME


def _rest_rulesets_payload() -> list[dict]:
    """REST-shaped active branch ruleset with the merge-queue method inline."""
    return [
        {
            "id": 16186443,
            "name": _RULESET_NAME,
            "target": "branch",
            "enforcement": "active",
            "rules": [{"type": "merge_queue", "parameters": {"merge_method": "squash"}}],
        }
    ]


def _graphql_rulesets_ok_stdout() -> str:
    """GraphQL-shaped (upper-case enums) rulesets payload; _map_graphql_ruleset lowercases it."""
    return json.dumps(
        {
            "data": {
                "repository": {
                    "rulesets": {
                        "nodes": [
                            {
                                "databaseId": 16186443,
                                "name": _RULESET_NAME,
                                "enforcement": "ACTIVE",
                                "target": "BRANCH",
                                "rules": {
                                    "nodes": [
                                        {
                                            "type": "MERGE_QUEUE",
                                            "parameters": {
                                                "__typename": "MergeQueueParameters",
                                                "mergeMethod": "SQUASH",
                                            },
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                }
            }
        }
    )


def _rate_limit_stdout(*, core_remaining: int, graphql_remaining: int) -> str:
    """`gh api -i rate_limit` output: authoritative core HEADER + a body carrying both pools."""
    body = {
        "resources": {
            "core": {"remaining": core_remaining, "limit": 5000, "reset": 1893456000},
            "graphql": {"remaining": graphql_remaining, "limit": 5000, "reset": 1893456000},
        }
    }
    head = (
        "HTTP/2.0 200 OK\r\n"
        "X-Ratelimit-Limit: 5000\r\n"
        f"X-Ratelimit-Remaining: {core_remaining}\r\n"
        "X-Ratelimit-Reset: 1893456000\r\n"
        "X-Ratelimit-Resource: core\r\n\r\n"
    )
    return head + json.dumps(body)


def _is_graphql_rulesets(cmd: list[str]) -> bool:
    return cmd[:3] == ["gh", "api", "graphql"] and any("rulesets(first" in part for part in cmd)


def _is_rest_rulesets(cmd: list[str]) -> bool:
    return (
        cmd[:5] == ["gh", "api", "--method", "GET", "-H"]
        and len(cmd) > 6
        and cmd[6].endswith("/rulesets")
    )


def _make_runner(
    calls: list[str],
    *,
    core_remaining: int,
    graphql_remaining: int = 4000,
    graphql_rulesets_rc: int = 0,
    graphql_rulesets_stdout: str | None = None,
    rest_rulesets_rc: int = 0,
):
    """Header-driven runner: serves rate_limit, the GraphQL rulesets query, and the REST read."""

    def runner(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                _rate_limit_stdout(
                    core_remaining=core_remaining, graphql_remaining=graphql_remaining
                ),
                "",
            )
        if _is_graphql_rulesets(cmd):
            calls.append("graphql")
            if graphql_rulesets_rc != 0:
                return subprocess.CompletedProcess(cmd, graphql_rulesets_rc, "", "schema miss")
            return subprocess.CompletedProcess(
                cmd, 0, graphql_rulesets_stdout or _graphql_rulesets_ok_stdout(), ""
            )
        if _is_rest_rulesets(cmd):
            calls.append("rest")
            if rest_rulesets_rc != 0:
                return subprocess.CompletedProcess(cmd, rest_rulesets_rc, "", "rest refused")
            return subprocess.CompletedProcess(cmd, 0, json.dumps(_rest_rulesets_payload()), "")
        return subprocess.CompletedProcess(cmd, 1, "", f"unexpected:{cmd}")

    return runner


def _run(tmp_path: Path, runner) -> tuple[str | None, str]:
    return autoqueue.fetch_merge_queue_merge_method(
        repo="owner/repo", repo_root=tmp_path, runner=runner
    )


# --- Routing is driven by measured HEADER headroom, not a static decision -------------------


def test_rest_exhausted_routes_rulesets_to_graphql_by_headers(tmp_path: Path) -> None:
    calls: list[str] = []
    # core below the routing floor; graphql healthy -> choose_transport (real) must pick graphql.
    method, source = _run(tmp_path, _make_runner(calls, core_remaining=3, graphql_remaining=4000))
    assert calls == ["graphql"], f"REST exhausted must route the read to GraphQL; calls={calls}"
    assert method == "SQUASH", (method, source)


def test_graphql_low_routes_rulesets_to_rest_by_headers(tmp_path: Path) -> None:
    calls: list[str] = []
    # graphql below its floor; core healthy -> real choose_transport must pick REST.
    method, source = _run(tmp_path, _make_runner(calls, core_remaining=4800, graphql_remaining=3))
    assert calls == ["rest"], f"GraphQL below floor must route the read to REST; calls={calls}"
    assert method == "SQUASH", (method, source)


def test_both_pools_low_holds_with_a_reason(tmp_path: Path) -> None:
    calls: list[str] = []
    method, source = _run(tmp_path, _make_runner(calls, core_remaining=3, graphql_remaining=3))
    assert method is None, "both pools below floor must hold, not spend into a doomed transport"
    assert calls == [], "no transport implementation may run when both pools are below floor"
    assert source.startswith("rulesets_fetch_failed:github_both_pools_below_floor"), source


# --- GraphQL chosen then fails: fall back to REST only above the conservative floor ----------


def test_graphql_failure_falls_back_to_rest_when_rest_has_fallback_floor(tmp_path: Path) -> None:
    calls: list[str] = []
    # core healthy and >= the fallback floor, graphql proportionally roomier -> graphql chosen;
    # the REAL _rulesets_graphql then fails (rc!=0) and REST must serve the read.
    runner = _make_runner(calls, core_remaining=1500, graphql_remaining=4800, graphql_rulesets_rc=1)
    method, source = _run(tmp_path, runner)
    assert calls == ["graphql", "rest"], (
        f"GraphQL must be tried then REST must serve; calls={calls}"
    )
    assert method == "SQUASH", (method, source)


def test_graphql_failure_holds_when_rest_below_fallback_floor(tmp_path: Path) -> None:
    calls: list[str] = []
    # core above the ROUTING floor (so graphql is chosen for balancing) but below the higher
    # FALLBACK floor -> the fallback must NOT spend REST; it holds with a reason.
    runner = _make_runner(calls, core_remaining=999, graphql_remaining=4800, graphql_rulesets_rc=1)
    method, source = _run(tmp_path, runner)
    assert method is None, "fallback must not drain REST below its conservative floor"
    assert calls == ["graphql"], f"no REST read may run below the fallback floor; calls={calls}"
    assert "rest_below_fallback_floor" in source, source


@pytest.mark.parametrize(
    ("core_remaining", "expect_fallback"),
    [
        (autoqueue.DEFAULT_GRAPHQL_FALLBACK_REST_MIN_REMAINING, True),  # at the floor -> fall back
        (autoqueue.DEFAULT_GRAPHQL_FALLBACK_REST_MIN_REMAINING - 1, False),  # one below -> hold
    ],
)
def test_fallback_floor_boundary(
    tmp_path: Path, core_remaining: int, expect_fallback: bool
) -> None:
    calls: list[str] = []
    runner = _make_runner(
        calls, core_remaining=core_remaining, graphql_remaining=4800, graphql_rulesets_rc=1
    )
    method, source = _run(tmp_path, runner)
    if expect_fallback:
        assert calls == ["graphql", "rest"] and method == "SQUASH", (calls, method, source)
    else:
        assert calls == ["graphql"] and method is None, (calls, method, source)


# --- Every GraphQL error path is exercised through the REAL _rulesets_graphql ----------------


def test_rulesets_graphql_bad_repo(tmp_path: Path) -> None:
    rulesets, reason = autoqueue._rulesets_graphql(
        "norepo", repo_root=tmp_path, runner=lambda *_a, **_k: None
    )
    assert rulesets is None
    assert reason.startswith("rulesets_graphql_bad_repo:norepo") and "next=" in reason, reason


def test_rulesets_graphql_nonzero_rc(tmp_path: Path) -> None:
    calls: list[str] = []
    runner = _make_runner(calls, core_remaining=4800, graphql_rulesets_rc=1)
    rulesets, reason = autoqueue._rulesets_graphql("owner/repo", repo_root=tmp_path, runner=runner)
    assert rulesets is None
    assert reason.startswith("rulesets_graphql_rc1:") and "next=" in reason, reason


def test_rulesets_graphql_malformed_payload(tmp_path: Path) -> None:
    calls: list[str] = []
    runner = _make_runner(calls, core_remaining=4800, graphql_rulesets_stdout='{"data":{}}')
    rulesets, reason = autoqueue._rulesets_graphql("owner/repo", repo_root=tmp_path, runner=runner)
    assert rulesets is None
    assert reason.startswith("rulesets_graphql_malformed") and "next=" in reason, reason
