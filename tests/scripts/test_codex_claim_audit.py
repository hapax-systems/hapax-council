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


def _gh_stub(tmp_path: Path, state: str = "OPEN") -> Path:
    """Create a fake gh command that returns a fixed PR state."""
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
    remote_task: str | None = None,
    read_fails: bool = False,
    clear_fails: bool = False,
) -> tuple[Path, Path, Path]:
    """Create a fake ssh command plus a remote claim-file fixture."""
    stub = tmp_path / "bin" / "ssh"
    stub.parent.mkdir(parents=True, exist_ok=True)
    remote_state = tmp_path / "remote-claim"
    calls = tmp_path / "ssh-calls.log"
    if remote_task is not None:
        remote_state.write_text(f"{remote_task}\n", encoding="utf-8")
    stub.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        cmd="${{@: -1}}"
        printf '%s\\n' "$cmd" >> "{calls}"
        case "$cmd" in
          remote_file=*)
            if [[ "{"1" if read_fails else "0"}" == "1" ]]; then
              exit 255
            fi
            if [[ ! -s "{remote_state}" ]]; then
              printf 'ABSENT\\n'
              exit 0
            fi
            remote_task="$(head -n1 "{remote_state}" | tr -d '[:space:]')"
            task_id="$(printf '%s\\n' "$cmd" | sed -nE 's/.*task_id=([^ ;]+).*/\\1/p' | head -n1)"
            if [[ "$remote_task" != "$task_id" ]]; then
              printf 'MISMATCH:%s\\n' "$remote_task"
              exit 3
            fi
            if [[ "{"1" if clear_fails else "0"}" == "1" ]]; then
              exit 255
            fi
            rm -f "{remote_state}"
            printf 'CLEARED\\n'
            exit 0
            ;;
          if\\ \\[\\ -s*)
            if [[ "{"1" if read_fails else "0"}" == "1" ]]; then
              exit 255
            fi
            if [[ -s "{remote_state}" ]]; then
              head -n1 "{remote_state}" | tr -d '[:space:]'
            fi
            exit 0
            ;;
          rm\\ -f*)
            if [[ "{"1" if clear_fails else "0"}" == "1" ]]; then
              exit 255
            fi
            rm -f "{remote_state}"
            exit 0
            ;;
        esac
        exit 0
        """),
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub, remote_state, calls


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
        _stub, _remote_state, calls = _ssh_stub(tmp_path, remote_task=task_id)

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=["--reconcile-host=fake-host", "--reconcile-cache-dir=/remote/cache"],
            gh_state="CLOSED",
        )

        assert result.returncode == 0
        assert not claim_file.exists()
        assert "RECONCILED" in result.stdout
        assert len(calls.read_text(encoding="utf-8").splitlines()) == 1

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
        _ssh_stub(tmp_path, remote_task="other-live-task")
        original_note = note.read_text(encoding="utf-8")

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=["--reconcile-host=fake-host", "--reconcile-cache-dir=/remote/cache"],
            gh_state="CLOSED",
        )

        assert claim_file.exists()
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
        _ssh_stub(tmp_path, remote_task=None)

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=["--reconcile-host=fake-host", "--reconcile-cache-dir=/remote/cache"],
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
        _ssh_stub(tmp_path, remote_task="phantom-ssh-fails", read_fails=True)
        original_note = note.read_text(encoding="utf-8")

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=["--reconcile-host=fake-host", "--reconcile-cache-dir=/remote/cache"],
            gh_state="CLOSED",
        )

        assert claim_file.exists()
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
        _stub, remote_state, _calls = _ssh_stub(tmp_path, remote_task=task_id)

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=["--reconcile-host=fake-host", "--reconcile-cache-dir=/remote/cache"],
            gh_state="CLOSED",
        )

        assert not remote_state.exists()
        assert "RECONCILED" in result.stdout
        assert "status: offered" in note.read_text(encoding="utf-8")

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
        _ssh_stub(tmp_path, remote_task="sweep-reconcile-task")

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=["--reconcile-host=fake-host", "--reconcile-cache-dir=/remote/cache"],
            gh_state="CLOSED",
        )

        assert not claim_file.exists()
        assert "RECONCILED" in result.stdout

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

    def test_dropin_tracked(self) -> None:
        dropin = (
            SCRIPT.parent.parent
            / "systemd"
            / "units"
            / "codex-claim-audit.service.d"
            / "99-findings-are-warning.conf"
        )
        text = dropin.read_text()
        assert "SuccessExitStatus=1" in text
        assert "SuccessExitStatus=2" not in text
        assert "exit 2" in text

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
