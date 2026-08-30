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
    argv.append(task_id)
    return subprocess.run(
        argv,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


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


# ----------------------------------------------------------------- role release, end to end
#
# Review finding (PR #4611, codex-1/codex-2 major): the role-release tests parsed the shell
# case and asserted set membership without ever running cc-claim against existing ready-state
# sidecars. They stayed green exactly where the downstream canonical-publication gate rejects.
# These exercise the real path: claim A, move A to a releasing status, claim B.


def _release_and_claim_next(
    home: Path, *, first: str, second: str, released_status: str
) -> subprocess.CompletedProcess:
    """Claim `first`, transition it to `released_status`, then claim `second`."""
    first_note = _write_task(home, "active", first)
    _write_task(home, "active", second)

    initial = _claim(home, first)
    assert initial.returncode == 0, f"setup claim failed: {initial.stderr}"

    text = first_note.read_text(encoding="utf-8")
    assert "status: claimed" in text, text[:200]
    first_note.write_text(
        text.replace("status: claimed", f"status: {released_status}"), encoding="utf-8"
    )

    return _claim(home, second)


@pytest.mark.parametrize(
    "released_status",
    ["pr_open", "merge_queue", "ready_for_review", "merged_awaiting_runtime_witness", "backlog"],
)
def test_released_status_frees_the_lane_for_a_new_claim(
    tmp_path: Path, released_status: str
) -> None:
    """The predicate the whole change exists for: finished work must not hold a lane.

    Asserts the SECOND task is actually claimed — not merely that the bash role-cap check was
    bypassed. An earlier revision passed that check and still failed downstream, and reporting
    the partial pass as success is precisely what this test exists to prevent.
    """
    home = tmp_path / "home"
    result = _release_and_claim_next(
        home, first="task-a", second="task-b", released_status=released_status
    )

    assert result.returncode == 0, (
        f"a lane holding a {released_status} task must be free to claim new work.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    second_note = _task_root(home) / "active" / "task-b.md"
    assert "status: claimed" in second_note.read_text(encoding="utf-8")


@pytest.mark.parametrize("held_status", ["claimed", "in_progress", "blocked"])
def test_worker_held_status_still_blocks_a_new_claim(tmp_path: Path, held_status: str) -> None:
    """The cap must still bind while the lane is genuinely engaged."""
    home = tmp_path / "home"
    result = _release_and_claim_next(
        home, first="task-a", second="task-b", released_status=held_status
    )

    assert result.returncode != 0, "a lane actually working a task must not take another"
    assert "already has active task" in result.stderr


def test_unknown_status_still_blocks_a_new_claim(tmp_path: Path) -> None:
    """Fails closed: an unrecognised status holds the lane rather than releasing it."""
    home = tmp_path / "home"
    result = _release_and_claim_next(
        home, first="task-a", second="task-b", released_status="not_a_real_status"
    )

    assert result.returncode != 0
    assert "already has active task" in result.stderr


# ------------------------------------------------------- aged leases, and where residue goes
#
# Review finding (PR #4611, codex-1 critical + major): the tests above claim A and immediately
# claim B, so the lease is always fresh. Lease expiry is evaluated in the same loop, and an
# earlier revision evaluated it FIRST — so every lease older than the six-hour TTL took the
# canonical HOLD path and the release case was unreachable for exactly the aged, pre-existing
# sidecars that most need it. The suite stayed green on that critical because it never aged a
# lease. These do.


def _age_leases(home: Path, *, seconds: int) -> None:
    """Backdate every claim sidecar so the next cc-claim sees an expired lease."""
    cache_dir = home / ".cache" / "hapax"
    stale = time.time() - seconds
    aged = 0
    for sidecar in cache_dir.glob("cc-active-task-*"):
        os.utime(sidecar, (stale, stale))
        aged += 1
    assert aged, f"no claim sidecars to age under {cache_dir} — the setup claim did not publish"


@pytest.mark.parametrize("released_status", ["pr_open", "done", "merged_awaiting_runtime_witness"])
def test_expired_lease_on_a_released_task_still_frees_the_lane(
    tmp_path: Path, released_status: str
) -> None:
    """Release is a property of the TASK, not of the lease's age.

    A task that is finished or pipeline-held is released whether or not its lease also
    aged out. Ageing the lease past the TTL must not resurrect the role cap.
    """
    home = tmp_path / "home"
    first_note = _write_task(home, "active", "task-a")
    _write_task(home, "active", "task-b")

    initial = _claim(home, "task-a")
    assert initial.returncode == 0, f"setup claim failed: {initial.stderr}"
    first_note.write_text(
        first_note.read_text(encoding="utf-8").replace(
            "status: claimed", f"status: {released_status}"
        ),
        encoding="utf-8",
    )
    _age_leases(home, seconds=21600 * 2)

    result = _claim(home, "task-b")

    assert result.returncode == 0, (
        f"an AGED lease on a {released_status} task must still free the lane.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "status: claimed" in (_task_root(home) / "active" / "task-b.md").read_text(
        encoding="utf-8"
    )


def test_expired_lease_on_a_worker_held_task_still_holds(tmp_path: Path) -> None:
    """The converse, and the reason this is not a blanket "expired means free".

    Failure paths narrow; they do not widen. An aged lease on genuinely engaged work must
    still take the canonical stale-lease HOLD, which requires an exact operator release.
    """
    home = tmp_path / "home"
    _write_task(home, "active", "task-a")
    _write_task(home, "active", "task-b")

    initial = _claim(home, "task-a")
    assert initial.returncode == 0, f"setup claim failed: {initial.stderr}"
    _age_leases(home, seconds=21600 * 2)

    result = _claim(home, "task-b")

    assert result.returncode != 0, "an aged lease on in-progress work must not self-release"
    assert "requires exact stale-lease release" in result.stderr


def test_a_closed_task_releases_the_lane(tmp_path: Path) -> None:
    """All three review families, unanimously: the release lookup only searched `active/`.

    A task that reaches a terminal status is usually MOVED to `closed/`, so an active/-only
    lookup finds no note for exactly the tasks most certain to have released the role — it
    falls through to the expiry HOLD and a closed task holds a lane forever. The Python side
    already searched both directories; the bash side had silently diverged from it.
    """
    home = tmp_path / "home"
    first_note = _write_task(home, "active", "task-a")
    _write_task(home, "active", "task-b")

    assert _claim(home, "task-a").returncode == 0

    closed_dir = _task_root(home) / "closed"
    closed_dir.mkdir(parents=True, exist_ok=True)
    first_note.write_text(
        first_note.read_text(encoding="utf-8").replace("status: claimed", "status: done"),
        encoding="utf-8",
    )
    first_note.rename(closed_dir / first_note.name)
    _age_leases(home, seconds=21600 * 2)

    result = _claim(home, "task-b")

    assert result.returncode == 0, (
        f"a task that was closed and moved out of active/ must free its lane.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_released_task_residue_is_archived_with_a_receipt(tmp_path: Path) -> None:
    """Retirement archives into task lineage; it does not `rm -f`.

    An earlier revision deleted the three sidecars from the bash loop with
    ``rm -f ... 2>/dev/null || true`` — unlocked, unreceipted, and reporting success after a
    failed delete. Removal now happens inside the Gate-0B publication section, so this pins
    both halves: the cache is clear of the prior key, AND the release is reconstructable.
    """
    home = tmp_path / "home"
    result = _release_and_claim_next(
        home, first="task-a", second="task-b", released_status="pr_open"
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    lineage = _task_root(home) / "_lineage" / "task-a"
    residue_dirs = list(lineage.glob("released-claim-residue-*"))
    assert residue_dirs, (
        f"released-task residue must be archived under {lineage}, not deleted.\n"
        f"stderr: {result.stderr}"
    )

    receipt = (residue_dirs[0] / "README.md").read_text(encoding="utf-8")
    assert "task_id: task-a" in receipt
    assert "claimed_next: task-b" in receipt
    assert "cc-active-task-" in receipt

    archived_names = {path.name for path in residue_dirs[0].iterdir()}
    assert any(name.startswith("cc-active-task-") for name in archived_names), archived_names


def test_unreadable_claim_sidecar_holds_instead_of_being_swept(tmp_path: Path) -> None:
    """Fails closed on residue it cannot account for.

    A sidecar that cannot be read is not evidence that the lane is free. The earlier
    ``rm -f`` swallowed exactly this case; archival must HOLD instead.
    """
    home = tmp_path / "home"
    first_note = _write_task(home, "active", "task-a")
    _write_task(home, "active", "task-b")

    initial = _claim(home, "task-a")
    assert initial.returncode == 0, f"setup claim failed: {initial.stderr}"
    first_note.write_text(
        first_note.read_text(encoding="utf-8").replace("status: claimed", "status: pr_open"),
        encoding="utf-8",
    )

    cache_dir = home / ".cache" / "hapax"
    sidecars = sorted(cache_dir.glob("cc-active-task-*"))
    assert sidecars, "setup claim published no sidecar"
    sidecars[0].write_bytes(b"\xff\xfe\x00not-utf-8")

    result = _claim(home, "task-b")

    assert result.returncode != 0, (
        "an unreadable claim sidecar must HOLD, not be swept away.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "unreadable claim sidecar" in result.stderr

    # The load-bearing assertion, and the reason the two above are not enough. Both of them
    # stay green if the unreadable sidecar is merely SKIPPED: the message still prints, and
    # the claim still fails later with claim_cache_missing — the same exit code, for an
    # unrelated reason. What separates fail-closed from fail-open is that a HOLD archives
    # NOTHING. Skipping lets the sibling key's residue be swept while the malformed one is
    # left behind, which is exactly the partial-sweep hazard this must refuse.
    lineage = _task_root(home) / "_lineage"
    archived = list(lineage.glob("*/released-claim-residue-*")) if lineage.exists() else []
    assert archived == [], (
        "a HOLD on unreadable residue must archive nothing at all; "
        f"these were swept anyway: {archived}"
    )
