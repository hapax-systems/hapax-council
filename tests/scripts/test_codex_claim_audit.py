"""Regression tests for codex-claim-audit v2.

Pins the two failure shapes from the 2026-06-12 postmortem:
  - Failure class #5 (STATE-ERASING-AUDIT-ON-LIVE-LANES): the audit must never
    clear a claim cache whose task's PR is open on GitHub.
  - Failure class #4 (CLAIM-PLANE-HOST-FORK): the audit must reconcile to
    a remote host when --reconcile-host is given.

Also tests:
  - gh fail-safe: lookup errors retain the claim (treat as open)
  - Journal attribution: every cache mutation emits a structured log line.
  - Dry-run mode: --dry-run prevents ALL mutations (notes and caches).
  - Version flag: --version prints version.
  - Systemd unit validation.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "codex-claim-audit"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_vault(tmp_path: Path) -> Path:
    """Create a minimal vault structure."""
    active = tmp_path / "vault" / "active"
    active.mkdir(parents=True)
    closed = tmp_path / "vault" / "closed"
    closed.mkdir(parents=True)
    return tmp_path / "vault"


def _write_task_note(
    vault: Path,
    task_id: str,
    *,
    status: str = "claimed",
    assigned_to: str = "cx-alpha",
    pr: str = "null",
    branch: str = "null",
    claimed_at: str = "2026-06-12T08:00:00Z",
    subdir: str = "active",
) -> Path:
    note = vault / subdir / f"{task_id}.md"
    note.write_text(
        textwrap.dedent(f"""\
        ---
        type: cc-task
        task_id: {task_id}
        title: "test task {task_id}"
        status: {status}
        assigned_to: {assigned_to}
        pr: {pr}
        branch: {branch}
        claimed_at: {claimed_at}
        ---
        ## Session log
        """),
        encoding="utf-8",
    )
    return note


def _write_claim_cache(cache_dir: Path, role: str, task_id: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / f"cc-active-task-{role}"
    f.write_text(f"{task_id}\n", encoding="utf-8")
    return f


def _gh_stub(
    tmp_path: Path,
    state: str = "OPEN",
    *,
    open_pr_branch: str | None = None,
    open_pr_number: str = "8888",
) -> Path:
    """Create a fake gh command.

    - ``pr view <n> --jq .state`` echoes ``state``.
    - ``pr list --head <branch> --jq '.[0].number // empty'`` echoes
      ``open_pr_number`` when ``<branch>`` matches ``open_pr_branch`` (an OPEN
      branch PR), else echoes nothing (no open PR). Exit 0 either way so the
      branch probe distinguishes "no open PR" from "gh failed".
    """
    branch_match = open_pr_branch or ""
    stub = tmp_path / "bin" / "gh"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # Stub gh for testing
        if [[ "$1" == "pr" && "$2" == "view" ]]; then
            echo '{state}'
            exit 0
        fi
        if [[ "$1" == "pr" && "$2" == "list" ]]; then
            head=""
            while [[ $# -gt 0 ]]; do
                if [[ "$1" == "--head" ]]; then head="$2"; fi
                shift
            done
            if [[ -n "{branch_match}" && "$head" == "{branch_match}" ]]; then
                echo '{open_pr_number}'
            fi
            exit 0
        fi
        exit 1
        """),
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def _gh_stub_failing(tmp_path: Path) -> Path:
    """Create a gh command that always fails (simulates unavailable/rate-limited)."""
    stub = tmp_path / "bin" / "gh"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(
        textwrap.dedent("""\
        #!/usr/bin/env bash
        # Stub gh that always fails (rate limit / network error)
        exit 1
        """),
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def _ssh_stub(
    tmp_path: Path,
    *,
    assigned: str,
    remote_task: str | None = None,
    read_fails: bool = False,
) -> tuple[Path, Path, Path]:
    """Create a fake ssh that EXECUTES the audit's real remote command.

    Higher fidelity than re-implementing the remote logic: the fake ssh evals
    the exact command string the script sends, against a real on-disk remote
    claim fixture at ``<reconcile-dir>/cc-active-task-<assigned>``. This means
    the rename-aside atomic compare-and-delete is genuinely exercised (and its
    erasure-safety can be asserted), not merely re-stated by the stub.

    Returns ``(stub_path, remote_claim_file, calls_log)``. Tests must pass
    ``--reconcile-cache-dir=<remote_claim_file.parent>`` so the path the script
    builds resolves to the fixture.
    """
    stub = tmp_path / "bin" / "ssh"
    stub.parent.mkdir(parents=True, exist_ok=True)
    reconcile_dir = tmp_path / "remote-cache"
    reconcile_dir.mkdir(parents=True, exist_ok=True)
    remote_state = reconcile_dir / f"cc-active-task-{assigned}"
    calls = tmp_path / "ssh-calls.log"
    if remote_task is not None:
        remote_state.write_text(f"{remote_task}\n", encoding="utf-8")
    stub.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # High-fidelity ssh stub: log then eval the script's real remote command.
        cmd="${{@: -1}}"
        printf '%s\\n' "$cmd" >> "{calls}"
        if [[ "{"1" if read_fails else "0"}" == "1" ]]; then
          exit 255
        fi
        eval "$cmd"
        """),
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub, remote_state, calls


def _reconcile_args(remote_state: Path) -> list[str]:
    """Reconcile flags pointing the script's remote path at the real fixture."""
    return [
        "--reconcile-host=fake-host",
        f"--reconcile-cache-dir={remote_state.parent}",
    ]


def _write_quota_receipt(tmp_path: Path, role: str) -> Path:
    receipt = (
        tmp_path
        / "fakehome"
        / ".cache"
        / "hapax"
        / "relay"
        / "receipts"
        / f"{role}-quota-wall.yaml"
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        "status: quota_blocked\nresets_at: 2999-01-01T00:00:00Z\n",
        encoding="utf-8",
    )
    return receipt


def _run_audit(
    tmp_path: Path,
    vault: Path,
    cache_dir: Path,
    *,
    release: bool = True,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    gh_state: str = "OPEN",
    gh_stub_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run codex-claim-audit in a test sandbox."""
    if gh_stub_path is None:
        gh_stub_path = _gh_stub(tmp_path, state=gh_state)
    env = {
        "HOME": str(tmp_path / "fakehome"),
        "PATH": f"{gh_stub_path.parent}:/usr/bin:/bin",
        "HAPAX_CLAIM_CACHE_DIR": str(cache_dir),
        "HAPAX_GH_CMD": str(gh_stub_path),
        "HAPAX_CLAIM_AUDIT_PS_FIXTURE": str(tmp_path / "empty_ps.txt"),
        "NTFY_URL": "https://localhost:1",
        "NTFY_TOPIC": "test",
    }
    if extra_env:
        env.update(extra_env)

    (tmp_path / "empty_ps.txt").write_text("", encoding="utf-8")
    fake_vault = tmp_path / "fakehome" / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    fake_vault.mkdir(parents=True, exist_ok=True)
    for sub in ("active", "closed"):
        src = vault / sub
        dst = fake_vault / sub
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)

    args = [str(SCRIPT)]
    if release:
        args.append("--release")
    args.append("--stale-hours=6")
    if extra_args:
        args.extend(extra_args)

    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=str(tmp_path),
    )


# ---------------------------------------------------------------------------
# CLASS #5: STATE-ERASING-AUDIT-ON-LIVE-LANES
# ---------------------------------------------------------------------------


class TestPROpenClaimProtection:
    """Failure class #5 regression: open PR = claim is LIVE, never cleared."""

    def test_cache_sweep_open_pr_not_cleared(self, tmp_path: Path) -> None:
        """Cache sweep must not clear a cache whose PR is OPEN."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        _write_task_note(
            vault,
            "sweep-open-pr-task",
            assigned_to="cx-beta",
            pr="4108",
            branch="alpha/sdlc-vocab-export-20260612",
            status="offered",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-alpha", "sweep-open-pr-task")

        result = _run_audit(tmp_path, vault, cache_dir, release=True, gh_state="OPEN")

        assert claim_file.exists(), (
            "REGRESSION class #5: claim cache was cleared despite PR being OPEN! "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PR_OPEN_PROTECTED" in result.stdout

    def test_cache_sweep_merged_pr_cleared(self, tmp_path: Path) -> None:
        """Cache sweep clears a cache whose PR is MERGED."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        _write_task_note(
            vault,
            "sweep-merged-task",
            assigned_to="cx-beta",
            pr="3999",
            branch="beta/old-work",
            status="done",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-alpha", "sweep-merged-task")

        _run_audit(tmp_path, vault, cache_dir, release=True, gh_state="MERGED")
        assert not claim_file.exists()

    def test_quota_release_open_pr_protected_before_note_mutation(self, tmp_path: Path) -> None:
        """Quota release must not mutate the note when the task's PR is OPEN."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        note = _write_task_note(
            vault,
            "quota-with-open-pr-task",
            assigned_to="cx-alpha",
            pr="4109",
            branch="codex/cx-oofta",
            status="claimed",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-alpha", "quota-with-open-pr-task")
        _write_quota_receipt(tmp_path, "cx-alpha")
        original_note = note.read_text(encoding="utf-8")

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=["--release-quota-blocked"],
            gh_state="OPEN",
        )

        assert claim_file.exists()
        assert note.read_text(encoding="utf-8") == original_note
        assert "PR_OPEN_PROTECTED" in result.stdout

    def test_orphaned_cache_open_pr_protected(self, tmp_path: Path) -> None:
        """Cache whose note is in closed/ but PR is still OPEN must be kept."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        _write_task_note(
            vault,
            "moved-note-task",
            assigned_to="cx-oofta",
            pr="4109",
            branch="codex/cx-oofta",
            status="done",
            subdir="closed",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-oofta", "moved-note-task")

        _run_audit(tmp_path, vault, cache_dir, release=True, gh_state="OPEN")
        assert claim_file.exists()

    def test_orphaned_cache_closed_pr_cleared(self, tmp_path: Path) -> None:
        """Cache whose note is in closed/ and PR is CLOSED is cleared."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        _write_task_note(
            vault,
            "closed-note-task",
            assigned_to="cx-oofta",
            pr="4000",
            branch="codex/old",
            status="done",
            subdir="closed",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-oofta", "closed-note-task")

        _run_audit(tmp_path, vault, cache_dir, release=True, gh_state="CLOSED")
        assert not claim_file.exists()


# ---------------------------------------------------------------------------
# CLASS #5 via branch: pr:null tasks whose branch head has an OPEN PR
# ---------------------------------------------------------------------------


class TestBranchHeadRealityCheck:
    """A pr:null claim whose branch head has an OPEN PR must not be cleared.

    Covers the gh-pr-create -> note-sync race window: the PR exists on GitHub
    before the note's pr field is populated.
    """

    def test_branch_head_open_pr_protects_phantom(self, tmp_path: Path) -> None:
        """pr:null + branch with an OPEN branch PR = protected (not released)."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "branch-live-pr"
        note = _write_task_note(
            vault,
            task_id,
            assigned_to="cx-red",
            pr="null",
            branch="cx-red/live-branch",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",  # stale -> phantom-eligible
        )
        claim_file = _write_claim_cache(cache_dir, "cx-red", task_id)
        # gh: pr:null so `pr view` is never hit; `pr list --head cx-red/live-branch`
        # returns an OPEN PR (#8888).
        gh = _gh_stub(tmp_path, state="CLOSED", open_pr_branch="cx-red/live-branch")

        result = _run_audit(tmp_path, vault, cache_dir, release=True, gh_stub_path=gh)

        assert claim_file.exists(), "live branch-PR claim must be retained"
        assert "status: offered" not in note.read_text(encoding="utf-8")
        assert "PR_OPEN_PROTECTED" in result.stdout
        assert "cx-red/live-branch" in result.stdout

    def test_branch_head_indeterminate_protects_phantom(self, tmp_path: Path) -> None:
        """pr:null + branch but gh lookup FAILS = fail-safe retain."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "branch-gh-down"
        _write_task_note(
            vault,
            task_id,
            assigned_to="cx-red",
            pr="null",
            branch="cx-red/some-branch",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-red", task_id)
        gh = _gh_stub_failing(tmp_path)  # all gh calls fail -> branch probe rc 2

        result = _run_audit(tmp_path, vault, cache_dir, release=True, gh_stub_path=gh)

        assert claim_file.exists(), "indeterminate branch PR state must fail-safe retain"
        assert "PR_OPEN_PROTECTED" in result.stdout

    def test_branch_head_no_open_pr_releases(self, tmp_path: Path) -> None:
        """pr:null + branch with NO open PR = released (not over-protected)."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "branch-dead-pr"
        note = _write_task_note(
            vault,
            task_id,
            assigned_to="cx-red",
            pr="null",
            branch="cx-red/merged-branch",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-red", task_id)
        # gh succeeds but the branch has no OPEN PR (open_pr_branch unset).
        gh = _gh_stub(tmp_path, state="CLOSED")

        _run_audit(tmp_path, vault, cache_dir, release=True, gh_stub_path=gh)

        assert not claim_file.exists(), "a branch with no open PR must release"
        assert "status: offered" in note.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# gh fail-safe: lookup errors must retain the claim
# ---------------------------------------------------------------------------


class TestGHFailSafe:
    """_gh_pr_is_open must fail-safe: lookup error = treat as open."""

    def test_gh_unavailable_retains_claim(self, tmp_path: Path) -> None:
        """When gh fails (rate limit, network error), claim cache must be retained."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        _write_task_note(
            vault,
            "gh-fail-task",
            assigned_to="cx-beta",
            pr="5000",
            branch="beta/work",
            status="offered",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-alpha", "gh-fail-task")

        failing_gh = _gh_stub_failing(tmp_path)
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            gh_stub_path=failing_gh,
        )

        assert claim_file.exists(), (
            "CRITICAL: claim cache was cleared when gh was unavailable! "
            "This is the exact class #5 failure path. "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_gh_empty_output_retains_claim(self, tmp_path: Path) -> None:
        """When gh returns empty output, claim must be retained (fail-safe)."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        _write_task_note(
            vault,
            "gh-empty-task",
            assigned_to="cx-beta",
            pr="5001",
            branch="beta/work2",
            status="offered",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-alpha", "gh-empty-task")

        # gh stub that outputs empty string (simulates parse failure)
        empty_gh = tmp_path / "bin" / "gh"
        empty_gh.parent.mkdir(parents=True, exist_ok=True)
        empty_gh.write_text("#!/usr/bin/env bash\necho ''\nexit 0\n", encoding="utf-8")
        empty_gh.chmod(0o755)

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            gh_stub_path=empty_gh,
        )

        assert claim_file.exists(), (
            f"claim cache cleared on empty gh output (should fail-safe). stdout: {result.stdout}"
        )


# ---------------------------------------------------------------------------
# CLASS #4: CLAIM-PLANE-HOST-FORK
# ---------------------------------------------------------------------------


class TestHostReconciliation:
    """Failure class #4 regression."""

    def test_reconcile_success_clears_remote_then_local(self, tmp_path: Path) -> None:
        """Matching remote claim is cleared before the local claim is removed."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "phantom-task-reconcile"
        _write_task_note(
            vault,
            task_id,
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-gold", task_id)
        _stub, remote_state, calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=task_id)

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert result.returncode == 0
        assert not claim_file.exists()
        assert not remote_state.exists()  # real remote command actually cleared it
        assert "RECONCILED" in result.stdout
        assert len(calls.read_text(encoding="utf-8").splitlines()) == 1

    def test_local_clear_atomic_against_concurrent_repoint(self, tmp_path: Path) -> None:
        """A cc-claim re-point during the reconcile window must not be erased.

        Class #5 TOCTOU on the LOCAL clear path: the audit decides task X is
        releasable, reads the local claim cache, then (slowly) reconciles the
        remote over ssh. If another session re-points the SAME cache to a
        different LIVE task Y during that window, a plain read-then-rm would
        erase Y's live claim. The local clear must capture the claim atomically
        (rename-aside) so only the private snapshot is ever removed — mirroring
        the remote compare-and-delete.
        """
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "phantom-toctou-task"
        _write_task_note(
            vault,
            task_id,
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-gold", task_id)

        # ssh stub: re-point the LOCAL claim to a different live task mid-reconcile
        # (the concurrent cc-claim race), THEN run the script's real remote cmd.
        reconcile_dir = tmp_path / "remote-cache"
        reconcile_dir.mkdir(parents=True, exist_ok=True)
        remote_state = reconcile_dir / "cc-active-task-cx-gold"
        remote_state.write_text(f"{task_id}\n", encoding="utf-8")
        stub = tmp_path / "bin" / "ssh"
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(
            textwrap.dedent(f"""\
            #!/usr/bin/env bash
            cmd="${{@: -1}}"
            printf 'other-live-task\\n' > "{claim_file}"
            eval "$cmd"
            """),
            encoding="utf-8",
        )
        stub.chmod(0o755)

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert claim_file.exists(), (
            "REGRESSION class #5 TOCTOU: a concurrently re-pointed live claim was "
            "erased by a read-then-rm local clear (result rc="
            f"{result.returncode})\nSTDOUT:\n{result.stdout}"
        )
        assert claim_file.read_text(encoding="utf-8").strip() == "other-live-task"

    def test_reconcile_mismatch_keeps_local_and_note_claimed(self, tmp_path: Path) -> None:
        """A different remote task is a live-claim fork; local release fails closed."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        note = _write_task_note(
            vault,
            "phantom-mismatch-task",
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-gold", "phantom-mismatch-task")
        _stub, remote_state, _calls = _ssh_stub(
            tmp_path, assigned="cx-gold", remote_task="other-live-task"
        )
        original_note = note.read_text(encoding="utf-8")

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert claim_file.exists()
        # Atomic guard: the re-pointed remote claim is preserved intact, never
        # erased by a read-then-rm race (the rename-aside restores it).
        assert remote_state.exists()
        assert remote_state.read_text(encoding="utf-8").strip() == "other-live-task"
        assert note.read_text(encoding="utf-8") == original_note
        assert result.returncode == 2
        assert "RECONCILE_SKIP" in result.stdout
        assert "HELD: claim release preflight failed" in result.stdout

    def test_reconcile_absent_remote_allows_local_clear(self, tmp_path: Path) -> None:
        """Absent remote file is explicitly safe and local stale cache can clear."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "phantom-remote-absent"
        _write_task_note(
            vault,
            task_id,
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-gold", task_id)
        _stub, remote_state, _calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=None)

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert not claim_file.exists()
        assert "RECONCILE_SKIP" in result.stdout

    def test_reconcile_ssh_failure_keeps_local_and_note_claimed(self, tmp_path: Path) -> None:
        """ssh read failure must not be collapsed into remote-absent success."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        note = _write_task_note(
            vault,
            "phantom-ssh-fails",
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-gold", "phantom-ssh-fails")
        _stub, remote_state, _calls = _ssh_stub(
            tmp_path, assigned="cx-gold", remote_task="phantom-ssh-fails", read_fails=True
        )
        original_note = note.read_text(encoding="utf-8")

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert claim_file.exists()
        assert remote_state.exists()  # ssh failed before any mutation
        assert note.read_text(encoding="utf-8") == original_note
        assert result.returncode == 2
        assert "RECONCILE_FAILED" in result.stdout

    def test_missing_local_cache_reconciles_remote_before_note_release(
        self, tmp_path: Path
    ) -> None:
        """A vanished local cache must still reconcile appendix before note release."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)

        task_id = "phantom-local-missing"
        note = _write_task_note(
            vault,
            task_id,
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        _stub, remote_state, _calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=task_id)

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert not remote_state.exists()
        assert "RECONCILED" in result.stdout
        assert "status: offered" in note.read_text(encoding="utf-8")

    def test_missing_local_cache_open_branch_pr_retains_remote(self, tmp_path: Path) -> None:
        """A vanished local cache must NOT erase a live REMOTE open-PR claim.

        Regression for the cross-family critical: the PR/branch reality check
        was nested inside `[ -f $claim_file ]`, so when the local cache vanished
        the missing-local reconcile path cleared the remote claim with no reality
        check — the exact delta/zeta + appendix-fork surface. The check is now
        hoisted above the local/missing split: an open branch PR protects the
        remote claim and the note stays claimed.
        """
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)

        task_id = "phantom-missing-but-live-pr"
        note = _write_task_note(
            vault,
            task_id,
            assigned_to="cx-gold",
            pr="null",
            branch="cx-gold/live-branch",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        _stub, remote_state, _calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=task_id)
        gh = _gh_stub(tmp_path, state="CLOSED", open_pr_branch="cx-gold/live-branch")

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_stub_path=gh,
        )

        assert remote_state.exists(), "remote claim with an OPEN branch PR must be retained"
        assert "PR_OPEN_PROTECTED" in result.stdout
        assert "status: offered" not in note.read_text(encoding="utf-8")
        assert "RECONCILED" not in result.stdout  # reconcile never reached

    def test_missing_local_cache_gh_indeterminate_retains_remote(self, tmp_path: Path) -> None:
        """Missing local cache + gh down on the branch probe = fail-safe retain."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)

        task_id = "phantom-missing-gh-down"
        note = _write_task_note(
            vault,
            task_id,
            assigned_to="cx-gold",
            pr="null",
            branch="cx-gold/some-branch",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        _stub, remote_state, _calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=task_id)
        gh = _gh_stub_failing(tmp_path)

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_stub_path=gh,
        )

        assert remote_state.exists(), "indeterminate branch PR state must fail-safe retain remote"
        assert "PR_OPEN_PROTECTED" in result.stdout
        assert "status: offered" not in note.read_text(encoding="utf-8")

    def test_cache_sweep_deletion_uses_host_reconciliation(self, tmp_path: Path) -> None:
        """Stale-cache sweep must not bypass host reconciliation."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        _write_task_note(
            vault,
            "sweep-reconcile-task",
            assigned_to="cx-beta",
            pr="null",
            branch="beta/old-work",
            status="done",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-alpha", "sweep-reconcile-task")
        _stub, remote_state, _calls = _ssh_stub(
            tmp_path, assigned="cx-alpha", remote_task="sweep-reconcile-task"
        )

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert not claim_file.exists()
        assert not remote_state.exists()
        assert "RECONCILED" in result.stdout

    def test_reconcile_to_self_skips_ssh(self, tmp_path: Path) -> None:
        """When the reconcile target IS this host, never ssh to self.

        The preset auto-enables the unit on both hosts; an unguarded reconcile
        to self yields a persistent failed unit. The local clear path already
        owns the local cache, so a self-target reconcile is a no-op.
        """
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "phantom-self-reconcile"
        note = _write_task_note(
            vault,
            task_id,
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-gold", task_id)
        # ssh stub is on PATH; if the self-guard fails, it WOULD be invoked.
        _stub, _remote_state, calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=task_id)

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=["--reconcile-host=localhost", f"--reconcile-cache-dir={cache_dir}"],
            gh_state="CLOSED",
        )

        assert not calls.exists()  # ssh never called for a self-target
        assert not claim_file.exists()  # local clear still proceeds
        assert "self" in result.stdout
        assert "status: offered" in note.read_text(encoding="utf-8")

    def test_dry_run_prevents_all_mutations(self, tmp_path: Path) -> None:
        """--dry-run prevents BOTH cache deletion AND task note mutation."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        note = _write_task_note(
            vault,
            "dry-run-phantom",
            assigned_to="cx-cyan",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        claim_file = _write_claim_cache(cache_dir, "cx-cyan", "dry-run-phantom")
        original_note_text = note.read_text()

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=["--dry-run"],
            gh_state="CLOSED",
        )

        assert claim_file.exists(), "Dry-run should not delete claim cache"
        assert note.read_text() == original_note_text, (
            "Dry-run should not mutate the task note via sed"
        )
        assert "DRY-RUN" in result.stdout


# ---------------------------------------------------------------------------
# Session-keyed lease protection (class #4/#5: never erase a live lease)
# ---------------------------------------------------------------------------


class TestSessionKeyedLeaseProtection:
    """The cache sweep must treat a session-keyed cc-active-task-<role>-<session>
    lease as belonging to the note's base <role>, not as a stale foreign role."""

    def test_session_keyed_live_lease_not_cleared(self, tmp_path: Path) -> None:
        """A live session-keyed fallback lease must survive the sweep.

        Regression for codex-1 critical: the sweep derived assigned from the
        full filename suffix, so cc-active-task-cx-alpha-<session> was read as
        role cx-alpha-<session> and mismatched the note's assigned_to=cx-alpha,
        clearing a live lease for active branch/no-PR work.
        """
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "session-keyed-live"
        # Future claim time neutralises the staleness axis, so the ONLY thing
        # that can protect the session-keyed lease is the base-role match.
        _write_task_note(
            vault,
            task_id,
            assigned_to="cx-alpha",
            pr="null",
            branch="cx-alpha/active-work",
            status="claimed",
            claimed_at="2999-01-01T00:00:00Z",
        )
        legacy = _write_claim_cache(cache_dir, "cx-alpha", task_id)
        session_keyed = _write_claim_cache(cache_dir, "cx-alpha-sess0xDEADBEEF", task_id)

        result = _run_audit(tmp_path, vault, cache_dir, release=True, gh_state="OPEN")

        assert legacy.exists(), "legacy lease must survive"
        assert session_keyed.exists(), "session-keyed lease must survive"
        assert "CLEARED stale claim cache" not in result.stdout

    def test_session_keyed_stale_lease_still_cleared(self, tmp_path: Path) -> None:
        """A session-keyed lease whose note is terminal is still swept.

        The base-role match must not OVER-protect: when the note is done (no
        live claim), the session-keyed cache is genuinely stale and is cleared.
        """
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "session-keyed-stale"
        _write_task_note(
            vault,
            task_id,
            assigned_to="cx-alpha",
            pr="null",
            branch="null",
            status="done",
        )
        session_keyed = _write_claim_cache(cache_dir, "cx-alpha-sess0xCAFE", task_id)

        result = _run_audit(tmp_path, vault, cache_dir, release=True, gh_state="CLOSED")

        assert not session_keyed.exists(), "stale session-keyed lease must be cleared"
        assert "CLEARED stale claim cache" in result.stdout


# ---------------------------------------------------------------------------
# Journal attribution
# ---------------------------------------------------------------------------


class TestJournalAttribution:
    """Every claim-cache mutation must emit a structured log line."""

    def test_clear_emits_journal_line(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        _write_task_note(
            vault,
            "journal-test-task",
            assigned_to="cx-delta",
            pr="null",
            branch="null",
            status="done",
        )
        _write_claim_cache(cache_dir, "cx-delta", "journal-test-task")

        result = _run_audit(tmp_path, vault, cache_dir, release=True, gh_state="CLOSED")
        assert "codex-claim-audit[v2]" in result.stdout

    def test_protect_emits_journal_line(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        _write_task_note(
            vault,
            "protect-journal-task",
            assigned_to="cx-beta",
            pr="5000",
            branch="beta/work",
            status="offered",
        )
        _write_claim_cache(cache_dir, "cx-alpha", "protect-journal-task")

        result = _run_audit(tmp_path, vault, cache_dir, release=True, gh_state="OPEN")
        assert "PROTECT" in result.stdout

    def test_gh_lookup_failure_emits_journal_line(self, tmp_path: Path) -> None:
        """gh failure emits a GH_LOOKUP_FAILED journal line."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        _write_task_note(
            vault,
            "gh-journal-task",
            assigned_to="cx-beta",
            pr="5002",
            branch="beta/work3",
            status="offered",
        )
        _write_claim_cache(cache_dir, "cx-alpha", "gh-journal-task")

        failing_gh = _gh_stub_failing(tmp_path)
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            gh_stub_path=failing_gh,
        )
        assert "GH_LOOKUP_FAILED" in result.stdout


# ---------------------------------------------------------------------------
# Version flag
# ---------------------------------------------------------------------------


class TestVersionFlag:
    def test_version_output(self, tmp_path: Path) -> None:
        env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
        result = subprocess.run(
            [str(SCRIPT), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        assert result.returncode == 0
        assert "codex-claim-audit v2" in result.stdout


# ---------------------------------------------------------------------------
# Missing cache coherence
# ---------------------------------------------------------------------------


class TestMissingCacheCoherence:
    def test_missing_cache_reports_coherence(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        _write_task_note(
            vault,
            "missing-cache-task",
            assigned_to="cx-zeta",
            pr="4200",
            branch="zeta/work",
            status="claimed",
            claimed_at="2026-06-12T18:00:00Z",
        )

        result = _run_audit(tmp_path, vault, cache_dir, release=False, gh_state="OPEN")
        assert "CACHE_MISSING" in result.stdout


# ---------------------------------------------------------------------------
# Systemd unit validation
# ---------------------------------------------------------------------------


class TestSystemdUnits:
    def test_service_uses_activation_worktree(self) -> None:
        unit = SCRIPT.parent.parent / "systemd" / "units" / "codex-claim-audit.service"
        text = unit.read_text()
        assert "[Service]" in text
        assert "WorkingDirectory=%h/.cache/hapax/source-activation/worktree" in text
        assert "Environment=GH_REPO=hapax-systems/hapax-council" in text
        assert "source-activation/worktree/scripts/codex-claim-audit" in text, (
            "ExecStart must point to source-activation worktree, not mutable dev tree"
        )
        # Must NOT point to mutable dev tree
        assert "%h/projects/hapax-council/scripts/" not in text, (
            "ExecStart must NOT point to mutable dev tree (canonical-root violation)"
        )

    def test_service_enables_reconciliation(self) -> None:
        unit = SCRIPT.parent.parent / "systemd" / "units" / "codex-claim-audit.service"
        text = unit.read_text()
        # HAPAX_RECONCILE_HOST must be set (not commented out)
        assert "Environment=HAPAX_RECONCILE_HOST=" in text, (
            "Host reconciliation must be enabled in the scheduled unit"
        )
        # Verify it's not commented out
        for line in text.splitlines():
            if "HAPAX_RECONCILE_HOST" in line:
                assert not line.strip().startswith("#"), (
                    "HAPAX_RECONCILE_HOST must not be commented out"
                )

    def test_timer_unit_parses(self) -> None:
        unit = SCRIPT.parent.parent / "systemd" / "units" / "codex-claim-audit.timer"
        text = unit.read_text()
        assert "[Timer]" in text
        assert "OnCalendar=" in text

    def test_timer_has_auto_enable_marker(self) -> None:
        """Exit predicate: the timer must auto-enable on deploy.

        hapax-post-merge-deploy `enable --now`s units carrying the
        `# Hapax-Auto-Enable: true` annotation (+ an [Install] section) and
        verifies marked timers are active. Without the marker the timer relies
        on the preset alone and would not be enabled by the governed deploy.
        """
        unit = SCRIPT.parent.parent / "systemd" / "units" / "codex-claim-audit.timer"
        text = unit.read_text()
        assert any(
            line.strip().lower().replace(" ", "")
            in ("#hapax-auto-enable:true", ";hapax-auto-enable:true")
            for line in text.splitlines()
        ), "timer must carry the # Hapax-Auto-Enable: true marker"
        assert "[Install]" in text  # marker is a no-op without an [Install] section

    def test_dropin_tracked(self) -> None:
        dropin = (
            SCRIPT.parent.parent
            / "systemd"
            / "units"
            / "codex-claim-audit.service.d"
            / "99-findings-are-warning.conf"
        )
        text = dropin.read_text()
        # Findings exit a DISTINCT code (10) so a set -e crash at exit 1 is not
        # masked as success. Only 10 is whitelisted; 1 and 2 must fail the unit.
        assert "SuccessExitStatus=10" in text
        assert "SuccessExitStatus=1\n" not in text
        assert "SuccessExitStatus=2" not in text

    def test_dropin_success_code_matches_script_findings_exit(self, tmp_path: Path) -> None:
        """The drop-in's SuccessExitStatus must match the script's findings code.

        A drift between the two would either mask crashes (too broad) or fail
        the unit on every audit-with-findings (too narrow).
        """
        script_text = SCRIPT.read_text(encoding="utf-8")
        assert "FINDINGS_EXIT=10" in script_text
        dropin = (
            SCRIPT.parent.parent
            / "systemd"
            / "units"
            / "codex-claim-audit.service.d"
            / "99-findings-are-warning.conf"
        )
        assert "SuccessExitStatus=10" in dropin.read_text(encoding="utf-8")

    def test_findings_exit_is_distinct_from_crash(self, tmp_path: Path) -> None:
        """An audit that finds an unresolved coherence issue exits 10, not 1.

        Exit 1 is reserved for set -e crashes; conflating the two is what let a
        crash read as success under SuccessExitStatus=1.
        """
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        # Active claimed note whose claim cache is MISSING -> CACHE_MISSING
        # coherence finding, no release (no --release).
        _write_task_note(
            vault,
            "coherence-finding-task",
            assigned_to="cx-gold",
            status="claimed",
            claimed_at="2026-06-12T08:00:00Z",
        )
        result = _run_audit(tmp_path, vault, cache_dir, release=False, gh_state="OPEN")
        assert result.returncode == 10, (
            f"findings must exit 10 (distinct from a crash), got {result.returncode}: "
            f"{result.stdout}\n{result.stderr}"
        )
        assert "coherence" in result.stdout.lower()

    def test_dropin_has_governed_install_path(self) -> None:
        repo = SCRIPT.parent.parent
        dropin = repo / "systemd" / "units" / "codex-claim-audit.service.d"
        installer = repo / "systemd" / "scripts" / "install-units.sh"
        body = installer.read_text(encoding="utf-8")
        assert dropin.is_dir()
        assert '"$REPO_DIR"/*.service.d' in body
        assert "dest_dropin_dir" in body
        assert '"$conf" "$dest_conf"' in body

    def test_preset_includes_timer(self) -> None:
        preset = SCRIPT.parent.parent / "systemd" / "user-preset.d" / "hapax.preset"
        text = preset.read_text()
        assert "codex-claim-audit.timer" in text
