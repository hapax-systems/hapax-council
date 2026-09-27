"""Carry independent branch evidence and eligible fallback through real rotation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.scripts.test_cc_pr_autoqueue_rotation import RotationRunner
from tests.test_cc_pr_autoqueue import autoqueue


class HydrationRunner(RotationRunner):
    def __init__(self, *, core: int = 0, graphql: int = 5000) -> None:
        super().__init__(1, "graphql" if graphql > core else "rest")
        self.core = core
        self.graphql = graphql
        self.detail_base: Any = "main"
        self.detail_head = "sha-1"
        self.graphql_fails = False
        self.rest_fails = False

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            self.calls.append(cmd)
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps(
                    {
                        "resources": {
                            name: {"remaining": value, "limit": 5000, "reset": 1893456000}
                            for name, value in (("core", self.core), ("graphql", self.graphql))
                        }
                    }
                ),
                "",
            )
        if cmd[:3] == ["gh", "pr", "view"]:
            if self.graphql_fails:
                self.calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 1, "", "HTTP 504")
            result = super().__call__(cmd, **kwargs)
            payload = json.loads(result.stdout)
            payload.update(baseRefName=self.detail_base, headRefOid=self.detail_head)
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if "repos/owner/repo/pulls/1" in cmd:
            if self.rest_fails:
                self.calls.append(cmd)
                raise subprocess.TimeoutExpired(cmd, 45)
            result = super().__call__(cmd, **kwargs)
            payload = json.loads(result.stdout)
            payload["base"]["ref"] = self.detail_base
            payload["head"]["sha"] = self.detail_head
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        return super().__call__(cmd, **kwargs)


def hydrate(tmp_path: Path, runner: HydrationRunner):
    return autoqueue.fetch_rotating_open_prs(
        repo="owner/repo",
        repo_root=tmp_path,
        limit=1,
        state_path=tmp_path / "rotation.json",
        persist=False,
        runner=runner,
    )


@pytest.mark.parametrize("fallback", [False, True])
def test_rotation_retains_conflicting_base_for_actual_governance(tmp_path, fallback):
    runner = HydrationRunner(core=3000 if fallback else 0)
    runner.graphql_fails = fallback
    runner.detail_base = "release"
    prs, _, count, failures, _ = hydrate(tmp_path, runner)
    assert count == 1 and not failures and len(prs) == 1
    assert prs[0].base_ref == "main"
    assert prs[0].base_ref_detail == "release"
    governance = autoqueue.fetch_pr_merge_queue_governance(
        prs[0], repo="owner/repo", repo_root=tmp_path, runner=runner
    )
    assert governance.reason == (
        "auto_merge_method_unverified:pr_base_ref_conflict:list=main:detail=release"
    )
    assert not any("rulesets" in " ".join(call) for call in runner.calls)


def test_rotation_matching_base_has_usable_queue_governance(tmp_path):
    runner = HydrationRunner()
    prs, _, _, failures, _ = hydrate(tmp_path, runner)
    assert not failures and len(prs) == 1
    governance = autoqueue.fetch_pr_merge_queue_governance(
        prs[0], repo="owner/repo", repo_root=tmp_path, runner=runner
    )
    assert governance.reason is None and governance.method == "SQUASH"


@pytest.mark.parametrize("invalid_base", [0, False, {"name": "release"}])
def test_rotation_preserves_malformed_detail_evidence(tmp_path, invalid_base):
    runner = HydrationRunner()
    runner.detail_base = invalid_base
    prs, _, _, failures, _ = hydrate(tmp_path, runner)
    assert not failures and len(prs) == 1
    governance = autoqueue.fetch_pr_merge_queue_governance(
        prs[0], repo="owner/repo", repo_root=tmp_path, runner=runner
    )
    assert governance.reason == "auto_merge_method_unverified:pr_base_ref_malformed"


@pytest.mark.parametrize("primary", ["graphql", "rest"])
def test_rotation_hydration_recovers_through_eligible_other_transport(tmp_path, primary):
    runner = HydrationRunner(core=3000 if primary == "graphql" else 5000)
    runner.graphql_fails = primary == "graphql"
    runner.rest_fails = primary == "rest"
    prs, _, count, failures, _ = hydrate(tmp_path, runner)
    assert count == 1 and not failures and len(prs) == 1
    assert prs[0].head_sha == "sha-1" and prs[0].files == ("shared/foo.py",)
    assert {"lint", "test", "typecheck"} <= set(prs[0].check_summary.passed)
    assert any(call[:3] == ["gh", "pr", "view"] for call in runner.calls)
    assert any("repos/owner/repo/pulls/1" in call for call in runner.calls)
    assert len([c for c in runner.calls if c[:4] == ["gh", "api", "-i", "rate_limit"]]) == 1


@pytest.mark.parametrize("primary", ["graphql", "rest"])
def test_rotation_never_falls_back_to_measured_exhausted_pool(tmp_path, primary):
    runner = HydrationRunner(
        core=0 if primary == "graphql" else 5000,
        graphql=5000 if primary == "graphql" else 0,
    )
    runner.graphql_fails = primary == "graphql"
    runner.rest_fails = primary == "rest"
    prs, _, count, failures, _ = hydrate(tmp_path, runner)
    assert count == 1 and prs == [] and set(failures) == {1}
    if primary == "graphql":
        assert not any("repos/owner/repo/pulls/1" in call for call in runner.calls)
    else:
        assert not any(call[:3] == ["gh", "pr", "view"] for call in runner.calls)


@pytest.mark.parametrize("fallback", [False, True])
def test_rotation_refuses_moved_head_on_primary_and_fallback(tmp_path, fallback):
    runner = HydrationRunner(core=3000 if fallback else 0)
    runner.graphql_fails = fallback
    runner.detail_head = "sha-moved"
    prs, _, count, failures, _ = hydrate(tmp_path, runner)
    assert count == 1 and prs == [] and set(failures) == {1}


def test_rotation_failed_fallback_remains_a_visible_retry(tmp_path):
    runner = HydrationRunner(core=3000)
    runner.graphql_fails = runner.rest_fails = True
    prs, _, count, failures, _ = hydrate(tmp_path, runner)
    assert count == 1 and prs == []
    assert failures[1]["attempted_this_tick"]
    assert failures[1]["consecutive_failures"] == 1
