"""Red-first tests for the gh-shaped Forgejo shim (scripts/gh-forge).

Phase A of the S2 re-target (task forge-s2-review-chain-20261005): the shim must
preserve gh argv shapes exactly (hooks classify by spelling; callers pin argv)
and emit gh-shaped JSON from Forgejo REST responses. All transport is faked;
live shadow verification runs outside pytest.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "gh-forge"


def _load_shim():
    loader = importlib.machinery.SourceFileLoader("gh_forge", str(SCRIPT))
    spec = importlib.util.spec_from_loader("gh_forge", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gh_forge"] = module
    loader.exec_module(module)
    return module


class FakeForge:
    """Records requests; serves canned Forgejo payloads."""

    def __init__(self, responses: dict[str, tuple[int, object]] | None = None):
        self.calls: list[SimpleNamespace] = []
        self.responses = responses or {}

    def __call__(self, method: str, url: str, body=None, headers=None):
        self.calls.append(
            SimpleNamespace(method=method, url=url, body=body, headers=headers or {})
        )
        for suffix, response in self.responses.items():
            if url.endswith(suffix):
                status, payload = response
                return status, payload if isinstance(payload, str) else json.dumps(payload)
        return 404, json.dumps({"message": "not found", "url": suffix_bad(url)})


def suffix_bad(url: str) -> str:
    return url


@pytest.fixture()
def shim(monkeypatch, tmp_path):
    module = _load_shim()
    fake = FakeForge()
    monkeypatch.setattr(module, "transport_request", fake)
    monkeypatch.setattr(module, "resolve_repo", lambda cwd=None, env=None: "forge-admin/driver")
    monkeypatch.setattr(module, "_env", lambda k, d=None: {"FORGE_URL": "http://forge.test"}.get(k, d))
    monkeypatch.setattr(module, "_token", lambda: "test-token")
    module._fake_forge = fake
    return module


def run(shim, argv: list[str]) -> tuple[int, str, str, SimpleNamespace | None]:
    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = shim.main(argv)
    return code, out.getvalue(), err.getvalue(), getattr(shim, "_fake_forge", None)


def last(fake: FakeForge) -> SimpleNamespace:
    return fake.calls[-1]


# --- issue view ---------------------------------------------------------------


def test_issue_view_maps_fields_and_uppercases_state(shim):
    shim._fake_forge.responses = {
        "/issues/9": (
            200,
            {
                "number": 9,
                "title": "scratch",
                "body": "text",
                "state": "open",
                "labels": [{"name": "agent-eligible"}],
            },
        )
    }
    code, out, err, fake = run(
        shim, ["issue", "view", "9", "--json", "number,title,body,labels"]
    )
    assert code == 0, err
    data = json.loads(out)
    assert data == {
        "number": 9,
        "title": "scratch",
        "body": "text",
        "labels": [{"name": "agent-eligible"}],
    }
    assert last(fake).method == "GET"
    assert "/repos/forge-admin/driver/issues/9" in last(fake).url


def test_issue_view_state_mapping_open_and_closed(shim):
    shim._fake_forge.responses = {
        "/issues/1": (200, {"number": 1, "title": "t", "body": "", "state": "closed", "labels": []}),
        "/issues/2": (200, {"number": 2, "title": "t", "body": "", "state": "open", "labels": []}),
    }
    for n, expected in ((1, "CLOSED"), (2, "OPEN")):
        _, out, _, _ = run(shim, ["issue", "view", str(n), "--json", "state"])
        assert json.loads(out)["state"] == expected


# --- issue list ---------------------------------------------------------------


def test_issue_list_maps_state_search_limit(shim):
    shim._fake_forge.responses = {
        "/issues?type=issues&state=closed&q=typo&limit=5": (
            200,
            [
                {
                    "number": 3,
                    "title": "Fix typo",
                    "state": "closed",
                    "labels": [{"name": "sdlc:done"}],
                }
            ],
        )
    }
    code, out, err, fake = run(
        shim,
        [
            "issue",
            "list",
            "--state",
            "closed",
            "--search",
            "typo",
            "--limit",
            "5",
            "--json",
            "number,title,labels,state",
        ],
    )
    assert code == 0, err
    items = json.loads(out)
    assert items == [
        {"number": 3, "title": "Fix typo", "labels": [{"name": "sdlc:done"}], "state": "CLOSED"}
    ]
    url = last(fake).url
    assert "state=closed" in url and "q=typo" in url and "limit=5" in url


# --- pr view ------------------------------------------------------------------


def test_pr_view_headrefname_and_labels(shim):
    shim._fake_forge.responses = {
        "/pulls/10": (
            200,
            {
                "number": 10,
                "title": "probe",
                "body": "b",
                "state": "open",
                "merged": False,
                "merged_at": None,
                "labels": [],
                "head": {"ref": "shim/phase-a-verify"},
            },
        )
    }
    code, out, err, _ = run(
        shim, ["pr", "view", "10", "--json", "number,title,body,labels,headRefName"]
    )
    assert code == 0, err
    data = json.loads(out)
    assert data["headRefName"] == "shim/phase-a-verify"
    assert data["number"] == 10


def test_pr_view_merged_state_and_mergedat(shim):
    shim._fake_forge.responses = {
        "/pulls/6": (
            200,
            {
                "number": 6,
                "title": "repair",
                "body": "",
                "state": "closed",
                "merged": True,
                "merged_at": "2026-10-05T18:49:00Z",
                "labels": [],
                "head": {"ref": "repair/gate-scope"},
            },
        )
    }
    code, out, err, _ = run(shim, ["pr", "view", "6", "--json", "state,mergedAt"])
    assert code == 0, err
    data = json.loads(out)
    assert data["state"] == "MERGED"
    assert data["mergedAt"] == "2026-10-05T18:49:00Z"


def test_pr_view_files_shape(shim):
    shim._fake_forge.responses = {
        "/pulls/10": (200, {"number": 10, "title": "probe", "head": {"ref": "shim/phase-a-verify"}}),
        "/pulls/10/files": (200, [{"filename": "shim-phase-a-probe.txt", "additions": 1}]),
    }
    code, out, err, _ = run(shim, ["pr", "view", "10", "--json", "files"])
    assert code == 0, err
    data = json.loads(out)
    assert data["files"][0]["path"] == "shim-phase-a-probe.txt"


def test_pr_diff_raw_passthrough(shim):
    shim._fake_forge.responses = {"/pulls/10.diff": (200, "diff --git a/x b/x\n")}
    code, out, err, fake = run(shim, ["pr", "diff", "10"])
    assert code == 0, err
    assert out == "diff --git a/x b/x\n"
    assert last(fake).url.endswith("/pulls/10.diff")


# --- labels -------------------------------------------------------------------


def test_label_add_is_idempotent_replace(shim):
    shim._fake_forge.responses = {
        "/issues/9/labels": (
            200,
            [{"name": "agent-eligible"}],
        )
    }
    code, _, err, fake = run(
        shim, ["issue", "edit", "9", "--add-label=agent-eligible", "--add-label=sdlc:planning"]
    )
    assert code == 0, err
    assert last(fake).method == "PUT"
    assert json.loads(last(fake).body) == {"labels": ["agent-eligible", "sdlc:planning"]}


def test_label_flags_accept_space_form_like_gh(shim):
    # production sdlc workflows spell flags space-separated (gh accepts both
    # forms); the equals-only parser silently no-ops this argv shape
    shim._fake_forge.responses = {"/issues/9/labels": (200, [{"name": "agent-eligible"}])}
    code, _, err, fake = run(
        shim,
        ["issue", "edit", "9", "--add-label", "sdlc:triaged", "--remove-label", "agent-eligible"],
    )
    assert code == 0, err
    assert last(fake).method == "PUT"
    assert json.loads(last(fake).body) == {"labels": ["sdlc:triaged"]}


def test_pr_create_posts_pull_and_labels_like_gh(shim, tmp_path, monkeypatch):
    # production sdlc-implement calls `gh pr create` with --title/--body and
    # repeatable --label flags only; like gh, the shim infers head from the
    # cwd git branch and base from the repo default branch, then applies labels
    shim._fake_forge.responses = {
        "/repos/forge-admin/driver": (200, {"default_branch": "main"}),
        "/repos/forge-admin/driver/pulls": (
            201,
            {"number": 21, "html_url": "http://forge.test/forge-admin/driver/pulls/21"},
        ),
        "/issues/21/labels": (200, [{"name": "agent-authored"}]),
    }
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/agent/issue-9-probe\n")
    monkeypatch.chdir(tmp_path)
    code, out, err, fake = run(
        shim,
        [
            "pr", "create",
            "--title", "[agent] Probe",
            "--body", "## Summary\n\nAutomated implementation.",
            "--label", "agent-authored",
            "--label", "sdlc:in-review",
        ],
    )
    assert code == 0, err
    create = next(c for c in fake.calls if c.method == "POST" and c.url.endswith("/pulls"))
    assert json.loads(create.body) == {
        "title": "[agent] Probe",
        "body": "## Summary\n\nAutomated implementation.",
        "head": "agent/issue-9-probe",
        "base": "main",
    }
    lab = next(c for c in fake.calls if c.method == "POST" and c.url.endswith("/issues/21/labels"))
    assert json.loads(lab.body) == {"labels": ["agent-authored", "sdlc:in-review"]}
    assert "pulls/21" in out


def test_pr_create_explicit_head_and_base_override_inference(shim, tmp_path, monkeypatch):
    shim._fake_forge.responses = {
        "/repos/forge-admin/driver": (200, {"default_branch": "main"}),
        "/repos/forge-admin/driver/pulls": (
            201,
            {"number": 22, "html_url": "http://forge.test/forge-admin/driver/pulls/22"},
        ),
    }
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/some-other\n")
    monkeypatch.chdir(tmp_path)
    code, _, err, fake = run(
        shim,
        ["pr", "create", "--title", "t", "--body", "b",
         "--head", "agent/issue-2-work", "--base", "stage/x"],
    )
    assert code == 0, err
    create = next(c for c in fake.calls if c.method == "POST" and c.url.endswith("/pulls"))
    body = json.loads(create.body)
    assert body["head"] == "agent/issue-2-work"
    assert body["base"] == "stage/x"


def test_pr_create_without_git_head_fails_closed_with_next_action(shim, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, _, err, _ = run(shim, ["pr", "create", "--title", "t", "--body", "b"])
    assert code == 1
    assert "Next action" in err



def test_label_remove_absent_is_noop_success(shim):
    shim._fake_forge.responses = {"/issues/9/labels": (200, [{"name": "other"}])}
    code, _, err, fake = run(shim, ["issue", "edit", "9", "--remove-label=absent"])
    assert code == 0, err
    # only the GET happened; nothing to PATCH
    assert [c.method for c in fake.calls] == ["GET"]


def test_label_remove_present_patches_without_it(shim):
    shim._fake_forge.responses = {"/issues/9/labels": (200, [{"name": "a"}, {"name": "b"}])}
    code, _, err, fake = run(shim, ["pr", "edit", "9", "--remove-label=a"])
    assert code == 0, err
    assert json.loads(last(fake).body) == {"labels": ["b"]}


# --- api subcommand -----------------------------------------------------------


def test_api_get_owner_repo_templating(shim):
    shim._fake_forge.responses = {"/pulls/10/reviews": (200, [])}
    code, _, err, fake = run(shim, ["api", "repos/{owner}/{repo}/pulls/10/reviews"])
    assert code == 0, err
    assert last(fake).url.endswith("/repos/forge-admin/driver/pulls/10/reviews")
    assert last(fake).method == "GET"


def test_api_post_fields_and_review_event_mapping(shim):
    shim._fake_forge.responses = {"/pulls/10/reviews": (201, {"id": 1})}
    code, _, err, fake = run(
        shim,
        [
            "api",
            "repos/{owner}/{repo}/pulls/10/reviews",
            "-X",
            "POST",
            "-f",
            "event=APPROVE",
            "-f",
            "body=ship it",
        ],
    )
    assert code == 0, err
    body = json.loads(last(fake).body)
    assert body == {"event": "APPROVED", "body": "ship it"}


def test_api_dispatches_fails_closed_with_next_action(shim):
    code, _, err, _ = run(
        shim,
        [
            "api",
            "repos/{owner}/{repo}/dispatches",
            "-X",
            "POST",
            "-f",
            "event_type=triage",
        ],
    )
    assert code != 0
    assert "workflow_dispatch" in err or "actions/workflows" in err
    assert "next action" in err.lower()


def test_api_workflow_dispatch_passes_through(shim):
    """V1 shape: actions/workflows/{file}/dispatches is the supported route."""
    shim._fake_forge.responses = {
        "/actions/workflows/sdlc-plan.yml/dispatches": (204, ""),
    }
    code, _, err, fake = run(
        shim,
        [
            "api",
            "repos/{owner}/{repo}/actions/workflows/sdlc-plan.yml/dispatches",
            "-X",
            "POST",
            "-f",
            "ref=main",
            "-f",
            "inputs.issue_number=9",
        ],
    )
    assert code == 0, err
    assert last(fake).method == "POST"
    body = json.loads(last(fake).body)
    assert body == {"ref": "main", "inputs": {"issue_number": "9"}}


def test_pr_checks_state_mapping(shim):
    shim._fake_forge.responses = {
        "/commits/deadbeef/statuses": (
            200,
            [
                # history rows in arbitrary order; per context only the max-id row counts
                {"id": 6, "context": "ci-shaped / lint-shaped", "status": "pending"},
                {"id": 5, "context": "mq-gate / gate", "status": "pending"},
                {"id": 7, "context": "ci-shaped / lint-shaped", "status": "success"},
                {"id": 4, "context": "broken / job", "status": "error"},
            ],
        ),
        "/pulls/10": (
            200,
            {"number": 10, "head": {"sha": "deadbeef"}},
        ),
    }
    code, out, err, _ = run(shim, ["pr", "checks", "10", "--json", "name,state,conclusion"])
    assert code == 0, err
    rows = json.loads(out)
    by_name = {r["name"]: r for r in rows}
    assert by_name["ci-shaped / lint-shaped"]["state"] == "pass"
    assert by_name["mq-gate / gate"]["state"] == "pending"
    assert by_name["broken / job"]["state"] == "fail"
    assert by_name["broken / job"]["conclusion"] == "error"
    assert len(rows) == 3


# --- repo resolution ----------------------------------------------------------


def test_repo_resolution_env_override_and_origin_shapes(shim, tmp_path, monkeypatch):
    resolved = shim.resolve_repo
    assert resolved(env={"GH_REPO": "forge-admin/driver"}) == "forge-admin/driver"
    cases = {
        "http://100.85.131.41:3000/forge-admin/driver.git": "forge-admin/driver",
        "https://forge.example/forge-admin/driver": "forge-admin/driver",
        "ssh://git@100.85.131.41:2222/forge-admin/driver.git": "forge-admin/driver",
        "git@100.85.131.41:forge-admin/driver.git": "forge-admin/driver",
    }
    for origin, expected in cases.items():
        assert resolved(env={"FAKE_ORIGIN": origin}) == expected, origin


# --- jq passthrough -----------------------------------------------------------


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_jq_filter_applies_to_json_output(shim):
    shim._fake_forge.responses = {
        "/issues/9": (200, {"number": 9, "title": "t", "body": "", "state": "open", "labels": []}),
    }
    code, out, err, _ = run(shim, ["issue", "view", "9", "--json", "state", "--jq", ".state"])
    assert code == 0, err
    # gh prints --jq scalar string results raw (jq -r), not JSON-quoted
    assert out.strip() == "OPEN"


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_jq_string_stream_prints_raw_lines_like_gh(shim):
    # production sdlc-review consumes `pr view --json labels --jq '.labels[].name'`
    # in a shell loop matching review-round:* — quoted lines would never match
    shim._fake_forge.responses = {
        "/pulls/16": (200, {"labels": [{"name": "agent-authored"}, {"name": "review-round:1"}]}),
    }
    code, out, err, _ = run(
        shim, ["pr", "view", "16", "--json", "labels", "--jq", ".labels[].name"]
    )
    assert code == 0, err
    assert out == "agent-authored\nreview-round:1\n"


# --- sdlc/github.py re-point ---------------------------------------------------


def test_sdlc_github_uses_hapax_gh_bin(monkeypatch):
    sys.path.insert(0, str(REPO_ROOT))
    import sdlc.github as gh

    seen: list[list[str]] = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.delenv("HAPAX_GH_BIN", raising=False)
    gh._run_gh("issue", "view", "9")
    assert seen[0][0] == "gh"

    monkeypatch.setenv("HAPAX_GH_BIN", "/opt/gh-forge")
    gh._run_gh("issue", "view", "9")
    assert seen[1][0] == "/opt/gh-forge"
