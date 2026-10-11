"""REST-budget behavior of the review dispatcher's ``--all`` scan.

REQ: the account's GitHub REST budget is shared by every lane, so the scan
fetches only what changed. Invariants under test (each mutation-verified):

- a PR whose head sha matches the last cycle's record makes no diff fetch;
- a rate-limit 403 stops the scan, names the reset from X-RateLimit-Reset,
  and never falls back to ``gh pr diff`` or a local git diff;
- the open-PR list is fetched once per cycle with If-None-Match, reusing the
  cached page on 304 (a 304 does not count against the budget);
- ``--force`` bypasses the unchanged-head gate; dry-run plans never record
  heads; heads of closed PRs are pruned.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO_ROOT / "scripts"
for _p in (REPO_ROOT, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
# Append, never insert: tests/shared/ must not shadow the repo's shared/ package.
_TESTS = str(Path(__file__).resolve().parent)
if _TESTS not in sys.path:
    sys.path.append(_TESTS)

from test_cc_pr_review_dispatch import (  # noqa: E402
    FakeGh,
    RecordingReviewers,
    _load,
    _make_vault,
    _write_task,
)

dispatch = _load("cc_pr_review_dispatch", "cc-pr-review-dispatch.py")

RESET_EPOCH = 1791707173
RESET_AT = datetime.fromtimestamp(RESET_EPOCH, tz=UTC).isoformat(timespec="seconds")
RATE_LIMIT_STDERR = (
    "gh: API rate limit exceeded for user ID 418460. If you reach out to GitHub "
    "Support for help, please include this request ID (HTTP 403)"
)


@pytest.fixture(autouse=True)
def _isolate_outage_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dispatch, "FAMILY_OUTAGE_STATE", tmp_path / "family-outage.json")
    monkeypatch.setattr(dispatch, "DEGRADED_MERGES_LEDGER", tmp_path / "degraded-merges.jsonl")


class ScanGh(FakeGh):
    """FakeGh over an explicit open-PR set with per-PR heads."""

    def __init__(self, heads: dict[int, str], *, files: list[str] | None = None) -> None:
        super().__init__(files=files or ["shared/foo.py", "tests/test_foo.py"])
        self.heads = heads
        self.pr_number = next(iter(heads), 42)

    def _rest_open_prs(self) -> list[dict[str, Any]]:
        return [
            {
                "number": number,
                "title": f"PR {number}",
                "base": {"ref": "main", "sha": "b" * 40},
                "head": {"ref": f"feat/{number}", "sha": sha},
                "draft": False,
                "state": "open",
            }
            for number, sha in sorted(self.heads.items())
        ]

    def _rest_pull(self, number: int) -> dict[str, Any] | None:
        sha = self.heads.get(number)
        if sha is None:
            return None
        return {
            "number": number,
            "title": f"PR {number}",
            "body": "PR body acceptance evidence",
            "head": {"ref": f"feat/{number}", "sha": sha},
            "draft": False,
            "changed_files": len(self.files),
            "mergeable_state": "clean",
            "state": "open",
        }

    def _rest_pull_files(self, number: int) -> list[dict[str, Any]] | None:
        if number not in self.heads:
            return None
        return [{"filename": path} for path in self.files]


def _scan_kwargs(vault: Path, tmp_path: Path, gh: Any, **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "repo": "owner/repo",
        "repo_root": REPO_ROOT,
        "vault_root": vault,
        "apply": True,
        "gh_runner": gh,
        "reviewer_runner": RecordingReviewers(),
        "wake_dir": tmp_path / "wake",
        "send_runner": lambda cmd: None,
        "route_blocked_families": {},
    }
    kwargs.update(overrides)
    return kwargs


def _read_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class TestUnchangedHeadGate:
    def test_scan_skips_pr_with_unchanged_head_without_fetches(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        head = "c" * 40
        state_path = tmp_path / "scan-state.json"
        state_path.write_text(json.dumps({"schema": 1, "heads": {"42": head}}), encoding="utf-8")
        gh = ScanGh({42: head})

        results = dispatch.review_all_open_prs(
            **_scan_kwargs(vault, tmp_path, gh, scan_state_path=state_path)
        )

        assert [r["status"] for r in results] == ["skipped_unchanged_head"]
        assert results[0]["pr"] == 42
        assert results[0]["head_sha"] == head
        # No diff fetch of any shape, and no per-PR metadata fetch either.
        assert not any("v3.diff" in " ".join(call) for call in gh.calls)
        assert not any(call[:3] == ["gh", "pr", "diff"] for call in gh.calls)
        assert not any(
            call[:5] == ["gh", "api", "--method", "GET", "-H"]
            and len(call) > 6
            and call[6].startswith("repos/owner/repo/pulls/42")
            for call in gh.calls
        )

    def test_scan_records_head_after_review_and_skips_next_cycle(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_task(vault)
        head = "c" * 40
        gh = ScanGh({42: head})
        state_path = tmp_path / "scan-state.json"

        first = dispatch.review_all_open_prs(
            **_scan_kwargs(vault, tmp_path, gh, scan_state_path=state_path)
        )
        assert [r["status"] for r in first] == ["dispatched"]
        assert _read_state(state_path)["heads"] == {"42": head}

        gh_second = ScanGh({42: head})
        second = dispatch.review_all_open_prs(
            **_scan_kwargs(vault, tmp_path, gh_second, scan_state_path=state_path)
        )
        assert [r["status"] for r in second] == ["skipped_unchanged_head"]
        assert not any("v3.diff" in " ".join(call) for call in gh_second.calls)

    def test_changed_head_is_reviewed_and_re_recorded(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_task(vault)
        state_path = tmp_path / "scan-state.json"
        state_path.write_text(
            json.dumps({"schema": 1, "heads": {"42": "d" * 40}}), encoding="utf-8"
        )
        head = "e" * 40
        gh = ScanGh({42: head})

        results = dispatch.review_all_open_prs(
            **_scan_kwargs(vault, tmp_path, gh, scan_state_path=state_path)
        )

        assert [r["status"] for r in results] == ["dispatched"]
        assert _read_state(state_path)["heads"] == {"42": head}

    def test_force_bypasses_the_unchanged_head_gate(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_task(vault)
        head = "c" * 40
        state_path = tmp_path / "scan-state.json"
        state_path.write_text(json.dumps({"schema": 1, "heads": {"42": head}}), encoding="utf-8")
        reviewers = RecordingReviewers()
        gh = ScanGh({42: head})

        results = dispatch.review_all_open_prs(
            **_scan_kwargs(
                vault,
                tmp_path,
                gh,
                scan_state_path=state_path,
                force=True,
                reviewer_runner=reviewers,
            )
        )

        assert [r["status"] for r in results] == ["dispatched"]
        assert reviewers.invocations

    def test_dry_run_scan_does_not_record_heads(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_task(vault)
        head = "c" * 40
        state_path = tmp_path / "scan-state.json"
        gh = ScanGh({42: head})

        results = dispatch.review_all_open_prs(
            **_scan_kwargs(vault, tmp_path, gh, scan_state_path=state_path, apply=False)
        )

        assert [r["status"] for r in results] == ["planned"]
        state = _read_state(state_path)
        assert state.get("heads", {}) == {}

    def test_dry_run_scan_does_not_record_heads_for_fresh_dossiers(self, tmp_path: Path) -> None:
        # The dossier freshness gate fires before review_pr's `not apply` return, so a
        # dry-run scan over an already-reviewed head answers skipped_fresh — a head
        # recording status. Only the apply guard keeps the dry run read-only.
        vault = _make_vault(tmp_path)
        _write_task(vault, "task-41", pr=41)
        head = "a" * 40
        state_path = tmp_path / "scan-state.json"
        gh = ScanGh({41: head})

        first = dispatch.review_all_open_prs(
            **_scan_kwargs(vault, tmp_path, gh, scan_state_path=state_path)
        )
        assert [r["status"] for r in first] == ["dispatched"]
        assert _read_state(state_path)["heads"] == {"41": head}

        # Scan state lost, dossiers intact: the next cycle re-observes the PR and the
        # freshness gate answers for it. The dry run must still record nothing.
        state_path.unlink()
        results = dispatch.review_all_open_prs(
            **_scan_kwargs(vault, tmp_path, gh, scan_state_path=state_path, apply=False)
        )

        assert [r["status"] for r in results] == ["skipped_fresh"]
        assert _read_state(state_path).get("heads", {}) == {}

    def test_scan_does_not_record_heads_for_constitution_blocked_reviews(
        self, tmp_path: Path
    ) -> None:
        # The head-recording status filter: a cycle where the constitution cannot form
        # reviewed nothing, so the PR must stay unrecorded and retry next cycle.
        vault = _make_vault(tmp_path)
        _write_task(vault, "task-41", pr=41)
        head = "a" * 40
        state_path = tmp_path / "scan-state.json"
        gh = ScanGh({41: head})
        dispatch.FAMILY_OUTAGE_STATE.parent.mkdir(parents=True, exist_ok=True)
        dispatch.FAMILY_OUTAGE_STATE.write_text(
            json.dumps(
                {
                    "claude": {
                        "observed_at": "2026-06-11T20:55:00+00:00",
                        "outage_started_at": "2026-06-11T20:00:00+00:00",
                    }
                }
            ),
            encoding="utf-8",
        )

        results = dispatch.review_all_open_prs(
            **_scan_kwargs(
                vault,
                tmp_path,
                gh,
                scan_state_path=state_path,
                route_blocked_families={
                    family: ("route_state_blocked",)
                    for family in ("gemini", "glm", "muse", "vibe", "local")
                },
            )
        )

        assert [r["status"] for r in results] == ["constitution_blocked"]
        assert _read_state(state_path).get("heads", {}) == {}

    def test_scan_prunes_heads_of_prs_no_longer_open(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_task(vault, "task-41", pr=41)
        head41 = "a" * 40
        state_path = tmp_path / "scan-state.json"
        # Only 99 is primed: 41 must dispatch fresh this cycle so the test exercises
        # recording AND pruning in one pass.
        state_path.write_text(
            json.dumps({"schema": 1, "heads": {"99": "f" * 40}}),
            encoding="utf-8",
        )
        gh = ScanGh({41: head41})

        results = dispatch.review_all_open_prs(
            **_scan_kwargs(vault, tmp_path, gh, scan_state_path=state_path)
        )

        assert [r["status"] for r in results] == ["dispatched"]
        assert _read_state(state_path)["heads"] == {"41": head41}


class TestRateLimitStop:
    def test_rate_limit_403_stops_scan_and_names_reset(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_task(vault, "task-41", pr=41)
        _write_task(vault, "task-42", pr=42)
        state_path = tmp_path / "scan-state.json"

        class RateLimitedDiffGh(ScanGh):
            def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
                if (
                    cmd[:5] == ["gh", "api", "--method", "GET", "-H"]
                    and len(cmd) > 6
                    and "v3.diff" in cmd[5]
                    and cmd[6] == "repos/owner/repo/pulls/41"
                ):
                    self.calls.append(list(cmd))
                    headers = (
                        "HTTP/1.1 403 Forbidden\r\n"
                        f"X-RateLimit-Reset: {RESET_EPOCH}\r\n"
                        "X-RateLimit-Remaining: 0\r\n"
                        "\r\n"
                    )
                    return subprocess.CompletedProcess(cmd, 1, headers, RATE_LIMIT_STDERR)
                return super().__call__(cmd, **kwargs)

        reviewers = RecordingReviewers()
        gh = RateLimitedDiffGh({41: "a" * 40, 42: "c" * 40})

        results = dispatch.review_all_open_prs(
            **_scan_kwargs(
                vault, tmp_path, gh, scan_state_path=state_path, reviewer_runner=reviewers
            )
        )

        # The scan stops at PR 41: PR 42 is never attempted, no reviewers burn.
        assert [r["status"] for r in results] == ["rate_limited"]
        assert results[0]["pr"] == 41
        assert results[0]["reset_epoch"] == RESET_EPOCH
        assert results[0]["reset_at"] == RESET_AT
        assert results[0]["next_action"]
        assert reviewers.invocations == []
        # No fallback diff of any shape after the 403.
        assert not any(call[:3] == ["gh", "pr", "diff"] for call in gh.calls)
        assert not any(call[:2] == ["git", "diff"] for call in gh.calls)
        # The rate-limited PR is not recorded as done; the next cycle retries it.
        assert _read_state(state_path).get("heads", {}) == {}

    def test_fetch_pr_diff_raises_typed_error_without_headers(self, tmp_path: Path) -> None:
        head = "c" * 40
        pr_info = dispatch.PRInfo(
            number=42,
            title="PR 42",
            body="body",
            base_ref="main",
            base_sha="b" * 40,
            head_ref="feat/42",
            head_sha=head,
            changed_file_count=1,
            is_draft=False,
            files=("shared/foo.py",),
        )

        class NoHeader403Gh(ScanGh):
            def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
                if (
                    cmd[:5] == ["gh", "api", "--method", "GET", "-H"]
                    and len(cmd) > 6
                    and "v3.diff" in cmd[5]
                ):
                    self.calls.append(list(cmd))
                    return subprocess.CompletedProcess(cmd, 1, "", RATE_LIMIT_STDERR)
                if cmd[:3] == ["gh", "pr", "diff"]:
                    self.calls.append(list(cmd))
                    pytest.fail("rate-limited diff must not fall back to gh pr diff")
                if cmd[:2] == ["git", "diff"]:
                    self.calls.append(list(cmd))
                    pytest.fail("rate-limited diff must not fall back to a local git diff")
                return super().__call__(cmd, **kwargs)

        gh = NoHeader403Gh({42: head})
        with pytest.raises(dispatch.RateLimitExceeded) as excinfo:
            dispatch.fetch_pr_diff(pr_info, repo="owner/repo", repo_root=REPO_ROOT, runner=gh)
        assert excinfo.value.reset_epoch is None
        assert "next action" in str(excinfo.value).lower()
        assert not any(call[:3] == ["gh", "pr", "diff"] for call in gh.calls)

    def test_non_rate_limit_diff_failure_keeps_existing_fallback_chain(
        self, tmp_path: Path
    ) -> None:
        head = "c" * 40
        pr_info = dispatch.PRInfo(
            number=42,
            title="PR 42",
            body="body",
            base_ref="main",
            base_sha="b" * 40,
            head_ref="feat/42",
            head_sha=head,
            changed_file_count=1,
            is_draft=False,
            files=("shared/foo.py",),
        )

        class PlainUnavailableGh(ScanGh):
            def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
                if (
                    cmd[:5] == ["gh", "api", "--method", "GET", "-H"]
                    and len(cmd) > 6
                    and "v3.diff" in cmd[5]
                ):
                    self.calls.append(list(cmd))
                    return subprocess.CompletedProcess(cmd, 1, "", "connection reset by peer")
                return super().__call__(cmd, **kwargs)

        gh = PlainUnavailableGh({42: head})
        diff = dispatch.fetch_pr_diff(pr_info, repo="owner/repo", repo_root=REPO_ROOT, runner=gh)
        assert "diff --git" in diff
        assert any(call[:3] == ["gh", "pr", "diff"] for call in gh.calls)


class TestConditionalList:
    def _primed_state(self, head: str, etag: str) -> dict[str, Any]:
        items = ScanGh({42: head})._rest_open_prs()
        return {
            "schema": 1,
            "heads": {"42": head},
            "list_pages": {
                "repos/owner/repo/pulls|state=open": {
                    "1": {"etag": etag, "items": items},
                }
            },
        }

    def test_scan_sends_if_none_match_and_reuses_304_page(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        head = "c" * 40
        etag = '"list-etag-1"'
        state_path = tmp_path / "scan-state.json"
        state_path.write_text(json.dumps(self._primed_state(head, etag)), encoding="utf-8")

        class NotModifiedGh(ScanGh):
            def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
                if (
                    cmd[:5] == ["gh", "api", "--method", "GET", "-H"]
                    and len(cmd) > 6
                    and cmd[6] == "repos/owner/repo/pulls"
                ):
                    self.calls.append(list(cmd))
                    # gh takes a header as ONE argv token: "If-None-Match: <etag>".
                    header = next(tok for tok in cmd if tok.startswith("If-None-Match:"))
                    assert header == f"If-None-Match: {etag}"
                    body = "HTTP/1.1 304 Not Modified\r\nX-RateLimit-Remaining: 5000\r\n\r\n"
                    return subprocess.CompletedProcess(cmd, 0, body, "")
                return super().__call__(cmd, **kwargs)

        gh = NotModifiedGh({42: head})
        results = dispatch.review_all_open_prs(
            **_scan_kwargs(vault, tmp_path, gh, scan_state_path=state_path)
        )

        assert [r["status"] for r in results] == ["skipped_unchanged_head"]
        # Exactly one conditional list call: no page-2 fetch, no per-PR fetches.
        list_calls = [c for c in gh.calls if len(c) > 6 and c[6] == "repos/owner/repo/pulls"]
        assert len(list_calls) == 1
        assert not any("v3.diff" in " ".join(call) for call in gh.calls)

    def test_scan_refreshes_page_and_etag_on_200(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_task(vault)
        new_head = "9" * 40
        state_path = tmp_path / "scan-state.json"
        state_path.write_text(
            json.dumps(self._primed_state("c" * 40, '"stale-etag"')), encoding="utf-8"
        )

        class FreshPageGh(ScanGh):
            def __init__(self) -> None:
                super().__init__({42: new_head})
                self.sent_if_none_match = False

            def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
                if (
                    cmd[:5] == ["gh", "api", "--method", "GET", "-H"]
                    and len(cmd) > 6
                    and cmd[6] == "repos/owner/repo/pulls"
                ):
                    self.calls.append(list(cmd))
                    if any(tok.startswith("If-None-Match:") for tok in cmd):
                        self.sent_if_none_match = True
                    body = (
                        "HTTP/1.1 200 OK\r\n"
                        'ETag: "fresh-etag"\r\n'
                        "X-RateLimit-Remaining: 4999\r\n"
                        "\r\n" + json.dumps(self._rest_open_prs())
                    )
                    return subprocess.CompletedProcess(cmd, 0, body, "")
                return super().__call__(cmd, **kwargs)

        gh = FreshPageGh()
        results = dispatch.review_all_open_prs(
            **_scan_kwargs(vault, tmp_path, gh, scan_state_path=state_path)
        )

        assert [r["status"] for r in results] == ["dispatched"]
        assert gh.sent_if_none_match
        state = _read_state(state_path)
        page = state["list_pages"]["repos/owner/repo/pulls|state=open"]["1"]
        assert page["etag"] == '"fresh-etag"'
        assert state["heads"] == {"42": new_head}


class TestLegacyMode:
    def test_scan_without_state_path_reviews_every_cycle(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_task(vault)

        first = ScanGh({42: "c" * 40})
        results = dispatch.review_all_open_prs(**_scan_kwargs(vault, tmp_path, first))
        assert [r["status"] for r in results] == ["dispatched"]
        assert any("v3.diff" in " ".join(call) for call in first.calls)

        # Legacy (no scan state) keeps today's exact behavior: the dossier freshness
        # gate stops the DIFF re-fetch, but the per-PR metadata fetch (the REST spend
        # this row removes) still happens every cycle.
        second = ScanGh({42: "c" * 40})
        results = dispatch.review_all_open_prs(**_scan_kwargs(vault, tmp_path, second))
        assert [r["status"] for r in results] == ["skipped_fresh"]
        assert not any("v3.diff" in " ".join(call) for call in second.calls)
        assert any(
            call[:5] == ["gh", "api", "--method", "GET", "-H"]
            and len(call) > 6
            and call[6] == "repos/owner/repo/pulls/42"
            for call in second.calls
        )
