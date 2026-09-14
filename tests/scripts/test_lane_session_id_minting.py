"""A lane launch mints its own session id; only an explicit pin is inherited.

Claims key on ``<role>-<session_id>`` (coordination reform Phase 1, cluster 6,
FM-2) and ``shared/session_identity.py`` states the cluster-11 contract in its
module docstring: *every spawn mints a fresh per-session id*. Six launch paths
did not implement it — they honoured whatever ``HAPAX_SESSION_ID`` an ancestor
shell happened to export, so several lanes launched from one parent shared a
claim key and the session suffix disambiguated nothing. Measured 2026-09-13:
``cc-active-task-{cx-glmcp,cx-p0,cx-crit}-041482e9-0535-4502-a3f2-100149a03a8c``
— three roles, one id.

The fix cannot be "always mint", because ONE path inherits for a real reason:
``scripts/hapax-codex`` writes a tmux runner that re-execs *itself*, and the
inner process must keep the outer's id or it orphans the ``session-role-<sid>``
marker and any claim the outer already wrote. A single boolean ("is
HAPAX_SESSION_ID set?") was standing in for two distinct conditions — *an
ancestor exported one* (ignore) and *my own outer invocation pinned one*
(honour). ``hapax_launch_session_id`` splits them: an inherited id is honoured
only alongside ``HAPAX_SESSION_ID_PINNED=1``, which makes the safety
precondition checkable at the moment of use rather than an assertion about what
some other process must have been doing.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROLE = REPO_ROOT / "hooks" / "scripts" / "agent-role.sh"
SCRIPTS = REPO_ROOT / "scripts"

sys.path.insert(0, str(REPO_ROOT))

from shared.session_identity import is_claim_keyable_session_id  # noqa: E402

# Identity env pytest's own lane exports; stripped so the subshell resolves only
# what each case sets (HAPAX_AGENT_NAME outranks role, and CLAUDE_CODE_SESSION_ID
# is always present under Claude Code — either would leak the harness lane's
# identity into the assertion).
_IDENTITY_ENV = (
    "HAPAX_SESSION_ID",
    "HAPAX_SESSION_ID_PINNED",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_SESSION",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
)


def _bash(script: str, env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
    env.update(env_overrides)
    return subprocess.run(
        ["bash", "-c", f'. "{AGENT_ROLE}"\n{script}'],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _launch_session_id(env_overrides: dict[str, str]) -> str:
    """Resolve one launch identity through the helper, under a controlled env."""
    result = _bash(
        "hapax_consume_launch_session_id hapax-codex\nprintf '%s\\n' \"$HAPAX_LAUNCH_SESSION_ID\"",
        env_overrides,
    )
    assert result.returncode == 0, f"helper failed: {result.stderr}"
    return result.stdout.strip()


def _enclosing_if_condition(code: str, needle: str) -> str | None:
    """The condition of the innermost `if` block containing ``needle``.

    Crude but sufficient for these launchers: tracks `if`/`fi` nesting over
    comment-stripped shell and returns the condition text of the innermost block
    still open when ``needle`` is reached. Returns None when the call sits at top
    level. Asserting on this rather than on "the flag appears somewhere earlier"
    is what makes the guard test survive an `if true` mutation.
    """
    stack: list[str] = []
    for line in code.splitlines():
        stripped = line.strip()
        if needle in stripped:
            return stack[-1] if stack else None
        if stripped.startswith("if ") or stripped == "if":
            stack.append(stripped)
        elif stripped == "fi" and stack:
            stack.pop()
    return None


def _strip_comments(text: str) -> str:
    """Shell source with comment lines removed.

    Round 1 of review on PR #4668 found the conformance pins below vacuous:
    they grepped the whole file, and the *comments* explaining the mechanism
    contained the very strings being asserted. codex-1 mutated every launcher's
    SESSION_UUID assignment to a constant, deleted the runner pin export and
    commented out the dispatch env.pop calls — and all 17 assertions still
    passed. Asserting over code only is what makes them mean anything.
    """
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


class TestLaunchSessionId:
    def test_ambient_inherited_id_is_ignored(self) -> None:
        """The measured defect: an ancestor's exported id must not become ours."""
        ambient = "041482e9-0535-4502-a3f2-100149a03a8c"
        got = _launch_session_id({"HAPAX_SESSION_ID": ambient})
        assert got != ambient, (
            "an ambient HAPAX_SESSION_ID was adopted as this launch's identity — "
            "every lane launched from one ancestor shell then shares a claim key"
        )
        assert got, "a launch must always resolve to some id"

    def test_explicitly_pinned_id_is_honoured(self) -> None:
        """hapax-codex's runner re-execs the launcher; that id must survive."""
        pinned = "7a9e1d91-be4a-4354-a109-482b2bd0e5e3"
        got = _launch_session_id(
            {"HAPAX_SESSION_ID": pinned, "HAPAX_SESSION_ID_PINNED": "hapax-codex"}
        )
        assert got == pinned, (
            "a re-exec'd inner launcher minted a second id — it orphans the outer's "
            "session-role marker and any claim the outer already wrote"
        )

    def test_pin_without_an_id_still_mints(self) -> None:
        """The pin is not a license to return empty; it only selects a source."""
        got = _launch_session_id({"HAPAX_SESSION_ID_PINNED": "hapax-codex"})
        assert got, "pinned-but-absent must still mint, never return empty"
        assert is_claim_keyable_session_id(got)

    def test_pin_set_to_something_other_than_1_does_not_honour(self) -> None:
        """Only the exact sentinel opts in — a stray truthy value must not."""
        ambient = "041482e9-0535-4502-a3f2-100149a03a8c"
        got = _launch_session_id({"HAPAX_SESSION_ID": ambient, "HAPAX_SESSION_ID_PINNED": "0"})
        assert got != ambient

    def test_minted_ids_are_unique_across_launches(self) -> None:
        ids = {_launch_session_id({}) for _ in range(5)}
        assert len(ids) == 5, f"minted ids collided: {ids}"

    def test_minted_id_is_claim_keyable(self) -> None:
        """A pid-shaped id must never key a claim (taxonomy-a3-session-identity)."""
        got = _launch_session_id({})
        assert is_claim_keyable_session_id(got), f"minted id is not claim-keyable: {got!r}"

    def test_inherited_unsafe_id_is_not_honoured_even_when_pinned(self) -> None:
        """A pin may not smuggle a path-hostile id into a filename."""
        got = _launch_session_id(
            {"HAPAX_SESSION_ID": "../../etc/passwd", "HAPAX_SESSION_ID_PINNED": "hapax-codex"}
        )
        assert got != "../../etc/passwd"
        assert is_claim_keyable_session_id(got)


class TestPinIsConsumedOnce:
    """The pin authorises ONE hop. Round 1 of review shipped it as a standing grant.

    All four reviewer families converged on this. The first cut exported
    HAPAX_SESSION_ID_PINNED=1 into hapax-codex's runner and never cleared it, so
    every process in that lane's subtree inherited pin=1 plus the outer session id.
    A grandchild launcher then adopted it — reconstructing the exact
    cc-active-task-{cx-glmcp,cx-p0,cx-crit}-041482e9-… collision this repairs, and
    regressing hapax-claude-headless and hapax-kimi, which minted unconditionally
    before. Reproduced against the live tree, then fixed.

    An env var is inherited transitively by construction, so "is the pin set" can
    never express "this invocation is the re-exec my outer invocation created".
    Consuming it is the only shape that can.
    """

    def test_grandchild_does_not_inherit_the_pinned_id(self) -> None:
        """Two consecutive resolutions in one pinned env: only the first inherits."""
        pinned = "041482e9-0535-4502-a3f2-100149a03a8c"
        result = _bash(
            'hapax_consume_launch_session_id hapax-codex;inner="$HAPAX_LAUNCH_SESSION_ID"\n'
            'hapax_consume_launch_session_id hapax-codex;grandchild="$HAPAX_LAUNCH_SESSION_ID"\n'
            'printf "%s %s\\n" "$inner" "$grandchild"',
            {"HAPAX_SESSION_ID": pinned, "HAPAX_SESSION_ID_PINNED": "hapax-codex"},
        )
        assert result.returncode == 0, result.stderr
        inner, grandchild = result.stdout.split()
        assert inner == pinned, "the one legitimate hop must still inherit"
        assert grandchild != pinned, (
            "a grandchild launcher adopted the outer lane's session id — the pin "
            "outlived the single re-exec it was written for"
        )
        assert is_claim_keyable_session_id(grandchild)

    def test_pin_is_cleared_from_the_environment_children_inherit(self) -> None:
        """The clear must reach real child processes, not just the shell's own scope.

        This is why the helper sets a caller-shell variable instead of printing:
        `$(...)` is a subshell, and an unset there would never reach the env handed
        to the runner script.
        """
        result = _bash(
            'hapax_consume_launch_session_id hapax-codex\nenv | grep -c "^HAPAX_SESSION_ID_PINNED=" || true',
            {
                "HAPAX_SESSION_ID": "041482e9-0535-4502-a3f2-100149a03a8c",
                "HAPAX_SESSION_ID_PINNED": "hapax-codex",
            },
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0", (
            "HAPAX_SESSION_ID_PINNED survived into the child environment — every "
            "launcher in the subtree would honour it"
        )

    @pytest.mark.parametrize(
        "addressee", ["hapax-kimi", "hapax-claude-headless", "hapax-codex-headless", ""]
    )
    def test_a_pin_addressed_elsewhere_is_ignored(self, addressee: str) -> None:
        """Only the launcher a pin NAMES may honour it.

        Consume-once alone was still too broad: a launcher invoked into an
        environment carrying any pin adopted the outer id, regressing the paths
        that minted unconditionally. Every non-addressee — and a launcher passing
        no addressee at all — must mint.
        """
        pinned = "041482e9-0535-4502-a3f2-100149a03a8c"
        result = _bash(
            f"hapax_consume_launch_session_id {addressee}\n"
            'printf "%s\\n" "$HAPAX_LAUNCH_SESSION_ID"',
            {"HAPAX_SESSION_ID": pinned, "HAPAX_SESSION_ID_PINNED": "hapax-codex"},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() != pinned, (
            f"a pin addressed to hapax-codex was honoured by {addressee or '<no addressee>'}"
        )

    def test_a_truthy_pin_value_is_ignored_not_honoured(self) -> None:
        """The pin is an ADDRESSEE, not a boolean — `=1` addresses a launcher named "1".

        Documented explicitly because the retired form really was `=1`, so a reader
        (or a stray ancestor export) could reasonably expect truthiness to work.
        Ignored rather than refused: refusing would let any ancestor break a launch
        by exporting a stray variable, and minting is always the safe outcome.
        """
        pinned = "041482e9-0535-4502-a3f2-100149a03a8c"
        for value in ("1", "true", "yes"):
            result = _bash(
                "hapax_consume_launch_session_id hapax-codex\n"
                'printf "%s\\n" "$HAPAX_LAUNCH_SESSION_ID"',
                {"HAPAX_SESSION_ID": pinned, "HAPAX_SESSION_ID_PINNED": value},
            )
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() != pinned, f"truthy pin {value!r} was honoured"

    def test_pin_is_cleared_even_when_it_was_not_honoured(self) -> None:
        """An unusable pin must not linger for the next launcher to pick up."""
        result = _bash(
            'hapax_consume_launch_session_id hapax-codex\nprintf "%s\\n" "${HAPAX_SESSION_ID_PINNED:-<unset>}"',
            {"HAPAX_SESSION_ID": "short", "HAPAX_SESSION_ID_PINNED": "hapax-codex"},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "<unset>"


# --- Launcher conformance ----------------------------------------------------
# The behavioural contract above is carried by the helper; these pins assert the
# launchers actually route through it. Without them the helper can be correct
# while every launcher keeps its own inheriting copy — which is exactly the state
# this task found (hapax-claude-headless had the fix from #3875; five siblings
# never adopted it).
#
# They are DRIFT PINS, not behavioural proof, and round 1 of review showed how
# little that is worth when done carelessly: the first cut grepped whole files, so
# the comments explaining the mechanism satisfied the assertions, and a mutation
# that replaced every SESSION_UUID assignment with a constant still passed all 17.
# Two changes: they read code with comments stripped, and they assert the call
# SHAPE (outside a command substitution), which is what makes the pin consumable.
# The behavioural coverage lives in TestPinIsConsumedOnce and
# TestLauncherBehaviour.

#: Launchers that start a NEW lane and must therefore mint.
MINTING_LAUNCHERS = (
    "hapax-claude",
    "hapax-claude-headless",
    "hapax-codex",
    "hapax-codex-headless",
    "hapax-vibe",
    "hapax-kimi",
)

#: Launchers exempt from passing a task to succession. EMPTY, and that is the
#: point: hapax-kimi's CLI carries no --task, and the first instinct was to exempt
#: it and do role-only succession. A role-only lookup can adopt a claim for
#: DIFFERENT work, so the exemption would have been a real hole. The role's own
#: claim file names the task it holds, so kimi recovers it from there and passes
#: it like everyone else. Kept as a declared (empty) set rather than deleted, so
#: the next launcher that "cannot" pass a task has to be argued for here.
_TASKLESS_LAUNCHERS: frozenset[str] = frozenset()

#: The bare inheriting form the defect consisted of: `${HAPAX_SESSION_ID:-...}`
#: (parameter expansion with a default) anywhere a launch identity is computed.
_INHERITING_FORM = re.compile(r"SESSION_UUID=.*\$\{HAPAX_SESSION_ID:-")


@pytest.mark.parametrize("name", MINTING_LAUNCHERS)
def test_launcher_does_not_inherit_ambient_session_id(name: str) -> None:
    script = SCRIPTS / name
    assert script.is_file(), f"missing launcher {script}"
    code = _strip_comments(script.read_text(encoding="utf-8"))
    offenders = [line.strip() for line in code.splitlines() if _INHERITING_FORM.search(line)]
    assert not offenders, (
        f"{name} computes its launch identity from an ambient HAPAX_SESSION_ID: "
        f"{offenders} — use hapax_consume_launch_session_id so inheritance requires "
        "an explicit, single-use HAPAX_SESSION_ID_PINNED=1"
    )


@pytest.mark.parametrize("name", MINTING_LAUNCHERS)
def test_launcher_routes_through_the_shared_helper(name: str) -> None:
    """A launcher that hand-rolls minting drifts from the helper's contract."""
    code = _strip_comments((SCRIPTS / name).read_text(encoding="utf-8"))
    assert "hapax_consume_launch_session_id" in code, (
        f"{name} does not call hapax_consume_launch_session_id — its session "
        "identity is not governed by the tested helper"
    )


@pytest.mark.parametrize("name", MINTING_LAUNCHERS)
def test_launcher_calls_the_helper_outside_a_command_substitution(name: str) -> None:
    """`SESSION_UUID="$(hapax_consume_launch_session_id)"` would silently re-leak.

    The helper clears the one-shot pin in the shell it runs in. Called inside
    `$(...)` that shell is a subshell, so the clear evaporates and the pin reaches
    every child again — the round-1 defect restored while still "calling the
    helper". The call must stand alone, with the value read from the variable.
    """
    code = _strip_comments((SCRIPTS / name).read_text(encoding="utf-8"))
    bad = [
        line.strip()
        for line in code.splitlines()
        if "hapax_consume_launch_session_id" in line and "$(" in line
    ]
    assert not bad, (
        f"{name} calls the helper inside a command substitution: {bad} — the pin "
        "clear happens in a subshell and never reaches the child environment"
    )
    assert "HAPAX_LAUNCH_SESSION_ID" in code, (
        f"{name} calls the helper but never reads HAPAX_LAUNCH_SESSION_ID"
    )


def test_codex_runner_pins_the_id_it_propagates() -> None:
    """The one legitimate inheritor must say so explicitly.

    hapax-codex's tmux runner re-execs hapax-codex. It already exports
    HAPAX_SESSION_ID; that export alone is no longer honoured, so it must also
    export the pin or the inner process mints a divergent id.
    """
    code = _strip_comments((SCRIPTS / "hapax-codex").read_text(encoding="utf-8"))
    assert "HAPAX_SESSION_ID_PINNED=hapax-codex" in code, (
        "hapax-codex re-execs itself but does not pin the id it propagates — the "
        "inner launcher will mint a fresh one and orphan the outer's marker"
    )


def test_only_the_self_reexecing_launcher_pins() -> None:
    """A launcher that does not re-enter itself has no business granting a pin.

    hapax-claude, hapax-vibe, hapax-kimi and hapax-codex-headless exec their target
    binary directly. If one of them started exporting the pin, it would hand a
    standing inheritance grant to a process that never needed one.
    """
    for name in MINTING_LAUNCHERS:
        if name == "hapax-codex":
            continue
        code = _strip_comments((SCRIPTS / name).read_text(encoding="utf-8"))
        assert "HAPAX_SESSION_ID_PINNED=" not in code, (
            f"{name} exports the inheritance pin but does not re-exec itself"
        )
        assert "hapax_consume_launch_session_id hapax" not in code, (
            f"{name} claims an addressee, so it would honour a pin — only the "
            "self-re-execing launcher may"
        )


#: Dispatch launch functions must hand every lane a scrubbed env. The two claude
#: paths already did (env.pop at 1529/1570); codex/vibe did not.
DISPATCH_LAUNCHERS = (
    "launch_claude_headless",
    "launch_claude_interactive",
    "launch_codex_headless",
    "launch_vibe_headless",
)


@pytest.mark.parametrize("func", DISPATCH_LAUNCHERS)
def test_dispatch_launcher_scrubs_inherited_session_id(func: str) -> None:
    text = (SCRIPTS / "hapax-methodology-dispatch").read_text(encoding="utf-8")
    start = text.index(f"def {func}(")
    # The function body ends at the next top-level def.
    nxt = text.find("\ndef ", start + 1)
    body = text[start : nxt if nxt != -1 else len(text)]
    assert 'env.pop("HAPAX_SESSION_ID", None)' in body, (
        f"{func} propagates the dispatcher's own HAPAX_SESSION_ID to the lane — "
        "two same-role re-dispatched lanes then share a claim key"
    )


class TestRoleSessionSuccession:
    """A resume keeps the identity its admitted claim is bound to; a fresh launch does not.

    A Gate-0B claim binds `session_id`, and resolve_applied_claim_publication
    refuses with `claim_binding_vector_mismatch` when the resolving session
    differs — so a lane relaunched under a new id cannot resume its own claim. That
    is already true on main for any relaunch from a clean shell (the base
    `${HAPAX_SESSION_ID:-<mint>}` form mints whenever the var is unset); the
    accidental inheritance this task removes was doing succession's job by luck.
    `--continue` makes it deliberate.
    """

    def _succeed(self, home: Path, role: str) -> str:
        result = _bash(
            f'hapax_role_succession_session_id {role} || printf "MINT\\n"',
            {"HOME": str(home)},
        )
        return result.stdout.strip()

    def _marker(self, home: Path, key: str, task: str = "t1") -> None:
        cache = home / ".cache" / "hapax"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / f"cc-active-task-{key}").write_text(f"{task}\n", encoding="utf-8")

    def test_one_live_claim_is_succeeded(self, tmp_path: Path) -> None:
        sid = "3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01"
        self._marker(tmp_path, f"eta-{sid}")
        assert self._succeed(tmp_path, "eta") == sid

    def test_no_live_claim_mints(self, tmp_path: Path) -> None:
        (tmp_path / ".cache" / "hapax").mkdir(parents=True)
        assert self._succeed(tmp_path, "eta") == "MINT"

    def test_two_live_claims_refuse_rather_than_guess(self, tmp_path: Path) -> None:
        """Ambiguous claim state must not be resolved by picking one."""
        self._marker(tmp_path, "eta-3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01")
        self._marker(tmp_path, "eta-b8e2d7c4-1a55-4f93-8c60-77ad3e9b0125")
        assert self._succeed(tmp_path, "eta") == "MINT"

    def test_a_role_extending_this_name_is_not_succeeded(self, tmp_path: Path) -> None:
        """`cx-blue` must not adopt `cx-blue-shadow`'s session — that steals a claim."""
        self._marker(tmp_path, "cx-blue-shadow-9d4e1f77-2a3b-4c58-b0e6-1f2a3b4c5d6e")
        assert self._succeed(tmp_path, "cx-blue") == "MINT"

    def test_a_foreign_marker_does_not_make_a_real_one_ambiguous(self, tmp_path: Path) -> None:
        sid = "3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01"
        self._marker(tmp_path, f"cx-blue-{sid}")
        self._marker(tmp_path, "cx-blue-shadow-9d4e1f77-2a3b-4c58-b0e6-1f2a3b4c5d6e")
        assert self._succeed(tmp_path, "cx-blue") == sid

    @pytest.mark.parametrize("name", MINTING_LAUNCHERS)
    def test_every_launcher_implements_succession(self, name: str) -> None:
        """The whole set, enumerated — because hand-enumeration is what kept failing.

        Three review rounds each found a DIFFERENT launcher with an unhandled
        resume spelling: round 2 the headless pair, round 3 hapax-codex's forwarded
        `resume` subcommand and hapax-vibe's --resume/--continue. Each time the
        design was accepted and the application incomplete. Asserting over the full
        launcher list makes "I forgot one" a test failure rather than a review
        round.
        """
        code = _strip_comments((SCRIPTS / name).read_text(encoding="utf-8"))
        assert "hapax_role_succession_session_id" in code, (
            f"{name} never succeeds a live claim — a relaunch for a task it already "
            "holds will mint a new id and the admitted claim cannot resolve"
        )

    @pytest.mark.parametrize("name", MINTING_LAUNCHERS)
    def test_succession_is_keyed_on_the_task_where_one_is_known(self, name: str) -> None:
        """A task-keyed call needs no resume flag, which is why it is complete.

        `--continue`, `--resume`, a forwarded `resume` subcommand and a bare
        relaunch are all the same thing when the task is already held. Launchers
        that know a task must pass it; only a resume that names no task may fall
        back to role-only.
        """
        code = _strip_comments((SCRIPTS / name).read_text(encoding="utf-8"))
        calls = [
            line.strip()
            for line in code.splitlines()
            if "hapax_role_succession_session_id" in line and "()" not in line
        ]
        assert calls, f"{name} has no succession call"
        if name in _TASKLESS_LAUNCHERS:
            # Declared exemption, not a silent pass: this launcher's CLI has no
            # task concept, so it can only do role-only succession, guarded by an
            # explicit resume flag. Asserted against the CLI rather than skipped —
            # if a task flag is ever added, the exemption must go with it.
            assert "--task" not in code, (
                f"{name} now accepts a task but is still listed as task-less — "
                "thread the task into succession and drop the exemption"
            )
            return
        two_arg = [
            c for c in calls if re.search(r'hapax_role_succession_session_id\s+"?\$\S+"?\s+"?\$', c)
        ]
        assert two_arg, (
            f"{name} calls succession without a task id: {calls} — a role-only "
            "lookup can adopt a claim for DIFFERENT work"
        )

    @pytest.mark.parametrize("name", MINTING_LAUNCHERS)
    def test_succession_is_guarded_by_the_task_not_by_a_resume_flag(self, name: str) -> None:
        """One rule for all six: succeed iff this role already holds THIS task.

        Earlier cuts guarded succession behind each launcher's own resume spelling
        — `--continue`, `--resume`, a forwarded `resume` subcommand — and three
        review rounds each found a launcher whose spelling had been missed. The
        task match needs no flag and is self-limiting, so there is no spelling left
        to miss; the enclosing conditional must test the task, not a resume flag.
        """
        code = _strip_comments((SCRIPTS / name).read_text(encoding="utf-8"))
        condition = _enclosing_if_condition(code, "hapax_role_succession_session_id")
        assert condition is not None, (
            f"{name} calls succession unconditionally — a launch that knows no task "
            "would adopt whatever claim the role happens to hold"
        )
        assert "TASK" in condition.upper(), (
            f"{name} guards succession with {condition!r}, which does not test a "
            "task id — a resume-flag guard misses every spelling it does not name"
        )


#: Argv that reaches each launcher's identity block. These differ — hapax-kimi
#: parses its own args before resolving the helper and rejects a trailing prompt,
#: so handing every launcher the same argv tests the arg parser in one of them and
#: the identity path in the rest.
_LAUNCHER_ARGS: dict[str, list[str]] = {
    "hapax-claude": ["--role", "zeta", "--terminal", "none"],
    "hapax-claude-headless": ["zeta", "governed msg"],
    "hapax-codex": ["--session", "cx-zeta", "--terminal", "none"],
    "hapax-codex-headless": ["cx-zeta", "governed msg"],
    "hapax-vibe": ["--session", "vbe-9", "--terminal", "none"],
    "hapax-kimi": ["zeta", "--terminal", "none"],
}


class TestLauncherBehaviour:
    """Run the launchers, don't read them.

    The pins above catch drift in the call shape; these catch a launcher that
    wires the helper up wrongly, which the pins cannot see.
    """

    @pytest.mark.parametrize("name", MINTING_LAUNCHERS)
    def test_launcher_refuses_when_the_identity_helper_is_missing(
        self, name: str, tmp_path: Path
    ) -> None:
        """A launcher with no helper must refuse by name, never limp.

        This is the discipline's own prescription: a refusal naming its own remedy
        beats a path that is silently wrong. Before this change the launchers
        hand-rolled the mint, which is how five divergent copies happened; the cost
        of centralising it is that an incomplete checkout must now say so.
        """
        # A copy outside any council tree, with COUNCIL_DIR pointed at an empty
        # dir: neither the script-relative nor the fallback lookup can resolve.
        lonely = tmp_path / name
        lonely.write_bytes((SCRIPTS / name).read_bytes())
        lonely.chmod(0o755)
        empty = tmp_path / "not-a-council"
        empty.mkdir()

        env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
        env["HAPAX_COUNCIL_DIR"] = str(empty)
        env["HOME"] = str(tmp_path)
        env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
        env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
        result = subprocess.run(
            [str(lonely), *_LAUNCHER_ARGS[name]],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        assert result.returncode != 0, (
            f"{name} launched without an identity helper — its session id is "
            f"ungoverned\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "identity helper not found" in combined, (
            f"{name} failed without naming the cause or a remedy\n{combined}"
        )

    def _headless_marker_sid(self, tmp_path: Path, task: str, **extra: str) -> str:
        """Run hapax-claude-headless and return the session id it actually adopted."""
        env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
        for k in ("CLAUDE_ROLE", "HAPAX_AGENT_NAME", "HAPAX_AGENT_ROLE", "HAPAX_WORKTREE_ROLE"):
            env.pop(k, None)
        env["HOME"] = str(tmp_path)
        env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
        env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
        env.update(extra)
        subprocess.run(
            [str(SCRIPTS / "hapax-claude-headless"), "--task", task, "zeta", "msg"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        markers = sorted((tmp_path / ".cache" / "hapax").glob("session-role-*"))
        assert len(markers) == 1, f"expected one session marker, got {markers}"
        return markers[0].name.removeprefix("session-role-")

    def test_headless_redispatch_succeeds_its_own_live_claim(self, tmp_path: Path) -> None:
        """The round-3 critical, exercised through the real launcher.

        A Gate-0B claim binds session_id; a re-dispatch that mints a new one makes
        resolve_applied_claim_publication refuse with claim_binding_vector_mismatch
        before resumption is reached. So a launch for a task this role already
        holds must adopt that claim's session.
        """
        prior = "3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01"
        cache = tmp_path / ".cache" / "hapax"
        cache.mkdir(parents=True)
        (cache / f"cc-active-task-zeta-{prior}").write_text("task-a\n", encoding="utf-8")

        assert self._headless_marker_sid(tmp_path, "task-a") == prior, (
            "a re-dispatched headless lane minted a new id instead of succeeding "
            "the session its admitted claim is bound to"
        )

    def test_headless_relaunch_without_task_flag_still_succeeds(self, tmp_path: Path) -> None:
        """The supported `--task`-less relaunch must succeed too.

        Round 3 put the succession branch behind `-n "$CLAUDE_TASK"` but left the
        legacy-claim task recovery further down, so this invocation skipped
        succession entirely, then adopted the recovered task while keeping a freshly
        minted id — and the worker's next cc-claim failed against the original
        session binding. The task is now resolved BEFORE the session is chosen.
        """
        prior = "3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01"
        cache = tmp_path / ".cache" / "hapax"
        cache.mkdir(parents=True)
        (cache / f"cc-active-task-zeta-{prior}").write_text("task-a\n", encoding="utf-8")
        # The legacy role-keyed file is what a --task-less relaunch recovers from.
        (cache / "cc-active-task-zeta").write_text("task-a\n", encoding="utf-8")

        env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
        for k in ("CLAUDE_ROLE", "HAPAX_AGENT_NAME", "HAPAX_AGENT_ROLE", "HAPAX_WORKTREE_ROLE"):
            env.pop(k, None)
        env["HOME"] = str(tmp_path)
        env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
        env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
        subprocess.run(
            [str(SCRIPTS / "hapax-claude-headless"), "zeta", "msg"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        markers = sorted((tmp_path / ".cache" / "hapax").glob("session-role-*"))
        assert len(markers) == 1, f"expected one session marker, got {markers}"
        assert markers[0].name.removeprefix("session-role-") == prior, (
            "a --task-less relaunch minted a new id even though the role's claim "
            "named the task it was about to adopt"
        )

    def test_headless_launch_for_a_different_task_still_mints(self, tmp_path: Path) -> None:
        """Succession is keyed on the TASK, so new work never adopts a live claim."""
        prior = "3f1c9a20-77b4-4d0e-9a11-2c8e5b6d4f01"
        cache = tmp_path / ".cache" / "hapax"
        cache.mkdir(parents=True)
        (cache / f"cc-active-task-zeta-{prior}").write_text("task-a\n", encoding="utf-8")

        assert self._headless_marker_sid(tmp_path, "task-b") != prior

    def test_headless_launch_with_no_live_claim_mints(self, tmp_path: Path) -> None:
        (tmp_path / ".cache" / "hapax").mkdir(parents=True)
        sid = self._headless_marker_sid(tmp_path, "task-a")
        assert is_claim_keyable_session_id(sid)

    def test_headless_does_not_succeed_a_role_extending_its_name(self, tmp_path: Path) -> None:
        """`zeta` must not adopt `zeta-shadow`'s claim — that steals it."""
        cache = tmp_path / ".cache" / "hapax"
        cache.mkdir(parents=True)
        (cache / "cc-active-task-zeta-shadow-9d4e1f77-2a3b-4c58-b0e6-1f2a3b4c5d6e").write_text(
            "task-a\n", encoding="utf-8"
        )

        sid = self._headless_marker_sid(tmp_path, "task-a")
        assert sid != "shadow-9d4e1f77-2a3b-4c58-b0e6-1f2a3b4c5d6e"
        assert is_claim_keyable_session_id(sid)

    def test_headless_launcher_ignores_an_inherited_pin(self, tmp_path: Path) -> None:
        """hapax-claude-headless minted unconditionally before this change (#3875).

        glm-1 flagged the regression risk directly: routing it through a helper
        that honours a pin means two headless lanes dispatched from inside a pinned
        codex pane would share one claim key — a net regression for the one path
        that was already correct. Every headless launch is a fresh lane, and the
        pin is consumed by the codex launcher that issued it, so nothing should
        reach here; this asserts it.
        """
        env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
        for k in ("CLAUDE_ROLE", "HAPAX_AGENT_NAME", "HAPAX_AGENT_ROLE", "HAPAX_WORKTREE_ROLE"):
            env.pop(k, None)
        env["HOME"] = str(tmp_path)
        env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
        env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
        env["HAPAX_SESSION_ID"] = "041482e9-0535-4502-a3f2-100149a03a8c"
        env["HAPAX_SESSION_ID_PINNED"] = "1"
        # The zeta worktree does not exist under this HOME, so the launcher exits
        # right after minting and writing its identity marker.
        subprocess.run(
            [str(SCRIPTS / "hapax-claude-headless"), "zeta", "governed msg"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        markers = sorted((tmp_path / ".cache" / "hapax").glob("session-role-*"))
        assert len(markers) == 1, f"expected exactly one session marker, got {markers}"
        sid = markers[0].name.removeprefix("session-role-")
        assert sid != "041482e9-0535-4502-a3f2-100149a03a8c", (
            "a headless lane adopted a pinned ambient session id — two lanes "
            "dispatched from one pinned pane would share a claim key"
        )
        assert is_claim_keyable_session_id(sid)
