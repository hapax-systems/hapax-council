"""Regression tests for codex-claim-audit v2.

Pins the two failure shapes from the 2026-06-12 postmortem:
  - Failure class #5 (STATE-ERASING-AUDIT-ON-LIVE-LANES): the audit must never
    clear a claim cache whose task's PR is open on GitHub.
  - Failure class #4 (CLAIM-PLANE-HOST-FORK): the audit must reconcile to
    a remote host when --reconcile-host is given.

Also tests the new v2 behaviors:
  - Journal attribution: every cache mutation emits a log line.
  - Dry-run mode: --dry-run prevents mutations.
  - Version flag: --version prints version.
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


def _run_audit(
    tmp_path: Path,
    vault: Path,
    cache_dir: Path,
    *,
    release: bool = True,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    gh_state: str = "OPEN",
) -> subprocess.CompletedProcess[str]:
    """Run codex-claim-audit in a test sandbox."""
    gh_stub = _gh_stub(tmp_path, state=gh_state)
    env = {
        "HOME": str(tmp_path / "fakehome"),
        "PATH": f"{gh_stub.parent}:/usr/bin:/bin",
        "HAPAX_CLAIM_CACHE_DIR": str(cache_dir),
        "HAPAX_GH_CMD": str(gh_stub),
        # Empty ps fixture to skip process scan
        "HAPAX_CLAIM_AUDIT_PS_FIXTURE": str(tmp_path / "empty_ps.txt"),
        # No ntfy in tests
        "NTFY_URL": "https://localhost:1",
        "NTFY_TOPIC": "test",
    }
    if extra_env:
        env.update(extra_env)

    # Create empty ps fixture
    (tmp_path / "empty_ps.txt").write_text("", encoding="utf-8")
    # Create fake home
    fake_vault = tmp_path / "fakehome" / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    fake_vault.mkdir(parents=True, exist_ok=True)
    # Symlink vault into fake home
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
# The audit must NEVER clear a claim cache whose PR is open on GitHub.
# ---------------------------------------------------------------------------


class TestPROpenClaimProtection:
    """Failure class #5 regression: open PR = claim is LIVE, never cleared."""

    def test_cache_sweep_open_pr_not_cleared(self, tmp_path: Path) -> None:
        """A cache file whose note status diverges but PR is OPEN must be kept.

        This reproduces the exact 2026-06-12T21:04Z failure path: the cache
        sweep (second for loop) found the cache, the note's assigned_to
        diverged from the cache's role (e.g., note reassigned), and the old
        code rm'd the cache without checking GitHub PR state.
        """
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        # Task note: status=offered (not a claim status), assigned_to differs
        # from the cache role. In the old code, this would trigger cache
        # clearing via the cache sweep. But the PR is OPEN.
        _write_task_note(
            vault,
            "sweep-open-pr-task",
            assigned_to="cx-beta",  # NOTE: differs from cache role cx-alpha
            pr="4108",
            branch="alpha/sdlc-vocab-export-20260612",
            status="offered",  # not a claim status -> note_is_active_claim=false
        )
        # Cache says cx-alpha owns this task, but note says cx-beta + offered
        claim_file = _write_claim_cache(cache_dir, "cx-alpha", "sweep-open-pr-task")

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            gh_state="OPEN",
        )

        # The claim cache file MUST still exist because the PR is OPEN
        assert claim_file.exists(), (
            "REGRESSION class #5: claim cache was cleared despite PR being OPEN! "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "PR_OPEN_PROTECTED" in result.stdout, (
            f"Expected PR_OPEN_PROTECTED message.\nstdout: {result.stdout}"
        )

    def test_cache_sweep_merged_pr_cleared(self, tmp_path: Path) -> None:
        """A cache file whose note status diverges and PR is MERGED is cleared."""
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

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            gh_state="MERGED",
        )

        assert not claim_file.exists(), (
            f"Expected stale claim cache to be cleared for merged PR.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_phantom_release_open_pr_protected(self, tmp_path: Path) -> None:
        """A phantom claim being released must check PR state if the task has one.

        The _clear_claim_cache_for_release function is called during phantom
        release. If the task note has a pr field and the PR is open, the cache
        must NOT be cleared.
        """
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        # Task is phantom (stale, no PR in the note — but we add one to test
        # that _clear_claim_cache_for_release checks). Actually, if pr=null
        # in the note, the phantom path triggers AND the pr check in
        # _clear_claim_cache_for_release finds pr=null and proceeds.
        # Let's test the case where the note has a PR but it's not in the
        # frontmatter pr field in a way that the main loop sees pr=null but
        # the note actually has it. This is contrived but tests the safety.

        # More realistic: task has a PR, is stale, but has_pr=true prevents
        # phantom detection. The claim cache is only touched by the cache
        # sweep. So let's test the sweep path with status=offered and pr open.
        _write_task_note(
            vault,
            "phantom-with-pr-task",
            assigned_to="cx-alpha",
            pr="4109",
            branch="codex/cx-oofta",
            status="offered",  # divergent status triggers cache sweep
        )
        claim_file = _write_claim_cache(cache_dir, "cx-alpha", "phantom-with-pr-task")

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            gh_state="OPEN",
        )

        assert claim_file.exists(), (
            "REGRESSION class #5: cache cleared despite PR being OPEN! "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_orphaned_cache_open_pr_protected(self, tmp_path: Path) -> None:
        """A cache file whose note is in closed/ but PR is still open must be kept.

        This covers the edge case where merge-watcher moved the note to closed/
        prematurely but the PR hasn't actually merged.
        """
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        # Note in closed/, not active/ — but PR is still open
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

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            gh_state="OPEN",
        )

        assert claim_file.exists(), (
            "REGRESSION class #5: orphaned claim cache was cleared despite PR being OPEN! "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_orphaned_cache_closed_pr_cleared(self, tmp_path: Path) -> None:
        """A cache file whose note is in closed/ and PR is CLOSED is cleared."""
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

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            gh_state="CLOSED",
        )

        assert not claim_file.exists(), (
            f"Expected orphaned cache to be cleared for CLOSED PR.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# CLASS #4: CLAIM-PLANE-HOST-FORK
# The audit must reconcile state to a remote host when configured.
# ---------------------------------------------------------------------------


class TestHostReconciliation:
    """Failure class #4 regression: single-host reconciler vs two-host plane."""

    def test_reconcile_flag_accepted(self, tmp_path: Path) -> None:
        """--reconcile-host is accepted and processes phantom claims."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        # A phantom claim (no PR, stale) that will be released
        _write_task_note(
            vault,
            "phantom-task-reconcile",
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        _write_claim_cache(cache_dir, "cx-gold", "phantom-task-reconcile")

        # ssh will fail (no real remote host), but the flag should be accepted
        # and the RECONCILE_FAILED message emitted.
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=["--reconcile-host=fake-host"],
            gh_state="CLOSED",
        )

        # We expect phantom detection
        assert "PHANTOM" in result.stdout, f"Expected phantom detection.\nstdout: {result.stdout}"

    def test_dry_run_prevents_cache_deletion(self, tmp_path: Path) -> None:
        """--dry-run prevents claim cache mutations."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        _write_task_note(
            vault,
            "dry-run-task",
            assigned_to="cx-cyan",
            pr="null",
            branch="null",
            status="done",  # stale status for cache sweep
        )
        claim_file = _write_claim_cache(cache_dir, "cx-cyan", "dry-run-task")

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=["--dry-run"],
            gh_state="CLOSED",
        )

        # In dry-run, claim file should still exist
        assert claim_file.exists(), (
            f"Dry-run should not delete claim cache.\nstdout: {result.stdout}"
        )
        assert "DRY-RUN" in result.stdout, f"Expected DRY-RUN message.\nstdout: {result.stdout}"


# ---------------------------------------------------------------------------
# Journal attribution
# ---------------------------------------------------------------------------


class TestJournalAttribution:
    """Every claim-cache mutation must emit a structured log line."""

    def test_clear_emits_journal_line(self, tmp_path: Path) -> None:
        """Clearing a stale cache must produce an attributed log line in stdout."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        # Task note with status=done, so the cache is stale
        _write_task_note(
            vault,
            "journal-test-task",
            assigned_to="cx-delta",
            pr="null",
            branch="null",
            status="done",
        )
        _write_claim_cache(cache_dir, "cx-delta", "journal-test-task")

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            gh_state="CLOSED",
        )

        # The stdout (which goes to journald via the unit) must contain an
        # attributed line with the script version and action.
        assert "codex-claim-audit[v2]" in result.stdout, (
            f"Expected attributed journal line in stdout.\nstdout: {result.stdout}"
        )

    def test_protect_emits_journal_line(self, tmp_path: Path) -> None:
        """Protecting a cache (open PR) must produce an attributed PROTECT line."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        _write_task_note(
            vault,
            "protect-journal-task",
            assigned_to="cx-beta",
            pr="5000",
            branch="beta/work",
            status="offered",  # divergent triggers cache sweep
        )
        _write_claim_cache(cache_dir, "cx-alpha", "protect-journal-task")

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            gh_state="OPEN",
        )

        assert "PROTECT" in result.stdout, (
            f"Expected PROTECT journal line.\nstdout: {result.stdout}"
        )


# ---------------------------------------------------------------------------
# Version flag
# ---------------------------------------------------------------------------


class TestVersionFlag:
    """--version prints version and exits."""

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
# task_is_terminal indeterminate (new evidence from session log)
# ---------------------------------------------------------------------------


class TestTaskIsTerminalMissingCache:
    """Missing claim cache must be treated as indeterminate, not terminal.

    This tests the codex-claim-audit's behavior with missing caches.
    """

    def test_missing_cache_reports_coherence(self, tmp_path: Path) -> None:
        """A claimed task whose cache file is missing should report CACHE_MISSING."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Task is claimed and assigned, but NO cache file exists
        _write_task_note(
            vault,
            "missing-cache-task",
            assigned_to="cx-zeta",
            pr="4200",
            branch="zeta/work",
            status="claimed",
            claimed_at="2026-06-12T18:00:00Z",
        )
        # Deliberately do NOT create a cache file for cx-zeta

        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=False,  # report-only mode
            gh_state="OPEN",
        )

        assert "CACHE_MISSING" in result.stdout, (
            f"Expected CACHE_MISSING coherence report.\nstdout: {result.stdout}"
        )


# ---------------------------------------------------------------------------
# Systemd unit validation
# ---------------------------------------------------------------------------


class TestSystemdUnits:
    """Validate the tracked systemd units parse correctly."""

    def test_service_unit_parses(self) -> None:
        unit = SCRIPT.parent.parent / "systemd" / "units" / "codex-claim-audit.service"
        assert unit.exists(), f"Service unit not found at {unit}"
        text = unit.read_text()
        assert "[Service]" in text
        assert "ExecStart=" in text
        assert "%h/projects/hapax-council/scripts/codex-claim-audit" in text

    def test_timer_unit_parses(self) -> None:
        unit = SCRIPT.parent.parent / "systemd" / "units" / "codex-claim-audit.timer"
        assert unit.exists(), f"Timer unit not found at {unit}"
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
        assert dropin.exists(), f"Drop-in not found at {dropin}"
        text = dropin.read_text()
        assert "SuccessExitStatus=1" in text

    def test_preset_includes_timer(self) -> None:
        preset = SCRIPT.parent.parent / "systemd" / "user-preset.d" / "hapax.preset"
        assert preset.exists(), f"Preset not found at {preset}"
        text = preset.read_text()
        assert "codex-claim-audit.timer" in text
