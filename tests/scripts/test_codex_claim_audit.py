"""Regression tests for the projection-only Codex claim audit."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "codex-claim-audit"
SERVICE = REPO_ROOT / "systemd" / "units" / "codex-claim-audit.service"
TIMER = REPO_ROOT / "systemd" / "units" / "codex-claim-audit.timer"
FINDINGS_EXIT = 10
AUDIT_ERROR_EXIT = 2
REFUSAL_EXIT = 2


def _base(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    home = tmp_path / "home"
    vault = home / "vault"
    cache = home / ".cache" / "hapax"
    for path in (
        vault / "active",
        vault / "closed",
        cache,
        cache / "relay" / "receipts",
        cache / "orchestration",
    ):
        path.mkdir(parents=True, exist_ok=True)
    ps_fixture = tmp_path / "ps.txt"
    ps_fixture.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "HAPAX_CLAIM_AUDIT_VAULT_ROOT": str(vault),
            "HAPAX_CLAIM_CACHE_DIR": str(cache),
            "HAPAX_RELAY_RECEIPT_DIR": str(cache / "relay" / "receipts"),
            "HAPAX_ORCHESTRATION_LEDGER_DIR": str(cache / "orchestration"),
            "HAPAX_CLAIM_AUDIT_PS_FIXTURE": str(ps_fixture),
        }
    )
    return env, vault, cache


def _write_note(
    vault: Path,
    task_id: str,
    *,
    status: str = "claimed",
    assigned_to: str = "cx-alpha",
    pr: str = "null",
    branch: str = "null",
    claimed_at: str = "2999-01-01T00:00:00Z",
) -> Path:
    note = vault / "active" / f"{task_id}.md"
    note.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "Task {task_id}"
            status: {status}
            assigned_to: {assigned_to}
            pr: {pr}
            branch: {branch}
            claimed_at: {claimed_at}
            ---
            ## Session Log
            """
        ),
        encoding="utf-8",
    )
    return note


def _write_ownership_sentinels(
    cache: Path, role: str, task_id: str, *, session: str = ""
) -> tuple[Path, Path, Path]:
    suffix = f"-{session}" if session else ""
    claim = cache / f"cc-active-task-{role}{suffix}"
    epoch = cache / f"cc-claim-epoch-{role}{suffix}"
    binding = cache / f"cc-dispatch-binding-{role}{suffix}.json"
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    epoch.write_text(f"1783814400 {task_id}\n", encoding="utf-8")
    binding.write_text('{"binding":"sentinel"}\n', encoding="utf-8")
    return claim, epoch, binding


def _snapshot(*paths: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30)


def test_stale_candidate_is_reported_without_task_or_claim_mutation(tmp_path: Path) -> None:
    env, vault, cache = _base(tmp_path)
    note = _write_note(
        vault,
        "stale-task",
        assigned_to="cx-gold",
        claimed_at="2020-01-01T00:00:00Z",
    )
    sentinels = _write_ownership_sentinels(cache, "cx-gold", "stale-task")
    before = _snapshot(note, *sentinels)

    result = _run(env, "--stale-hours=1")

    assert result.returncode == FINDINGS_EXIT, result.stderr
    assert "PHANTOM_CANDIDATE" in result.stdout
    assert "action=HOLD" in result.stdout
    assert "effects=0" in result.stdout
    assert _snapshot(note, *sentinels) == before


def test_live_claim_is_observed_without_findings_or_mutation(tmp_path: Path) -> None:
    env, vault, cache = _base(tmp_path)
    note = _write_note(vault, "live-task", assigned_to="cx-red", pr="4463")
    sentinels = _write_ownership_sentinels(cache, "cx-red", "live-task")
    before = _snapshot(note, *sentinels)

    result = _run(env, "--stale-hours=1")

    assert result.returncode == 0, result.stderr
    assert "no claim/lane coherence candidates found" in result.stdout
    assert "projection-only; effects=0" in result.stdout
    assert _snapshot(note, *sentinels) == before


def test_platform_qualified_live_claim_and_process_remain_coherent(tmp_path: Path) -> None:
    env, vault, cache = _base(tmp_path)
    note = _write_note(vault, "live-task", assigned_to="codex/cx-red", pr="4463")
    sentinels = _write_ownership_sentinels(cache, "cx-red", "live-task")
    ps_fixture = Path(env["HAPAX_CLAIM_AUDIT_PS_FIXTURE"])
    ps_fixture.write_text(
        "123 456 env CODEX_ROLE=cx-red codex Resume governed task live-task\n",
        encoding="utf-8",
    )
    before = _snapshot(note, *sentinels, ps_fixture)

    result = _run(env, "--stale-hours=1")

    assert result.returncode == 0, result.stderr
    assert "MISMATCH" not in result.stdout
    assert "no claim/lane coherence candidates found" in result.stdout
    assert _snapshot(note, *sentinels, ps_fixture) == before


def test_wrong_platform_qualified_owner_never_matches_codex_cache(tmp_path: Path) -> None:
    env, vault, cache = _base(tmp_path)
    note = _write_note(vault, "live-task", assigned_to="claude/eta", pr="4463")
    sentinels = _write_ownership_sentinels(cache, "cx-red", "live-task")
    before = _snapshot(note, *sentinels)

    result = _run(env, "--stale-hours=1")

    assert result.returncode == FINDINGS_EXIT, result.stderr
    assert "CACHE_MISSING" in result.stdout
    assert "assigned=claude/eta" in result.stdout
    assert "assigned=claude/cx-red" not in result.stdout
    assert _snapshot(note, *sentinels) == before


def test_contradictory_platform_qualified_owner_is_an_audit_error(tmp_path: Path) -> None:
    env, vault, cache = _base(tmp_path)
    note = _write_note(vault, "live-task", assigned_to="claude/cx-red", pr="4463")
    sentinels = _write_ownership_sentinels(cache, "cx-red", "live-task")
    before = _snapshot(note, *sentinels)

    result = _run(env, "--stale-hours=1")

    assert result.returncode == 2
    assert "AUDIT_ERROR authoritative task-store input incomplete" in result.stderr
    assert "task owner platform contradicts the role identity" in result.stderr
    assert _snapshot(note, *sentinels) == before


def test_quota_candidate_is_reported_without_release(tmp_path: Path) -> None:
    env, vault, cache = _base(tmp_path)
    note = _write_note(vault, "quota-task", assigned_to="cx-alpha")
    sentinels = _write_ownership_sentinels(cache, "cx-alpha", "quota-task")
    receipt = cache / "relay" / "receipts" / "cx-alpha-quota-wall.yaml"
    receipt.write_text(
        "status: quota_blocked\nresets_at: 2999-01-01T00:00:00Z\n",
        encoding="utf-8",
    )
    before = _snapshot(note, *sentinels, receipt)

    result = _run(env, "--stale-hours=999999")

    assert result.returncode == FINDINGS_EXIT, result.stderr
    assert "QUOTA_BLOCKED" in result.stdout
    assert "quota-wall-receipt" in result.stdout
    assert "action=HOLD" in result.stdout
    assert _snapshot(note, *sentinels, receipt) == before


@pytest.mark.parametrize(
    "status,task_id",
    [("done", "terminal-cache"), ("offered", "offered-cache")],
)
def test_stale_cache_candidate_is_reported_but_not_deleted(
    tmp_path: Path, status: str, task_id: str
) -> None:
    env, vault, cache = _base(tmp_path)
    note = _write_note(vault, task_id, status=status, assigned_to="cx-delta")
    sentinels = _write_ownership_sentinels(cache, "cx-delta", task_id)
    before = _snapshot(note, *sentinels)

    result = _run(env, "--stale-hours=6")

    assert result.returncode == FINDINGS_EXIT, result.stderr
    assert "CACHE_STALE_CANDIDATE" in result.stdout
    assert _snapshot(note, *sentinels) == before


def test_orphan_cache_candidate_is_reported_but_not_deleted(tmp_path: Path) -> None:
    env, _vault, cache = _base(tmp_path)
    sentinels = _write_ownership_sentinels(cache, "cx-eta", "missing-task")
    before = _snapshot(*sentinels)

    result = _run(env)

    assert result.returncode == FINDINGS_EXIT, result.stderr
    assert "status=not_active" in result.stdout
    assert _snapshot(*sentinels) == before


def test_session_keyed_live_claim_remains_coherent_and_unchanged(tmp_path: Path) -> None:
    env, vault, cache = _base(tmp_path)
    note = _write_note(vault, "session-task", assigned_to="cx-alpha", pr="4463")
    sentinels = _write_ownership_sentinels(
        cache,
        "cx-alpha",
        "session-task",
        session="019f0000-0000-7000-8000-000000000001",
    )
    before = _snapshot(note, *sentinels)

    result = _run(env)

    assert result.returncode == 0, result.stdout
    assert "CACHE_MISSING" not in result.stdout
    assert "CACHE_STALE_CANDIDATE" not in result.stdout
    assert _snapshot(note, *sentinels) == before


def test_process_incoherence_is_diagnostic_only(tmp_path: Path) -> None:
    env, vault, cache = _base(tmp_path)
    note = _write_note(vault, "process-task", assigned_to="cx-red", pr="4463")
    sentinels = _write_ownership_sentinels(cache, "cx-red", "process-task")
    ps_fixture = Path(env["HAPAX_CLAIM_AUDIT_PS_FIXTURE"])
    ps_fixture.write_text(
        "123 456 env CODEX_ROLE=cx-blue codex Resume governed task process-task\n",
        encoding="utf-8",
    )
    before = _snapshot(note, *sentinels, ps_fixture)

    result = _run(env)

    assert result.returncode == FINDINGS_EXIT, result.stderr
    assert "PROCESS_ASSIGNEE_MISMATCH" in result.stdout
    assert _snapshot(note, *sentinels, ps_fixture) == before


def test_malformed_task_note_is_fatal_before_cache_or_process_derivation(tmp_path: Path) -> None:
    env, vault, cache = _base(tmp_path)
    note = vault / "active" / "broken.md"
    note.write_text(
        "---\ntask_id: broken\nstatus: claimed\nassigned_to: cx-red\nassigned_to: cx-blue\n---\n",
        encoding="utf-8",
    )
    sentinels = _write_ownership_sentinels(cache, "cx-red", "missing-task")
    ps_fixture = Path(env["HAPAX_CLAIM_AUDIT_PS_FIXTURE"])
    ps_fixture.write_text(
        "123 456 env CODEX_ROLE=cx-red codex Resume governed task missing-task\n",
        encoding="utf-8",
    )
    before = _snapshot(note, *sentinels, ps_fixture)

    result = _run(env)

    assert result.returncode == AUDIT_ERROR_EXIT
    assert result.stdout == ""
    assert "AUDIT_ERROR authoritative task-store input incomplete" in result.stderr
    assert "duplicate key" in result.stderr
    assert "CACHE_STALE_CANDIDATE" not in result.stdout + result.stderr
    assert "PROCESS_TASK_NOT_ACTIVE" not in result.stdout + result.stderr
    assert _snapshot(note, *sentinels, ps_fixture) == before


def test_missing_task_store_is_fatal_before_cache_or_process_derivation(tmp_path: Path) -> None:
    env, vault, cache = _base(tmp_path)
    (vault / "active").rmdir()
    sentinels = _write_ownership_sentinels(cache, "cx-red", "missing-task")
    ps_fixture = Path(env["HAPAX_CLAIM_AUDIT_PS_FIXTURE"])
    ps_fixture.write_text(
        "123 456 env CODEX_ROLE=cx-red codex Resume governed task missing-task\n",
        encoding="utf-8",
    )
    before = _snapshot(*sentinels, ps_fixture)

    result = _run(env)

    assert result.returncode == AUDIT_ERROR_EXIT
    assert result.stdout == ""
    assert "AUDIT_ERROR authoritative task-store input incomplete" in result.stderr
    assert "missing-or-not-directory" in result.stderr
    assert "CACHE_STALE_CANDIDATE" not in result.stdout + result.stderr
    assert "PROCESS_TASK_NOT_ACTIVE" not in result.stdout + result.stderr
    assert _snapshot(*sentinels, ps_fixture) == before


def test_unreadable_task_store_entry_is_fatal_before_derived_scans(tmp_path: Path) -> None:
    env, vault, cache = _base(tmp_path)
    unreadable = vault / "active" / "unreadable.md"
    unreadable.mkdir()
    sentinels = _write_ownership_sentinels(cache, "cx-red", "missing-task")
    ps_fixture = Path(env["HAPAX_CLAIM_AUDIT_PS_FIXTURE"])
    ps_fixture.write_text(
        "123 456 env CODEX_ROLE=cx-red codex Resume governed task missing-task\n",
        encoding="utf-8",
    )
    before = _snapshot(*sentinels, ps_fixture)

    result = _run(env)

    assert result.returncode == AUDIT_ERROR_EXIT
    assert result.stdout == ""
    assert "AUDIT_ERROR authoritative task-store input incomplete" in result.stderr
    assert "unreadable.md" in result.stderr
    assert "CACHE_STALE_CANDIDATE" not in result.stdout + result.stderr
    assert "PROCESS_TASK_NOT_ACTIVE" not in result.stdout + result.stderr
    assert unreadable.is_dir()
    assert _snapshot(*sentinels, ps_fixture) == before


@pytest.mark.parametrize(
    "effect_args",
    [
        ("--release",),
        ("--release", "--release-quota-blocked"),
        ("--reconcile-host=hapax-appendix",),
        ("--reconcile-cache-dir=/tmp/remote-cache",),
    ],
)
def test_legacy_effect_cli_refuses_before_any_mutation(
    tmp_path: Path, effect_args: tuple[str, ...]
) -> None:
    env, vault, cache = _base(tmp_path)
    note = _write_note(
        vault,
        "refused-task",
        assigned_to="cx-gold",
        claimed_at="2020-01-01T00:00:00Z",
    )
    sentinels = _write_ownership_sentinels(cache, "cx-gold", "refused-task")
    before = _snapshot(note, *sentinels)

    result = _run(env, *effect_args)

    assert result.returncode == REFUSAL_EXIT
    assert "REFUSED_EFFECT" in result.stderr
    assert "authority is absent" in result.stderr
    assert "performed no effects" in result.stderr
    assert _snapshot(note, *sentinels) == before


def test_dry_run_is_compatibility_alias_for_read_only_scan(tmp_path: Path) -> None:
    env, vault, cache = _base(tmp_path)
    note = _write_note(
        vault,
        "dry-task",
        assigned_to="cx-cyan",
        claimed_at="2020-01-01T00:00:00Z",
    )
    sentinels = _write_ownership_sentinels(cache, "cx-cyan", "dry-task")
    before = _snapshot(note, *sentinels)

    result = _run(env, "--dry-run", "--stale-hours=1")

    assert result.returncode == FINDINGS_EXIT
    assert "PHANTOM_CANDIDATE" in result.stdout
    assert _snapshot(note, *sentinels) == before


def test_source_contains_no_claim_or_task_effect_primitive() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "sed -i",
        "rm -f",
        "mv -f",
        "ssh ",
        "status: offered",
        "assigned_to: unassigned",
        "RECONCILED:",
        "CLEARED stale claim",
    ):
        assert forbidden not in text
    assert "REFUSED_EFFECT" in text
    assert "effects=0" in text


def test_version_and_shell_syntax() -> None:
    syntax = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr
    version = subprocess.run([str(SCRIPT), "--version"], capture_output=True, text=True)
    assert version.returncode == 0
    assert "v3 (projection-only)" in version.stdout


def test_installed_service_is_projection_only_and_read_only() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    exec_start = next(line for line in text.splitlines() if line.startswith("ExecStart="))
    assert 'state="%h/.cache/hapax/source-activation"' in exec_start
    assert 'target="$(/usr/bin/readlink -f "$state/worktree")"' in exec_start
    assert '[ "${target##*/}" = "$sha" ]' in exec_start
    assert 'exec "$target/scripts/codex-claim-audit" --stale-hours=6' in exec_start
    assert "--stale-hours=6" in exec_start
    assert "--release" not in exec_start
    assert "--reconcile" not in exec_start
    assert "HAPAX_CLAIM_PLANE_HOSTS" not in text
    assert "ProtectHome=read-only" in text
    assert "ProtectSystem=strict" in text
    assert "NoNewPrivileges=true" in text
    assert "PrivateNetwork=true" in text
    assert "RestrictAddressFamilies=AF_UNIX" in text
    assert "CapabilityBoundingSet=" in text
    assert "AmbientCapabilities=" in text
    assert "ReadOnlyPaths=%t /tmp /var/tmp" in text
    assert "SystemCallFilter=~@network-io kill " in text
    assert "ConditionFileIsExecutable=%h/.cache/hapax/source-activation/worktree/" in text


def test_timer_remains_recurring_diagnostic_surface() -> None:
    text = TIMER.read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 00/4:00:00" in text
    assert "Hapax-Auto-Enable: true" in text
    assert "Project Codex claim coherence" in text


def test_findings_dropin_matches_script_exit_code() -> None:
    dropin = (
        REPO_ROOT
        / "systemd"
        / "units"
        / "codex-claim-audit.service.d"
        / "99-findings-are-warning.conf"
    )
    text = dropin.read_text(encoding="utf-8")
    success_status = [
        line.strip() for line in text.splitlines() if line.startswith("SuccessExitStatus=")
    ]
    assert success_status == ["SuccessExitStatus=10"]
    assert "SuccessExitStatus=" not in SERVICE.read_text(encoding="utf-8")
    assert "FINDINGS_EXIT=10" in SCRIPT.read_text(encoding="utf-8")
