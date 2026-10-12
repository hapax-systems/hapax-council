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

import json
import os
import re
import shutil
import socket
import subprocess
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "codex-claim-audit"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_vault(tmp_path: Path) -> Path:
    """Create a minimal vault structure."""
    vault = tmp_path / "fakehome/Documents/Personal/20-projects/hapax-cc-tasks"
    (vault / "active").mkdir(parents=True)
    (vault / "closed").mkdir()
    return vault


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
    pr_repo: str = "null",
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
        pr_repo: {pr_repo}
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
        if [[ "$1" == "api" ]]; then
            if printf '%s\\n' "$@" | grep -q 'repos/.*/pulls/[0-9]'; then
                echo '{state}'
                exit 0
            fi
            if printf '%s\\n' "$@" | grep -q 'repos/.*/pulls$'; then
                head=""
                while [[ $# -gt 0 ]]; do
                    if [[ "$1" == "-f" && "$2" == head=* ]]; then head="${{2#head=}}"; shift; fi
                    shift
                done
                head_branch="${{head#*:}}"
                if [[ -n "{branch_match}" && "$head_branch" == "{branch_match}" ]]; then
                    echo '{open_pr_number}'
                fi
                exit 0
            fi
            exit 1
        fi
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
        if src.resolve() == dst.resolve():
            continue
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


@pytest.mark.parametrize(
    "fault", ["live", "missing", "pending", "host", "boot", "pid_reuse", "session"]
)
def test_active_holder_past_six_hours_keeps_exact_claim_publication(
    tmp_path: Path, fault: str
) -> None:
    """Age selects inspection; a live, committed holder is not a phantom."""
    from shared.gate0b_claim_publication_install import default_claim_publication_roots
    from shared.worktree_registry import _slug
    from tests.scripts.test_cc_claim import _SESSION_ID, _claim, _write_task

    home = tmp_path / "fakehome"
    task_id = "continuing-charter"
    note = _write_task(home, "active", task_id)
    note.write_text(note.read_text().replace("type: cc-task", "type: cc-task\nclaim_form: charter"))
    registry = home / ".cache/hapax/worktree-registry"
    registry.mkdir(parents=True)
    worktree = str(SCRIPT.parents[1])
    # The fixture's actual root stays alive through the audit. The independent
    # observer must not substitute its own PID or synthesize a holder renewal.
    stat_fields = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()
    now = datetime.now(UTC)
    record = {
        "path": worktree,
        "role": "cx-test",
        "session_id": _SESSION_ID,
        "task_id": task_id,
        "created_at": now.isoformat(),
        "last_heartbeat": now.isoformat(),
        "executor": {
            "state": "committed",
            "attempt_id": "test-live-executor",
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "start_ticks": int(stat_fields[19]),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        },
    }
    (registry / f"{_slug(worktree)}.json").write_text(json.dumps(record))
    claimed = _claim(home, task_id, extra_env={"HAPAX_WORKTREE_REGISTRY_DIR": str(registry)})
    assert claimed.returncode == 0, claimed.stderr
    rp = registry / f"{_slug(worktree)}.json"
    if fault == "missing":
        rp.unlink()
    elif fault != "live":
        if fault == "pending":
            record["executor"]["state"] = "pending"
        elif fault == "host":
            record["executor"]["host"] = "unavailable-peer"
        elif fault == "boot":
            record["executor"]["boot_id"] = "old-boot"
        elif fault == "pid_reuse":
            record["executor"]["start_ticks"] += 1
        elif fault == "session":
            record["session_id"] = "different-session"
        rp.write_text(json.dumps(record))
    cache = home / ".cache/hapax"
    roots = default_claim_publication_roots(home=home)
    protected = [note, *cache.glob("cc-*"), *Path(roots.claim_transaction_root).rglob("*")]
    before = {p: p.read_bytes() for p in protected if p.is_file()}
    # Advance the audit's selection clock without changing any published bytes.
    gh = _gh_stub(tmp_path)
    date = gh.parent / "date"
    date.write_text(
        '#!/usr/bin/env bash\nif [ "$*" = "+%s" ]; then\n'
        f"  echo {int(now.timestamp()) + 7 * 3600}\n"
        'else\n  exec /usr/bin/date "$@"\nfi\n'
    )
    date.chmod(0o755)
    result = _run_audit(
        tmp_path,
        note.parent.parent,
        cache,
        gh_stub_path=gh,
        extra_env={"HAPAX_WORKTREE_REGISTRY_DIR": str(registry)},
    )
    assert all(p.is_file() and p.read_bytes() == data for p, data in before.items()), (
        "A live holder's note, markers, epochs and publication must stay byte-identical.\n"
        + result.stdout
        + result.stderr
    )
    assert ("HOLDER_PRESENT" if fault == "live" else "HOLDER_UNKNOWN") in result.stdout


# ---------------------------------------------------------------------------
# CLASS #5: STATE-ERASING-AUDIT-ON-LIVE-LANES
# ---------------------------------------------------------------------------


class TestPROpenClaimProtection:
    """Failure class #5 regression: open PR = claim is LIVE, never cleared."""

    def test_rest_pull_state_jq_maps_raw_payloads(self) -> None:
        """The inline REST /pulls/{n} jq expression preserves open/closed precedence."""
        assert shutil.which("jq"), "jq is required to verify the gh --jq expression"
        script = SCRIPT.read_text(encoding="utf-8")
        match = re.search(r"--jq '([^']*merged_at[^']*)'", script)
        assert match is not None
        expression = match.group(1)

        cases = [
            ({"state": "closed", "merged": True, "merged_at": "2026-07-05T00:00:00Z"}, "MERGED"),
            ({"state": "closed", "merged": False, "merged_at": None}, "CLOSED"),
            ({"state": "open", "draft": True, "merged": False, "merged_at": None}, "DRAFT"),
            ({"state": "open", "draft": False, "merged": False, "merged_at": None}, "OPEN"),
        ]

        for payload, expected in cases:
            result = subprocess.run(
                ["jq", "-r", expression],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                check=True,
            )
            assert result.stdout.strip() == expected

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

    def test_cache_sweep_merged_pr_without_holder_proof_is_retained(self, tmp_path: Path) -> None:
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
        assert claim_file.exists()

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

    def test_orphaned_cache_closed_pr_without_holder_proof_is_retained(
        self, tmp_path: Path
    ) -> None:
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
        assert claim_file.exists()


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
        repo = _pushed_repo(tmp_path, "cx-red/merged-branch")
        _canonical_absent_claim(tmp_path, vault, cache_dir, "cx-red", task_id, repo)
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

    def test_matching_legacy_peer_task_without_holder_proof_preserves_both(
        self, tmp_path: Path
    ) -> None:
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
        _write_claim_cache(cache_dir, "cx-gold", task_id)
        _stub, remote_state, calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=task_id)

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "HOLDER_UNKNOWN" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

    def test_unknown_holder_never_starts_the_repointing_peer_command(self, tmp_path: Path) -> None:
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

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "HOLDER_UNKNOWN" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

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
        _write_claim_cache(cache_dir, "cx-gold", "phantom-mismatch-task")
        _stub, remote_state, _calls = _ssh_stub(
            tmp_path, assigned="cx-gold", remote_task="other-live-task"
        )
        note.read_text(encoding="utf-8")

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "HOLDER_UNKNOWN" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

    def test_absent_peer_marker_does_not_supply_holder_proof(self, tmp_path: Path) -> None:
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
        _write_claim_cache(cache_dir, "cx-gold", task_id)
        _stub, remote_state, _calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=None)

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "HOLDER_UNKNOWN" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

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
        _write_claim_cache(cache_dir, "cx-gold", "phantom-ssh-fails")
        _stub, remote_state, _calls = _ssh_stub(
            tmp_path, assigned="cx-gold", remote_task="phantom-ssh-fails", read_fails=True
        )
        note.read_text(encoding="utf-8")

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "HOLDER_UNKNOWN" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

    def test_missing_local_proof_does_not_release_peer_or_note(self, tmp_path: Path) -> None:
        """A vanished local cache must still reconcile appendix before note release."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)

        task_id = "phantom-local-missing"
        _write_task_note(
            vault,
            task_id,
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        _stub, remote_state, _calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=task_id)

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "HOLDER_UNKNOWN" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

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
        _write_task_note(
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

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_stub_path=gh,
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "branch_open_pr" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

    def test_missing_local_cache_gh_indeterminate_retains_remote(self, tmp_path: Path) -> None:
        """Missing local cache + gh down on the branch probe = fail-safe retain."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)

        task_id = "phantom-missing-gh-down"
        _write_task_note(
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

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_stub_path=gh,
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "branch_pr_indeterminate" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

    def test_legacy_cache_sweep_holds_before_peer_mutation(self, tmp_path: Path) -> None:
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
        _write_claim_cache(cache_dir, "cx-alpha", "sweep-reconcile-task")
        _stub, remote_state, _calls = _ssh_stub(
            tmp_path, assigned="cx-alpha", remote_task="sweep-reconcile-task"
        )

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=_reconcile_args(remote_state),
            gh_state="CLOSED",
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "HOLDER_UNKNOWN" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

    def test_legacy_holder_stays_unknown_with_self_reconcile_target(self, tmp_path: Path) -> None:
        """A self-target with no derivable peer (single-host plane) never sshes.

        The "never ssh to self" invariant is now structural: peer resolution
        excludes self, so when the plane has no other host the reconcile target
        resolves to empty and the path is cleanly skipped. The local clear path
        still owns the local cache and proceeds.
        """
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "phantom-self-reconcile"
        _write_task_note(
            vault,
            task_id,
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        _write_claim_cache(cache_dir, "cx-gold", task_id)
        # ssh stub is on PATH; if the self-guard fails, it WOULD be invoked.
        _stub, _remote_state, calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=task_id)

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=["--reconcile-host=solo-host", f"--reconcile-cache-dir={cache_dir}"],
            extra_env={
                "HAPAX_AUDIT_SELF_HOST": "solo-host",
                "HAPAX_CLAIM_PLANE_HOSTS": "solo-host",  # single-host plane: no peer
            },
            gh_state="CLOSED",
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "HOLDER_UNKNOWN" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

    def test_declared_appendix_peer_does_not_substitute_for_holder_proof(
        self, tmp_path: Path
    ) -> None:
        """A self-pointing reconcile target must derive the PEER, not skip.

        Cross-family review consensus (gemini-1 + codex-1 + claude-1): the unit's
        single hardcoded target means that when the audit runs ON that host
        (the preset enables it on both), the reconcile no-ops to self and the
        peer replica is left stale — a single-host reconciler against a two-host
        plane. The fix derives the peer from the claim-plane topology, so an
        appendix-side audit reconciles to podium.
        """
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "phantom-peer-appendix"
        _write_task_note(
            vault,
            task_id,
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        _write_claim_cache(cache_dir, "cx-gold", task_id)
        _stub, remote_state, _calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=task_id)

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=[
                "--reconcile-host=hapax-appendix",  # the hardcoded unit value, self here
                f"--reconcile-cache-dir={remote_state.parent}",
            ],
            extra_env={
                "HAPAX_AUDIT_SELF_HOST": "hapax-appendix",
                "HAPAX_CLAIM_PLANE_HOSTS": "hapax-podium hapax-appendix",
            },
            gh_state="CLOSED",
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "HOLDER_UNKNOWN" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

    def test_declared_podium_peer_does_not_substitute_for_holder_proof(
        self, tmp_path: Path
    ) -> None:
        """With no explicit target, a podium audit derives the appendix peer."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "phantom-peer-podium"
        _write_task_note(
            vault,
            task_id,
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        _write_claim_cache(cache_dir, "cx-gold", task_id)
        _stub, remote_state, _calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=task_id)

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=[f"--reconcile-cache-dir={remote_state.parent}"],  # no --reconcile-host
            extra_env={
                "HAPAX_AUDIT_SELF_HOST": "hapax-podium",
                "HAPAX_CLAIM_PLANE_HOSTS": "hapax-podium hapax-appendix",
            },
            gh_state="CLOSED",
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "HOLDER_UNKNOWN" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

    def test_explicit_peer_does_not_substitute_for_holder_proof(self, tmp_path: Path) -> None:
        """An explicit non-self reconcile target wins over peer derivation."""
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"

        task_id = "phantom-explicit-host"
        _write_task_note(
            vault,
            task_id,
            assigned_to="cx-gold",
            pr="null",
            branch="null",
            status="claimed",
            claimed_at="2026-06-10T01:00:00Z",
        )
        _write_claim_cache(cache_dir, "cx-gold", task_id)
        _stub, remote_state, _calls = _ssh_stub(tmp_path, assigned="cx-gold", remote_task=task_id)

        before = {
            p: p.read_bytes()
            for root in (vault, cache_dir, tmp_path / "remote-cache")
            if root.exists()
            for p in root.rglob("*")
            if p.is_file()
        }
        result = _run_audit(
            tmp_path,
            vault,
            cache_dir,
            release=True,
            extra_args=[
                "--reconcile-host=fake-host",
                f"--reconcile-cache-dir={remote_state.parent}",
            ],
            extra_env={
                "HAPAX_AUDIT_SELF_HOST": "hapax-podium",
                "HAPAX_CLAIM_PLANE_HOSTS": "hapax-podium hapax-appendix",
            },
            gh_state="CLOSED",
        )

        assert result.returncode == 10, result.stdout + result.stderr
        assert "HOLDER_UNKNOWN" in result.stdout
        assert all(p.is_file() and p.read_bytes() == data for p, data in before.items())
        assert "RECONCILED" not in result.stdout

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
        assert "HOLDER_UNKNOWN" in result.stdout


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

    def test_session_keyed_legacy_lease_without_holder_proof_is_retained(
        self, tmp_path: Path
    ) -> None:
        """A terminal note does not prove absence for a legacy session-keyed lease.

        Missing holder evidence remains UNKNOWN and preserves the legacy cache.
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

        assert session_keyed.exists(), "age and terminal note do not prove executor absence"
        assert "HOLDER_UNKNOWN" in result.stdout


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
            branch="feat/journal",
            status="claimed",
        )
        _write_claim_cache(cache_dir, "cx-delta", "journal-test-task")

        repo = _pushed_repo(tmp_path, "feat/journal")
        _canonical_absent_claim(tmp_path, vault, cache_dir, "cx-delta", "journal-test-task", repo)
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
# NO-STALL U1: a claim whose holder's route is blocked beyond tolerance
# ---------------------------------------------------------------------------

SESSION = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_dispatch_binding(
    cache_dir: Path,
    role: str,
    task_id: str,
    *,
    platform: str = "codex",
    session: str | None = None,
    manual: bool = True,
) -> Path:
    """cc-claim's binding; manual by default, as on the estate, where it always says codex."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = role if session is None else f"{role}-{session}"
    binding = cache_dir / f"cc-claim-dispatch-{key}.json"
    binding.write_text(
        json.dumps(
            {
                "schema": "hapax.claim-dispatch-binding.v1",
                "lane": role,
                "task_id": task_id,
                "platform": platform,
                "session_id": session or SESSION,
                "dispatch_message_id": (
                    "manual-cc-claim:0123456789abcdef0123456789abcdef"
                    if manual
                    else "01a1beef-0000-7000-8000-000000000001"
                ),
            }
        ),
        encoding="utf-8",
    )
    return binding


def _write_relay(tmp_path: Path, role: str, platform: str) -> Path:
    relay = tmp_path / "relay" / f"{role}.yaml"
    relay.parent.mkdir(parents=True, exist_ok=True)
    relay.write_text(f"session: {role}\nplatform: {platform}\n", encoding="utf-8")
    return relay


def _write_family_outage(
    tmp_path: Path,
    family: str = "codex",
    *,
    resets_in: timedelta | None = timedelta(days=4),
    observed_ago: timedelta = timedelta(minutes=5),
) -> Path:
    now = datetime.now(UTC)
    entry: dict[str, object] = {
        "observed_at": _iso(now - observed_ago),
        "outage_started_at": _iso(now - timedelta(days=1)),
        "cause": "quota_wall",
    }
    if resets_in is not None:
        entry["wall_evidence"] = {"resets_at": _iso(now + resets_in), "label": "observed"}
    record = tmp_path / "family-outage.json"
    record.write_text(json.dumps({family: entry}), encoding="utf-8")
    return record


def _run_blocked_audit(
    tmp_path: Path,
    vault: Path,
    cache_dir: Path,
    record: Path,
    *,
    release_flag: bool = True,
    repo: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        "HAPAX_FAMILY_OUTAGE_RECORD": str(record),
        "HAPAX_RELAY_STATE_DIR": str(tmp_path / "relay"),
        # Never the real checkout: a test that reaches the branch reads must name its own repo.
        "HAPAX_CLAIM_AUDIT_REPO": str(repo or tmp_path / "no-repo"),
    }
    return _run_audit(
        tmp_path,
        vault,
        cache_dir,
        extra_args=["--release-capability-blocked"] if release_flag else None,
        extra_env=env,
    )


def _pushed_repo(tmp_path: Path, branch: str) -> Path:
    """A repo whose branch exists only on its (local, bare) remote."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(tmp_path, "init", "-q", "--bare", str(tmp_path / "remote.git"))
    _git(repo, "remote", "add", "origin", str(tmp_path / "remote.git"))
    _git(repo, "push", "-q", "origin", f"main:refs/heads/{branch}", "main")
    return repo


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "-c",
            "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


class TestCapabilityBlockedHolders:
    """NO-STALL U1n (REQ-20261011T0451): a blocked holder's claim moves on, with nothing lost."""

    def test_blocked_beyond_tolerance_releases_and_carries_the_open_pr(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        # A lane name that looks like no family: the family comes from the relay record.
        note = _write_task_note(
            vault, "walled-task", assigned_to="lane-a", pr="89", branch="feat/walled"
        )
        base = _write_claim_cache(cache_dir, "lane-a", "walled-task")
        keyed = _write_claim_cache(cache_dir, f"lane-a-{SESSION}", "walled-task")
        _write_dispatch_binding(cache_dir, "lane-a", "walled-task")
        _write_relay(tmp_path, "lane-a", "codex")
        record = _write_family_outage(tmp_path)
        # A note without the heading gets one, so the release still leaves its lineage line.
        note.write_text(note.read_text(encoding="utf-8").replace("## Session log\n", ""), "utf-8")
        repo = _pushed_repo(tmp_path, "feat/walled")  # pushed, with no local ref

        _canonical_absent_claim(tmp_path, vault, cache_dir, "lane-a", "walled-task", repo)
        result = _run_blocked_audit(tmp_path, vault, cache_dir, record, repo=repo)  # gh: PR OPEN

        assert "CAPABILITY_BLOCKED: walled-task assigned=lane-a" in result.stdout
        assert "family=codex cause=quota_wall" in result.stdout
        text = note.read_text(encoding="utf-8")
        for line in ("status: offered", "assigned_to: unassigned", "pr: 89", "branch: feat/walled"):
            assert f"\n{line}\n" in text
        assert "## Session log\n- " in text
        assert "codex-claim-audit observed the exact executor absent" in text
        assert "audit_absent" in text
        # Both markers are gone, so no leftover marker refuses the next holder's claim.
        assert not base.exists()
        assert not keyed.exists()

    def test_a_short_wall_or_a_stale_witness_is_no_evidence(self, tmp_path: Path) -> None:
        # A wall ending in 2 h is inside the 6 h tolerance; a 3 h old witness is past the 2 h TTL.
        for case, kwargs in (
            ("short", {"resets_in": timedelta(hours=2)}),
            ("stale", {"observed_ago": timedelta(hours=3)}),
        ):
            base = tmp_path / case
            vault, cache_dir = _make_vault(base), base / "cache"
            note = _write_task_note(vault, "walled-task", assigned_to="lane-a")
            marker = _write_claim_cache(cache_dir, "lane-a", "walled-task")
            _write_relay(base, "lane-a", "codex")
            original = note.read_text(encoding="utf-8")

            record = _write_family_outage(base, **kwargs)  # type: ignore[arg-type]
            result = _run_blocked_audit(base, vault, cache_dir, record)

            assert "CAPABILITY_BLOCKED" not in result.stdout, case
            assert note.read_text(encoding="utf-8") == original and marker.exists(), case

    def test_absent_or_conflicting_family_evidence_holds(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        # With an open PR, so the name-based phantom path (cx-*, no PR) cannot release it either.
        named = _write_task_note(
            vault, "named-only-task", assigned_to="cx-walled", pr="77", branch="feat/named"
        )
        # None is evidence: the name, the manual binding (always codex), a dispatched binding
        # for another task, and one for a role whose name only starts with the holder's.
        _write_dispatch_binding(cache_dir, "cx-walled", "named-only-task", manual=True)
        _write_dispatch_binding(
            cache_dir, "cx-walled", "some-other-task", manual=False, session=SESSION
        )
        _write_dispatch_binding(cache_dir, "cx-walled-twin", "named-only-task", manual=False)
        # A dispatched binding says the walled family; the lane's relay says another.
        conflict = _write_task_note(vault, "conflict-task", assigned_to="lane-c")
        _write_dispatch_binding(cache_dir, "lane-c", "conflict-task", manual=False)
        _write_relay(tmp_path, "lane-c", "claude")
        markers = [
            _write_claim_cache(cache_dir, "cx-walled", "named-only-task"),
            _write_claim_cache(cache_dir, "lane-c", "conflict-task"),
        ]
        originals = [named.read_text(encoding="utf-8"), conflict.read_text(encoding="utf-8")]

        result = _run_blocked_audit(tmp_path, vault, cache_dir, _write_family_outage(tmp_path))

        assert "CAPABILITY_BLOCKED" not in result.stdout
        assert [
            named.read_text(encoding="utf-8"),
            conflict.read_text(encoding="utf-8"),
        ] == originals
        assert all(m.exists() for m in markers)

    def test_dispatched_binding_is_evidence_and_an_unknown_end_holds(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        note = _write_task_note(vault, "no-end-task", assigned_to="lane-b", branch="feat/no-end")
        _write_claim_cache(cache_dir, "lane-b", "no-end-task")
        # Evidence from a dispatched (not manual) session-keyed binding.
        _write_dispatch_binding(cache_dir, "lane-b", "no-end-task", session=SESSION, manual=False)
        original = note.read_text(encoding="utf-8")

        result = _run_blocked_audit(
            tmp_path, vault, cache_dir, _write_family_outage(tmp_path, resets_in=None)
        )
        assert "HELD: blocker_end_unknown" in result.stdout
        assert note.read_text(encoding="utf-8") == original

        repo = _pushed_repo(tmp_path, "feat/no-end")
        _canonical_absent_claim(tmp_path, vault, cache_dir, "lane-b", "no-end-task", repo)
        result = _run_blocked_audit(
            tmp_path, vault, cache_dir, _write_family_outage(tmp_path), repo=repo
        )
        assert "-> RELEASED" in result.stdout
        assert "\nassigned_to: unassigned\n" in note.read_text(encoding="utf-8")

    def test_live_executor_holds_the_release(self, tmp_path: Path) -> None:
        live = "1a2b3c4d-5e6f-4a0b-9c8d-7e6f5a4b3c2d"
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        note = _write_task_note(vault, "live-task", assigned_to="lane-d", branch="feat/live")
        _write_claim_cache(cache_dir, "lane-d", "live-task")
        _write_dispatch_binding(cache_dir, "lane-d", "live-task", session=live)
        _write_relay(tmp_path, "lane-d", "codex")
        original = note.read_text(encoding="utf-8")
        # A resumed session carries its session id in its arguments (`codex resume <id>`).
        repo = _pushed_repo(tmp_path, "feat/live")
        proc = subprocess.Popen(["bash", "-c", "sleep 60; :", live])
        try:
            record = _write_family_outage(tmp_path)
            result = _run_blocked_audit(tmp_path, vault, cache_dir, record, repo=repo)
        finally:
            proc.kill()
            proc.wait()

        assert f"HELD: live_executor_pid_{proc.pid}" in result.stdout
        assert note.read_text(encoding="utf-8") == original

    def test_local_work_holds_until_the_branch_is_pushed_and_clean(self, tmp_path: Path) -> None:
        for state, reason in (
            ("ahead", "unpushed_commits"),
            ("dirty", "uncommitted_paths"),
            ("unpublished", "branch_absent_from_remote"),
            ("clean", None),
        ):
            self._assert_local_work_holds(tmp_path / state, state, reason)

    def test_a_failed_read_holds(self, tmp_path: Path) -> None:
        for reason in ("worktrees_unreadable", "remote_unreadable", "worktree_status_unreadable"):
            base = tmp_path / reason
            vault, cache_dir = _make_vault(base), base / "cache"
            _write_task_note(vault, "read-task", assigned_to="lane-r", branch="feat/item")
            _write_claim_cache(cache_dir, "lane-r", "read-task")
            _write_relay(base, "lane-r", "codex")
            repo = None  # no repository at all: the worktree list cannot be read
            if reason != "worktrees_unreadable":
                repo = base / "repo"  # a repository with no origin: the remote cannot be read
                repo.mkdir(parents=True)
                _git(repo, "init", "-q", "-b", "main")
                _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
            if reason == "worktree_status_unreadable":  # the branch's worktree is gone from disk
                _git(repo, "worktree", "add", "-q", "-b", "feat/item", str(base / "tree"))
                shutil.rmtree(base / "tree")

            record = _write_family_outage(base)
            result = _run_blocked_audit(base, vault, cache_dir, record, repo=repo)

            assert f"HELD: {reason}; next action: repair the failed read" in result.stdout, reason

    def test_a_branch_this_audit_cannot_verify_is_held(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        notes = [
            _write_task_note(vault, "branchless-task", assigned_to="lane-g"),
            _write_task_note(
                vault, "spine-task", assigned_to="lane-e", branch="feat/x", pr_repo="o/spine"
            ),
            _write_task_note(vault, "nowhere-task", assigned_to="lane-h", branch="feat/nowhere"),
        ]
        originals = [n.read_text(encoding="utf-8") for n in notes]
        for lane, note in zip(("lane-g", "lane-e", "lane-h"), notes, strict=True):
            _write_claim_cache(cache_dir, lane, note.stem)
            _write_relay(tmp_path, lane, "codex")
        repo = _pushed_repo(tmp_path, "feat/other")  # feat/nowhere is on no remote and not local

        result = _run_blocked_audit(
            tmp_path, vault, cache_dir, _write_family_outage(tmp_path), repo=repo
        )

        for reason in (
            "no_branch_to_verify",
            "cross_repository_branch",
            "branch_absent_from_remote",
        ):
            assert f"HELD: {reason}; next action: " in result.stdout
        assert [n.read_text(encoding="utf-8") for n in notes] == originals

    @staticmethod
    def _assert_local_work_holds(tmp_path: Path, state: str, reason: str | None) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
        tree = tmp_path / "item-tree"
        _git(repo, "worktree", "add", "-q", "-b", "feat/item", str(tree))
        _git(tree, "commit", "-q", "--allow-empty", "-m", "work")
        _git(tmp_path, "init", "-q", "--bare", str(tmp_path / "remote.git"))
        _git(repo, "remote", "add", "origin", str(tmp_path / "remote.git"))
        _git(
            repo,
            "push",
            "-q",
            "origin",
            "main",
            *(() if state == "unpublished" else ("feat/item",)),
        )
        if state == "ahead":
            _git(tree, "commit", "-q", "--allow-empty", "-m", "not pushed")
        if state == "dirty":
            (tree / "unsaved.txt").write_text("unsaved\n", encoding="utf-8")
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        note = _write_task_note(vault, "item-task", assigned_to="lane-f", branch="feat/item")
        _write_claim_cache(cache_dir, "lane-f", "item-task")
        _write_relay(tmp_path, "lane-f", "codex")
        original = note.read_text(encoding="utf-8")

        if reason is None:
            _canonical_absent_claim(tmp_path, vault, cache_dir, "lane-f", "item-task", tree)
        record = _write_family_outage(tmp_path)
        result = _run_blocked_audit(tmp_path, vault, cache_dir, record, repo=repo)

        if reason is None:
            assert "-> RELEASED" in result.stdout
            assert "\nassigned_to: unassigned\n" in note.read_text(encoding="utf-8")
        else:
            assert f"HELD: {reason}" in result.stdout
            assert note.read_text(encoding="utf-8") == original

    def test_a_claim_this_hosts_cache_does_not_hold_is_never_released(self, tmp_path: Path) -> None:
        # A peer host's lane: this host's /proc and worktrees cannot see it (#5111 review).
        vault = _make_vault(tmp_path)
        note = _write_task_note(vault, "peer-task", assigned_to="lane-p", branch="feat/peer")
        _write_relay(tmp_path, "lane-p", "codex")
        original = note.read_text(encoding="utf-8")
        repo = _pushed_repo(tmp_path, "feat/peer")
        record = _write_family_outage(tmp_path)
        result = _run_blocked_audit(tmp_path, vault, tmp_path / "cache", record, repo=repo)
        assert "CAPABILITY_BLOCKED: peer-task" not in result.stdout
        assert note.read_text(encoding="utf-8") == original

    def test_a_local_binding_without_a_marker_is_judged_here(self, tmp_path: Path) -> None:
        # U1b: the estate's walled claims lost their markers; cc-claim's binding stays on the claiming host.
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        note = _write_task_note(vault, "bound-task", assigned_to="lane-b2", branch="feat/bound")
        _write_dispatch_binding(cache_dir, "lane-b2", "bound-task")  # manual: host evidence only
        _write_relay(tmp_path, "lane-b2", "codex")
        repo = _pushed_repo(tmp_path, "feat/bound")
        result = _run_blocked_audit(
            tmp_path, vault, cache_dir, _write_family_outage(tmp_path), repo=repo
        )
        assert "CAPABILITY_BLOCKED: bound-task assigned=lane-b2" in result.stdout
        assert "\nassigned_to: lane-b2\n" in note.read_text(encoding="utf-8")
        assert "HOLDER_UNKNOWN" in result.stdout

    def test_a_session_keyed_marker_alone_is_judged_here(self, tmp_path: Path) -> None:
        # #5124 review (muse major): the keyed-marker branch, with no base marker and no binding.
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        note = _write_task_note(vault, "keyed-task", assigned_to="lane-k", branch="feat/keyed")
        _write_claim_cache(cache_dir, f"lane-k-{SESSION}", "keyed-task")
        _write_relay(tmp_path, "lane-k", "codex")
        repo = _pushed_repo(tmp_path, "feat/keyed")
        result = _run_blocked_audit(
            tmp_path, vault, cache_dir, _write_family_outage(tmp_path), repo=repo
        )
        assert "CAPABILITY_BLOCKED: keyed-task assigned=lane-k" in result.stdout
        assert "\nassigned_to: lane-k\n" in note.read_text(encoding="utf-8")
        assert "HOLDER_UNKNOWN" in result.stdout

    def test_a_binding_for_another_task_is_no_evidence_of_host(self, tmp_path: Path) -> None:
        # #5124 review (muse major): only a binding naming this task makes the claim local.
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        note = _write_task_note(vault, "other-task", assigned_to="lane-o", branch="feat/other")
        _write_dispatch_binding(cache_dir, "lane-o", "unrelated-task")
        _write_relay(tmp_path, "lane-o", "codex")
        original = note.read_text(encoding="utf-8")
        repo = _pushed_repo(tmp_path, "feat/other")
        result = _run_blocked_audit(
            tmp_path, vault, cache_dir, _write_family_outage(tmp_path), repo=repo
        )
        assert "CAPABILITY_BLOCKED: other-task" not in result.stdout
        assert note.read_text(encoding="utf-8") == original

    def test_without_the_flag_it_is_reported_and_held(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        cache_dir = tmp_path / "cache"
        note = _write_task_note(
            vault, "flagless-task", assigned_to="lane-a", branch="feat/flagless"
        )
        marker = _write_claim_cache(cache_dir, "lane-a", "flagless-task")
        _write_relay(tmp_path, "lane-a", "codex")
        original = note.read_text(encoding="utf-8")
        record = _write_family_outage(tmp_path)

        repo = _pushed_repo(tmp_path, "feat/flagless")
        result = _run_blocked_audit(
            tmp_path, vault, cache_dir, record, release_flag=False, repo=repo
        )

        assert "CAPABILITY_BLOCKED: flagless-task" in result.stdout
        assert "HELD: pass --release-capability-blocked" in result.stdout
        assert note.read_text(encoding="utf-8") == original
        assert marker.exists()
        assert result.returncode == 10


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

    def test_service_releases_capability_blocked_claims(self) -> None:
        """NO-STALL U1 is live only if the scheduled run passes the flag."""
        unit = SCRIPT.parent.parent / "systemd" / "units" / "codex-claim-audit.service"
        exec_lines = [
            line for line in unit.read_text().splitlines() if line.startswith("ExecStart=")
        ]
        assert len(exec_lines) == 1
        assert "--release " in exec_lines[0]
        assert "--release-capability-blocked" in exec_lines[0]

    def test_service_enables_reconciliation(self) -> None:
        unit = SCRIPT.parent.parent / "systemd" / "units" / "codex-claim-audit.service"
        text = unit.read_text()
        # The scheduled unit opts into reconciliation via the activation
        # worktree's registry declaration (HAPAX_COUNCIL_DIR): the audit
        # resolves the claim plane from claim_plane.hosts and derives the peer
        # per-host — no hardcoded single target that would silently no-op to
        # self on the host it names, and no pair pin in the unit itself.
        council_lines = [
            line
            for line in text.splitlines()
            if "HAPAX_COUNCIL_DIR=" in line and not line.strip().startswith("#")
        ]
        assert council_lines, "Host reconciliation must be enabled via HAPAX_COUNCIL_DIR"
        assert "source-activation/worktree" in council_lines[0], (
            "the declared plane context must be the governed activation worktree, "
            "not the mutable dev tree"
        )
        registry = SCRIPT.parent.parent / "config" / "infrastructure" / "host-storage-registry.json"
        reg_text = registry.read_text()
        assert (
            '"claim_plane"' in reg_text
            and '"hapax-podium"' in reg_text
            and ('"hapax-appendix"' in reg_text)
        ), "the shipped registry must declare both plane hosts so each derives the other as peer"

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


def _canonical_absent_claim(tmp_path, vault, cache, role, task_id, worktree):
    """An actual admitted journal and a positively reaped fixture executor."""
    from shared import sdlc_claim
    from shared import worktree_registry as wr
    from shared.gate0b_claim_publication_install import default_claim_publication_roots
    from shared.sdlc_task_store import ClaimDispatchBinding, resolve_task_note
    from tests.shared.test_sdlc_claim import ClaimFixture, _active_admission_fixture

    note = vault / "active" / (task_id + ".md")
    after = note.read_text()
    after = after.replace(
        "type: cc-task",
        "type: cc-task\nkind: build\nauthority_case: CASE-CLAIM-001\nparent_spec: /tmp/holder-spec.md\nclaimable: true",
    )
    before = re.sub(r"^status:.*$", "status: offered", after, count=1, flags=re.M)
    before = re.sub(r"^assigned_to:.*$", "assigned_to: unassigned", before, count=1, flags=re.M)
    before = re.sub(r"^claimed_at:.*$", "claimed_at: null", before, count=1, flags=re.M)
    note.write_text(before)
    # Replace only fixture marker/binding seeds, before the observed test begins.
    cache.mkdir(parents=True, exist_ok=True)
    for p in cache.glob(f"cc-*-{role}*"):
        p.unlink()
    binding = ClaimDispatchBinding.create(
        task_id=task_id,
        lane=role,
        session_id=SESSION,
        claim_epoch=1720700000,
        dispatch_message_id="fixture-dispatch",
        platform="codex",
        mode="headless",
        profile="ultra",
        authority_case="CASE-CLAIM-001",
        binding_hash="a" * 64,
        coord_dispatch_idempotency_key="fixture",
    )
    intent = sdlc_claim.ClaimPublicationIntent.create(
        task=resolve_task_note(vault, task_id),
        cache_dir=cache,
        note_after=after.encode(),
        binding=binding,
    )
    roots = default_claim_publication_roots(home=tmp_path / "fakehome")
    fixture = ClaimFixture(
        intent=intent,
        vault=vault,
        cache=cache,
        transactions=Path(roots.claim_transaction_root),
        locks=Path(roots.claim_lock_root),
    )
    proof_dir = tmp_path / ("admission-" + task_id)
    proof_dir.mkdir()
    admission = _active_admission_fixture(proof_dir, fixture)
    sdlc_claim._apply_admitted_claim_publication_transaction(
        intent,
        admission.consumption,
        transaction_root=fixture.transactions,
        receipt_root=Path(roots.claim_receipt_root),
        lock_root=fixture.locks,
        now=admission.checked_at,
    )
    registry = tmp_path / "fakehome/.cache/hapax/worktree-registry"
    registry.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    with subprocess.Popen(["sleep", "30"]) as child:
        record = wr.WorktreeRecord(
            path=str(worktree),
            role=role,
            session_id=SESSION,
            task_id=task_id,
            created_at=now,
            last_heartbeat=now,
            executor=dict(
                state="committed",
                attempt_id="fixture-admitted-root",
                pid=child.pid,
                start_ticks=wr._process_identity(child.pid)[2],
                host=socket.gethostname(),
                boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            ),
        )
        child.terminate()
        child.wait()
    (registry / (wr._slug(str(worktree)) + ".json")).write_text(wr._record_to_json(record))
    return fixture


@pytest.mark.parametrize(
    "work",
    [
        "clean",
        "dirty",
        "ahead",
        "pr_unknown",
        "peer_unknown",
        "cache_mismatch",
        "dry_run",
        "dry_dirty",
        "other_session_marker",
    ],
)
def test_positive_absence_uses_exact_journal_and_preserves_work_guards(tmp_path, work):
    vault = tmp_path / "fakehome/Documents/Personal/20-projects/hapax-cc-tasks"
    (vault / "active").mkdir(parents=True)
    (vault / "closed").mkdir()
    cache = tmp_path / "cache"
    repo = _pushed_repo(tmp_path, "feat/absent")
    note = _write_task_note(vault, "absent-holder", assigned_to="cx-test", branch="feat/absent")
    fixture = _canonical_absent_claim(tmp_path, vault, cache, "cx-test", "absent-holder", repo)
    if work in {"dirty", "dry_dirty"}:
        (repo / "unsaved").write_text("keep")
    if work == "ahead":
        _git(repo, "fetch", "-q", "origin", "feat/absent:feat/absent")
        _git(repo, "checkout", "-q", "feat/absent")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "not pushed")
    if work == "cache_mismatch":
        (cache / "cc-claim-epoch-cx-test").write_text("99999999 another-task\n")
    if work == "other_session_marker":
        (cache / "cc-active-task-cx-test-ffffffff-ffff-ffff-ffff-ffffffffffff").write_text(
            "absent-holder\n"
        )
    before = {p: p.read_bytes() for p in [note, *cache.glob("cc-*")] if p.is_file()}
    extra = (
        ["--reconcile-host=unavailable-peer"]
        if work == "peer_unknown"
        else (["--dry-run"] if work in {"dry_run", "dry_dirty"} else None)
    )
    gh = _gh_stub_failing(tmp_path) if work == "pr_unknown" else _gh_stub(tmp_path)
    result = _run_audit(tmp_path, vault, cache, gh_stub_path=gh, extra_args=extra)
    if work == "clean":
        assert "RELEASED:" in result.stdout, result.stdout + result.stderr
        assert "status: offered" in note.read_text()
        assert not list(cache.glob("cc-active-task-*"))
        archives = list((vault / "_lineage/absent-holder").glob("*/README.md"))
        assert len(archives) == 1 and "shape: audit_absent" in archives[0].read_text()
        assert list(fixture.transactions.glob("*/manifest.json"))
    else:
        assert all(p.read_bytes() == data for p, data in before.items()), (
            result.stdout + result.stderr
        )
        assert "RELEASED:" not in result.stdout
        reason = {
            "dirty": "uncommitted_paths",
            "ahead": "unpushed_commits",
            "pr_unknown": "branch_pr_indeterminate",
            "peer_unknown": "remote_epoch_reconciliation_unavailable",
            "cache_mismatch": "claim",
            "dry_run": "WOULD_RELEASE:",
            "dry_dirty": "uncommitted_paths",
            "other_session_marker": "other_marker",
        }[work]
        assert reason in result.stdout, result.stdout + result.stderr
        if work != "dry_run":
            assert "[DRY-RUN] WOULD RELEASE" not in result.stdout


def test_audit_rechecks_branch_pr_during_locked_work_inspection(tmp_path):
    vault = _make_vault(tmp_path)
    cache = tmp_path / "cache"
    repo = _pushed_repo(tmp_path, "feat/absent")
    note = _write_task_note(vault, "late-pr-holder", assigned_to="cx-test", branch="feat/absent")
    _canonical_absent_claim(tmp_path, vault, cache, "cx-test", "late-pr-holder", repo)
    gh = _gh_stub(tmp_path)
    calls = tmp_path / "gh-calls"
    gh.write_text(f"""#!/usr/bin/env bash
n=0
[[ ! -f '{calls}' ]] || read -r n < '{calls}'
n=$((n+1))
printf '%s\\n' "$n" > '{calls}'
if (( n > 2 )); then printf '999\\n'; fi
exit 0
""")
    before = {p: p.read_bytes() for p in [note, *cache.glob("cc-*")] if p.is_file()}
    result = _run_audit(tmp_path, vault, cache, gh_stub_path=gh)
    assert all(p.is_file() and p.read_bytes() == data for p, data in before.items()), result.stdout
    assert "branch_pr_changed_or_unknown" in result.stdout
    assert 3 <= int(calls.read_text()) <= 5


@pytest.mark.parametrize("fault", ["TypeError", "PermissionError"])
def test_audit_distinguishes_internal_error_from_unknown_holder(tmp_path, fault):
    vault = _make_vault(tmp_path)
    cache = tmp_path / "cache"
    repo = _pushed_repo(tmp_path, "feat/absent")
    note = _write_task_note(vault, "observer-fault", assigned_to="cx-test", branch="feat/absent")
    _canonical_absent_claim(tmp_path, vault, cache, "cx-test", "observer-fault", repo)
    body = SCRIPT.read_text().split("<<'PYHOLDER'\n", 1)[1].split("\nPYHOLDER", 1)[0]
    body = body.replace(
        "from shared import worktree_registry as wr",
        "from shared import worktree_registry as wr\n"
        f"def broken_observer(*a, **k): raise {fault}('untrusted detail')\n"
        "wr.observe_holder = broken_observer",
    )
    before = {p: p.read_bytes() for p in [note, *cache.glob("cc-*")] if p.is_file()}
    result = subprocess.run(
        [
            str(SCRIPT.parent.parent / ".venv/bin/python"),
            "-I",
            "-c",
            body,
            str(SCRIPT.parent.parent),
            "cx-test",
            "observer-fault",
            str(vault),
            str(cache),
            "true",
            "false",
            "",
            "false",
            "fixture/repo",
            "/unused-gh",
        ],
        env={
            **os.environ,
            "HOME": str(tmp_path / "fakehome"),
            "HAPAX_WORKTREE_REGISTRY_DIR": str(
                tmp_path / "fakehome/.cache/hapax/worktree-registry"
            ),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    prefix = "HOLDER_ERROR:" if fault == "TypeError" else "HOLDER_UNKNOWN:"
    assert prefix in result.stdout, result.stdout + result.stderr
    assert "Next action:" in result.stdout
    if fault == "TypeError":
        assert "untrusted detail" not in result.stdout
    assert all(p.is_file() and p.read_bytes() == content for p, content in before.items())
