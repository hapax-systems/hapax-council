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
(honour). ``hapax_consume_launch_session_id`` splits them: an inherited id is honoured
only alongside a ``HAPAX_SESSION_ID_PINNED`` that NAMES it, which makes the safety
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

#: No launcher-side succession is asserted here, deliberately. A helper for it
#: lived across review rounds 2-6 and was removed: it cannot be made correct in a
#: launcher (see the REMOVED block in hooks/scripts/agent-role.sh). Every launcher
#: mints, which is what origin/main does today, so nothing here regressed.

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


def test_codex_runner_pins_a_VARIABLE_not_a_literal_identity() -> None:
    """The Codex re-entry path, as a source pin beside its behavioural test.

    An earlier revision of this docstring said the behavioural version was
    unreachable — that hapax-codex refuses before writing its runner without a real
    codex-native worktree. That was wrong, and review round 14 said so: passing
    `--cd` makes the worktree explicit, and a tmux stub that records the runner
    path is enough to reach it. TestCodexRunnerReentry below executes the generated
    runner; this stays as the cheap source pin, no longer as a substitute.
    """
    code = _strip_comments((SCRIPTS / "hapax-codex").read_text(encoding="utf-8"))
    pin_lines = [
        line.strip()
        for line in code.splitlines()
        if "export HAPAX_SESSION_ID=" in line and "printf" in line
    ]
    assert pin_lines, "hapax-codex's runner no longer pins a session id at all"
    for line in pin_lines:
        assert '"$SESSION_UUID"' in line, (
            f"the runner pins a literal rather than the minted variable: {line!r} — "
            "every re-exec would then carry the same identity"
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
        # 78 (sysexits EX_CONFIG), pinned because the code is the only thing a
        # caller reading a non-zero exit has to go on. hapax-methodology-dispatch
        # already returns 8 for "launcher not found" and 9 for "no declared model
        # pin"; these launchers used 9 too, so those three refusals were
        # indistinguishable by code.
        assert result.returncode == 78, (
            f"{name} refused with {result.returncode}, which collides with "
            "hapax-methodology-dispatch's own launch refusals (8, 9)"
        )
        combined = result.stdout + result.stderr
        assert "identity helper not found" in combined, (
            f"{name} failed without naming the cause or a remedy\n{combined}"
        )

    def test_two_launches_export_different_identities(self, tmp_path: Path) -> None:
        """The EXPORTED id must differ per launch — asserted by running it twice.

        The source conformance pins verify the launcher calls the helper. They
        cannot see what it exports: an in-memory mutation replacing five
        launchers' HAPAX_SESSION_ID exports with one constant left all 20 of them
        green. The helper can mint perfectly while every child still shares an
        identity, which is the original defect.

        The `session-role-<sid>` marker is written from the exported value, so two
        launches producing one marker means one identity was exported twice.
        """
        sids = []
        for _ in range(2):
            home = tmp_path / f"h{len(sids)}"
            env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
            for k in (
                "CLAUDE_ROLE",
                "HAPAX_AGENT_NAME",
                "HAPAX_AGENT_ROLE",
                "HAPAX_WORKTREE_ROLE",
            ):
                env.pop(k, None)
            env["HOME"] = str(home)
            env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
            env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
            subprocess.run(
                [str(SCRIPTS / "hapax-claude-headless"), "--task", "task-a", "zeta", "msg"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            markers = sorted((home / ".cache" / "hapax").glob("session-role-*"))
            assert len(markers) == 1, f"expected one marker, got {markers}"
            sids.append(markers[0].name.removeprefix("session-role-"))

        assert sids[0] != sids[1], (
            f"two launches minted the SAME identity ({sids[0]}) — every lane "
            "started this way keys one claim file"
        )
        assert all(is_claim_keyable_session_id(s) for s in sids)

    def test_the_identity_the_child_actually_receives_differs_per_launch(
        self, tmp_path: Path
    ) -> None:
        """Assert the EXPORTED value, via a stub harness — not the marker.

        The marker above is written from SESSION_UUID, so it cannot see a launcher
        that mints correctly and then exports something else: the reviewers'
        mutation (replace the HAPAX_SESSION_ID export with one constant) left both
        the source pins and the marker test green. `hapax-claude` resolves its
        harness with `command -v claude`, so a stub on PATH observes exactly what
        the child receives.
        """
        stub_dir = tmp_path / "bin"
        stub_dir.mkdir()
        stub = stub_dir / "claude"
        stub.write_text(
            '#!/bin/sh\nprintf "%s" "$HAPAX_SESSION_ID" > "$STUB_OUT"\n', encoding="utf-8"
        )
        stub.chmod(0o755)
        worktree = tmp_path / "wt"
        worktree.mkdir()

        seen = []
        for i in range(2):
            out = tmp_path / f"out{i}"
            env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
            for k in ("CLAUDE_ROLE", "HAPAX_AGENT_NAME", "HAPAX_AGENT_ROLE"):
                env.pop(k, None)
            env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
            env["HOME"] = str(tmp_path / "home")
            env["STUB_OUT"] = str(out)
            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPTS / "hapax-claude"),
                    "--role",
                    "zeta",
                    "--terminal",
                    "none",
                    "--cd",
                    str(worktree),
                    "--readonly",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            # FAIL, do not skip. A skip here lets a launch regression evade the
            # assertion entirely: the launcher failing to reach its harness is
            # itself the thing that would hide a broken identity path.
            assert out.exists(), (
                "hapax-claude never reached its harness, so the exported identity "
                f"was not observed: rc={result.returncode}\n{result.stderr.strip()[-400:]}"
            )
            seen.append(out.read_text().strip())

        assert seen[0] and seen[1], f"no identity reached the child: {seen}"
        assert seen[0] != seen[1], (
            f"both launches handed the child the SAME identity ({seen[0]}) — a "
            "launcher can mint correctly and still export a constant"
        )
        assert all(is_claim_keyable_session_id(s) for s in seen)

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


class TestCodexRunnerReentry:
    """The one legitimate inheritance, executed rather than read.

    hapax-codex writes a tmux runner that re-execs hapax-codex, and the pin exists
    so the inner process keeps the outer's id. Every other launcher mints. That
    makes this the central exception, and until round 14 it was covered only by
    source pins: the child-environment tests all use `--terminal none`, which is
    precisely the path that skips the runner.

    A stub `tmux` records the runner path instead of spawning it; the test then
    runs the runner itself with a stub `codex`, and reads what the grandchild got.
    """

    STUB_CODEX = (
        "#!/bin/sh\n"
        'if [ -n "${STUB_OUT:-}" ]; then\n'
        '  { printf "sid=%s\\n" "${HAPAX_SESSION_ID:-}"\n'
        '    printf "pinned=%s\\n" "${HAPAX_SESSION_ID_PINNED:-}"\n'
        '    printf "role=%s\\n" "${HAPAX_AGENT_ROLE:-}"\n'
        '  } > "$STUB_OUT"\n'
        "fi\n"
        # The saved-auth probe re-runs this binary with a narrow env and demands the
        # sentinel back as a JSON event; without it hapax-codex refuses first.
        "printf '%s\\n' "
        '\'{"type":"item.completed","item":{"type":"agent_message",'
        '"text":"HAPAX_CODEX_EXEC_AUTH_OK"}}\'\n'
    )

    STUB_TMUX = (
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  has-session) exit 1 ;;\n"
        "esac\n"
        'for a in "$@"; do last="$a"; done\n'
        'printf "%s\\n" "$last" >> "$TMUX_RECORD"\n'
        "exit 0\n"
    )

    def _launch(self, tmp_path: Path, tag: str) -> tuple[Path, Path, dict[str, str]]:
        """Run hapax-codex through the tmux path; return (runner, out, env)."""
        stub_dir = tmp_path / f"bin-{tag}"
        stub_dir.mkdir(parents=True, exist_ok=True)
        (stub_dir / "codex").write_text(self.STUB_CODEX, encoding="utf-8")
        (stub_dir / "codex").chmod(0o755)
        (stub_dir / "tmux").write_text(self.STUB_TMUX, encoding="utf-8")
        (stub_dir / "tmux").chmod(0o755)

        home = tmp_path / f"home-{tag}"
        (home / ".cache" / "hapax").mkdir(parents=True, exist_ok=True)
        workdir = tmp_path / f"wt-{tag}"
        workdir.mkdir(parents=True, exist_ok=True)
        record = tmp_path / f"tmux-{tag}.txt"
        out = tmp_path / f"out-{tag}.txt"

        env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
        for k in ("CLAUDE_ROLE", "HAPAX_AGENT_NAME", "HAPAX_AGENT_ROLE", "CODEX_ROLE"):
            env.pop(k, None)
        env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
        env["HOME"] = str(home)
        env["TMUX_RECORD"] = str(record)
        env["STUB_OUT"] = str(out)
        env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
        # The council dir supplies the codex hook adapter; the stub HOME has none.
        env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)

        result = subprocess.run(
            [
                "bash",
                str(SCRIPTS / "hapax-codex"),
                "--session",
                "cx-green",
                "--slot",
                "alpha",
                "--cd",
                str(workdir),
                "--terminal",
                "tmux",
                "--no-claim",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        assert record.is_file(), (
            "hapax-codex never reached its tmux spawn, so no runner was written: "
            f"rc={result.returncode}\n{result.stderr.strip()[-600:]}"
        )
        runner = Path(record.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert runner.is_file(), f"the recorded runner path does not exist: {runner}"
        return runner, out, env

    def _run_runner(self, runner: Path, out: Path, env: dict[str, str]) -> dict[str, str]:
        result = subprocess.run(
            ["bash", str(runner)],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        assert out.is_file(), (
            "the re-exec never reached the codex harness, so nothing was observed: "
            f"rc={result.returncode}\n{result.stderr.strip()[-600:]}"
        )
        observed: dict[str, str] = {}
        for line in out.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            observed[key] = value
        return observed

    def test_the_reexec_keeps_the_outer_identity_and_consumes_the_pin(self, tmp_path: Path) -> None:
        runner, out, env = self._launch(tmp_path, "a")
        runner_text = runner.read_text(encoding="utf-8")
        pinned = [
            line.split("=", 1)[1]
            for line in runner_text.splitlines()
            if line.startswith("export HAPAX_SESSION_ID=")
        ]
        assert pinned, f"the runner exports no session id:\n{runner_text}"
        outer = pinned[0].strip().strip("'\"")

        observed = self._run_runner(runner, out, env)

        assert observed["sid"] == outer, (
            "the inner hapax-codex minted a fresh id instead of keeping the outer's "
            f"({observed['sid']} != {outer}) — the outer's marker and any claim it "
            "already wrote are orphaned"
        )
        assert is_claim_keyable_session_id(observed["sid"])
        assert observed["pinned"] == "", (
            "the pin survived into the harness, so it is a standing grant over the "
            "whole lane subtree rather than one hop — the round-1 defect"
        )

    def test_a_second_launch_still_mints_a_different_identity(self, tmp_path: Path) -> None:
        """Preserving one re-exec must not make the launcher stop minting."""
        runner_a, out_a, env_a = self._launch(tmp_path, "a")
        runner_b, out_b, env_b = self._launch(tmp_path, "b")
        first = self._run_runner(runner_a, out_a, env_a)["sid"]
        second = self._run_runner(runner_b, out_b, env_b)["sid"]
        assert first and second and first != second, (
            f"two hapax-codex launches produced one identity ({first}) — every lane "
            "started this way keys the same claim file"
        )

    def test_a_grandchild_launcher_inside_the_lane_mints_its_own(self, tmp_path: Path) -> None:
        """TWO HOPS, through real launchers — the shape the round-1 defect had.

        The helper-level grandchild test resolves twice in one shell. Review round
        15 asked for confirmation that a launcher-level two-hop case exists, and it
        did not. This is it: hapax-codex -> its runner -> hapax-codex (the one
        legitimate inheritance) -> hapax-kimi started from inside that lane, which
        must mint. The shipped defect was a pin that survived hop one and let the
        grandchild adopt the lane's id, reconstructing the three-lane collision.
        """
        runner, out, env = self._launch(tmp_path, "gc")
        grandchild_out = tmp_path / "grandchild.txt"
        kimi_stub = tmp_path / "bin-gc" / "kimi-harness"
        kimi_stub.write_text(
            "#!/bin/sh\n"
            'printf "sid=%s\\npinned=%s\\n" "${HAPAX_SESSION_ID:-}" '
            '"${HAPAX_SESSION_ID_PINNED:-}" > "$GRANDCHILD_OUT"\n',
            encoding="utf-8",
        )
        kimi_stub.chmod(0o755)

        # The codex harness stub launches the SECOND launcher from inside the lane,
        # with exactly the environment that lane exports.
        codex_stub = tmp_path / "bin-gc" / "codex"
        codex_stub.write_text(
            self.STUB_CODEX.replace(
                "fi\n",
                'fi\nif [ -n "${GRANDCHILD_LAUNCHER:-}" ]; then\n'
                '  "$GRANDCHILD_LAUNCHER" zeta --terminal none >/dev/null 2>&1 || true\n'
                "fi\n",
                1,
            ),
            encoding="utf-8",
        )
        codex_stub.chmod(0o755)

        env = dict(env)
        env["GRANDCHILD_LAUNCHER"] = str(SCRIPTS / "hapax-kimi")
        env["GRANDCHILD_OUT"] = str(grandchild_out)
        env["KIMI_BIN"] = str(kimi_stub)

        lane = self._run_runner(runner, out, env)
        assert grandchild_out.is_file(), (
            "the grandchild launcher never reached its harness, so nothing was observed"
        )
        observed: dict[str, str] = {}
        for line in grandchild_out.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            observed[key] = value

        assert observed["sid"] != lane["sid"], (
            "a grandchild launcher adopted the lane's session id — the pin outlived "
            "the single re-exec it was written for, and three lanes key one claim file"
        )
        assert is_claim_keyable_session_id(observed["sid"])
        assert observed["pinned"] == "", "the pin reached the grandchild's harness"
