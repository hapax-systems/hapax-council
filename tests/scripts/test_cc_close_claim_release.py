"""cc-close must release the claim of the session that is actually claiming it.

The claim plane has three participants and one fact — *which role holds this
claim*:

* the WRITER, ``cc-claim``, which binds role via ``hapax_effective_role``
* the READER, ``cc-task-gate.impl.sh``, which binds role via ``hapax_effective_role``
* the RELEASER, ``cc-close``, which bound role via ``hapax_agent_identity``

Those two resolvers agree for every session that carries an explicit role, and
disagree for exactly one case: a session with a session id but no role signal.
``hapax_agent_identity`` returns EMPTY there; ``hapax_effective_role`` returns
the literal ``roleless``. ``cc-close`` guards its whole claim-release block with
``[[ -n "$role" ]]``, so with the divergent resolver the block was skipped, the
lease survived the close, and the gate — resolving through the other function —
found a lease naming a task that had just moved to ``closed/`` and blocked every
subsequent mutation with ``claimed task not found in vault``.

Measured twice on 2026-08-21, both times immediately after a *clean* close: a
session that finished its work correctly ended up worse off than one that
abandoned it, and both recoveries needed the operator.

``tests/scripts/test_cc_close_session_lease.py`` already pins the release LOOP
(reform finding #12/#13) but sets ``HAPAX_AGENT_ROLE=eta`` in every case, so
``$role`` is never empty and the guard above the loop is never exercised. The
repair was applied at the loop; the failure moved one level up to the binding.
These tests drive the roleless case end to end instead: real ``cc-close``, real
gate, real vault layout.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CC_CLOSE = REPO_ROOT / "scripts" / "cc-close"
CC_CLAIM = REPO_ROOT / "scripts" / "cc-claim"
GATE = REPO_ROOT / "hooks" / "scripts" / "cc-task-gate.impl.sh"

TASK_ID = "roleless-close-cycle"
# Deliberately NOT a prefix extension of TASK_ID: the vault lookup globs
# active/<task_id>-*.md, so "roleless-close-cycle-next" would collide with
# "roleless-close-cycle" (the class pinned by test_cc_close_prefix_collision.py).
NEXT_TASK_ID = "roleless-recovery-work"
SESSION_ID = "sess-roleless-e2e"
STRAND_MESSAGE = "not found in vault"
# The gate's post-close state for a session that closed correctly: no claim held, and
# the role still resolves. Recoverable — the session can claim again — and distinct
# from the strand, where a lease points at a task that no longer exists in active/.
RECOVERABLE_DENIAL = "no claimed task for role 'roleless'"
# cc-claim's HOLD exit. The REASON CODE varies with which residue survived and with
# what the vault holds — observed forms include claim_task_mismatch and
# claim_dispatch_binding_missing. The latter is what a partially-cleared close leaves,
# and what was live in the operator's own HOME; it names a MISSING dispatch binding
# while the trigger is a LEFTOVER sidecar, pointing away from the cause. The reason
# code is therefore NOT asserted anywhere here — only the HOLD, which is invariant and
# is what actually strands a session.
CLAIM_HOLD_RC = 8

# Every signal agent-role.sh consults to resolve an explicit role. The session
# running pytest sets several of these; stripping them is what makes the
# subprocess genuinely roleless rather than inheriting the harness lane.
_ROLE_SIGNAL_ENV = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_INTERFACE",
    "HAPAX_WORKTREE_ROLE",
    "HAPAX_AGENT_SLOT",
    "CLAUDE_ROLE",
    "CODEX_THREAD_NAME",
    "CODEX_SESSION_NAME",
    "CODEX_SESSION",
    "CODEX_ROLE",
    "CODEX_HOME",
    # SESSION-ID sources, not role signals — but hapax_effective_role returns
    # "roleless" whenever any of them is set, so leaving one in place would silently
    # give the "no session id" tests a session id and stop them exercising the branch
    # they name. CODEX_THREAD_ID was missing and would have leaked through on a
    # Codex-run CI, where these tests would have passed without testing anything.
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
)

# A PATH without ~/.local/bin: `hapax-whoami` is an identity source of last
# resort inside hapax_agent_identity, and letting the operator's real one
# answer would make "roleless" depend on the developer's window manager.
_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

# Captured before any PATH narrowing so a test that removes /usr/bin from PATH can
# still start a shell.
_BASH = shutil.which("bash") or "/bin/bash"


def _env(home: Path, *, session_id: str | None = SESSION_ID) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _ROLE_SIGNAL_ENV}
    env.pop("HAPAX_SESSION_ID", None)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    env["HOME"] = str(home)
    # Stub bin FIRST so the post-clear systemctl call can never reach live units.
    env["PATH"] = f"{home / 'stubbin'}:{_SYSTEM_PATH}"
    # XDG_RUNTIME_DIR into the sandbox so the `systemctl --user start
    # hapax-cc-hygiene.service` that follows a successful clear cannot reach the
    # operator's real session bus. A test must not start live units.
    env["XDG_RUNTIME_DIR"] = str(home / "run")
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    if session_id is not None:
        env["HAPAX_SESSION_ID"] = session_id
    return env


def _stub_bin(home: Path) -> Path:
    """A stub ``systemctl`` shadowing the real one.

    A successful claim release runs ``systemctl --user start
    hapax-cc-hygiene.service``. Redirecting XDG_RUNTIME_DIR made that fail rather
    than reach the operator's session bus, but nothing ASSERTED the isolation — the
    test's containment was an unverified side effect of an env var, which is the
    same "declared, not enforced" shape this row is about. The stub makes the call
    observable and makes it impossible for a test run to touch live units.
    """
    bin_dir = home / "stubbin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "systemctl"
    stub.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$HOME/systemctl-calls.log"\nexit 0\n',
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def _systemctl_calls(home: Path) -> list[str]:
    log = home / "systemctl-calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.is_file() else []


def _vault(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    (home / "run").mkdir(parents=True, exist_ok=True)
    _stub_bin(home)
    return root


def _write_task(vault_root: Path, scope_ref: str, task_id: str = TASK_ID) -> Path:
    """An authorized OFFERED task — claimable by the real cc-claim, and once claimed
    the shape the gate ACCEPTS, so the pre-close leg proves the gate permits rather
    than merely failing differently."""
    path = vault_root / "active" / f"{task_id}.md"
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
            priority: p2
            authority_case: CASE-SYSTEM-INTEGRITY-20260611
            parent_spec: 30-areas/hapax/synthesis-representation-without-enforcement-2026-08-20.md
            route_metadata_schema: 1
            stage: S6_IMPLEMENTING
            implementation_authorized: true
            source_mutation_authorized: true
            mutation_scope_refs:
              - {scope_ref}
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


def _run_claim(home: Path, task_id: str) -> subprocess.CompletedProcess[str]:
    """The REAL writer. The exit predicate calls for a claim->close cycle, and a
    hand-seeded lease would only prove cc-close can delete files this test wrote —
    not that it clears what cc-claim actually produces, in the forms cc-claim
    actually produces them.

    cc-claim issues a manual self-witnessed binding when no --dispatch-* flags are
    given, so a roleless session can claim in a clean HOME without dispatch
    machinery.
    """
    return subprocess.run(
        ["bash", str(CC_CLAIM), task_id],
        env=_env(home),
        cwd=str(home),
        text=True,
        capture_output=True,
        check=False,
    )


def _leases(home: Path) -> list[Path]:
    """Every lease artifact present, whatever form the writer chose."""
    cache = home / ".cache" / "hapax"
    if not cache.is_dir():
        return []
    return sorted(
        p for p in cache.iterdir() if p.name.startswith(("cc-active-task-", "cc-claim-epoch-"))
    )


def _run_close(
    home: Path,
    script: Path = CC_CLOSE,
    *,
    task_id: str = TASK_ID,
    status: str = "withdrawn",
) -> subprocess.CompletedProcess[str]:
    # withdrawn is the default because it isolates the claim-release block: the
    # done-only gates (rapid-close, AC checklist, PR-merge evidence) are skipped,
    # while the release runs for every terminal status. See
    # test_the_release_runs_for_every_terminal_status for the second witness.
    return subprocess.run(
        ["bash", str(script), task_id, "--status", status],
        env=_env(home),
        cwd=str(home),  # not a git repo: no path-inferred role (FM-1)
        text=True,
        capture_output=True,
        check=False,
    )


def _run_gate(home: Path, target: Path) -> subprocess.CompletedProcess[str]:
    """Drive the real gate the way Claude Code does: a PreToolUse JSON payload
    on stdin. Exit 2 is a block; the message is on stderr."""
    payload = json.dumps(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(target),
                "old_string": "a",
                "new_string": "b",
            },
        }
    )
    return subprocess.run(
        ["bash", str(GATE)],
        input=payload,
        env=_env(home),
        cwd=str(home),
        text=True,
        capture_output=True,
        check=False,
    )


def _divergent_cc_close(tmp_path: Path) -> Path:
    """A copy of the real cc-close with ONLY the resolver reverted to
    hapax_agent_identity — the mutation, encoded as a fixture so the causal link
    is pinned by the suite instead of by a one-off manual check.

    Layout is preserved (scripts/ beside hooks/) because cc-close resolves its
    helpers through $SCRIPT_DIR/../hooks/scripts.
    """
    root = tmp_path / "divergent"
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "hooks").symlink_to(REPO_ROOT / "hooks", target_is_directory=True)

    text = CC_CLOSE.read_text(encoding="utf-8")
    fixed = 'role="$(hapax_effective_role 2>/dev/null || true)"'
    reverted = 'role="$(hapax_agent_identity 2>/dev/null || true)"'
    assert text.count(fixed) == 1, (
        "cc-close no longer binds role through hapax_effective_role exactly once — "
        "this mutation fixture is stale and is no longer proving anything"
    )
    dest = root / "scripts" / "cc-close"
    dest.write_text(text.replace(fixed, reverted), encoding="utf-8")
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR)
    return dest


def test_a_roleless_session_resolves_to_roleless_not_empty(tmp_path: Path) -> None:
    """The precondition the whole cycle rests on, asserted rather than assumed:
    in this harness the two resolvers really do disagree."""
    home = tmp_path / "home"
    _vault(home)
    snippet = (
        'source "$AGENT_ROLE_PATH" >/dev/null 2>&1; '
        'printf "identity=[%s] effective=[%s]" '
        '"$(hapax_agent_identity 2>/dev/null || true)" '
        '"$(hapax_effective_role 2>/dev/null || true)"'
    )
    env = {**_env(home), "AGENT_ROLE_PATH": str(REPO_ROOT / "hooks/scripts/agent-role.sh")}
    result = subprocess.run(
        ["bash", "-c", snippet],
        env=env,
        cwd=str(home),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.stdout.strip() == "identity=[] effective=[roleless]", (
        f"harness is not exercising the roleless divergence: {result.stdout!r}"
    )


def test_roleless_close_clears_its_own_lease(tmp_path: Path) -> None:
    """(a) + (b): the close announces the session-keyed path it cleared, and
    every lease form — claim file and cc-claim-epoch sidecar, session-keyed and
    legacy — is gone afterwards."""
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, str(home / "scratch.txt"))

    claimed = _run_claim(home, TASK_ID)
    assert claimed.returncode == 0, (
        f"the real writer could not claim, so this proves nothing about what it "
        f"writes\nstdout={claimed.stdout}\nstderr={claimed.stderr}"
    )
    written = _leases(home)
    session_lease = home / ".cache" / "hapax" / f"cc-active-task-roleless-{SESSION_ID}"
    assert session_lease in written, (
        f"cc-claim did not write the session-keyed lease this test is about: {written}"
    )

    result = _run_close(home)

    assert result.returncode == 0, result.stderr
    assert "cleared claim file" in result.stdout, (
        f"close did not announce a claim release\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert str(session_lease) in result.stdout, (
        f"close cleared something, but not the session-keyed lease the gate reads "
        f"FIRST\nstdout={result.stdout}"
    )
    # Every artifact the real writer produced, not merely the ones this test knew
    # to look for — a leftover epoch sidecar is not cosmetic: it is what makes the
    # NEXT cc-claim HOLD (see the recovery test below).
    assert _leases(home) == [], (
        f"lease artifacts leaked past the close: {[p.name for p in _leases(home)]}"
    )
    # The hygiene kick is part of a successful release, and asserting it here also
    # proves the stub — not the operator's session bus — received it.
    assert any("hapax-cc-hygiene.service" in call for call in _systemctl_calls(home)), (
        f"expected the post-clear hygiene kick, saw: {_systemctl_calls(home)}"
    )


def test_gate_permits_before_the_close_and_is_not_stranded_after(tmp_path: Path) -> None:
    """(c), end to end and in both directions: with the claim held the gate
    PERMITS the in-scope mutation; once the task is closed the gate must not
    report the strand.

    After a correct close the session holds no claim, so a protected mutation is
    refused — but for the RECOVERABLE reason (no claim held, role still resolving),
    never because a lease points at a task that no longer exists in active/. Both
    the return code and that exact reason are asserted, so this leg cannot pass on
    an unrelated failure or on a reworded strand message.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    target = home / "scratch.txt"
    target.write_text("a\n", encoding="utf-8")
    _write_task(vault, str(target))
    _write_task(vault, str(target), NEXT_TASK_ID)

    assert _run_claim(home, TASK_ID).returncode == 0

    before = _run_gate(home, target)
    assert before.returncode == 0, (
        "gate refused an in-scope mutation while the claim was held — the "
        f"post-close leg would prove nothing\nstderr={before.stderr}"
    )

    closed = _run_close(home)
    assert closed.returncode == 0, closed.stderr

    after = _run_gate(home, target)
    # Assert the CONCRETE post-close outcome, not merely the absence of a string.
    # Absence alone accepted any denial at all — an unrelated earlier failure, or a
    # reworded strand message, would have left this leg green while the session was
    # just as stuck. (Raised independently by two review seats.)
    #
    # Measured post-close state: rc 2, "no claimed task for role 'roleless'". That is
    # the RECOVERABLE denial and the assertion is deliberately on that exact reason:
    # the session holds no claim, which is correct after a close, and the gate names
    # the role — proving both that the lease was cleared and that the gate still
    # resolves this session's identity rather than losing it.
    assert after.returncode == 2, (
        f"unexpected post-close gate outcome rc={after.returncode}; the recoverable "
        f"denial is what this asserts\nstderr={after.stderr}"
    )
    assert RECOVERABLE_DENIAL in after.stderr, (
        "gate did not report the recoverable no-claim state after the close — it "
        f"failed for some other reason, so this leg proves nothing\nstderr={after.stderr}"
    )
    assert STRAND_MESSAGE not in after.stderr, (
        "session is stranded behind its own closed task: the lease survived the "
        f"close and the gate still reads it\nstderr={after.stderr}"
    )

    # RECOVERY — the point of the whole row. "Not stranded" is only meaningful if
    # the session can actually resume, so claim the NEXT task with the real writer
    # and mutate again. Without this leg a gate that refused everything forever
    # would satisfy every assertion above.
    recovered = _run_claim(home, NEXT_TASK_ID)
    assert recovered.returncode == 0, (
        "session could not claim new work after a clean close — the strand is gone "
        f"but the deadlock is not\nstdout={recovered.stdout}\nstderr={recovered.stderr}"
    )
    resumed = _run_gate(home, target)
    assert resumed.returncode == 0, (
        "gate refused an in-scope mutation under a freshly claimed task: the "
        f"close->reclaim->mutate cycle does not close\nstderr={resumed.stderr}"
    )


def test_the_installed_symlink_entrypoint_releases_the_claim(tmp_path: Path) -> None:
    """cc-close is installed as ``~/.local/bin/cc-close`` -> the deployed worktree, and
    bash does NOT resolve symlinks for ``BASH_SOURCE``. Invoked that way, SCRIPT_DIR was
    the symlink's directory, ``agent-role.sh`` was never found, and NEITHER role resolver
    existed — so the claim-release block could not run no matter which one it named.

    Every other test here invokes cc-close by its real path, where the helper is
    adjacent and the bug is invisible. That is the same blindness this whole row is
    about: the suite exercised a path the operator does not use. This test drives the
    entrypoint as installed.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, str(home / "scratch.txt"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    installed = bin_dir / "cc-close"
    installed.symlink_to(CC_CLOSE)

    assert _run_claim(home, TASK_ID).returncode == 0

    result = _run_close(home, installed)

    assert result.returncode == 0, (
        f"cc-close failed when invoked through its installed symlink\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "cleared claim file" in result.stdout, (
        "the symlinked entrypoint did not release the claim — SCRIPT_DIR is resolving "
        f"to the symlink's directory again\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert _leases(home) == [], (
        f"lease artifacts leaked through the installed entrypoint: "
        f"{[p.name for p in _leases(home)]}"
    )


def test_a_broken_install_refuses_instead_of_releasing_nothing(tmp_path: Path) -> None:
    """With the resolver library absent, cc-close must REFUSE. The prior behaviour —
    carry on with env-only resolution — is exactly how the lease leaked: a close that
    cannot resolve its own role releases nothing and reports success, stranding the
    session behind the task it just closed. Failure paths narrow; they do not widen.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, str(home / "scratch.txt"))
    assert _run_claim(home, TASK_ID).returncode == 0

    # A checkout with the script but no hooks/scripts beside it.
    broken = tmp_path / "broken" / "scripts"
    broken.mkdir(parents=True)
    orphan = broken / "cc-close"
    orphan.write_text(CC_CLOSE.read_text(encoding="utf-8"), encoding="utf-8")

    result = _run_close(home, orphan)

    assert result.returncode != 0, (
        "cc-close completed without its role resolver — it cannot have released the "
        f"lease, so reporting success is the silent-strand behaviour\nstdout={result.stdout}"
    )
    assert "agent-role.sh not found" in result.stderr, (
        f"refused, but not for the reason under test\nstderr={result.stderr}"
    )
    assert _leases(home) != [], (
        "the lease should still be held after a refused close — the session keeps its "
        "claim rather than losing it to a close that could not complete"
    )


def test_when_readlink_cannot_resolve_the_entrypoint_refuses(tmp_path: Path) -> None:
    """The readlink fallback's other branch: ``readlink -f`` failing, so ``_cc_self``
    keeps the unresolved symlink path and the helper is not found. The script must
    REFUSE rather than proceed with no resolver — which is what makes that fallback safe
    to have at all. It degrades to a loud failure, never to a close that silently
    releases nothing.

    A failing readlink stub is used rather than an emptied PATH: removing /usr/bin also
    removes dirname, and the script then died earlier for an unrelated reason — a test
    that fails for the wrong cause proves nothing about the branch it names.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, str(home / "scratch.txt"))
    assert _run_claim(home, TASK_ID).returncode == 0

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    installed = bin_dir / "cc-close"
    installed.symlink_to(CC_CLOSE)

    failing = home / "stubbin" / "readlink"
    failing.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    failing.chmod(failing.stat().st_mode | stat.S_IXUSR)

    result = subprocess.run(
        [_BASH, str(installed), TASK_ID, "--status", "withdrawn"],
        env=_env(home),
        cwd=str(home),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0, (
        "cc-close proceeded through an unresolvable symlink with no role resolver — "
        f"it cannot have released the lease\nstdout={result.stdout}"
    )
    assert "agent-role.sh not found" in result.stderr, (
        f"refused, but not for the reason under test\nstderr={result.stderr}"
    )
    assert _leases(home) != [], "the lease must survive a refused close"


def test_an_explicit_role_session_still_releases_after_the_cascade_deletion(
    tmp_path: Path,
) -> None:
    """The env cascade that used to bind $role directly was deleted. It read the same
    names hapax_agent_identity reads, so deleting it should change nothing for a session
    that DOES carry an explicit role — but "should" is the word that precedes every
    regression. Drive a HAPAX_AGENT_ROLE session end to end and assert its lease is
    released under the role it declared, not under 'roleless'.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, str(home / "scratch.txt"))

    env = {**_env(home), "HAPAX_AGENT_ROLE": "eta"}
    claimed = subprocess.run(
        [_BASH, str(CC_CLAIM), TASK_ID],
        env=env,
        cwd=str(home),
        text=True,
        capture_output=True,
        check=False,
    )
    assert claimed.returncode == 0, f"explicit-role claim failed\nstderr={claimed.stderr}"
    assert any("-eta" in p.name or p.name.endswith("eta") for p in _leases(home)), (
        f"cc-claim did not key the lease to the declared role: {[p.name for p in _leases(home)]}"
    )

    closed = subprocess.run(
        [_BASH, str(CC_CLOSE), TASK_ID, "--status", "withdrawn"],
        env=env,
        cwd=str(home),
        text=True,
        capture_output=True,
        check=False,
    )
    assert closed.returncode == 0, closed.stderr
    assert "cleared claim file" in closed.stdout, (
        f"explicit-role session's lease was not released\nstdout={closed.stdout}"
    )
    assert _leases(home) == [], f"explicit-role lease leaked: {[p.name for p in _leases(home)]}"


def test_the_guard_never_touches_an_epoch_sidecar(tmp_path: Path) -> None:
    """The guard REFUSES; it never deletes.

    An earlier revision classified epoch sidecars and removed the ones it judged
    orphaned (sidecar present, claim file absent). Three review seats independently
    found the same race: cc-claim writes the sidecar and the claim file as two steps, so
    "sidecar without claim file" is also what a claim being created right now looks
    like. The guard would have deleted a live claim's sidecar.

    No lock was added. A failure path that deletes files it does not own, justified by
    an assumption about what other processes are doing rather than by anything checkable
    at the moment of use, is a path that WIDENS — so it was removed. This test pins that
    it stays removed: an epoch sidecar naming this task neither blocks the close nor is
    modified by it.

    Epoch residue is a real defect with a real consequence — it HOLDs the next cc-claim
    — but closing does not create or worsen it, and the normal release path leaves it
    too. It belongs to the claim-key builder work, not to a guard that can only refuse.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, str(home / "scratch.txt"))

    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    sidecar = cache / "cc-claim-epoch-eta"
    body = f"1780000000 {TASK_ID}\n"
    sidecar.write_text(body, encoding="utf-8")

    result = subprocess.run(
        [_BASH, str(CC_CLOSE), TASK_ID, "--status", "withdrawn"],
        env=_env(home, session_id=None),
        cwd=str(home),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0, "the unresolvable-role refusal is unconditional"
    assert sidecar.exists() and sidecar.read_text(encoding="utf-8") == body, (
        "the guard modified an epoch sidecar; it must only ever refuse, because "
        "'sidecar without claim file' is indistinguishable from a claim mid-creation"
    )


@pytest.mark.parametrize(
    ("lease_name", "lease_body"),
    [
        ("cc-active-task-eta", "{task_id}\n"),
        # The CANONICAL shape. cc-claim session-keys a lease whenever a session id
        # exists, so this — not the legacy form — is what a real blocked close faces.
        ("cc-active-task-eta-sess9", "{task_id}\n"),
    ],
    ids=["legacy-claim-file", "session-keyed-claim-file"],
)
def test_the_named_remedy_actually_recovers_the_refused_close(
    tmp_path: Path, lease_name: str, lease_body: str
) -> None:
    """The refusal's remedy is EXERCISED, not spell-checked, against BOTH lease shapes.

    Asserting that a command name appears in the source proves the string exists, not
    that following it works — and every earlier draft of this refusal named something
    that could not touch its own case. The canonical shape is the session-keyed
    ``cc-active-task-<role>-<session_id>``; a role alone cannot release it, because the
    release loop needs the session id to build that key. A remedy covering only the
    legacy form would half-work, which is the failure this row keeps meeting.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, str(home / "scratch.txt"))

    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / lease_name).write_text(lease_body.format(task_id=TASK_ID), encoding="utf-8")

    refused = subprocess.run(
        [_BASH, str(CC_CLOSE), TASK_ID, "--status", "withdrawn"],
        env=_env(home, session_id=None),
        cwd=str(home),
        text=True,
        capture_output=True,
        check=False,
    )
    assert refused.returncode != 0, f"expected a refusal to recover from\nstdout={refused.stdout}"

    # Exactly what the message says: name the identity that holds the claim. The
    # session id is supplied only when the lease carries one.
    remedy_env = {**_env(home, session_id=None), "HAPAX_AGENT_ROLE": "eta"}
    if lease_name.count("-") > 3:  # cc-active-task-<role>-<session_id>
        remedy_env["HAPAX_SESSION_ID"] = lease_name.rsplit("-", 1)[-1]

    recovered = subprocess.run(
        [_BASH, str(CC_CLOSE), TASK_ID, "--status", "withdrawn"],
        env=remedy_env,
        cwd=str(home),
        text=True,
        capture_output=True,
        check=False,
    )
    assert recovered.returncode == 0, (
        "following the remedy the refusal names did not close the task — the message "
        f"points at a dead end\nstdout={recovered.stdout}\nstderr={recovered.stderr}"
    )
    # Exit zero is not recovery. The whole failure mode this row is about was a close
    # that returned success having released nothing, so the recovery must be judged by
    # the lease actually being gone.
    assert not (cache / lease_name).exists(), (
        "the remedy closed the task but left the blocking claim behind — the next "
        f"mutation is still gated on it\nstdout={recovered.stdout}"
    )


def test_an_unresolvable_role_refuses_without_reading_the_claim_cache(
    tmp_path: Path,
) -> None:
    """The refusal is UNCONDITIONAL and inspects nothing.

    Earlier revisions scanned the cache so they could refuse only when a lease actually
    named this task. Review found a race in that classification, and then the same race
    on the read once the deletion was gone: cc-claim publishes a sidecar and a claim
    file as two steps, so any point-in-time look can observe a half-published claim and
    "no lease names this task" can go stale between check and close. Closing that needs
    a locking protocol the claim plane does not have.

    So the guard asks something it can answer without reading shared state: can this
    process know which lease is its own? Without a role it cannot. Refusing is not a
    heuristic — it is the honest report of an unanswerable question, and it is the one
    shape with no race in it.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, str(home / "scratch.txt"))
    # Nothing in the cache at all: the refusal must not depend on what is there.
    assert _leases(home) == []

    result = subprocess.run(
        [_BASH, str(CC_CLOSE), TASK_ID, "--status", "withdrawn"],
        env=_env(home, session_id=None),
        cwd=str(home),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0, (
        f"cc-close closed a task while unable to identify its own lease\nstdout={result.stdout}"
    )
    assert "cannot tell which claim lease is its own" in result.stderr, (
        f"refused, but not for the reason under test\nstderr={result.stderr}"
    )


def test_the_broken_install_refusal_names_a_repair_that_exists() -> None:
    """An error that names an unreachable remedy costs the reader a full attempt cycle
    to discover the exit is sealed — the failure mode this row met four times in one
    session. So the repair this refusal points at must be a real artifact, asserted, not
    a plausible-sounding string.
    """
    text = CC_CLOSE.read_text(encoding="utf-8")
    assert "hapax-source-activate" in text, (
        "the broken-install refusal no longer names its repair path"
    )
    assert (REPO_ROOT / "scripts" / "hapax-source-activate").is_file(), (
        "cc-close's broken-install refusal names hapax-source-activate as the repair, "
        "but no such script exists — the remedy is fiction"
    )
    assert "HAPAX_AGENT_ROLE=" in text, "the unresolvable-role refusal no longer names its remedy"


def test_the_release_runs_for_every_terminal_status(tmp_path: Path) -> None:
    """The release block is documented as running for every terminal status, but the
    coverage above drives only ``withdrawn`` (chosen because it skips the done-only
    gates). A status-specific regression would therefore be invisible. ``superseded``
    is the cheap second witness.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, str(home / "scratch.txt"))
    assert _run_claim(home, TASK_ID).returncode == 0

    result = _run_close(home, status="superseded")

    assert result.returncode == 0, result.stderr
    assert "cleared claim file" in result.stdout, (
        f"the release did not run under --status superseded\nstdout={result.stdout}"
    )
    assert _leases(home) == [], (
        f"lease artifacts leaked past a superseded close: {[p.name for p in _leases(home)]}"
    )


def test_the_divergent_resolver_cannot_complete_a_roleless_close(tmp_path: Path) -> None:
    """(d): the mutation. Revert ONLY the resolver and a roleless close must not
    succeed. A test that stays green when the fix is removed is documentation, not
    verification.

    Note what the failure now LOOKS like. Before the unresolvable-role guard, the
    divergent resolver produced a silent success: exit 0, nothing released, and the
    session discovered the strand later when the gate blocked its next mutation. With
    the guard, the same divergence is caught at the moment of use and refuses loudly,
    and the task stays open with its lease intact.

    The two changes are not two mitigations of one hazard. The resolver fix makes a
    roleless close CORRECT; the guard handles a genuinely different condition — role
    unresolvable at all — which the code previously collapsed into "no claim to
    release". Distinguishing "measured: no lease" from "could not measure" is the point.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    target = home / "scratch.txt"
    target.write_text("a\n", encoding="utf-8")
    note = _write_task(vault, str(target))

    assert _run_claim(home, TASK_ID).returncode == 0
    session_lease = home / ".cache" / "hapax" / f"cc-active-task-roleless-{SESSION_ID}"

    result = _run_close(home, _divergent_cc_close(tmp_path))

    assert result.returncode != 0, (
        "the divergent resolver completed a roleless close — the mutation fixture no "
        f"longer reproduces the defect\nstdout={result.stdout}"
    )
    assert "cannot resolve this session's role" in result.stderr, (
        f"failed, but not for the reason under test\nstderr={result.stderr}"
    )
    assert session_lease.exists(), "the lease must survive a close that could not run"
    assert note.is_file(), (
        "the task was moved out of active/ by a close that refused — the refusal must "
        "happen before any state change, or it leaves worse behind than it prevents"
    )
    assert "cleared claim file" not in result.stdout


def test_leaked_lease_residue_deadlocks_the_next_claim(tmp_path: Path) -> None:
    """Why a strand ever needed an operator rather than a retry, pinned independently
    of cc-close so it survives however cc-close changes.

    A lease left behind is not merely noise: with residue present the next ``cc-claim``
    HOLDs, so the gate's advertised remedy ("Re-claim a fresh task: cc-claim <task_id>")
    cannot succeed. The defect produced exactly the residue that disabled its own
    recovery path — which is why this row's fix has to be about not leaving residue,
    not about detecting it afterwards.

    Measured 2026-08-21 by controlled comparison — identical sandbox, residue the only
    variable, rc 4 -> rc 8. See ``CLAIM_HOLD_RC`` for why this asserts the HOLD and the
    named lease rather than one reason code.
    """
    home = tmp_path / "home"
    vault = _vault(home)
    target = home / "scratch.txt"
    target.write_text("a\n", encoding="utf-8")
    _write_task(vault, str(target), NEXT_TASK_ID)

    # Exactly what a close that released nothing leaves behind.
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "cc-active-task-roleless").write_text(f"{TASK_ID}\n", encoding="utf-8")
    (cache / "cc-claim-epoch-roleless").write_text(f"1780000000 {TASK_ID}\n", encoding="utf-8")

    stuck = _run_claim(home, NEXT_TASK_ID)

    assert stuck.returncode == CLAIM_HOLD_RC, (
        f"expected the HOLD exit ({CLAIM_HOLD_RC}) from leaked residue, got "
        f"rc={stuck.returncode}\nstderr={stuck.stderr}"
    )
    assert "HOLD" in stuck.stderr, (
        f"cc-claim failed, but not with the residue HOLD\nstderr={stuck.stderr}"
    )
    # Deliberately not asserting a reason code. Three were observed across residue
    # shapes and vault contents (claim_task_mismatch, claim_dispatch_binding_missing),
    # and pinning one would make this test a hostage to which variant a future
    # cc-claim reports. What is invariant, and what actually strands a session, is
    # that the residue turns the recovery path into a HOLD.
