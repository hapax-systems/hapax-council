import json
import os
import re
import subprocess
import textwrap
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.gate0b_claim_publication_install import (
    default_claim_publication_roots,
    install_claim_publication_composition,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-claim"
_SESSION_ID = "0f9f9f9f-1111-2222-3333-444455556666"
_BINDING_HASH = "a" * 64


def _task_root(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def _write_task(
    home: Path,
    subdir: str,
    task_id: str,
    *,
    status: str = "offered",
    assigned_to: str = "unassigned",
    blocked_reason: str | None = None,
    blocked_witness: str | None = None,
    depends_on: str | None = "[]",
    kind: str = "build",
    task_type: str | None = None,
    authority_case: str | None = "CASE-TEST-001",
    parent_spec: str | None = "/tmp/isap-test.md",
    quality_floor: str | None = "frontier_required",
    mutation_surface: str | None = "source",
    authority_level: str | None = "authoritative",
    route_metadata_schema: int | None = 1,
    tags: list[str] | None = None,
    body: str = "",
) -> Path:
    root = _task_root(home)
    path = root / subdir / f"{task_id}.md"
    frontmatter = [
        "---",
        "type: cc-task",
        f"task_id: {task_id}",
        f'title: "{task_id}"',
        f"status: {status}",
        f"assigned_to: {assigned_to}",
        "claimable: true",
        f"kind: {kind}",
    ]
    if blocked_reason is not None:
        frontmatter.append(f"blocked_reason: {blocked_reason}")
    if blocked_witness is not None:
        frontmatter.append(f"blocked_witness: {blocked_witness}")
    if task_type is not None:
        frontmatter.append(f"task_type: {task_type}")
    if authority_case is not None:
        frontmatter.append(f"authority_case: {authority_case}")
    if parent_spec is not None:
        frontmatter.append(f"parent_spec: {parent_spec}")
    if quality_floor is not None:
        frontmatter.append(f"quality_floor: {quality_floor}")
    if mutation_surface is not None:
        frontmatter.append(f"mutation_surface: {mutation_surface}")
    if authority_level is not None:
        frontmatter.append(f"authority_level: {authority_level}")
    if route_metadata_schema is not None:
        frontmatter.append(f"route_metadata_schema: {route_metadata_schema}")
    if tags is not None:
        frontmatter.append("tags:")
        frontmatter.extend(f"  - {tag}" for tag in tags)
    if depends_on is not None:
        if depends_on.startswith("\n"):
            frontmatter.append(f"depends_on:{depends_on}")
        else:
            frontmatter.append(f"depends_on: {depends_on}")
    frontmatter.extend(
        [
            "created_at: 2026-05-09T00:00:00Z",
            "updated_at: 2026-05-09T00:00:00Z",
            "claimed_at: null",
            "---",
            "",
            f"# {task_id}",
            "",
            body,
            "",
            "## Session log",
        ]
    )
    path.write_text("\n".join(frontmatter), encoding="utf-8")
    return path


# Identity inputs that outrank HAPAX_AGENT_ROLE in
# hooks/scripts/agent-role.sh::hapax_agent_identity, which returns the FIRST one
# set. HAPAX_AGENT_NAME is checked BEFORE HAPAX_AGENT_ROLE, so setting only the
# role leaves a lane's ambient name in place and every claim runs as that lane —
# silently, and in the dangerous direction: assertions that a claim file was NOT
# written pass vacuously because they glob for a role the script never used.
_AMBIENT_IDENTITY_ENV = (
    "HAPAX_AGENT_NAME",
    "CODEX_THREAD_NAME",
    "CODEX_SESSION_NAME",
    "CODEX_SESSION",
    "CODEX_ROLE",
    "CLAUDE_ROLE",
    "CLAUDE_CODE_SESSION_ID",
    "HAPAX_SESSION_ID",
    "HAPAX_GATE0B_CLAIM_PUBLICATION_OFF",
    "HAPAX_CLAIM_DISPATCH_MESSAGE_ID",
    "HAPAX_CLAIM_DISPATCH_BINDING_HASH",
    "HAPAX_CLAIM_DISPATCH_PLATFORM",
    "HAPAX_CLAIM_DISPATCH_MODE",
    "HAPAX_CLAIM_DISPATCH_PROFILE",
    "HAPAX_CLAIM_DISPATCH_AUTHORITY_CASE",
    "HAPAX_CLAIM_DISPATCH_IDEMPOTENCY_KEY",
)


def _dispatch_env(
    task_id: str,
    *,
    authority_case: str = "CASE-TEST-001",
) -> dict[str, str]:
    return {
        "HAPAX_CLAIM_DISPATCH_MESSAGE_ID": f"dispatch-{task_id}",
        "HAPAX_CLAIM_DISPATCH_BINDING_HASH": _BINDING_HASH,
        "HAPAX_CLAIM_DISPATCH_PLATFORM": "codex",
        "HAPAX_CLAIM_DISPATCH_MODE": "headless",
        "HAPAX_CLAIM_DISPATCH_PROFILE": "ultra",
        "HAPAX_CLAIM_DISPATCH_AUTHORITY_CASE": authority_case,
        "HAPAX_CLAIM_DISPATCH_IDEMPOTENCY_KEY": f"coord-{task_id}",
    }


def _install_gate0b_claim_publication_root(home: Path) -> None:
    install_claim_publication_composition(
        roots=default_claim_publication_roots(home=home),
        installed_at=datetime(2026, 8, 9, 17, 0, tzinfo=UTC),
        install_task_ref="cc-task-gate0b-slice1b-cc-claim-reland-20260809-test",
    )


def _claim(
    home: Path,
    task_id: str,
    *,
    legacy: bool = False,
    dispatch: bool = True,
    install_gate0b: bool | None = None,
    session_id: str | None = _SESSION_ID,
    extra_env: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for leaked in _AMBIENT_IDENTITY_ENV:
        env.pop(leaked, None)
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "cx-test"
    env["HAPAX_AGENT_NAME"] = "cx-test"
    if session_id is not None:
        env["HAPAX_SESSION_ID"] = session_id
    if legacy:
        env["HAPAX_GATE0B_CLAIM_PUBLICATION_OFF"] = "1"
    elif dispatch:
        env.update(_dispatch_env(task_id))
    if install_gate0b is None:
        install_gate0b = not legacy and dispatch
    if install_gate0b:
        _install_gate0b_claim_publication_root(home)
    if extra_env:
        env.update(extra_env)
    argv = ["bash", str(SCRIPT)]
    if extra_args:
        argv.extend(extra_args)
    if task_id:
        argv.append(task_id)
    return subprocess.run(
        argv,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("conflict", [False, True], ids=["restore_and_noop", "refuse_conflict"])
def test_rehydrate_activation_cache_wrapper(tmp_path: Path, conflict: bool) -> None:
    home = tmp_path / "home"
    task_id = "rehydrate-wrapper"
    note = _write_task(home, "active", task_id)
    published = _claim(home, task_id)
    assert published.returncode == 0, published.stderr
    note.write_text(
        re.sub(r"updated_at: [^\n]+", "updated_at: 2026-09-05T02:30:00Z", note.read_text())
        + "\nProgress after publication.\n"
    )
    cache = home / ".cache" / "hapax"
    paths = (cache / "cc-active-task-cx-test", cache / f"cc-active-task-cx-test-{_SESSION_ID}")
    for path in paths:
        path.unlink()
    if conflict:
        paths[0].write_bytes(b"another-task\n")
        paths[0].chmod(0o644)
    before = {
        path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
        for path in home.rglob("*")
        if path.is_file()
    }

    result = _claim(
        home,
        task_id,
        dispatch=False,
        install_gate0b=False,
        extra_args=["--rehydrate-activation-cache"],
    )

    if conflict:
        assert result.returncode == 8
        assert "claim_activation_cache_conflict" in result.stderr
        assert (
            "Next action: preserve the conflicting activation cache and reconcile its owner before retrying."
            in result.stderr
        )
        assert not paths[1].exists()
    else:
        assert result.returncode == 0, result.stderr
        assert ":rehydrated:" in result.stdout
        for path in paths:
            assert f"{path}: absent -> restored" in result.stdout
            assert path.read_bytes() == f"{task_id}\n".encode()
            assert path.stat().st_mode & 0o777 == 0o644
    assert {
        path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns) for path in before
    } == before
    assert {path for path in home.rglob("*") if path.is_file()} == set(before) | (
        set() if conflict else set(paths)
    )
    if not conflict:
        all_before = {
            path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
            for path in home.rglob("*")
            if path.is_file()
        }
        again = _claim(
            home,
            task_id,
            dispatch=False,
            install_gate0b=False,
            extra_args=["--rehydrate-activation-cache"],
        )
        assert again.returncode == 0, again.stderr
        assert ":noop:" in again.stdout
        assert {
            path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
            for path in home.rglob("*")
            if path.is_file()
        } == all_before


@pytest.mark.parametrize(
    ("task_id", "options", "exit_code", "reason", "remedy"),
    [
        (
            "",
            [],
            1,
            "activation_cache_usage_invalid",
            "rerun cc-claim --rehydrate-activation-cache <task_id>",
        ),
        (
            "refused",
            ["--force"],
            1,
            "activation_cache_usage_invalid",
            "rerun cc-claim --rehydrate-activation-cache <task_id>",
        ),
        (
            "refused",
            ["--recover-claim-publications"],
            1,
            "activation_cache_usage_invalid",
            "rerun cc-claim --rehydrate-activation-cache <task_id>",
        ),
        ("../refused", [], 8, "task_id_invalid", "use one non-path task identifier"),
        (
            "bounded",
            [],
            8,
            "claim_publication_journal_entry_limit",
            "restore the bounded claim-publication journal set",
        ),
    ],
    ids=["missing_task", "force", "recover", "invalid_task", "journal_limit"],
)
def test_rehydrate_refusal_branches_leave_every_file_unchanged(
    tmp_path: Path, task_id: str, options: list[str], exit_code: int, reason: str, remedy: str
) -> None:
    from shared.sdlc_claim import _MAX_CLAIM_PUBLICATIONS

    home = tmp_path / "home"
    _write_task(home, "active", "unchanged-sentinel")
    roots = default_claim_publication_roots(home=home)
    if task_id == "bounded":
        journals = Path(roots.claim_transaction_root)
        journals.mkdir(parents=True, mode=0o700)
        for index in range(_MAX_CLAIM_PUBLICATIONS + 1):
            (journals / f"entry-{index}").write_bytes(b"untouched\n")
    before = {
        path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    tree_before = set(tmp_path.rglob("*"))

    result = _claim(
        home,
        task_id,
        dispatch=False,
        install_gate0b=False,
        extra_args=["--rehydrate-activation-cache", *options],
    )

    assert result.returncode == exit_code, result.stderr
    if exit_code == 1:
        expected = (
            f"cc-claim: {reason}: supply one task id without --force or "
            f"--recover-claim-publications. Next action: {remedy}.\n"
        )
    else:
        detail = str(roots.claim_transaction_root) if task_id == "bounded" else task_id
        expected = f"cc-claim: HOLD — {reason} ({detail}). Next action: {remedy}.\n"
    assert result.stderr == expected
    assert result.stdout == ""
    assert set(tmp_path.rglob("*")) == tree_before
    assert {
        path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before


def test_default_claim_without_dispatch_issues_manual_binding(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "needs-dispatch")

    result = _claim(home, "needs-dispatch", dispatch=False)

    assert result.returncode == 0, result.stderr
    assert "manual claim binding issued" in result.stderr
    assert "provenance=manual" in result.stderr
    assert "Gate-0B claim-publication root installed for first use" in result.stderr
    assert "admitted publication applied" in result.stdout
    assert "status: claimed" in note.read_text(encoding="utf-8")
    binding = json.loads(
        (home / ".cache" / "hapax" / "cc-claim-dispatch-cx-test.json").read_text(encoding="ascii")
    )
    assert binding["platform"] == "codex"
    assert binding["mode"] == "headless"
    assert binding["profile"] == "ultra"
    assert binding["authority_case"] == "CASE-TEST-001"
    assert binding["dispatch_message_id"].startswith("manual-cc-claim:")
    assert binding["coord_dispatch_idempotency_key"].startswith("manual-cc-claim:")
    assert re.fullmatch(r"[0-9a-f]{64}", binding["binding_hash"])


def test_partial_dispatch_binding_flags_fail_without_writes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "partial-dispatch")

    result = _claim(
        home,
        "partial-dispatch",
        dispatch=False,
        extra_env={"HAPAX_CLAIM_DISPATCH_MESSAGE_ID": "only-one-field"},
    )

    assert result.returncode == 1
    assert "dispatch binding flags are all-or-none" in result.stderr
    assert "Next action: rerun with all seven" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")
    assert not (home / ".cache" / "hapax").exists()


def test_dispatch_option_missing_operand_reports_next_action(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "missing-dispatch-value")

    result = _claim(
        home,
        "missing-dispatch-value",
        dispatch=False,
        extra_args=["--dispatch-message-id", "--dispatch-binding-hash"],
    )

    assert result.returncode == 1
    assert "missing value for --dispatch-message-id" in result.stderr
    assert "Next action: rerun with '--dispatch-message-id VALUE'" in result.stderr
    assert "Every --dispatch-* option requires one VALUE" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")


def test_default_claim_refuses_retired_force_flag(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "force-retired")

    result = _claim(home, "force-retired", extra_args=["--force"])

    assert result.returncode == 2
    assert "--force is retired under canon enforcement" in result.stderr
    assert "Next action: run cc-close" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")


def test_default_claim_expired_claim_hold_names_governed_release_path(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_task(home, "active", "new-task")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    stale = cache / "cc-active-task-cx-test"
    stale.write_text("stale-task\n", encoding="utf-8")
    os.utime(stale, (0, 0))

    result = _claim(
        home,
        "new-task",
        extra_env={"HAPAX_CLAIM_LEASE_TTL_SECS": "1"},
    )

    assert result.returncode == 7
    assert "expired claim" in result.stderr
    assert "Manual Stale-Lease Release runbook" in result.stderr
    assert str(stale) in result.stderr
    assert str(cache / "cc-claim-epoch-cx-test") in result.stderr
    assert str(cache / "cc-claim-dispatch-cx-test.json") in result.stderr
    assert "cc-close stale-task" not in result.stderr


def test_default_claim_expired_empty_claim_hold_names_manual_recovery(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_task(home, "active", "new-task")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    stale = cache / "cc-active-task-cx-test"
    stale.write_text("\n", encoding="utf-8")
    os.utime(stale, (0, 0))

    result = _claim(
        home,
        "new-task",
        extra_env={"HAPAX_CLAIM_LEASE_TTL_SECS": "1"},
    )

    assert result.returncode == 7
    assert "inspect '" in result.stderr
    assert "to recover the task id" in result.stderr
    assert "<task-id-from-" not in result.stderr
    assert "cc-close" not in result.stderr


def test_expired_session_claim_exact_release_allows_canonical_retry(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "new-task")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    stale_session = "99999999-1111-2222-3333-444455556666"
    stale_key = f"cx-test-{stale_session}"
    stale = cache / f"cc-active-task-{stale_key}"
    stale_epoch = cache / f"cc-claim-epoch-{stale_key}"
    stale_dispatch = cache / f"cc-claim-dispatch-{stale_key}.json"
    stale.write_text("stale-task\n", encoding="utf-8")
    stale_epoch.write_text("1 stale-task\n", encoding="utf-8")
    stale_dispatch.write_text('{"task_id":"stale-task"}\n', encoding="ascii")
    for path in (stale, stale_epoch, stale_dispatch):
        os.utime(path, (0, 0))

    held = _claim(
        home,
        "new-task",
        extra_env={"HAPAX_CLAIM_LEASE_TTL_SECS": "1"},
    )

    assert held.returncode == 7
    assert str(stale) in held.stderr
    assert "Manual Stale-Lease Release runbook" in held.stderr
    assert "cc-close" not in held.stderr

    release = subprocess.run(
        [
            "bash",
            "-c",
            textwrap.dedent(
                r"""
                set -euo pipefail
                claim_file="$(realpath -e "$1")"
                claim_base="$(basename "$claim_file")"
                case "$claim_base" in
                  cc-active-task-*) ;;
                  *) echo "not a cc-active-task path" >&2; exit 2 ;;
                esac
                claim_key="${claim_base#cc-active-task-}"
                task_id="$(head -n1 "$claim_file" | tr -d '[:space:]')"
                test -n "$task_id"
                archive_dir="$HOME/Documents/Personal/20-projects/hapax-cc-tasks/_lineage/$task_id/manual-stale-lease-release-test"
                mkdir -p "$archive_dir"
                cache_dir="$HOME/.cache/hapax"
                for path in \
                  "$claim_file" \
                  "$cache_dir/cc-claim-epoch-$claim_key" \
                  "$cache_dir/cc-claim-dispatch-$claim_key.json"; do
                  if test -e "$path"; then
                    archived="$archive_dir/$(basename "$path")"
                    tmp_archived="$archive_dir/.copying-$(basename "$path")"
                    cp -p -- "$path" "$tmp_archived"
                    cmp -s -- "$path" "$tmp_archived"
                    mv -f -- "$tmp_archived" "$archived"
                    cmp -s -- "$path" "$archived"
                    rm -f -- "$path"
                    test ! -e "$path"
                    test -e "$archived"
                  fi
                done
                printf 'archived stale lease sidecars to %s\n' "$archive_dir"
                """
            ),
            "bash",
            str(stale),
        ],
        env={**os.environ, "HOME": str(home)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert release.returncode == 0, release.stderr
    assert "archived stale lease sidecars" in release.stdout
    archive = (
        home
        / "Documents"
        / "Personal"
        / "20-projects"
        / "hapax-cc-tasks"
        / "_lineage"
        / "stale-task"
        / "manual-stale-lease-release-test"
    )
    assert sorted(path.name for path in archive.iterdir()) == [
        stale.name,
        stale_dispatch.name,
        stale_epoch.name,
    ]
    assert not stale.exists()
    assert not stale_epoch.exists()
    assert not stale_dispatch.exists()

    retried = _claim(home, "new-task")

    assert retried.returncode == 0, retried.stderr
    assert "admitted publication applied" in retried.stdout
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_default_claim_ignores_stale_role_shadow_when_session_lease_is_fresh(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "long-lived-review")
    first = _claim(home, "long-lived-review")
    cache = home / ".cache" / "hapax"
    role_claim = cache / "cc-active-task-cx-test"
    session_claim = cache / f"cc-active-task-cx-test-{_SESSION_ID}"

    assert first.returncode == 0, first.stderr
    assert role_claim.read_text(encoding="utf-8") == "long-lived-review\n"
    assert session_claim.read_text(encoding="utf-8") == "long-lived-review\n"
    os.utime(role_claim, (0, 0))
    os.utime(session_claim, None)

    second = _claim(
        home,
        "long-lived-review",
        extra_env={"HAPAX_CLAIM_LEASE_TTL_SECS": "1"},
    )

    assert second.returncode == 0, second.stderr
    assert "expired claim" not in second.stderr
    assert "applied publication already owns task" in second.stdout
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_default_claim_refuses_pid_shaped_session_id(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "pid-session")

    result = _claim(home, "pid-session", session_id="cx-test-12345")

    assert result.returncode == 2
    assert "requires a claim-keyable non-PID session id" in result.stderr
    assert "Next action: relaunch the lane" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")


def test_explicit_killswitch_uses_legacy_writer_with_warning(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "legacy-explicit")

    result = _claim(home, "legacy-explicit", legacy=True, dispatch=False, session_id=None)

    assert result.returncode == 0, result.stderr
    assert "HAPAX_GATE0B_CLAIM_PUBLICATION_OFF=1" in result.stderr
    assert "using legacy claim writer" in result.stderr
    assert "operator-authorized emergency fallback" in result.stderr
    assert "admitted publication applied" not in result.stdout
    assert "status: claimed" in note.read_text(encoding="utf-8")
    assert (home / ".cache" / "hapax" / "cc-active-task-cx-test").read_text(
        encoding="utf-8"
    ) == "legacy-explicit\n"
    assert not (home / ".local" / "share" / "hapax" / "claim-publications").exists()


def test_default_claim_publishes_admitted_receipt_and_dispatch_sidecars(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "admitted-default")

    result = _claim(home, "admitted-default")

    assert result.returncode == 0, result.stderr
    assert "admitted publication applied" in result.stdout
    assert "HAPAX_GATE0B_CLAIM_PUBLICATION_OFF" not in result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")
    cache = home / ".cache" / "hapax"
    assert (cache / "cc-active-task-cx-test").read_text(encoding="utf-8") == ("admitted-default\n")
    assert (cache / f"cc-active-task-cx-test-{_SESSION_ID}").read_text(
        encoding="utf-8"
    ) == "admitted-default\n"
    assert (cache / "cc-claim-dispatch-cx-test.json").is_file()
    assert (cache / f"cc-claim-dispatch-cx-test-{_SESSION_ID}.json").is_file()
    manifests = list(
        (
            home / ".local" / "share" / "hapax" / "claim-publications" / "gate0b-claim-publish-v1"
        ).glob("claim-pub-*/manifest.json")
    )
    receipts = list((cache / "claim-publication-receipts").glob("*.json"))
    proof_files = list(
        (
            home
            / ".local"
            / "share"
            / "hapax"
            / "claim-publications"
            / "execution-admission"
            / "claim-publication"
        ).glob("*/*/*.json")
    )
    assert len(manifests) == 1
    assert len(receipts) == 1
    assert len(proof_files) >= 5


def test_default_claim_first_use_installs_gate0b_composition(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "missing-install")

    result = _claim(home, "missing-install", install_gate0b=False)

    assert result.returncode == 0, result.stderr
    assert "Gate-0B claim-publication root installed for first use" in result.stderr
    assert "will not overwrite non-matching install artifacts" in result.stderr
    assert "admitted publication applied" in result.stdout
    assert "status: claimed" in note.read_text(encoding="utf-8")
    root = home / ".local" / "share" / "hapax" / "execution-invocations" / "gate0b-claim-publish-v1"
    assert (root / "activation-receipt.json").is_file()
    assert (root / "composition-manifest.json").is_file()


def test_default_claim_holds_corrupt_install_receipt_without_overwrite(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "corrupt-install")
    roots = default_claim_publication_roots(home=home)
    receipt = Path(roots.invocation_store_root) / "activation-receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.parent.chmod(0o700)
    receipt.write_text("{}\n", encoding="ascii")
    receipt.chmod(0o600)

    result = _claim(home, "corrupt-install", install_gate0b=False)

    assert result.returncode == 8
    assert "gate0b_install_receipt_malformed" in result.stderr
    assert "Next action: provision or repair the Gate-0B" in result.stderr
    assert receipt.read_text(encoding="ascii") == "{}\n"
    assert "status: offered" in note.read_text(encoding="utf-8")


def test_default_claim_is_idempotent_for_existing_applied_publication(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "idempotent-applied")

    first = _claim(home, "idempotent-applied")
    second = _claim(home, "idempotent-applied")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "applied publication already owns task" in second.stdout
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_default_claim_after_normal_close_archives_dispatch_only_residue(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    first_note = _write_task(home, "active", "closed-before-next")
    first = _claim(home, "closed-before-next")
    assert first.returncode == 0, first.stderr

    task_root = _task_root(home)
    closed_note = task_root / "closed" / first_note.name
    closed_note.write_text(
        first_note.read_text(encoding="utf-8").replace("status: claimed", "status: done", 1),
        encoding="utf-8",
    )
    first_note.unlink()
    cache = home / ".cache" / "hapax"
    for key in ("cx-test", f"cx-test-{_SESSION_ID}"):
        (cache / f"cc-active-task-{key}").unlink()
        (cache / f"cc-claim-epoch-{key}").unlink()
    assert (cache / "cc-claim-dispatch-cx-test.json").is_file()
    assert (cache / f"cc-claim-dispatch-cx-test-{_SESSION_ID}.json").is_file()

    second_note = _write_task(home, "active", "claim-after-close")
    second = _claim(home, "claim-after-close")

    assert second.returncode == 0, second.stderr
    assert "archived terminal dispatch-only claim residue" in second.stderr
    assert "admitted publication applied" in second.stdout
    assert "status: claimed" in second_note.read_text(encoding="utf-8")
    assert (cache / "cc-active-task-cx-test").read_text(encoding="utf-8") == ("claim-after-close\n")
    assert (cache / f"cc-active-task-cx-test-{_SESSION_ID}").read_text(
        encoding="utf-8"
    ) == "claim-after-close\n"
    assert (cache / "cc-claim-dispatch-cx-test.json").is_file()
    assert (cache / f"cc-claim-dispatch-cx-test-{_SESSION_ID}.json").is_file()
    archived = sorted(
        (task_root / "_lineage" / "closed-before-next").glob(
            "closed-claim-dispatch-residue-*/*.json"
        )
    )
    assert [path.name for path in archived] == [
        "cc-claim-dispatch-cx-test.json",
        f"cc-claim-dispatch-cx-test-{_SESSION_ID}.json",
    ]


def test_default_claim_holds_existing_publication_for_different_dispatch(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_task(home, "active", "different-dispatch")
    first = _claim(home, "different-dispatch")

    second = _claim(
        home,
        "different-dispatch",
        extra_env={"HAPAX_CLAIM_DISPATCH_BINDING_HASH": "b" * 64},
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 8
    assert "different dispatch vector" in second.stderr
    assert "Next action: rerun with the original dispatch binding" in second.stderr


def test_default_claim_holds_legacy_existing_cache_before_rewrite(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_task(home, "active", "legacy-before-canon")
    legacy = _claim(
        home,
        "legacy-before-canon",
        legacy=True,
        dispatch=False,
        session_id=None,
    )

    result = _claim(home, "legacy-before-canon")

    assert legacy.returncode == 0, legacy.stderr
    assert result.returncode == 8
    assert "claim_dispatch_binding_missing" in result.stderr
    assert "Next action: follow the repair action above" in result.stderr


def test_default_claim_holds_unresolved_existing_cache_before_rewrite(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    task_id = "unresolved-existing-cache"
    note = _write_task(home, "active", task_id)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-cx-test").write_text(f"{task_id}\n", encoding="utf-8")
    (cache / f"cc-active-task-cx-test-{_SESSION_ID}").write_text(
        f"{task_id}\n",
        encoding="utf-8",
    )

    result = _claim(home, task_id)

    assert result.returncode == 8
    assert "cc-claim: HOLD" in result.stderr
    assert "Next action: follow the repair action above" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")


def test_default_claim_holds_corrupt_publication_inspection_before_rewrite(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    task_id = "corrupt-publication"
    note = _write_task(home, "active", task_id)
    transaction = (
        home
        / ".local"
        / "share"
        / "hapax"
        / "claim-publications"
        / "gate0b-claim-publish-v1"
        / f"claim-pub-{'a' * 64}"
    )
    transaction.mkdir(parents=True)
    transaction.parent.chmod(0o700)
    transaction.chmod(0o700)
    (transaction / "manifest.json").write_text("{}\n", encoding="ascii")
    (transaction / "manifest.json").chmod(0o600)

    result = _claim(home, task_id)

    assert result.returncode == 8
    assert "claim publication inspection requires reconciliation" in result.stderr
    assert f"cc-claim --recover-claim-publications {task_id}" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")


def test_recover_claim_publications_subcommand_uses_live_gate0b_roots(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    task_id = "recover-live-root"
    _write_task(home, "active", task_id)
    transaction = (
        home
        / ".local"
        / "share"
        / "hapax"
        / "claim-publications"
        / "gate0b-claim-publish-v1"
        / f"claim-pub-{'a' * 64}"
    )
    transaction.mkdir(parents=True)
    transaction.parent.chmod(0o700)
    transaction.chmod(0o700)
    (transaction / "manifest.json").write_text("{}\n", encoding="ascii")
    (transaction / "manifest.json").chmod(0o600)

    result = _claim(
        home,
        task_id,
        dispatch=False,
        install_gate0b=False,
        extra_args=["--recover-claim-publications"],
    )

    assert result.returncode == 8
    assert f"cc-claim: recovery claim-pub-{'a' * 64}:hold" in result.stdout
    assert "cc-claim --recover-claim-publications recover-live-root" in result.stderr
    assert not (home / ".cache" / "hapax" / "claim-publications").exists()


def test_body_bullets_are_not_claim_dependencies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "claim-target",
        depends_on="[]",
        body=textwrap.dedent(
            """\
            Ordinary markdown body bullets must not be parsed as dependencies:

            - imaginary-dependency
            - another-body-bullet
            """
        ),
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")
    assert (home / ".cache" / "hapax" / "cc-active-task-cx-test").read_text(
        encoding="utf-8"
    ).strip() == "claim-target"


def test_missing_depends_on_field_means_no_dependencies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "no-deps-field", depends_on=None)

    result = _claim(home, "no-deps-field")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_terminal_frontmatter_dependency_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "closed", "done-dep", status="done", assigned_to="cx-peer")
    note = _write_task(
        home,
        "active",
        "claim-target",
        depends_on="\n  - done-dep",
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_nonterminal_frontmatter_dependency_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "active",
        "unfinished-dep",
        status="in_progress",
        assigned_to="cx-peer",
    )
    _write_task(
        home,
        "active",
        "claim-target",
        depends_on="\n  - unfinished-dep",
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 5
    assert "unmet dependencies" in result.stderr
    assert "unfinished-dep (status_not_fulfilling:in_progress)" in result.stderr


@pytest.mark.parametrize(("verdict", "claims"), [("accepted", True), ("rejected", False)])
def test_accepted_dependency_does_not_block_its_successor(
    tmp_path: Path, verdict: str, claims: bool
) -> None:
    """M102 (E0 -> E1, dev16 2026-09-24): accepted but not closed work blocked the p0
    successor's claim with status_not_fulfilling:in_progress."""
    home = tmp_path / "home"
    dep = _write_task(home, "active", "accepted-dep", status="in_progress", assigned_to="cx-peer")
    (dep.parent / "accepted-dep.acceptance.yaml").write_text(
        "acceptor: operator\n"
        f"verdict: {verdict}\n"
        "timestamp: 2026-09-24T23:40:00Z\n"
        "artifact: frame/entitlement-census-and-single-view-20260924.md\n",
        encoding="utf-8",
    )
    target = _write_task(home, "active", "successor", depends_on="\n  - accepted-dep")

    result = _claim(home, "successor")

    if claims:
        assert result.returncode == 0, result.stderr
        assert "status: claimed" in target.read_text(encoding="utf-8")
    else:
        assert result.returncode == 5
        assert "accepted-dep (status_not_fulfilling:in_progress)" in result.stderr


def test_blocked_task_refusal_includes_reason_and_witness(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "blocked-target",
        status="blocked",
        blocked_reason="minio_mirror_still_d_state",
        blocked_witness="~/.cache/hapax/witness/minio-d-state.json",
    )

    result = _claim(home, "blocked-target")

    assert result.returncode == 4
    assert "current status is 'blocked'" in result.stderr
    assert "blocked_reason: minio_mirror_still_d_state" in result.stderr
    assert "blocked_witness: ~/.cache/hapax/witness/minio-d-state.json" in result.stderr
    assert "status: blocked" in note.read_text(encoding="utf-8")
    assert not (home / ".cache" / "hapax" / "cc-active-task-cx-test").exists()


def test_blocked_dependency_reports_precise_reason_and_witness(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "active",
        "blocked-dep",
        status="blocked",
        blocked_reason="provider_budget_receipt_absent",
        blocked_witness="~/.cache/hapax/witness/provider-budget.json",
    )
    _write_task(
        home,
        "active",
        "claim-target",
        depends_on="\n  - blocked-dep",
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 5
    assert "blocked-dep (blocked_reason:provider_budget_receipt_absent" in result.stderr
    assert "blocked_witness:~/.cache/hapax/witness/provider-budget.json" in result.stderr


def test_missing_frontmatter_dependency_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "active",
        "claim-target",
        depends_on="\n  - missing-dep",
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 5
    assert "missing-dep (not found in vault)" in result.stderr


def test_unchecked_acceptance_dependency_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "closed",
        "false-done-dep",
        status="done",
        assigned_to="cx-peer",
        body="## Acceptance criteria\n\n- [ ] Evidence exists\n",
    )
    _write_task(
        home,
        "active",
        "claim-target",
        depends_on="\n  - false-done-dep",
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 5
    assert "unchecked_acceptance_criteria:Evidence exists" in result.stderr


def test_malformed_route_metadata_dependency_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "closed",
        "bad-route-dep",
        status="done",
        assigned_to="cx-peer",
        quality_floor="frontier_review_required",
        authority_level="authoritative",
        mutation_surface="source",
    )
    _write_task(
        home,
        "active",
        "claim-target",
        depends_on="\n  - bad-route-dep",
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 5
    assert "route_metadata:" in result.stderr
    assert "frontier_review_required artifacts cannot be authoritative directly" in result.stderr


def test_build_task_with_null_parent_spec_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "active",
        "ungoverned-build",
        parent_spec="null",
        authority_case="CASE-TEST-001",
    )

    result = _claim(home, "ungoverned-build")

    assert result.returncode == 6
    assert "missing required AuthorityCase/ISAP fields" in result.stderr
    assert "parent_spec" in result.stderr


def test_build_task_missing_authority_case_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "active",
        "missing-authority",
        authority_case=None,
        parent_spec="/tmp/isap-test.md",
    )

    result = _claim(home, "missing-authority")

    assert result.returncode == 6
    assert "missing required AuthorityCase/ISAP fields" in result.stderr
    assert "authority_case" in result.stderr


def test_explicit_read_only_intake_without_parent_spec_allows_claim(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "intake-only",
        kind="intake",
        task_type="read-only",
        authority_case=None,
        parent_spec=None,
        tags=["intake", "read-only"],
    )

    result = _claim(home, "intake-only", legacy=True, dispatch=False, session_id=None)

    assert result.returncode == 0, result.stderr
    assert "HAPAX_GATE0B_CLAIM_PUBLICATION_OFF=1" in result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_hapax_cc_tasks_root_wins_over_the_home_default(tmp_path: Path) -> None:
    """The gate-path consumer must use the resolver, not a welded $HOME path."""
    home = tmp_path / "home"
    override = tmp_path / "elsewhere"
    (override / "active").mkdir(parents=True)
    (override / "closed").mkdir(parents=True)
    decoy = _write_task(home, "active", "override-root")
    real = override / "active" / "override-root.md"
    real.write_text(decoy.read_text(encoding="utf-8"), encoding="utf-8")

    result = _claim(
        home,
        "override-root",
        extra_env={"HAPAX_CC_TASKS_ROOT": str(override)},
    )

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in real.read_text(encoding="utf-8")
    assert "status: offered" in decoy.read_text(encoding="utf-8")


def test_assigned_to_unassigned_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "unassigned-owner", assigned_to="unassigned")

    result = _claim(home, "unassigned-owner")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_assigned_to_null_scalar_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "null-owner", assigned_to="null")

    result = _claim(home, "null-owner")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_assigned_to_tilde_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "tilde-owner", assigned_to="~")

    result = _claim(home, "tilde-owner")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_assigned_to_none_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "none-owner", assigned_to="none")

    result = _claim(home, "none-owner")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_empty_assigned_to_scalar_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "empty-owner", assigned_to="")

    result = _claim(home, "empty-owner")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_assigned_to_other_role_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "owned-task", assigned_to="cx-other")

    result = _claim(home, "owned-task")

    assert result.returncode == 4
    assert "already assigned to 'cx-other'" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")


def test_pr_open_assigned_to_same_role_resumes_without_status_change(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "review-fix",
        status="pr_open",
        assigned_to="cx-test",
    )

    result = _claim(home, "review-fix")

    assert result.returncode == 0, result.stderr
    text = note.read_text(encoding="utf-8")
    assert "status: pr_open" in text
    assert "assigned_to: cx-test" in text
    assert "claimed_at: null" in text
    assert "resumed ready-state task (cc-claim" in text  # tolerate session=<sid> suffix
    assert (home / ".cache" / "hapax" / "cc-active-task-cx-test").read_text(
        encoding="utf-8"
    ).strip() == "review-fix"


def test_ready_state_resume_uses_existing_session_log_heading_case(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "capital-log",
        status="pr_open",
        assigned_to="cx-test",
    )
    note.write_text(
        note.read_text(encoding="utf-8").replace("## Session log", "## Session Log"),
        encoding="utf-8",
    )

    result = _claim(home, "capital-log")

    assert result.returncode == 0, result.stderr
    text = note.read_text(encoding="utf-8")
    assert "## Session Log\n- " in text
    assert "resumed ready-state task (cc-claim" in text  # tolerate session=<sid> suffix
    assert "## Session log" not in text


def test_merge_queue_assigned_to_same_role_resumes_without_status_change(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "queue-followup",
        status="merge_queue",
        assigned_to="cx-test",
    )

    result = _claim(home, "queue-followup")

    assert result.returncode == 0, result.stderr
    text = note.read_text(encoding="utf-8")
    assert "status: merge_queue" in text
    assert "assigned_to: cx-test" in text
    assert "claimed_at: null" in text
    assert "resumed ready-state task (cc-claim" in text  # tolerate session=<sid> suffix
    assert (home / ".cache" / "hapax" / "cc-active-task-cx-test").read_text(
        encoding="utf-8"
    ).strip() == "queue-followup"


def test_pr_open_unassigned_blocks_resume(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "unowned-review",
        status="pr_open",
        assigned_to="unassigned",
    )

    result = _claim(home, "unowned-review")

    assert result.returncode == 4
    assert "ready-state task is not assigned to 'cx-test'" in result.stderr
    assert "status: pr_open" in note.read_text(encoding="utf-8")
    assert not (home / ".cache" / "hapax" / "cc-active-task-cx-test").exists()


def test_merge_queue_different_assignee_blocks_resume(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "other-queue",
        status="merge_queue",
        assigned_to="cx-other",
    )

    result = _claim(home, "other-queue")

    assert result.returncode == 4
    assert "assigned to 'cx-other', not 'cx-test'" in result.stderr
    assert "status: merge_queue" in note.read_text(encoding="utf-8")
    assert not (home / ".cache" / "hapax" / "cc-active-task-cx-test").exists()


def test_depends_on_null_scalar_means_no_dependencies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "null-dep", depends_on="null")

    result = _claim(home, "null-dep")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_depends_on_tilde_means_no_dependencies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "tilde-dep", depends_on="~")

    result = _claim(home, "tilde-dep")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_depends_on_none_means_no_dependencies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "none-dep", depends_on="none")

    result = _claim(home, "none-dep")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_depends_on_quoted_null_means_no_dependencies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "quoted-null", depends_on='"null"')

    result = _claim(home, "quoted-null")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_block_style_depends_on_does_not_bleed_into_tags(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "closed", "real-dep", status="done", assigned_to="cx-peer")
    note = _write_task(
        home,
        "active",
        "bleed-test",
        depends_on="\n  - real-dep",
        tags=["cc-task", "sdlc", "implementation"],
    )

    result = _claim(home, "bleed-test")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_depends_on_as_terminal_frontmatter_key(tmp_path: Path) -> None:
    """depends_on as the last key before closing --- must not collect body items."""
    home = tmp_path / "home"
    _write_task(home, "closed", "term-dep", status="done", assigned_to="cx-peer")
    root = _task_root(home)
    path = root / "active" / "terminal-key.md"
    path.write_text(
        textwrap.dedent("""\
            ---
            type: cc-task
            task_id: terminal-key
            title: "terminal-key"
            status: offered
            assigned_to: unassigned
            claimable: true
            kind: build
            authority_case: CASE-TEST-001
            parent_spec: /tmp/isap-test.md
            created_at: 2026-05-09T00:00:00Z
            updated_at: 2026-05-09T00:00:00Z
            claimed_at: null
            depends_on:
              - term-dep
            ---

            # terminal-key

            Body bullets that must not be parsed as deps:

            - fake-dep-one
            - fake-dep-two

            ## Session log
        """),
        encoding="utf-8",
    )

    result = _claim(home, "terminal-key")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in path.read_text(encoding="utf-8")


def test_governed_build_task_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "governed-build")

    result = _claim(home, "governed-build")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_claim_inserts_missing_claim_keys(tmp_path: Path) -> None:
    """A note authored without claimed_at must still get a COMPLETE stamp.

    The re.sub stamps were silent no-ops for absent keys: the claim landed as
    `status: claimed` with claimed_at missing — exactly the cc-hygiene H1
    ghost predicate — and H1 reverted the fresh claim out from under the live
    lane (2026-07-01 eta/ndcvb-phase1 incident)."""
    home = tmp_path / "home"
    root = _task_root(home)
    task_id = "cc-missing-keys"
    path = root / "active" / f"{task_id}.md"
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: offered
            assigned_to: unassigned
            claimable: true
            kind: build
            authority_case: CASE-TEST-001
            parent_spec: /tmp/isap-test.md
            quality_floor: frontier_required
            mutation_surface: source
            authority_level: authoritative
            route_metadata_schema: 1
            depends_on: []
            created_at: 2026-05-09T00:00:00Z
            updated_at: 2026-05-09T00:00:00Z
            ---

            # {task_id}

            ## Session log
            """
        ),
        encoding="utf-8",
    )

    result = _claim(home, task_id)

    assert result.returncode == 0, result.stderr
    text = path.read_text(encoding="utf-8")
    frontmatter = text[: text.find("\n---", 4)]
    assert "status: claimed" in frontmatter
    assert "assigned_to: cx-test" in frontmatter
    assert re.search(r"^claimed_at: \d{4}-\d{2}-\d{2}T", frontmatter, flags=re.MULTILINE), (
        "claimed_at must be inserted when the authored note lacks the key:\n" + frontmatter
    )


def test_claim_stamp_ignores_body_decoy_lines(tmp_path: Path) -> None:
    """A column-0 `claimed_at:` line in the note BODY must neither absorb the
    stamp nor satisfy the verification — stamping is frontmatter-scoped."""
    home = tmp_path / "home"
    root = _task_root(home)
    task_id = "cc-body-decoy"
    path = root / "active" / f"{task_id}.md"
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: offered
            assigned_to: unassigned
            claimable: true
            kind: build
            authority_case: CASE-TEST-001
            parent_spec: /tmp/isap-test.md
            quality_floor: frontier_required
            mutation_surface: source
            authority_level: authoritative
            route_metadata_schema: 1
            depends_on: []
            created_at: 2026-05-09T00:00:00Z
            updated_at: 2026-05-09T00:00:00Z
            ---

            # {task_id}

            Quoted frontmatter from an earlier incident report:
            claimed_at: 1999-01-01T00:00:00Z
            status: offered

            ## Session log
            """
        ),
        encoding="utf-8",
    )

    result = _claim(home, task_id)

    assert result.returncode == 0, result.stderr
    text = path.read_text(encoding="utf-8")
    frontmatter = text[: text.find("\n---", 4)]
    assert re.search(r"^claimed_at: \d{4}-\d{2}-\d{2}T", frontmatter, flags=re.MULTILINE), (
        "claimed_at must be stamped INTO the frontmatter despite the body decoy:\n" + frontmatter
    )
    # The body decoy line is untouched.
    assert "claimed_at: 1999-01-01T00:00:00Z" in text


def test_claim_writes_task_bound_epoch_sidecar(tmp_path: Path) -> None:
    """cc-claim records `<epoch> <task_id>` in the cc-claim-epoch sidecar so
    task_is_terminal has a heartbeat-immune, task-bound claim-age witness."""
    home = tmp_path / "home"
    _write_task(home, "active", "cc-sidecar")

    result = _claim(home, "cc-sidecar")

    assert result.returncode == 0, result.stderr
    sidecar = home / ".cache" / "hapax" / "cc-claim-epoch-cx-test"
    assert sidecar.exists()
    epoch, _, task = sidecar.read_text(encoding="utf-8").strip().partition(" ")
    assert epoch.isdigit()
    assert task == "cc-sidecar"


def test_claim_writes_session_keyed_epoch_sidecar(tmp_path: Path) -> None:
    """The session-keyed sidecar is written alongside the session-keyed cache
    with an explicitly constructed path (never substring substitution on the
    full path, which corrupts when a parent dir contains cc-active-task)."""
    home = tmp_path / "home"
    _write_task(home, "active", "cc-sidecar-session")
    sid = "0f9f9f9f-1111-2222-3333-444455556666"
    result = _claim(home, "cc-sidecar-session", session_id=sid)

    assert result.returncode == 0, result.stderr
    cache_dir = home / ".cache" / "hapax"
    session_cache = cache_dir / f"cc-active-task-cx-test-{sid}"
    assert session_cache.read_text(encoding="utf-8").strip() == "cc-sidecar-session"
    session_sidecar = cache_dir / f"cc-claim-epoch-cx-test-{sid}"
    assert session_sidecar.exists(), sorted(p.name for p in cache_dir.iterdir())
    epoch, _, task = session_sidecar.read_text(encoding="utf-8").strip().partition(" ")
    assert epoch.isdigit()
    assert task == "cc-sidecar-session"


def test_claim_refuses_duplicate_claim_keys(tmp_path: Path) -> None:
    """Duplicate claim keys are fail-closed: re.sub stamps only the FIRST
    occurrence while YAML consumers treat the LAST as authoritative — the
    combination would leave a ghost-claimable note behind a written cache."""
    home = tmp_path / "home"
    root = _task_root(home)
    task_id = "cc-duplicate-keys"
    path = root / "active" / f"{task_id}.md"
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: offered
            assigned_to: unassigned
            claimable: true
            kind: build
            authority_case: CASE-TEST-001
            parent_spec: /tmp/isap-test.md
            quality_floor: frontier_required
            mutation_surface: source
            authority_level: authoritative
            route_metadata_schema: 1
            depends_on: []
            created_at: 2026-05-09T00:00:00Z
            updated_at: 2026-05-09T00:00:00Z
            claimed_at: null
            claimed_at: null
            ---

            # {task_id}

            ## Session log
            """
        ),
        encoding="utf-8",
    )

    result = _claim(home, task_id)

    assert result.returncode != 0
    assert "duplicate frontmatter keys" in result.stderr
    cache_dir = home / ".cache" / "hapax"
    leaked = list(cache_dir.glob("cc-active-task-*")) if cache_dir.exists() else []
    assert leaked == [], f"claim caches must not be written for a duplicate-key note: {leaked}"


def test_claim_refuses_note_without_closing_frontmatter(tmp_path: Path) -> None:
    """An unstampable note must fail loudly WITHOUT writing claim caches —
    the no-cache-on-failure guarantee is the load-bearing fail-closed
    property (a cache over a ghost-claimable note re-opens the H1 race)."""
    home = tmp_path / "home"
    root = _task_root(home)
    task_id = "cc-no-closing-delimiter"
    path = root / "active" / f"{task_id}.md"
    path.write_text(
        "---\n"
        f"task_id: {task_id}\n"
        "status: offered\n"
        "assigned_to: unassigned\n"
        "# frontmatter never closes\n",
        encoding="utf-8",
    )

    result = _claim(home, task_id)

    assert result.returncode != 0
    assert "no closing frontmatter delimiter" in result.stderr
    assert "No claim caches were written" in result.stderr
    cache_dir = home / ".cache" / "hapax"
    leaked = list(cache_dir.glob("cc-active-task-*")) if cache_dir.exists() else []
    assert leaked == [], f"claim caches must not be written on a failed stamp: {leaked}"


# ── governed release of a role's claim residue ───────────────────────────────
# claim-cache-missing-governed-release-20260926: M166-M173. Each shape once needed an
# operator-run shell script, because the cc-task-gate refuses shell cp/mv/rm (M160).


def _release(
    home: Path, task_id: str, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return _claim(
        home,
        task_id,
        dispatch=False,
        install_gate0b=False,
        extra_env=extra_env,
        extra_args=["--release-claim-residue"],
    )


def _role_sidecars(
    home: Path, *, role: str = "cx-test", session: str = _SESSION_ID
) -> dict[str, tuple[Path, Path]]:
    cache = home / ".cache" / "hapax"
    keys = (role, f"{role}-{session}")
    return {
        "marker": tuple(cache / f"cc-active-task-{key}" for key in keys),
        "epoch": tuple(cache / f"cc-claim-epoch-{key}" for key in keys),
        "dispatch": tuple(cache / f"cc-claim-dispatch-{key}.json" for key in keys),
    }


def _bytes_of(paths: tuple[Path, ...]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _release_archives(home: Path, task_id: str) -> list[Path]:
    return sorted((_task_root(home) / "_lineage" / task_id).glob("claim-residue-release-*"))


def test_release_frees_a_role_wedged_by_its_own_lapsed_lease(tmp_path: Path) -> None:
    home = tmp_path / "home"
    lapsed = _write_task(home, "active", "lapsed-row")
    assert _claim(home, "lapsed-row").returncode == 0
    sidecars = _role_sidecars(home)
    for marker in sidecars["marker"]:
        marker.unlink()  # the lease lapsed; its epoch and dispatch sidecars survive (M168)
    _write_task(home, "active", "next-row")
    wedged = _claim(home, "next-row")
    assert wedged.returncode == 8
    assert "claim_cache_missing" in wedged.stderr
    assert "cc-claim --release-claim-residue lapsed-row" in wedged.stderr
    note_before = lapsed.read_bytes()

    released = _release(home, "lapsed-row")

    assert released.returncode == 0, released.stderr
    assert "lapsed_lease" in released.stdout
    assert lapsed.read_bytes() == note_before  # the live row is never touched
    [archive] = _release_archives(home, "lapsed-row")
    residue = (*sidecars["epoch"], *sidecars["dispatch"])
    assert sorted(path.name for path in archive.iterdir()) == sorted(
        [*(path.name for path in residue), "README.md"]
    )
    assert not any(path.exists() for path in residue)
    retried = _claim(home, "next-row")
    assert retried.returncode == 0, retried.stderr


def test_release_frees_markers_that_name_a_row_now_in_closed(tmp_path: Path) -> None:
    # M173, twice: dev33 on frame-reduction, grok-sonar on sonar-alias-retirement. The PR-merge
    # watcher closed the row from another process, and the claimant's markers stayed behind.
    home = tmp_path / "home"
    note = _write_task(home, "active", "commission-row")
    assert _claim(home, "commission-row").returncode == 0
    closed = _task_root(home) / "closed" / note.name
    closed.write_text(
        note.read_text(encoding="utf-8").replace("status: claimed", "status: done", 1),
        encoding="utf-8",
    )
    note.unlink()
    _write_task(home, "active", "next-row")
    stranded = _claim(home, "next-row")
    assert stranded.returncode == 8
    assert "cc-claim --release-claim-residue commission-row" in stranded.stderr
    closed_before = closed.read_bytes()

    released = _release(home, "commission-row")

    assert released.returncode == 0, released.stderr
    assert "closed_task" in released.stdout
    assert closed.read_bytes() == closed_before
    sidecars = _role_sidecars(home)
    assert not any(path.exists() for group in sidecars.values() for path in group)
    [archive] = _release_archives(home, "commission-row")
    assert len([path for path in archive.iterdir() if path.name != "README.md"]) == 6
    retried = _claim(home, "next-row")
    assert retried.returncode == 0, retried.stderr


def test_release_refuses_a_live_claim_and_moves_nothing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "live-row")
    assert _claim(home, "live-row").returncode == 0
    sidecars = _role_sidecars(home)
    everything = tuple(path for group in sidecars.values() for path in group)
    before, note_before = _bytes_of(everything), note.read_bytes()

    released = _release(home, "live-row")

    assert released.returncode == 8
    assert "claim_residue_live_marker" in released.stderr
    assert _bytes_of(everything) == before
    assert note.read_bytes() == note_before
    assert _release_archives(home, "live-row") == []


def test_release_refuses_markers_of_a_row_still_in_active_mid_close(tmp_path: Path) -> None:
    # A terminal status alone is not enough: until cc-close moves the row out of active/, its
    # markers may still be in use.
    home = tmp_path / "home"
    note = _write_task(home, "active", "closing-row")
    assert _claim(home, "closing-row").returncode == 0
    note.write_text(
        note.read_text(encoding="utf-8").replace("status: claimed", "status: done", 1),
        encoding="utf-8",
    )
    sidecars = _role_sidecars(home)
    everything = tuple(path for group in sidecars.values() for path in group)
    before = _bytes_of(everything)

    released = _release(home, "closing-row")

    assert released.returncode == 8
    assert "claim_residue_live_marker" in released.stderr
    assert _bytes_of(everything) == before


def test_release_refuses_residue_that_differs_from_the_journal(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "active", "lapsed-row")
    assert _claim(home, "lapsed-row").returncode == 0
    sidecars = _role_sidecars(home)
    for marker in sidecars["marker"]:
        marker.unlink()
    sidecars["epoch"][1].write_text("1 lapsed-row\n", encoding="utf-8")
    residue = (*sidecars["epoch"], *sidecars["dispatch"])
    before = _bytes_of(residue)

    released = _release(home, "lapsed-row")

    assert released.returncode == 8
    assert "claim_residue_hash_mismatch" in released.stderr
    assert _bytes_of(residue) == before
    assert _release_archives(home, "lapsed-row") == []


def test_release_refuses_while_another_session_of_the_role_holds_the_task(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_task(home, "active", "lapsed-row")
    assert _claim(home, "lapsed-row").returncode == 0
    sidecars = _role_sidecars(home)
    for marker in sidecars["marker"]:
        marker.unlink()
    live = home / ".cache" / "hapax" / "cc-active-task-cx-test-77777777-1111-2222-3333-444455556666"
    live.write_text("lapsed-row\n", encoding="utf-8")
    residue = (*sidecars["epoch"], *sidecars["dispatch"], live)
    before = _bytes_of(residue)

    released = _release(home, "lapsed-row")

    assert released.returncode == 8
    assert "claim_residue_live_marker" in released.stderr
    assert _bytes_of(residue) == before


def test_release_reports_when_nothing_remains(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "active", "gone-row")
    assert _claim(home, "gone-row").returncode == 0
    for group in _role_sidecars(home).values():
        for path in group:
            path.unlink()

    released = _release(home, "gone-row")

    assert released.returncode == 8
    assert "claim_residue_none" in released.stderr
    assert _release_archives(home, "gone-row") == []


def test_release_refuses_a_lapsed_lease_missing_a_sidecar_never_archived(tmp_path: Path) -> None:
    # codex, #4801 round 2: a missing epoch beside a matching dispatch is not accounted for.
    home = tmp_path / "home"
    _write_task(home, "active", "lapsed-row")
    assert _claim(home, "lapsed-row").returncode == 0
    sidecars = _role_sidecars(home)
    for marker in sidecars["marker"]:
        marker.unlink()
    sidecars["epoch"][1].unlink()
    before = _bytes_of((*sidecars["epoch"], *sidecars["dispatch"]))

    released = _release(home, "lapsed-row")

    assert released.returncode == 8
    assert "claim_residue_projection_missing" in released.stderr
    assert _bytes_of((*sidecars["epoch"], *sidecars["dispatch"])) == before


def test_release_touches_no_other_role_or_session(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "active", "lapsed-row")
    assert _claim(home, "lapsed-row").returncode == 0
    for marker in _role_sidecars(home)["marker"]:
        marker.unlink()
    cache = home / ".cache" / "hapax"
    other_session = "77777777-1111-2222-3333-444455556666"
    foreign = (
        cache / f"cc-claim-epoch-cx-test-{other_session}",  # this role, another session
        cache / "cc-claim-epoch-cx-other",  # another role
        cache / "cc-active-task-cx-other",
    )
    for path in foreign:
        path.write_text("1 lapsed-row\n" if "epoch" in path.name else "lapsed-row\n")
    before = _bytes_of(foreign)

    # Released from a new session of the same role; another role cannot release it at all.
    new_session = "88888888-1111-2222-3333-444455556666"
    other_role = _release(
        home,
        "lapsed-row",
        extra_env={"HAPAX_AGENT_ROLE": "cx-other", "HAPAX_AGENT_NAME": "cx-other"},
    )
    released = _release(home, "lapsed-row", extra_env={"HAPAX_SESSION_ID": new_session})

    assert other_role.returncode == 8
    assert "claim_residue_no_journal" in other_role.stderr
    assert released.returncode == 0, released.stderr
    assert _bytes_of(foreign) == before


# ── self-resume of the role's own lapsed row ─────────────────────────────────
# claim-plane-self-resume-own-lapsed-row-20260927: a role whose own lease lapsed could not take
# its row back; the seat had to hand-edit the note (2026-09-26, dev44 and dev33).


def _next_second() -> None:
    """A real lapse takes hours; the claim epoch (and so the dispatch binding and its receipt)
    has one-second resolution, so never resume inside the claim's own second."""

    claimed_second = int(time.time())
    while int(time.time()) == claimed_second:
        time.sleep(0.05)


def _lapse_every_sidecar(home: Path) -> None:
    for group in _role_sidecars(home).values():
        for path in group:
            path.unlink(missing_ok=True)
    _next_second()


@pytest.mark.parametrize("status", ["claimed", "in_progress"])
def test_a_live_own_claim_is_answered_as_applied_and_never_self_resumed(
    tmp_path: Path, status: str
) -> None:
    # #4804 round 2 (claude): the safety invariant, pinned. With its lease live, the role's
    # rerun is answered by the applied publication before the status gate, so the new
    # self-resume branch never rewrites a live claim.
    home = tmp_path / "home"
    note = _write_task(home, "active", "live-row")
    assert _claim(home, "live-row").returncode == 0
    if status == "in_progress":
        note.write_text(
            note.read_text(encoding="utf-8").replace("status: claimed", "status: in_progress", 1),
            encoding="utf-8",
        )
    _next_second()
    before = note.read_bytes()

    rerun = _claim(home, "live-row")

    assert rerun.returncode == 0, rerun.stderr
    assert "applied publication already owns task" in rerun.stdout
    assert note.read_bytes() == before


@pytest.mark.parametrize("status", ["claimed", "in_progress"])
def test_a_role_resumes_its_own_row_after_its_lease_lapsed(tmp_path: Path, status: str) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "own-row")
    assert _claim(home, "own-row").returncode == 0
    if status == "in_progress":
        note.write_text(
            note.read_text(encoding="utf-8").replace("status: claimed", "status: in_progress", 1),
            encoding="utf-8",
        )
    _lapse_every_sidecar(home)

    resumed = _claim(home, "own-row")

    assert resumed.returncode == 0, resumed.stderr
    text = note.read_text(encoding="utf-8")
    assert f"status: {status}" in text
    assert "assigned_to: cx-test" in text
    assert text.count("resumed its own lapsed claim (cc-claim") == 1
    assert (home / ".cache" / "hapax" / "cc-active-task-cx-test").read_text(
        encoding="utf-8"
    ).strip() == "own-row"


def test_a_lapsed_lease_is_released_then_resumed(tmp_path: Path) -> None:
    # Composes with the residue release (#4801): the HOLD names it, it clears the residue,
    # and the role takes its own row back without a hand edit.
    home = tmp_path / "home"
    note = _write_task(home, "active", "own-row")
    assert _claim(home, "own-row").returncode == 0
    for marker in _role_sidecars(home)["marker"]:
        marker.unlink()
    held = _claim(home, "own-row")
    assert held.returncode == 8
    assert "cc-claim --release-claim-residue own-row" in held.stderr
    assert _release(home, "own-row").returncode == 0
    _next_second()

    resumed = _claim(home, "own-row")

    assert resumed.returncode == 0, resumed.stderr
    assert "resumed its own lapsed claim (cc-claim" in note.read_text(encoding="utf-8")


def test_a_role_claims_an_offered_row_already_assigned_to_it(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "own-offered-row", assigned_to="cx-test")

    result = _claim(home, "own-offered-row")

    assert result.returncode == 0, result.stderr
    text = note.read_text(encoding="utf-8")
    assert "status: claimed" in text
    assert "assigned_to: cx-test" in text


@pytest.mark.parametrize("status", ["claimed", "in_progress"])
def test_a_working_row_of_another_role_is_still_refused(tmp_path: Path, status: str) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "their-row", status=status, assigned_to="cx-other")
    before = note.read_bytes()

    result = _claim(home, "their-row")

    assert result.returncode == 4
    assert "cx-other" in result.stderr
    assert note.read_bytes() == before


@pytest.mark.parametrize(
    ("marker", "content"),
    [
        ("cc-active-task-cx-other", b"own-row\n"),
        ("cc-active-task-cx-test-77777777-1111-2222-3333-444455556666", b"own-row\n"),
        ("cc-active-task-cx-other", b"\xff\xfe"),  # unreadable: it may name the row
        ("cc-active-task-cx-other", b"garbage\nown-row\n"),  # names it on a later line
    ],
    ids=["other-role", "other-session", "unreadable", "later-line"],
)
def test_own_row_is_not_resumed_while_another_claim_marker_names_it(
    tmp_path: Path, marker: str, content: bytes
) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "own-row")
    assert _claim(home, "own-row").returncode == 0
    _lapse_every_sidecar(home)
    live = home / ".cache" / "hapax" / marker
    live.write_bytes(content)
    before = note.read_bytes()

    result = _claim(home, "own-row")

    assert result.returncode == 4
    assert str(live) in result.stderr
    assert note.read_bytes() == before
    assert not (home / ".cache" / "hapax" / "cc-active-task-cx-test").exists()


_OTHER_ROLE = {"HAPAX_AGENT_ROLE": "cx-other", "HAPAX_AGENT_NAME": "cx-other"}


def test_an_unassigned_offered_row_is_not_claimed_while_a_foreign_marker_names_it(
    tmp_path: Path,
) -> None:
    # #4804 round 1 (gemini; seat 04:05Z): the check holds for every claim, not only own rows.
    home = tmp_path / "home"
    note = _write_task(home, "active", "offered-row")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    live = cache / "cc-active-task-cx-other"
    live.write_text("offered-row\n", encoding="utf-8")
    before = note.read_bytes()

    result = _claim(home, "offered-row")

    assert result.returncode == 4
    assert str(live) in result.stderr
    assert note.read_bytes() == before


def test_a_ready_state_resume_refuses_while_a_foreign_marker_names_the_row(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "review-row", status="pr_open", assigned_to="cx-test")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    live = cache / "cc-active-task-cx-other"
    live.write_text("review-row\n", encoding="utf-8")
    before = note.read_bytes()

    result = _claim(home, "review-row")

    assert result.returncode == 4
    assert str(live) in result.stderr
    assert note.read_bytes() == before


def test_a_row_reoffered_over_a_stale_marker_is_unwedged_by_the_governed_release(
    tmp_path: Path,
) -> None:
    # The seat re-offers a lapsed row by hand; the old claimant's markers stay. The new claim
    # refuses on them, and the old claimant releases them: the note no longer names it, so they
    # cannot be a live claim (publication writes the note before the markers).
    home = tmp_path / "home"
    note = _write_task(home, "active", "reoffered-row")
    assert _claim(home, "reoffered-row", extra_env=_OTHER_ROLE).returncode == 0
    text = note.read_text(encoding="utf-8")
    note.write_text(
        text.replace("status: claimed", "status: offered", 1).replace(
            "assigned_to: cx-other", "assigned_to: unassigned", 1
        ),
        encoding="utf-8",
    )
    refused = _claim(home, "reoffered-row")
    assert refused.returncode == 4
    assert "cc-active-task-cx-other" in refused.stderr

    released = _release(home, "reoffered-row", extra_env=_OTHER_ROLE)

    assert released.returncode == 0, released.stderr
    assert "reassigned_task" in released.stdout
    claimed = _claim(home, "reoffered-row")
    assert claimed.returncode == 0, claimed.stderr
    assert "assigned_to: cx-test" in note.read_text(encoding="utf-8")


def test_an_own_offered_row_is_not_claimed_while_another_claim_marker_names_it(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "own-offered-row", assigned_to="cx-test")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    live = cache / "cc-active-task-cx-other"
    live.write_text("own-offered-row\n", encoding="utf-8")
    before = note.read_bytes()

    result = _claim(home, "own-offered-row")

    assert result.returncode == 4
    assert str(live) in result.stderr
    assert note.read_bytes() == before


def test_a_closed_row_stays_refused_and_points_at_the_residue_release(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "closed-row")
    assert _claim(home, "closed-row").returncode == 0
    closed = _task_root(home) / "closed" / note.name
    closed.write_text(
        note.read_text(encoding="utf-8").replace("status: claimed", "status: done", 1),
        encoding="utf-8",
    )
    note.unlink()
    before = closed.read_bytes()

    result = _claim(home, "closed-row")

    assert result.returncode == 2
    assert "cc-claim --release-claim-residue closed-row" in result.stderr
    assert closed.read_bytes() == before


def test_an_unassigned_working_row_is_still_refused(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "orphan-row", status="claimed", assigned_to="unassigned")
    before = note.read_bytes()

    result = _claim(home, "orphan-row")

    assert result.returncode == 4
    assert note.read_bytes() == before


# ── claim-plane-live-claim-handoff-verb-20260927 ──────────────────────────────


def _set_status(note: Path, old: str, new: str) -> None:
    note.write_text(
        note.read_text(encoding="utf-8").replace(f"status: {old}", f"status: {new}", 1),
        encoding="utf-8",
    )


def _lineage_shapes(home: Path, task_id: str) -> list[str]:
    lineage = _task_root(home) / "_lineage" / task_id
    return sorted(
        line.split(":", 1)[1].strip()
        for readme in lineage.glob("claim-residue-release-*/README.md")
        for line in readme.read_text(encoding="utf-8").splitlines()
        if line.startswith("shape:")
    )


def test_a_pipeline_held_row_frees_the_slot_and_keeps_its_named_resumer(tmp_path: Path) -> None:
    # (b), the seat's 2026-09-27T15:58:53Z ruling: pr_open is pipeline-held, not worker-held
    # (L-109; #4611's intent). fugu-rebase held #4770 (pr_open) and could not take #4767.
    home = tmp_path / "home"
    parked = _write_task(home, "active", "parked-row")
    _write_task(home, "active", "next-row")
    assert _claim(home, "parked-row").returncode == 0
    _set_status(parked, "claimed", "pr_open")

    taken = _claim(home, "next-row")

    assert taken.returncode == 0, taken.stderr
    text = parked.read_text(encoding="utf-8")
    assert "status: pr_open" in text and "assigned_to: cx-test" in text
    assert _lineage_shapes(home, "parked-row") == ["pipeline_held"]
    marker = _role_sidecars(home)["marker"][0]
    assert marker.read_text(encoding="utf-8").split()[0] == "next-row"


def test_every_marker_is_checked_so_a_second_held_row_is_released_too(tmp_path: Path) -> None:
    # codex on #4826: only the first readable marker was checked. A pipeline-held row named by a
    # lingering session-keyed marker stayed held although the lease scan counted it free.
    home = tmp_path / "home"
    first_session, second_session, third_session = (
        _SESSION_ID,
        "1f9f9f9f-1111-2222-3333-444455556666",
        "2f9f9f9f-1111-2222-3333-444455556666",
    )
    older = _write_task(home, "active", "older-row")
    newer = _write_task(home, "active", "newer-row")
    _write_task(home, "active", "next-row")
    assert _claim(home, "older-row", session_id=first_session).returncode == 0
    _set_status(older, "claimed", "pr_open")
    assert _claim(home, "newer-row", session_id=second_session).returncode == 0
    _set_status(newer, "claimed", "pr_open")
    # older-row's session-keyed files linger (as sessions from before this change can leave them).
    cache = home / ".cache" / "hapax"
    (staged,) = (cache / "claim-residue-release" / "older-row").iterdir()
    for kept in staged.iterdir():
        if first_session in kept.name:
            (cache / kept.name).write_bytes(kept.read_bytes())
            os.chmod(
                cache / kept.name, kept.stat().st_mode & 0o777
            )  # the residue check reads modes
    assert (cache / f"cc-active-task-cx-test-{first_session}").exists()
    # Releases are stamped to the second, and this fixture releases one publication twice; a
    # same-second second release holds on the taken staging name (fail closed). Real residue is
    # not released twice, so the test steps past the second rather than widen the stamp.
    time.sleep(1.1)

    taken = _claim(home, "next-row", session_id=third_session)

    assert taken.returncode == 0, taken.stderr
    assert _lineage_shapes(home, "older-row") == ["pipeline_held", "pipeline_held"]
    assert _lineage_shapes(home, "newer-row") == ["pipeline_held"]
    assert not (cache / f"cc-active-task-cx-test-{first_session}").exists()


_MALFORMED = [
    "unparseable",
    "duplicated_status",
    "duplicated_pr",
    "duplicated_assigned",
    "quoted_duplicate_assigned",
    "quoted_duplicate_status",
    "unhashable_key",
    "body_only",
]


def _malform(text: str, how: str) -> str:
    if how == "unparseable":  # parsed.ok is false
        return text.replace("status: pr_open", "status: pr_open\nbroken: [", 1)
    if how == "quoted_duplicate_status":
        return text.replace("status: pr_open", 'status: pr_open\n"status": claimed', 1)
    if how == "quoted_duplicate_assigned":  # one YAML key, two spellings (codex, round 5)
        return text.replace(
            "assigned_to: cx-test", 'assigned_to: cx-test\n"assigned_to": cx-other', 1
        )
    if how == "duplicated_assigned":  # the last value would read as reassigned
        return text.replace(
            "assigned_to: cx-test", "assigned_to: cx-test\nassigned_to: cx-other", 1
        )
    if how == "duplicated_status":
        return text.replace("status: pr_open", "status: claimed\nstatus: pr_open", 1)
    if how == "duplicated_pr":
        return text.replace("status: pr_open", "status: pr_open\npr: 4999\npr: null", 1)
    if how == "unhashable_key":  # a complex key constructs to a list (glm on #4826 round 7)
        return text.replace("status: pr_open", "status: pr_open\n? [a, b]\n: v", 1)
    # "body_only": no status in the frontmatter, and a pr_open line in the body
    return text.replace("status: pr_open\n", "", 1) + "\nstatus: pr_open\n"


def _malformed_parked_row(home: Path, how: str) -> tuple[Path, dict[Path, bytes | None]]:
    parked = _write_task(home, "active", "parked-row")
    _write_task(home, "active", "next-row")
    assert _claim(home, "parked-row").returncode == 0
    _set_status(parked, "claimed", "pr_open")
    parked.write_text(_malform(parked.read_text(encoding="utf-8"), how), encoding="utf-8")
    return parked, _bytes_of(_role_sidecars(home)["marker"])


@pytest.mark.parametrize("how", _MALFORMED)
def test_the_lease_check_reads_a_malformed_note_as_holding_the_slot(
    tmp_path: Path, how: str
) -> None:
    # codex on #4826 rounds 3-4, and the seat's round-5 ruling (sweep the class): every read
    # must parse and see each key once. The lease loop used a whole-file grep, so a body-only
    # status or the last of duplicate keys could free the slot.
    home = tmp_path / "home"
    _parked, markers = _malformed_parked_row(home, how)

    held = _claim(home, "next-row")

    assert held.returncode == 7, held.stderr
    assert "already has active task 'parked-row' (status: unreadable)" in held.stderr
    assert "repair that row's frontmatter by hand" in held.stderr  # codex on #4826 round 6
    assert _bytes_of(_role_sidecars(home)["marker"]) == markers
    assert _lineage_shapes(home, "parked-row") == []


@pytest.mark.parametrize("how", _MALFORMED)
def test_an_expired_lease_on_a_malformed_note_still_holds(tmp_path: Path, how: str) -> None:
    home = tmp_path / "home"
    _parked, markers = _malformed_parked_row(home, how)
    _expire(home)

    held = _claim(home, "next-row")

    assert held.returncode == 7, held.stderr
    assert "expired claim" in held.stderr
    assert _lineage_shapes(home, "parked-row") == []


@pytest.mark.parametrize("how", _MALFORMED)
def test_neither_release_path_releases_a_malformed_note(tmp_path: Path, how: str) -> None:
    # The Python paths, exercised directly: the lease check now blocks first end to end.
    from shared.sdlc_claim import release_pipeline_held_residue

    home = tmp_path / "home"
    _parked, markers = _malformed_parked_row(home, how)
    roots = default_claim_publication_roots(home=home)

    assert (
        release_pipeline_held_residue(
            vault_root=_task_root(home),
            cache_dir=Path(roots.claim_cache_dir),
            transaction_root=Path(roots.claim_transaction_root),
            lock_root=Path(roots.claim_lock_root),
            role="cx-test",
            current_task_id="next-row",
            observed_at="20260927T172000Z",
        )
        == []
    )
    explicit = _release(home, "parked-row")

    assert explicit.returncode == 8
    assert "claim_residue_live_marker" in explicit.stderr
    assert _bytes_of(_role_sidecars(home)["marker"]) == markers
    assert _lineage_shapes(home, "parked-row") == []


@pytest.mark.parametrize(
    ("front", "expected"),
    [
        ("status: pr_open", "pr_open"),
        ("status: claimed\nstatus: pr_open", "unreadable"),  # PyYAML would keep the last
        ("broken: [", "unreadable"),
        ("assigned_to: cx-test", "unreadable"),  # the body's status line never counts
        ("assigned_to: other\nassigned_to: cx-test\nstatus: pr_open", "unreadable"),  # any dup
        ("status: pr_open\npr: 4999\npr: null", "unreadable"),
        ('status: pr_open\n"status": claimed', "unreadable"),  # one key, two spellings
        ('"status": pr_open', "unreadable"),  # not plainly spelled, so not rewritable
        ('status: pr_open\npr: 4999\n"pr": null', "unreadable"),
        ('status: pr_open\nbranch: feat/started\n"branch": null', "unreadable"),
        ('status: pr_open\nroute: {a: 1, "a": 2}', "unreadable"),  # flow style, nested
        ("status: pr_open\nroute: {a: 1, b: 2}", "pr_open"),  # a flow mapping as such is fine
        ("status: pr_open\n? [a, b]\n: v", "unreadable"),  # an unhashable key holds, no traceback
        ("status: pr_open\nroute: {[a]: 1}", "unreadable"),  # the same, flow style and nested
        ("status: pr_open\nroute:\n  ? {x: 1}\n  : 2", "unreadable"),  # a mapping as a key
    ],
)
def test_a_release_reads_status_only_from_release_grade_frontmatter(
    tmp_path: Path, front: str, expected: str
) -> None:
    from shared.sdlc_claim import _task_status_for_any_state

    root = tmp_path / "tasks"
    (root / "active").mkdir(parents=True)
    (root / "active" / "row.md").write_text(
        f"---\ntask_id: row\n{front}\n---\n\nstatus: pr_open\n", encoding="utf-8"
    )

    assert _task_status_for_any_state(root, "row") == expected


@pytest.mark.parametrize("block", ["? [a, b]\n: v", "route: {[a]: 1}", "route:\n  ? {x: 1}\n  : 2"])
def test_the_unique_key_loader_refuses_an_unhashable_key_as_yaml(block: str) -> None:
    # glm on #4826 round 7: `key in mapping` raised TypeError, which is not a YAMLError, so a
    # release read would traceback instead of holding. The plain parse that runs first also
    # refuses these notes (the cases above), so this pins the loader on its own.
    import yaml

    from shared.sdlc_claim import _UniqueKeyLoader

    with pytest.raises(yaml.YAMLError, match="unhashable"):
        yaml.load(block, Loader=_UniqueKeyLoader)  # noqa: S506 - a SafeLoader subclass


def test_release_pipeline_held_residue_directly(tmp_path: Path) -> None:
    # gemini on #4826 round 3 read this function as uncalled; cc-claim calls it before publishing
    # (the E2E tests above). This exercises it directly as well.
    from shared.sdlc_claim import release_pipeline_held_residue

    home = tmp_path / "home"
    parked = _write_task(home, "active", "parked-row")
    assert _claim(home, "parked-row").returncode == 0
    roots = default_claim_publication_roots(home=home)
    kwargs = {
        "vault_root": _task_root(home),
        "cache_dir": Path(roots.claim_cache_dir),
        "transaction_root": Path(roots.claim_transaction_root),
        "lock_root": Path(roots.claim_lock_root),
        "role": "cx-test",
        "current_task_id": "next-row",
        "observed_at": "20260927T170000Z",
    }
    assert release_pipeline_held_residue(**kwargs) == []  # worker-held: left alone
    assert _role_sidecars(home)["marker"][0].exists()
    _set_status(parked, "claimed", "pr_open")

    (released,) = release_pipeline_held_residue(**kwargs)

    assert released.shape == "pipeline_held"
    assert not _role_sidecars(home)["marker"][0].exists()
    assert release_pipeline_held_residue(**{**kwargs, "observed_at": "20260927T170100Z"}) == []


def test_resuming_a_pipeline_held_row_still_needs_a_free_slot(tmp_path: Path) -> None:
    home = tmp_path / "home"
    parked = _write_task(home, "active", "parked-row")
    _write_task(home, "active", "next-row")
    assert _claim(home, "parked-row").returncode == 0
    _set_status(parked, "claimed", "pr_open")
    assert _claim(home, "next-row").returncode == 0
    before = parked.read_bytes()

    resumed = _claim(home, "parked-row")

    assert resumed.returncode == 7
    assert "already has active task 'next-row'" in resumed.stderr
    assert parked.read_bytes() == before


def test_a_worker_held_row_still_holds_the_slot(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "active", "working-row")
    _write_task(home, "active", "next-row")
    assert _claim(home, "working-row").returncode == 0

    refused = _claim(home, "next-row")

    assert refused.returncode == 7
    assert "already has active task 'working-row'" in refused.stderr


def test_the_lease_checks_release_vocabulary_is_the_ssot() -> None:
    from shared.sdlc_lifecycle import TASK_ROLE_RELEASING_STATUSES

    source = SCRIPT.read_text(encoding="utf-8")
    body = source.split("_cc_role_release_status() {", 1)[1].split("\n}", 1)[0]
    listed = {
        status
        for line in body.splitlines()
        if ")" in line and not line.strip().startswith("#")
        for status in line.split(")", 1)[0].strip().split("|")
        if status
    }
    assert listed == set(TASK_ROLE_RELEASING_STATUSES), (
        "scripts/cc-claim _cc_role_release_status must list exactly "
        "shared.sdlc_lifecycle.TASK_ROLE_RELEASING_STATUSES; missing "
        f"{sorted(set(TASK_ROLE_RELEASING_STATUSES) - listed)}, extra "
        f"{sorted(listed - set(TASK_ROLE_RELEASING_STATUSES))}"
    )


def _expire(home: Path, *, hours: int = 7) -> None:
    aged = time.time() - hours * 3600
    for paths in _role_sidecars(home).values():
        for path in paths:
            if path.exists():
                os.utime(path, (aged, aged))


def test_an_expired_lease_on_a_pipeline_held_row_still_frees_the_slot(tmp_path: Path) -> None:
    # #4826 round 2 (codex): the lease's expiry was checked before the row's status, so past the
    # 6 h TTL, which is when pipeline-held rows sit, the manual stale-lease HOLD came back.
    home = tmp_path / "home"
    parked = _write_task(home, "active", "parked-row")
    _write_task(home, "active", "next-row")
    assert _claim(home, "parked-row").returncode == 0
    _set_status(parked, "claimed", "pr_open")
    _expire(home)

    taken = _claim(home, "next-row")

    assert taken.returncode == 0, taken.stderr
    assert _lineage_shapes(home, "parked-row") == ["pipeline_held"]


def test_an_expired_lease_on_a_worker_held_row_still_holds(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "active", "working-row")
    _write_task(home, "active", "next-row")
    assert _claim(home, "working-row").returncode == 0
    _expire(home)

    refused = _claim(home, "next-row")

    assert refused.returncode == 7
    assert "expired claim" in refused.stderr
