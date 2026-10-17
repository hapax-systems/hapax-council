"""Tests for hooks/scripts/work-resolution-gate.sh.

227-LOC wired PreToolUse hook on Edit/Write/MultiEdit/NotebookEdit
that blocks file mutations when the current session has unresolved
work. Three protection categories:

1. On a feature branch with commits ahead of main but no open PR.
2. On a feature branch with an open PR whose required checks are
   failing (warn, but allow edits — they're CI fixes).
3. On main with open PRs whose head branch exists locally — must
   merge / close first.

Coverage focuses on the early-exit lattice — wrong tool, no
file_path, edit_path outside any git repo, gh CLI missing, detached
HEAD, no main/master ref, and the on-feature-branch-with-no-commits
case. The gh-PR-list-dependent positive paths require a live gh
integration and are deferred to a follow-up.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "work-resolution-gate.sh"


def _run(
    payload: dict,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=15,
    )


def _edit(file_path: Path | str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}


def _make_repo(tmp_path: Path, default_branch: str = "main") -> Path:
    subprocess.run(
        ["git", "init", "-q", "-b", default_branch],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "root"],
        cwd=tmp_path,
        check=True,
    )
    # Tag origin/main so the hook's `compare_ref="origin/main"` resolves.
    subprocess.run(
        ["git", "update-ref", f"refs/remotes/origin/{default_branch}", "HEAD"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def _install_rest_status_helper(repo: Path) -> None:
    scripts = repo / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copy2(REPO_ROOT / "scripts" / "github_pr_status.py", scripts / "github_pr_status.py")


def _install_fake_rest_gh(
    tmp_path: Path, *, branch: str = "feat/ci", fail_pull_list: bool = False
) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-calls.log"
    fake = bin_dir / "gh"
    fake.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${{GH_CALL_LOG}}"
if [[ "${{1:-}}" == "pr" ]]; then
  echo "unexpected gh pr call" >&2
  exit 97
fi
if [[ "${{1:-}}" != "api" ]]; then
  echo "unexpected gh command" >&2
  exit 98
fi
path="${{6:-}}"
case "$path" in
  repos/owner/repo/pulls)
    if [[ "{"1" if fail_pull_list else "0"}" == "1" ]]; then
      echo "pull list unavailable" >&2
      exit 42
    fi
    echo '[{{"number":42,"title":"PR 42","body":"","head":{{"ref":"{branch}","sha":"sha-42"}},"draft":false,"state":"open","changed_files":1}}]'
    ;;
  repos/owner/repo/pulls/42)
    echo '{{"number":42,"title":"PR 42","body":"","head":{{"ref":"{branch}","sha":"sha-42"}},"draft":false,"state":"open","changed_files":1,"mergeable_state":"clean"}}'
    ;;
  repos/owner/repo/commits/sha-42/check-runs)
    echo '{{"check_runs":[{{"name":"test","status":"completed","conclusion":"failure"}}]}}'
    ;;
  repos/owner/repo/commits/sha-42/status)
    echo '{{"statuses":[]}}'
    ;;
  *)
    echo "unexpected gh api path: $path" >&2
    exit 99
    ;;
esac
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return bin_dir, log_path


# ── Tool gating ────────────────────────────────────────────────────


class TestToolGating:
    def test_bash_tool_silent(self) -> None:
        result = _run({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        assert result.returncode == 0
        assert result.stderr == ""

    def test_read_tool_silent(self) -> None:
        result = _run({"tool_name": "Read", "tool_input": {"file_path": "/etc/hosts"}})
        assert result.returncode == 0
        assert result.stderr == ""


# ── File-path gating ───────────────────────────────────────────────


class TestFilePathGating:
    def test_no_file_path_silent(self) -> None:
        """Edit without a file_path is malformed but the hook doesn't
        crash — bails silently."""
        result = _run({"tool_name": "Edit", "tool_input": {}})
        assert result.returncode == 0

    def test_file_path_outside_any_repo_silent(self, tmp_path: Path) -> None:
        """Editing a file outside any git repo → exit 0 silent."""
        target = tmp_path / "loose-file.txt"
        target.write_text("x")
        result = _run(_edit(target))
        assert result.returncode == 0


# ── Repo gating ────────────────────────────────────────────────────


class TestRepoGating:
    def test_clean_main_branch_no_prs_silent(self, tmp_path: Path) -> None:
        """On main, no open PRs in this clean fixture repo → exit 0."""
        repo = _make_repo(tmp_path)
        target = repo / "ok.py"
        target.write_text("# ok\n")
        # Real gh queries the parent shell's auth; in tmp repo with no
        # remote it returns empty / errors which the hook tolerates.
        result = _run(_edit(target))
        assert result.returncode == 0

    def test_feature_branch_no_commits_ahead_silent(self, tmp_path: Path) -> None:
        """On a feature branch that has zero commits ahead of main,
        the work-resolution check has nothing to gate on → exit 0."""
        repo = _make_repo(tmp_path)
        subprocess.run(
            ["git", "checkout", "-q", "-b", "feat/empty"],
            cwd=repo,
            check=True,
        )
        target = repo / "ok.py"
        target.write_text("# ok\n")
        result = _run(_edit(target))
        assert result.returncode == 0

    def test_detached_head_silent(self, tmp_path: Path) -> None:
        """Detached HEAD short-circuits before the branch checks."""
        repo = _make_repo(tmp_path)
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        subprocess.run(["git", "checkout", "-q", head_sha], cwd=repo, check=True)
        target = repo / "ok.py"
        target.write_text("# ok\n")
        result = _run(_edit(target))
        assert result.returncode == 0

    def test_feature_branch_pr_status_uses_rest_helper_not_gh_pr(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _install_rest_status_helper(repo)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:owner/repo.git"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "checkout", "-q", "-b", "feat/ci"], cwd=repo, check=True)
        target = repo / "ok.py"
        target.write_text("# ok\n")
        subprocess.run(["git", "add", "ok.py"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "feature"], cwd=repo, check=True)
        bin_dir, log_path = _install_fake_rest_gh(tmp_path)

        result = _run(
            _edit(target),
            extra_env={
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "GH_CALL_LOG": str(log_path),
                "HAPAX_GITHUB_PR_STATUS_CACHE_TTL_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        assert "has 1 failing check(s)" in result.stderr
        calls = log_path.read_text(encoding="utf-8")
        assert "\npr " not in f"\n{calls}"
        assert "repos/owner/repo/pulls" in calls
        assert "check-runs" in calls

    def test_feature_branch_rest_failure_does_not_emit_false_no_pr_block(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        _install_rest_status_helper(repo)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:owner/repo.git"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "checkout", "-q", "-b", "feat/api-down"], cwd=repo, check=True)
        target = repo / "ok.py"
        target.write_text("# ok\n")
        subprocess.run(["git", "add", "ok.py"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "feature"], cwd=repo, check=True)
        bin_dir, log_path = _install_fake_rest_gh(
            tmp_path,
            branch="feat/api-down",
            fail_pull_list=True,
        )

        result = _run(
            _edit(target),
            extra_env={
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "GH_CALL_LOG": str(log_path),
                "HAPAX_GITHUB_PR_STATUS_CACHE_TTL_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        assert "with no PR" not in result.stderr
        calls = log_path.read_text(encoding="utf-8")
        assert "repos/owner/repo/pulls" in calls

    def test_main_branch_local_pr_sweep_uses_rest_helper_not_gh_pr(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _install_rest_status_helper(repo)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:owner/repo.git"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "branch", "feat/ci"], cwd=repo, check=True)
        target = repo / "ok.py"
        target.write_text("# ok\n")
        bin_dir, log_path = _install_fake_rest_gh(tmp_path)

        result = _run(
            _edit(target),
            extra_env={
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "GH_CALL_LOG": str(log_path),
                "HAPAX_GITHUB_PR_STATUS_CACHE_TTL_SECONDS": "0",
            },
        )

        assert result.returncode == 2
        assert "PR #42 (feat/ci) — failing" in result.stderr
        calls = log_path.read_text(encoding="utf-8")
        assert "\npr " not in f"\n{calls}"
        assert "repos/owner/repo/pulls" in calls
        assert "check-runs" in calls


# ── External-tool gating ───────────────────────────────────────────


class TestExternalToolGating:
    def test_no_gh_on_path_silent(self, tmp_path: Path) -> None:
        """When gh is missing, the hook fails-open since it can't
        determine PR state — exit 0 silent (the hook is advisory not
        mandatory; CI catches what it misses)."""
        repo = _make_repo(tmp_path)
        target = repo / "ok.py"
        target.write_text("# ok\n")
        # Use absolute bash so PATH override doesn't lose the shell.
        env = dict(os.environ)
        env["PATH"] = "/usr/bin:/bin"  # may still have gh if installed there
        # If gh is in /usr/bin (systemwide install), this test will
        # exercise the gh path instead — still returns 0 because no
        # PRs in the tmp repo. Either way the hook is silent.
        result = subprocess.run(
            ["/usr/bin/bash", str(HOOK)],
            input=json.dumps(_edit(target)),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=15,
        )
        assert result.returncode == 0


# ── Local-forge origins (PLAN §4 S2: local PR refs) ─────────────────


def _install_stub_status_helper(
    repo: Path, *, rows: str, log_path: Path, fail: bool = False, fail_stderr: str = ""
) -> None:
    """A github_pr_status.py stand-in that prints fixed rows and logs its argv.

    The shim path inside the real helper is covered by
    tests/scripts/test_github_pr_status.py; here only the gate's plumbing —
    slug parsing, HAPAX_GH_BIN export, gh independence — is under test.
    """
    scripts = repo / "scripts"
    scripts.mkdir(exist_ok=True)
    stub = scripts / "github_pr_status.py"
    lines = [
        "import json, os, sys",
        "with open(os.environ['FORGE_HELPER_LOG'], 'a', encoding='utf-8') as fh:",
        "    fh.write(json.dumps({'argv': sys.argv[1:], "
        "'gh_bin': os.environ.get('HAPAX_GH_BIN')}) + '\\n')",
    ]
    if fail:
        lines.append(f"print({fail_stderr!r}, file=sys.stderr)")
        lines.append("raise SystemExit(1)")
    lines.append(f"print({rows!r})")
    stub.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _gh_free_path(tmp_path: Path) -> Path:
    """PATH with the gate's shell tools symlinked in and gh excluded."""
    bin_dir = tmp_path / "gh-free-bin"
    bin_dir.mkdir(exist_ok=True)
    for tool in (
        "bash",
        "git",
        "jq",
        "python3",
        "cat",
        "dirname",
        "grep",
        "md5sum",
        "stat",
        "date",
        "cut",
        "head",
        "rm",
    ):
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    return bin_dir


def _forge_repo(tmp_path: Path, origin: str, branch: str = "feat/forge-wip") -> tuple[Path, Path]:
    repo = _make_repo(tmp_path)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=repo, check=True)
    target = repo / "ok.py"
    target.write_text("# ok\n")
    subprocess.run(["git", "add", "ok.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "feature"], cwd=repo, check=True)
    return repo, target


class TestForgeOrigins:
    def test_forge_http_origin_no_pr_blocks_without_gh(self, tmp_path: Path) -> None:
        """An http-origin forge repo is gated on its local PRs, with no gh binary."""
        repo, target = _forge_repo(tmp_path, "http://100.85.131.41:3000/owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(repo, rows="[]", log_path=log_path)
        bin_dir = _gh_free_path(tmp_path)

        result = _run(
            _edit(target),
            extra_env={
                "PATH": f"{bin_dir}",
                "FORGE_HELPER_LOG": str(log_path),
            },
        )

        assert result.returncode == 2
        assert "with no PR" in result.stderr
        calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        # one mechanism: the helper lists through the shim selected by
        # HAPAX_GH_BIN — the dropped --forge-url flag must never reappear
        assert all("--forge-url" not in call["argv"] for call in calls)
        assert any(call["gh_bin"] == str(repo / "scripts" / "gh-forge") for call in calls)
        assert any("--head" in call["argv"] and "feat/forge-wip" in call["argv"] for call in calls)

    def test_forge_http_origin_open_pr_allows_and_notes_failing_checks(
        self, tmp_path: Path
    ) -> None:
        repo, target = _forge_repo(tmp_path, "http://100.85.131.41:3000/owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(
            repo,
            rows=json.dumps(
                [
                    {
                        "number": 12,
                        "headRefName": "feat/forge-wip",
                        "statusCheckRollup": [{"context": "ci/lint", "state": "FAILURE"}],
                    }
                ]
            ),
            log_path=log_path,
        )

        result = _run(
            _edit(target),
            extra_env={"PATH": os.environ["PATH"], "FORGE_HELPER_LOG": str(log_path)},
        )

        assert result.returncode == 0
        assert "PR #12" in result.stderr
        assert "failing check(s)" in result.stderr

    def test_forge_ssh_origin_fails_open_without_forge_url_env(self, tmp_path: Path) -> None:
        repo, target = _forge_repo(tmp_path, "ssh://git@100.85.131.41:2222/owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(repo, rows="[]", log_path=log_path)
        env = {k: v for k, v in os.environ.items() if k != "HAPAX_FORGE_URL"}
        env["FORGE_HELPER_LOG"] = str(log_path)

        result = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(_edit(target)),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=15,
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert not log_path.exists()

    def test_forge_ssh_origin_uses_forge_url_env_when_hosts_match(self, tmp_path: Path) -> None:
        repo, target = _forge_repo(tmp_path, "ssh://git@100.85.131.41:2222/owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(repo, rows="[]", log_path=log_path)

        result = _run(
            _edit(target),
            extra_env={
                "HAPAX_FORGE_URL": "http://100.85.131.41:3000",
                "FORGE_HELPER_LOG": str(log_path),
            },
        )

        assert result.returncode == 2
        assert "with no PR" in result.stderr
        calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert all("--forge-url" not in call["argv"] for call in calls)
        assert any(call["gh_bin"] == str(repo / "scripts" / "gh-forge") for call in calls)

    def test_foreign_origin_with_forge_url_env_stays_open(self, tmp_path: Path) -> None:
        """HAPAX_FORGE_URL set for the forge must not claim an unrelated host."""
        repo, target = _forge_repo(tmp_path, "git@gitlab.example:owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(repo, rows="[]", log_path=log_path)

        result = _run(
            _edit(target),
            extra_env={
                "HAPAX_FORGE_URL": "http://100.85.131.41:3000",
                "FORGE_HELPER_LOG": str(log_path),
            },
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert not log_path.exists()

    def test_foreign_http_origin_with_forge_url_env_stays_on_github_path(
        self, tmp_path: Path
    ) -> None:
        """Re-review blocker (#5048): an http origin whose host is not the
        declared forge is NOT a forge origin — it stays on the GitHub path
        (gate open, no forge listing), never blocked as unreachable."""
        repo, target = _forge_repo(tmp_path, "http://gitlab.example/owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(repo, rows="[]", log_path=log_path)
        bin_dir = _gh_free_path(tmp_path)

        result = _run(
            _edit(target),
            extra_env={
                "PATH": f"{bin_dir}",
                "HAPAX_FORGE_URL": "http://100.85.131.41:3000",
                "FORGE_HELPER_LOG": str(log_path),
            },
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert not log_path.exists()

    def test_foreign_https_origin_with_forge_url_env_stays_on_github_path(
        self, tmp_path: Path
    ) -> None:
        """Same guard for https: gitea.example.org is not the declared forge."""
        repo, target = _forge_repo(tmp_path, "https://gitea.example.org/owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(repo, rows="[]", log_path=log_path)
        bin_dir = _gh_free_path(tmp_path)

        result = _run(
            _edit(target),
            extra_env={
                "PATH": f"{bin_dir}",
                "HAPAX_FORGE_URL": "http://100.85.131.41:3000",
                "FORGE_HELPER_LOG": str(log_path),
            },
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert not log_path.exists()

    def test_foreign_ssh_url_origin_with_forge_url_env_stays_on_github_path(
        self, tmp_path: Path
    ) -> None:
        """ssh://-form host mismatch takes the GitHub path, like scp-form."""
        repo, target = _forge_repo(tmp_path, "ssh://git@gitlab.example:2222/owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(repo, rows="[]", log_path=log_path)

        result = _run(
            _edit(target),
            extra_env={
                "HAPAX_FORGE_URL": "http://100.85.131.41:3000",
                "FORGE_HELPER_LOG": str(log_path),
            },
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert not log_path.exists()

    def test_matching_http_origin_with_forge_url_env_gates(self, tmp_path: Path) -> None:
        """Matching host with the env set: still the forge path, listed
        through the shim."""
        repo, target = _forge_repo(tmp_path, "http://100.85.131.41:3000/owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(repo, rows="[]", log_path=log_path)
        bin_dir = _gh_free_path(tmp_path)

        result = _run(
            _edit(target),
            extra_env={
                "PATH": f"{bin_dir}",
                "HAPAX_FORGE_URL": "http://100.85.131.41:3000",
                "FORGE_HELPER_LOG": str(log_path),
            },
        )

        assert result.returncode == 2
        assert "with no PR" in result.stderr
        calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert any(call["gh_bin"] == str(repo / "scripts" / "gh-forge") for call in calls)

    def test_matching_https_origin_port_insensitive_gates(self, tmp_path: Path) -> None:
        """The host guard compares hosts, not ports: an https origin on the
        forge host (different scheme/port) still matches the declared forge."""
        repo, target = _forge_repo(tmp_path, "https://100.85.131.41:3443/owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(repo, rows="[]", log_path=log_path)
        bin_dir = _gh_free_path(tmp_path)

        result = _run(
            _edit(target),
            extra_env={
                "PATH": f"{bin_dir}",
                "HAPAX_FORGE_URL": "http://100.85.131.41:3000",
                "FORGE_HELPER_LOG": str(log_path),
            },
        )

        assert result.returncode == 2
        assert "with no PR" in result.stderr
        calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert any(call["gh_bin"] == str(repo / "scripts" / "gh-forge") for call in calls)

    def test_forge_listing_failure_on_feature_branch_blocks(self, tmp_path: Path) -> None:
        """R1 (#5048): an unreachable forge blocks source edits.

        A listing the gate could not obtain must never read as "no PR" — that
        would let unmerged source work through on exactly the days the forge
        is down. The block carries a named next action, and the helper's
        error detail must reach the block message (rest_pr_json runs under
        $(...), so the detail travels via file, not variables).
        """
        repo, target = _forge_repo(tmp_path, "http://100.85.131.41:3000/owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(
            repo,
            rows="[]",
            log_path=log_path,
            fail=True,
            fail_stderr="github_pr_status: shim_listing_failed: cannot reach"
            " http://100.85.131.41:3000",
        )
        bin_dir = _gh_free_path(tmp_path)

        result = _run(
            _edit(target),
            extra_env={"PATH": f"{bin_dir}", "FORGE_HELPER_LOG": str(log_path)},
        )

        assert result.returncode == 2
        assert "local forge unreachable" in result.stderr
        assert "Restore the forge" in result.stderr
        assert "owner/repo" in result.stderr
        assert "shim_listing_failed: cannot reach http://100.85.131.41:3000" in result.stderr

    def test_forge_listing_failure_on_main_sweep_blocks(self, tmp_path: Path) -> None:
        """R1 (#5048) at the §7 site: the on-main open-PR sweep fails closed
        on the forge path too, instead of caching "[]" and letting edits
        through unverified."""
        repo = _make_repo(tmp_path)
        subprocess.run(
            ["git", "remote", "add", "origin", "http://100.85.131.41:3000/owner/repo.git"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "branch", "feat/forge-wip"], cwd=repo, check=True)
        target = repo / "ok.py"
        target.write_text("# ok\n")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(
            repo, rows="[]", log_path=log_path, fail=True, fail_stderr="listing failed"
        )
        bin_dir = _gh_free_path(tmp_path)

        result = _run(
            _edit(target),
            extra_env={"PATH": f"{bin_dir}", "FORGE_HELPER_LOG": str(log_path)},
        )

        assert result.returncode == 2
        assert "local forge unreachable" in result.stderr
        assert "listing failed" in result.stderr

    def test_docs_edit_allowed_even_when_forge_unreachable(self, tmp_path: Path) -> None:
        """The fail-closed block is for release-risk SOURCE work only: docs
        and cognition paths keep their exemption regardless of forge state."""
        repo, target = _forge_repo(tmp_path, "http://100.85.131.41:3000/owner/repo.git")
        docs_dir = repo / "docs"
        docs_dir.mkdir()
        doc = docs_dir / "note.md"
        doc.write_text("note\n")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(
            repo, rows="[]", log_path=log_path, fail=True, fail_stderr="listing failed"
        )
        bin_dir = _gh_free_path(tmp_path)

        result = _run(
            _edit(doc),
            extra_env={"PATH": f"{bin_dir}", "FORGE_HELPER_LOG": str(log_path)},
        )

        assert result.returncode == 0
        assert result.stderr == ""
        assert not log_path.exists()

    def test_cc_pr_repo_override_wins_on_forge_origin(self, tmp_path: Path) -> None:
        """R3 (#5048), set outcome: the override slug wins and the listing
        still runs through the forge mechanism (HAPAX_GH_BIN shim)."""
        repo, target = _forge_repo(tmp_path, "http://100.85.131.41:3000/owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(repo, rows="[]", log_path=log_path)
        bin_dir = _gh_free_path(tmp_path)

        result = _run(
            _edit(target),
            extra_env={
                "PATH": f"{bin_dir}",
                "FORGE_HELPER_LOG": str(log_path),
                "HAPAX_CC_PR_REPO": "other-owner/other-repo",
            },
        )

        assert result.returncode == 2
        assert "with no PR" in result.stderr
        calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert calls
        for call in calls:
            argv = call["argv"]
            assert argv[argv.index("--repo") + 1] == "other-owner/other-repo"
            assert call["gh_bin"] == str(repo / "scripts" / "gh-forge")

    def test_cc_pr_repo_unset_falls_back_to_forge_origin_slug(self, tmp_path: Path) -> None:
        """R3 (#5048), unset outcome: without the override the slug comes
        from the forge origin."""
        repo, target = _forge_repo(tmp_path, "http://100.85.131.41:3000/owner/repo.git")
        log_path = tmp_path / "helper.log"
        _install_stub_status_helper(repo, rows="[]", log_path=log_path)
        bin_dir = _gh_free_path(tmp_path)
        env = {k: v for k, v in os.environ.items() if k != "HAPAX_CC_PR_REPO"}
        env.update({"PATH": f"{bin_dir}", "FORGE_HELPER_LOG": str(log_path)})

        result = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(_edit(target)),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=15,
        )

        assert result.returncode == 2
        calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert calls
        for call in calls:
            argv = call["argv"]
            assert argv[argv.index("--repo") + 1] == "owner/repo"


# ── Executable bit (re-review blocker on #5048) ─────────────────────


class TestHookExecutableBit:
    """The hook must stay executable on disk and as the tracked git mode.

    A git-data API tree entry keeps its mode only when the push sends it
    explicitly; a push that omits it silently downgrades 100755 → 100644.
    Every functional test runs the hook as `bash HOOK`, so the mode loss
    is invisible to them — it is pinned here, on both signals.
    """

    def test_hook_executable_on_disk(self) -> None:
        assert os.access(HOOK, os.X_OK), (
            f"{HOOK} lost its on-disk executable bit; restore with chmod +x"
        )

    def test_hook_tracked_mode_is_100755(self) -> None:
        listing = subprocess.run(
            ["git", "ls-files", "-s", "--", "hooks/scripts/work-resolution-gate.sh"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert listing, "hook is not tracked by git"
        assert listing[0] == "100755", f"tracked mode is {listing[0]}, expected 100755"
