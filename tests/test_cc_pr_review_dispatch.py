"""Tests for ``scripts/cc-pr-review-dispatch.py`` — the review-team dispatcher.

Reviewer CLIs are stubbed via the injected ``reviewer_runner``; GitHub via the
injected ``gh_runner``. The exit-predicate integration test at the bottom runs
a test PR through the dispatcher and shows cc-pr-autoqueue blocks without the
produced dossier and admits with it.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _load(name: str, filename: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


dispatch = _load("cc_pr_review_dispatch", "cc-pr-review-dispatch.py")


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "hapax-cc-tasks"
    (vault / "active").mkdir(parents=True, exist_ok=True)
    (vault / "closed").mkdir(parents=True, exist_ok=True)
    return vault


def _write_task(
    vault: Path,
    task_id: str = "task-a",
    *,
    pr: int = 42,
    risk_tier: str = "T2",
    quality_floor: str = "frontier_required",
    assigned_to: str = "zeta",
) -> Path:
    path = vault / "active" / f"{task_id}.md"
    path.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "{task_id}"
status: pr_open
assigned_to: {assigned_to}
pr: {pr}
branch: feat/{pr}
risk_tier: {risk_tier}
quality_floor: {quality_floor}
authority_case: CASE-TEST
parent_spec: docs/spec.md
route_metadata_schema: 1
---

# {task_id}
""",
        encoding="utf-8",
    )
    return path


GOOD_REPLY = """I reviewed the diff against every charter.

```yaml
verdict: accept
findings: []
checklist:
  tests-cover-the-diff:
    diff-behavior-coverage: pass
    red-before-green: na
    new-paths-tested: pass
    no-coverage-theater: pass
```
"""

BLOCK_REPLY = """Problems found.

```yaml
verdict: block
findings:
  - severity: critical
    lens: correctness
    file: shared/foo.py
    line: 10
    title: off-by-one in window math
    detail: the ring index wraps one slot early
checklist: {}
```
"""


class FakeGh:
    """Stub for the gh CLI: pr view / pr diff / pr list / pr comment."""

    def __init__(self, *, pr_number: int = 42, files: list[str] | None = None) -> None:
        self.pr_number = pr_number
        self.files = files if files is not None else ["shared/foo.py", "tests/test_foo.py"]
        self.diff = "diff --git a/shared/foo.py b/shared/foo.py\n+changed\n"
        self.comments: list[str] = []
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.calls.append(list(cmd))
        if cmd[:3] == ["gh", "pr", "view"]:
            payload = {
                "number": self.pr_number,
                "title": f"PR {self.pr_number}",
                "body": "body",
                "headRefName": f"feat/{self.pr_number}",
                "headRefOid": "c" * 40,
                "isDraft": False,
                "files": [{"path": p} for p in self.files],
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "pr", "diff"]:
            return subprocess.CompletedProcess(cmd, 0, self.diff, "")
        if cmd[:3] == ["gh", "pr", "list"]:
            payload = [
                {
                    "number": self.pr_number,
                    "headRefName": f"feat/{self.pr_number}",
                    "headRefOid": "c" * 40,
                    "isDraft": False,
                }
            ]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "pr", "comment"]:
            body_file = cmd[cmd.index("--body-file") + 1]
            self.comments.append(Path(body_file).read_text(encoding="utf-8"))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", f"unexpected: {cmd}")


class RecordingReviewers:
    """Stub reviewer runner: records (seat, prompt) and replies per family."""

    def __init__(self, replies: dict[str, str] | None = None) -> None:
        self.replies = replies or {}
        self.invocations: list[tuple[str, str, str]] = []  # (seat_id, family, prompt)

    def __call__(self, seat: Any, family_cfg: dict, prompt: str) -> str:
        self.invocations.append((seat.id, seat.family, prompt))
        return self.replies.get(seat.family, self.replies.get(seat.id, GOOD_REPLY))


def _review(tmp_path: Path, **overrides: Any) -> tuple[dict, FakeGh, RecordingReviewers, Path]:
    vault = _make_vault(tmp_path)
    note = _write_task(vault, **overrides.pop("task_kwargs", {}))
    gh = overrides.pop("gh", FakeGh())
    reviewers = overrides.pop("reviewers", RecordingReviewers())
    kwargs: dict[str, Any] = {
        "repo": "owner/repo",
        "repo_root": REPO_ROOT,
        "vault_root": vault,
        "apply": True,
        "gh_runner": gh,
        "reviewer_runner": reviewers,
        "wake_dir": tmp_path / "wake",
        "send_runner": lambda cmd: None,
        "now_iso": "2026-06-11T21:00:00+00:00",
    }
    kwargs.update(overrides)
    result = dispatch.review_pr(42, **kwargs)
    return result, gh, reviewers, note


class TestDryRun:
    def test_dry_run_plans_without_dispatching(self, tmp_path: Path) -> None:
        result, gh, reviewers, note = _review(tmp_path, apply=False)
        assert result["status"] == "planned"
        assert result["plan"]["team_class"] == "t2_standard"
        assert len(result["plan"]["seats"]) == 3
        assert reviewers.invocations == []
        assert not list(note.parent.glob("*.review-dossier.yaml"))
        assert gh.comments == []


class TestApply:
    def test_three_reviewers_cross_family_dossier(self, tmp_path: Path) -> None:
        result, gh, reviewers, note = _review(tmp_path)
        assert result["status"] == "dispatched"
        dossier = yaml.safe_load(
            (note.parent / "task-a.review-dossier.yaml").read_text(encoding="utf-8")
        )
        assert dossier["dossier_schema"] == 1
        assert dossier["head_sha"] == "c" * 40
        assert len(dossier["reviewers"]) == 3
        families = {r["family"] for r in dossier["reviewers"]}
        assert len(families) >= 2
        assert dossier["review_team_verdict"] == "quorum-accept"

    def test_reviews_are_blind(self, tmp_path: Path) -> None:
        _, _, reviewers, _ = _review(tmp_path)
        seat_ids = [seat_id for seat_id, _, _ in reviewers.invocations]
        for _, _, prompt in reviewers.invocations:
            assert "verdict: accept" not in prompt  # no other reviewer's reply embedded
            for other in seat_ids:
                assert f"reviewer {other} said" not in prompt
        # every prompt carries the diff, charters, and the output contract
        for _, _, prompt in reviewers.invocations:
            assert "diff --git" in prompt
            assert "tests-cover-the-diff" in prompt
            assert "```yaml" in prompt

    def test_pr_comment_posted_with_dossier(self, tmp_path: Path) -> None:
        _, gh, _, _ = _review(tmp_path)
        assert len(gh.comments) == 1
        assert "quorum-accept" in gh.comments[0]

    def test_unparseable_reply_records_invalid_output(self, tmp_path: Path) -> None:
        reviewers = RecordingReviewers(replies={"codex": "I have no yaml for you"})
        result, _, _, note = _review(tmp_path, reviewers=reviewers)
        dossier = yaml.safe_load(
            (note.parent / "task-a.review-dossier.yaml").read_text(encoding="utf-8")
        )
        by_family = {r["family"]: r for r in dossier["reviewers"]}
        assert by_family["codex"]["verdict"] == "invalid-output"
        # 2 valid accepts remain -> still quorum for t2
        assert dossier["review_team_verdict"] == "quorum-accept"

    def test_diff_is_truncated(self, tmp_path: Path) -> None:
        gh = FakeGh()
        gh.diff = "diff --git a/x b/x\n" + ("+x\n" * 200_000)
        _, _, reviewers, _ = _review(tmp_path, gh=gh)
        for _, _, prompt in reviewers.invocations:
            assert len(prompt) < 400_000
            assert "[diff truncated" in prompt

    def test_skips_fresh_dossier_without_force(self, tmp_path: Path) -> None:
        result, _, reviewers, note = _review(tmp_path)
        assert result["status"] == "dispatched"
        # second run, same head sha
        gh2 = FakeGh()
        reviewers2 = RecordingReviewers()
        result2 = dispatch.review_pr(
            42,
            repo="owner/repo",
            repo_root=REPO_ROOT,
            vault_root=note.parent.parent,
            apply=True,
            gh_runner=gh2,
            reviewer_runner=reviewers2,
            wake_dir=tmp_path / "wake",
            send_runner=lambda cmd: None,
            now_iso="2026-06-11T22:00:00+00:00",
        )
        assert result2["status"] == "skipped_fresh"
        assert reviewers2.invocations == []


class TestAllMode:
    def test_review_all_scans_open_prs(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_task(vault)
        gh = FakeGh()
        reviewers = RecordingReviewers()
        results = dispatch.review_all_open_prs(
            repo="owner/repo",
            repo_root=REPO_ROOT,
            vault_root=vault,
            apply=True,
            gh_runner=gh,
            reviewer_runner=reviewers,
            wake_dir=tmp_path / "wake",
            send_runner=lambda cmd: None,
        )
        assert [r["status"] for r in results] == ["dispatched"]
        assert len(reviewers.invocations) == 3

    def test_review_all_reports_unlinked_prs_as_no_task(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)  # no task note written
        results = dispatch.review_all_open_prs(
            repo="owner/repo",
            repo_root=REPO_ROOT,
            vault_root=vault,
            apply=True,
            gh_runner=FakeGh(),
            reviewer_runner=RecordingReviewers(),
            wake_dir=tmp_path / "wake",
            send_runner=lambda cmd: None,
        )
        assert [r["status"] for r in results] == ["no_task"]


class TestReceiptAndWake:
    def test_quorum_accept_writes_acceptance_receipt_for_review_floor(self, tmp_path: Path) -> None:
        result, _, _, note = _review(
            tmp_path, task_kwargs={"quality_floor": "frontier_review_required"}
        )
        receipt_path = note.parent / "task-a.acceptance.yaml"
        assert receipt_path.is_file()
        receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
        assert receipt["verdict"] == "accepted"
        assert receipt["acceptor"].startswith("review-team:")
        assert "task-a.review-dossier.yaml" in receipt["artifact"]

    def test_existing_receipt_is_never_overwritten(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        note = _write_task(vault, quality_floor="frontier_review_required")
        receipt_path = note.parent / "task-a.acceptance.yaml"
        receipt_path.write_text("acceptor: operator\nverdict: accepted\n", encoding="utf-8")
        dispatch.review_pr(
            42,
            repo="owner/repo",
            repo_root=REPO_ROOT,
            vault_root=vault,
            apply=True,
            gh_runner=FakeGh(),
            reviewer_runner=RecordingReviewers(),
            wake_dir=tmp_path / "wake",
            send_runner=lambda cmd: None,
            now_iso="2026-06-11T21:00:00+00:00",
        )
        assert "operator" in receipt_path.read_text(encoding="utf-8")

    def test_no_receipt_for_non_review_floor(self, tmp_path: Path) -> None:
        _, _, _, note = _review(tmp_path)  # frontier_required, not review floor
        assert not (note.parent / "task-a.acceptance.yaml").is_file()

    def test_block_with_critical_fires_auto_wake(self, tmp_path: Path) -> None:
        sent: list[list[str]] = []
        reviewers = RecordingReviewers(replies={"claude": BLOCK_REPLY})
        result, _, _, note = _review(
            tmp_path,
            reviewers=reviewers,
            send_runner=lambda cmd: sent.append(list(cmd)),
        )
        dossier = yaml.safe_load(
            (note.parent / "task-a.review-dossier.yaml").read_text(encoding="utf-8")
        )
        assert dossier["review_team_verdict"] == "blocked"
        wake_files = list((tmp_path / "wake").glob("*.md"))
        assert len(wake_files) == 1
        payload = wake_files[0].read_text(encoding="utf-8")
        assert "off-by-one in window math" in payload  # findings verbatim
        assert sent, "auto-wake send was not attempted"
        assert "zeta" in " ".join(sent[0])


class TestExitPredicate:
    """Task exit predicate: a test PR through the dispatcher produces a
    3-reviewer cross-family dossier, and admission blocks without quorum."""

    def test_dispatcher_dossier_flips_autoqueue_admission(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        monkeypatch.delenv("HAPAX_REVIEW_TEAM_GATE_OFF", raising=False)
        autoqueue = _load("cc_pr_autoqueue", "cc-pr-autoqueue.py")
        vault = _make_vault(tmp_path)
        _write_task(vault)
        pr_payload = {
            "number": 42,
            "id": "PR_42",
            "title": "PR 42",
            "body": "",
            "headRefName": "feat/42",
            "headRefOid": "c" * 40,
            "isDraft": False,
            "mergeStateStatus": "CLEAN",
            "labels": [],
            "reviewDecision": None,
            "autoMergeRequest": None,
            "statusCheckRollup": [
                {"__typename": "CheckRun", "name": name, "conclusion": "SUCCESS"}
                for name in ("lint", "test", "typecheck", "web-build", "vscode-build")
            ],
        }
        pr = autoqueue._parse_pr(pr_payload)
        tasks = autoqueue.load_task_notes(vault)

        before = autoqueue.classify_pr(pr, tasks=tasks, queued_prs=set())
        assert before.action == "blocked"
        assert "missing_review_dossier" in before.reasons

        result = dispatch.review_pr(
            42,
            repo="owner/repo",
            repo_root=REPO_ROOT,
            vault_root=vault,
            apply=True,
            gh_runner=FakeGh(),
            reviewer_runner=RecordingReviewers(),
            wake_dir=tmp_path / "wake",
            send_runner=lambda cmd: None,
            now_iso="2026-06-11T21:00:00+00:00",
        )
        assert result["status"] == "dispatched"
        dossier = result["dossier"]
        assert len(dossier["reviewers"]) == 3
        assert len({r["family"] for r in dossier["reviewers"]}) >= 2

        tasks = autoqueue.load_task_notes(vault)
        after = autoqueue.classify_pr(pr, tasks=tasks, queued_prs=set())
        assert after.action == "queue", after.reasons
