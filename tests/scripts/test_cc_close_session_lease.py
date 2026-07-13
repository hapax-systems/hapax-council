"""cc-close must clear the session-keyed lease, not just the legacy one.

cc-claim (reform Phase 1, cluster 6) writes TWO claim files for a session:
the legacy ``cc-active-task-<role>`` and the session-keyed
``cc-active-task-<role>-<session_id>`` (agent-role.sh ``hapax_session_id``).
cc-close historically removed only the legacy file, leaking the session-keyed
lease until its 6h TTL — and the gate reads the session-keyed file FIRST, so it
kept seeing the just-closed task. Regression coverage for reform finding
#12/#13: cc-close must clear BOTH lease forms (the current session's only, and
only when the file still names the task being closed).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

from shared.sdlc_task_store import ClaimDispatchBinding, write_claim_dispatch_binding

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-close"

# Identity env that agent-role.sh consults to resolve role / session id. The
# session running pytest sets several of these (HAPAX_AGENT_NAME, CLAUDE_ROLE,
# CLAUDE_CODE_SESSION_ID, ...); stripping them keeps the subprocess role/session
# deterministic instead of leaking the harness lane's identity into the script.
_IDENTITY_ENV = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_INTERFACE",
    "HAPAX_SESSION_ID",
    "CLAUDE_ROLE",
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_THREAD_NAME",
    "CODEX_SESSION_NAME",
    "CODEX_SESSION",
    "CODEX_ROLE",
    "CODEX_HOME",
)


def _vault(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def _write_task(vault_root: Path, task_id: str, *, status: str = "in_progress") -> Path:
    path = vault_root / "active" / f"{task_id}.md"
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: {status}
            assigned_to: eta
            completed_at:
            updated_at:
            pr:
            ---

            # {task_id}

            ## Session log
            """
        ),
        encoding="utf-8",
    )
    return path


def _cache(home: Path) -> Path:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _run_close(
    home: Path,
    task_id: str,
    *,
    role: str,
    session_id: str | None,
    platform: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = role
    env["HAPAX_CC_HYGIENE_OFF"] = "1"
    if platform is not None:
        env["HAPAX_AGENT_INTERFACE"] = platform
    if session_id is not None:
        env["HAPAX_SESSION_ID"] = session_id
    if extra_env:
        env.update(extra_env)
    # --status withdrawn isolates the claim-clearing block (the done-only gates —
    # rapid-close, AC checklist, PR-merge — are skipped; the claim clear runs for
    # every terminal status).
    return subprocess.run(
        ["bash", str(SCRIPT), task_id, "--status", "withdrawn"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cc_close_clears_both_legacy_and_session_keyed_lease(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    legacy = cache / "cc-active-task-eta"
    session = cache / "cc-active-task-eta-session-abc123"
    legacy_sidecar = cache / "cc-claim-epoch-eta"
    session_sidecar = cache / "cc-claim-epoch-eta-session-abc123"
    legacy_binding = cache / "cc-claim-dispatch-eta.json"
    session_binding = cache / "cc-claim-dispatch-eta-session-abc123.json"
    legacy.write_text("foo\n", encoding="utf-8")
    session.write_text("foo\n", encoding="utf-8")
    legacy_sidecar.write_text("1780000000 foo\n", encoding="utf-8")
    session_sidecar.write_text("1780000000 foo\n", encoding="utf-8")
    binding = ClaimDispatchBinding.create(
        task_id="foo",
        lane="eta",
        session_id="session-abc123",
        claim_epoch=1780000000,
        dispatch_message_id="dispatch-message",
        platform="claude",
        mode="headless",
        profile="full",
        authority_case="CASE-TEST",
        binding_hash="1" * 64,
        coord_dispatch_idempotency_key="dispatch-key",
    )
    write_claim_dispatch_binding(cache, "eta", binding)
    write_claim_dispatch_binding(cache, "eta-session-abc123", binding)

    result = _run_close(home, "foo", role="eta", session_id="session-abc123")

    assert result.returncode == 0, result.stderr
    assert not legacy.exists(), f"legacy lease not cleared\nstdout={result.stdout}"
    assert not legacy_sidecar.exists(), f"legacy epoch sidecar leaked\nstdout={result.stdout}"
    assert not session.exists(), (
        f"session-keyed lease leaked (finding #12/#13)\nstdout={result.stdout}"
    )
    assert not session_sidecar.exists(), f"session epoch sidecar leaked\nstdout={result.stdout}"
    assert not legacy_binding.exists(), f"legacy dispatch sidecar leaked\nstdout={result.stdout}"
    assert not session_binding.exists(), f"session dispatch sidecar leaked\nstdout={result.stdout}"


def test_cc_close_refuses_session_projection_naming_a_different_task(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    session = cache / "cc-active-task-eta-session-abc123"
    sidecar = cache / "cc-claim-epoch-eta-session-abc123"
    binding = cache / "cc-claim-dispatch-eta-session-abc123.json"
    session.write_text("other-task\n", encoding="utf-8")
    sidecar.write_text("1780000000 other-task\n", encoding="utf-8")
    binding.write_text("{}\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id="session-abc123")

    assert result.returncode == 2
    assert "close_slot_projection_identity_mismatch" in result.stderr
    assert session.exists(), "a session lease for different work must not be clobbered"
    assert sidecar.exists(), "a sidecar for different work must not be clobbered"
    assert binding.exists(), "a dispatch sidecar for different work must not be clobbered"
    assert session.read_text(encoding="utf-8").strip() == "other-task"
    assert (vault / "active" / "foo.md").is_file()


def test_cc_close_without_session_id_still_clears_legacy(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "foo")
    cache = _cache(home)
    legacy = cache / "cc-active-task-eta"
    epoch = cache / "cc-claim-epoch-eta"
    legacy.write_text("foo\n", encoding="utf-8")
    epoch.write_text("1780000000 foo\n", encoding="utf-8")

    result = _run_close(home, "foo", role="eta", session_id=None)

    assert result.returncode == 0, result.stderr
    assert not legacy.exists(), f"legacy lease not cleared\nstdout={result.stdout}"
    assert not epoch.exists(), f"legacy epoch not cleared\nstdout={result.stdout}"


def test_cc_close_refuses_invalid_session_instead_of_legacy_downgrade(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    note = _write_task(vault, "foo")

    result = _run_close(home, "foo", role="eta", session_id="1234")

    assert result.returncode == 3
    assert "refusing legacy-role downgrade" in result.stderr
    assert note.is_file()
    assert not (vault / "closed" / "foo.md").exists()


def test_cc_close_refuses_dispatch_bound_task_from_wrong_session(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    note = _write_task(vault, "foo")
    cache = _cache(home)
    binding = ClaimDispatchBinding.create(
        task_id="foo",
        lane="eta",
        session_id="owner-session",
        claim_epoch=1780000000,
        dispatch_message_id="dispatch-message",
        platform="claude",
        mode="headless",
        profile="full",
        authority_case="CASE-TEST",
        binding_hash="1" * 64,
        coord_dispatch_idempotency_key="dispatch-key",
    )
    for key in ("eta", "eta-owner-session"):
        (cache / f"cc-active-task-{key}").write_text("foo\n", encoding="utf-8")
        (cache / f"cc-claim-epoch-{key}").write_text(
            "1780000000 foo\n",
            encoding="utf-8",
        )
        write_claim_dispatch_binding(cache, key, binding)

    result = _run_close(home, "foo", role="eta", session_id="other-session")

    assert result.returncode == 2
    assert "close_slot_owned_by_other_session" in result.stderr
    assert note.is_file()
    assert not (vault / "closed" / "foo.md").exists()


def test_cc_close_refuses_caller_who_does_not_own_task(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    note = _write_task(vault, "foo")
    cache = _cache(home)
    owner_claim = cache / "cc-active-task-eta"
    owner_claim.write_text("foo\n", encoding="utf-8")

    result = _run_close(home, "foo", role="intruder", session_id=None)

    assert result.returncode == 2
    assert "close_task_owner_mismatch" in result.stderr
    assert note.is_file()
    assert not (vault / "closed" / "foo.md").exists()
    assert owner_claim.read_text(encoding="utf-8") == "foo\n"


def test_cc_close_honors_platform_qualified_owner(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    note = _write_task(vault, "foo")
    note.write_text(
        note.read_text(encoding="utf-8").replace("assigned_to: eta", "assigned_to: codex/cx-red"),
        encoding="utf-8",
    )

    result = _run_close(home, "foo", role="cx-red", session_id=None, platform="codex")

    assert result.returncode == 0, result.stderr
    assert (vault / "closed" / "foo.md").is_file()


def test_cc_close_rejects_wrong_platform_for_qualified_owner(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    note = _write_task(vault, "foo")
    note.write_text(
        note.read_text(encoding="utf-8").replace("assigned_to: eta", "assigned_to: claude/eta"),
        encoding="utf-8",
    )

    result = _run_close(home, "foo", role="eta", session_id=None, platform="codex")

    assert result.returncode == 2
    assert "close_task_owner_mismatch" in result.stderr
    assert note.is_file()


def test_cc_close_holds_when_owner_is_replaced_before_hash_capture(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    note = _write_task(vault, "foo")
    cache = _cache(home)
    claim = cache / "cc-active-task-eta"
    claim.write_text("foo\n", encoding="utf-8")
    (cache / "cc-claim-epoch-eta").write_text("1780000000 foo\n", encoding="utf-8")

    real_sha256sum = shutil.which("sha256sum")
    real_python = shutil.which("python3")
    assert real_sha256sum is not None
    assert real_python is not None
    attack_bin = tmp_path / "attack-bin"
    attack_bin.mkdir()
    attack_marker = tmp_path / "owner-replaced"
    wrapper = attack_bin / "sha256sum"
    wrapper.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "${HAPAX_RACE_NOTE:-}" && ! -e "$HAPAX_RACE_MARKER" ]]; then
  : >"$HAPAX_RACE_MARKER"
  "$HAPAX_RACE_PYTHON" - "$1" <<'PYEOF'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
path.write_text(
    text.replace("assigned_to: eta", "assigned_to: codex/eta", 1),
    encoding="utf-8",
)
PYEOF
fi
exec "$HAPAX_REAL_SHA256SUM" "$@"
""",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    result = _run_close(
        home,
        "foo",
        role="eta",
        session_id=None,
        platform="claude",
        extra_env={
            "HAPAX_RACE_MARKER": str(attack_marker),
            "HAPAX_RACE_NOTE": str(note),
            "HAPAX_RACE_PYTHON": real_python,
            "HAPAX_REAL_SHA256SUM": real_sha256sum,
            "PATH": f"{attack_bin}:{os.environ['PATH']}",
        },
    )

    assert attack_marker.is_file(), (
        "the adversarial replacement seam did not execute\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert result.returncode == 9
    assert "close_task_owner_mismatch: HOLD" in result.stderr
    assert note.is_file()
    assert "assigned_to: codex/eta" in note.read_text(encoding="utf-8")
    assert not (vault / "closed" / "foo.md").exists()
    assert claim.read_text(encoding="utf-8") == "foo\n"
