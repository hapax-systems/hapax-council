"""REST-budget behavior of the review dispatcher's ``--all`` scan.

REQ: the account's GitHub REST budget is shared by every lane, so the scan
fetches only what changed. Invariants under test (each mutation-verified):

- a PR whose head sha matches the last cycle's record makes no diff fetch;
- the open-PR list is fetched once per cycle with If-None-Match, reusing the
  cached page on 304 (a 304 does not count against the budget);
- ``--force`` bypasses the unchanged-head gate; dry-run plans never record
  heads; heads of closed PRs are pruned;
- conditional-listing failures raise (fallback to the chooser; a 403's request
  ID containing "304" never reads as a 304); unusable scan state fails open.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
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


def _pulls_proc(stdout: str, stderr: str = "", rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["gh", "api"], rc, stdout, stderr)


class TestConditionalListingFailures:
    """Listing failures raise; the scan falls back."""

    @pytest.mark.parametrize(
        ("proc", "match"),
        [
            pytest.param(None, "could not run", id="runner-raises"),
            pytest.param(
                _pulls_proc("HTTP/1.1 403 Forbidden\r\n\r\n", "api rate limit exceeded", 1),
                "failed",
                id="nonzero-rc",
            ),
            pytest.param(_pulls_proc("HTTP/1.1 200 OK\r\n\r\nnot-json"), "non-json", id="non-json"),
            pytest.param(
                _pulls_proc("HTTP/1.1 200 OK\r\n\r\n" + json.dumps({"pr": 1})),
                "non-list payload",
                id="non-list",
            ),
            pytest.param(
                _pulls_proc("HTTP/1.1 304 Not Modified\r\n\r\n"),
                "without a cached copy",
                id="304-uncached",
            ),
        ],
    )
    def test_failures_raise_runtime_error(self, proc: Any, match: str) -> None:
        def runner(cmd: list[str], **kwargs: Any) -> Any:
            if proc is None:
                raise subprocess.TimeoutExpired(cmd, 120)
            return proc

        with pytest.raises(RuntimeError, match=match):
            dispatch._list_open_prs_conditional(
                repo="owner/repo",
                repo_root=REPO_ROOT,
                runner=runner,
                state={"schema": 1, "heads": {}, "list_pages": {}},
            )

    def test_403_stderr_with_304_in_request_id_does_not_read_as_304(self) -> None:
        # A 403's hex request ID can contain "304"; it must not serve the cached page.
        state = {
            "schema": 1,
            "heads": {},
            "list_pages": {
                "repos/owner/repo/pulls|state=open": {
                    "1": {"etag": '"list-etag-1"', "items": ScanGh({42: "c" * 40})._rest_open_prs()}
                }
            },
        }
        proc = _pulls_proc(
            "HTTP/1.1 403 Forbidden\r\nX-RateLimit-Remaining: 0\r\n\r\n",
            "gh: API rate limit exceeded ... request ID 0A1B:304C:5678DEF0",
            1,
        )
        with pytest.raises(RuntimeError, match="failed"):
            dispatch._list_open_prs_conditional(
                repo="owner/repo",
                repo_root=REPO_ROOT,
                runner=lambda cmd, **kwargs: proc,
                state=state,
            )


class TestChooserFallback:
    def test_conditional_listing_failure_falls_back_to_the_chooser(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        vault = _make_vault(tmp_path)
        _write_task(vault)
        head = "c" * 40
        state_path = tmp_path / "scan-state.json"
        gh = ScanGh({42: head})

        def _unavailable(**kwargs: Any) -> Any:
            raise RuntimeError("gh api pulls failed (rc=1): simulated")

        monkeypatch.setattr(dispatch, "_list_open_prs_conditional", _unavailable)

        with caplog.at_level(logging.WARNING, logger="cc-pr-review-dispatch"):
            results = dispatch.review_all_open_prs(
                **_scan_kwargs(vault, tmp_path, gh, scan_state_path=state_path)
            )

        assert [r["status"] for r in results] == ["dispatched"]
        assert "falling back to the transport chooser" in caplog.text
        assert "gh auth status" in caplog.text


class TestScanStateFailOpen:
    @pytest.mark.parametrize(
        ("content",),
        [
            pytest.param("{corrupt json", id="corrupt-file"),
            pytest.param(
                json.dumps({"schema": 999, "heads": {"42": "x" * 40}, "list_pages": {}}),
                id="wrong-schema",
            ),
        ],
    )
    def test_unusable_state_fails_open_to_fresh(self, tmp_path: Path, content: str) -> None:
        state_path = tmp_path / "scan-state.json"
        state_path.write_text(content, encoding="utf-8")
        assert dispatch._load_scan_state(state_path) == dispatch._fresh_scan_state()


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
