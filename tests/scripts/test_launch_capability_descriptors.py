"""Capability descriptors must describe THIS launch, not the pane it started in.

``HAPAX_CAPABILITY_ROUTE`` and ``HAPAX_CAPABILITY_MODEL`` are read by
``shared.session_identity.capability_shape_from_env`` and land in a claim's
recorded condition vector. Nothing consumes them as input — they exist only to be
recorded — so an inherited one is a false measurement that reads as an observed
one.

Round 12 of review on PR #4668 reproduced the gap: they were cleared in
``hapax-methodology-dispatch`` and nowhere else, so running ``hapax-claude`` by
hand from inside a codex lane produced ``harness=claude,
model_family=gpt-5.3-codex, route=codex.headless.full``.

The repair reuses the shape already proven for the session id: an ADDRESSED,
consume-once grant. These pin both halves — the helper's own contract, and what
each launcher's child process actually receives.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROLE = REPO_ROOT / "hooks" / "scripts" / "agent-role.sh"
SCRIPTS = REPO_ROOT / "scripts"

sys.path.insert(0, str(REPO_ROOT))

from shared.session_identity import (  # noqa: E402
    capability_shape_from_env,
    is_claim_keyable_session_id,
)

DESCRIPTORS = ("HAPAX_CAPABILITY_ROUTE", "HAPAX_CAPABILITY_MODEL")

#: Everything the harness lane exports that would otherwise answer for the
#: subject under test. HAPAX_AGENT_NAME outranks the role, and CLAUDE_CODE_SESSION_ID
#: is always set under Claude Code.
_INHERITED_ENV = (
    "HAPAX_SESSION_ID",
    "HAPAX_SESSION_ID_PINNED",
    "HAPAX_CAPABILITY_PINNED",
    "HAPAX_CAPABILITY_ROUTE",
    "HAPAX_CAPABILITY_MODEL",
    "HAPAX_CLAUDE_MODEL",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_ROLE",
    "CODEX_SESSION",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_SLOT",
    "HAPAX_AGENT_INTERFACE",
    "HAPAX_WORKTREE_ROLE",
    "HAPAX_DISPATCH_HOST",
)


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _INHERITED_ENV}


def _strip_comments(text: str) -> str:
    """Shell source with comment lines removed.

    Round 1 found the conformance pins in the sibling suite vacuous because the
    comments explaining a mechanism contained the strings being asserted. Same
    trap, same guard.
    """
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


def _helper(script: str, env_overrides: dict[str, str]) -> dict[str, str]:
    """Run `script` after sourcing agent-role.sh; parse its `k=v` stdout."""
    env = _clean_env()
    env.update(env_overrides)
    result = subprocess.run(
        ["bash", "-c", f'. "{AGENT_ROLE}"\n{script}'],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"helper failed: {result.stderr}"
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        out[key] = value
    return out


_REPORT = "\n".join(
    f"printf '{name}=%s\\n' \"${{{name}:-}}\"" for name in (*DESCRIPTORS, "HAPAX_CAPABILITY_PINNED")
)


class TestTheGrant:
    """The helper alone, with no launcher around it."""

    def test_unaddressed_descriptors_are_cleared(self) -> None:
        """The reproduction: a codex pane's route reaching a claude launch."""
        seen = _helper(
            f"hapax_consume_launch_capability_descriptors\n{_REPORT}",
            {
                "HAPAX_CAPABILITY_ROUTE": "codex.headless.full",
                "HAPAX_CAPABILITY_MODEL": "gpt-5.3-codex",
            },
        )
        assert seen["HAPAX_CAPABILITY_ROUTE"] == ""
        assert seen["HAPAX_CAPABILITY_MODEL"] == ""

    def test_descriptors_addressed_to_this_launcher_survive(self) -> None:
        seen = _helper(
            f"hapax_consume_launch_capability_descriptors hapax-claude-headless\n{_REPORT}",
            {
                "HAPAX_CAPABILITY_PINNED": "hapax-claude-headless",
                "HAPAX_CAPABILITY_ROUTE": "claude.headless.opus",
                "HAPAX_CAPABILITY_MODEL": "opus",
            },
        )
        assert seen["HAPAX_CAPABILITY_ROUTE"] == "claude.headless.opus"
        assert seen["HAPAX_CAPABILITY_MODEL"] == "opus"

    @pytest.mark.parametrize("pin", ["hapax-codex-headless", "1", "true", "yes", ""])
    def test_a_pin_addressed_elsewhere_does_not_authorise_us(self, pin: str) -> None:
        """No truthy form. `=1` addresses a launcher named "1", so nothing honours it."""
        seen = _helper(
            f"hapax_consume_launch_capability_descriptors hapax-claude-headless\n{_REPORT}",
            {
                "HAPAX_CAPABILITY_PINNED": pin,
                "HAPAX_CAPABILITY_ROUTE": "codex.headless.full",
            },
        )
        assert seen["HAPAX_CAPABILITY_ROUTE"] == ""

    def test_the_grant_is_consumed_even_when_honoured(self) -> None:
        """Otherwise the pin authorises the whole subtree.

        This is the exact defect the session-id pin shipped with in round 1: a
        standing grant let a grandchild launcher adopt descriptors addressed to its
        parent. Consumed means one hop, so a child launcher sees no pin and clears.
        """
        seen = _helper(
            f"hapax_consume_launch_capability_descriptors hapax-codex-headless\n{_REPORT}",
            {
                "HAPAX_CAPABILITY_PINNED": "hapax-codex-headless",
                "HAPAX_CAPABILITY_ROUTE": "codex.headless.full",
            },
        )
        assert seen["HAPAX_CAPABILITY_ROUTE"] == "codex.headless.full"
        assert seen["HAPAX_CAPABILITY_PINNED"] == "", (
            "the grant outlived the call — every descendant is now authorised"
        )

    def test_the_grant_is_consumed_when_it_was_not_honoured(self) -> None:
        seen = _helper(
            f"hapax_consume_launch_capability_descriptors hapax-vibe\n{_REPORT}",
            {"HAPAX_CAPABILITY_PINNED": "hapax-codex-headless"},
        )
        assert seen["HAPAX_CAPABILITY_PINNED"] == "", (
            "a pin nothing honoured lingered, and something downstream may"
        )

    def test_the_clear_reaches_children_of_the_calling_shell(self) -> None:
        """`unset` in a subshell would leave the child's environment untouched."""
        seen = _helper(
            "hapax_consume_launch_capability_descriptors\n"
            "env | grep -E '^HAPAX_CAPABILITY_(ROUTE|MODEL)=' || true\n"
            "printf 'done=1\\n'",
            {
                "HAPAX_CAPABILITY_ROUTE": "codex.headless.full",
                "HAPAX_CAPABILITY_MODEL": "gpt-5.3-codex",
            },
        )
        assert seen == {"done": "1"}, f"a descriptor survived into the child env: {seen}"

    def test_a_launcher_input_is_not_in_the_set(self) -> None:
        """HAPAX_CLAUDE_MODEL decides `--model`; clearing it would break a launch.

        `HAPAX_CLAUDE_MODEL=opus hapax-claude-headless <lane> <prompt>` is a
        documented operator invocation. The record is fixed by not READING an
        input, not by destroying one.
        """
        seen = _helper(
            "hapax_consume_launch_capability_descriptors\n"
            "printf 'HAPAX_CLAUDE_MODEL=%s\\n' \"${HAPAX_CLAUDE_MODEL:-}\"",
            {"HAPAX_CLAUDE_MODEL": "opus"},
        )
        assert seen["HAPAX_CLAUDE_MODEL"] == "opus"


LAUNCHERS = (
    "hapax-claude",
    "hapax-claude-headless",
    "hapax-codex",
    "hapax-codex-headless",
    "hapax-vibe",
    "hapax-kimi",
)

#: Launchers a dispatcher hands a route to, and the addressee each must consume.
PINNED_LAUNCHERS = {
    "hapax-claude-headless": "hapax-claude-headless",
    "hapax-codex-headless": "hapax-codex-headless",
}

#: How to drive each launcher all the way to its harness, so a stub can observe
#: the environment the child actually receives. Every launcher is here: the
#: finding was that behavioural coverage existed for Claude alone, so an omission
#: would reproduce it.
_DRIVE_ARGS = {
    "hapax-claude": lambda wt: [
        "--role",
        "zeta",
        "--terminal",
        "none",
        "--cd",
        str(wt),
        "--readonly",
    ],
    "hapax-claude-headless": lambda wt: ["--task", "task-a", "zeta", "governed msg"],
    "hapax-codex": lambda wt: [
        "--session",
        "cx-green",
        "--slot",
        "alpha",
        "--terminal",
        "none",
        "--cd",
        str(wt),
        "--no-claim",
    ],
    "hapax-codex-headless": lambda wt: [
        "--force",
        "--task",
        "task-a",
        "cx-green",
        "governed msg",
    ],
    "hapax-vibe": lambda wt: [
        "--session",
        "vbe-9",
        "--terminal",
        "none",
        "--cd",
        str(wt),
        "--no-claim",
    ],
    "hapax-kimi": lambda wt: ["zeta", "--terminal", "none"],
}
_DRIVABLE = set(_DRIVE_ARGS)


@pytest.mark.parametrize("name", LAUNCHERS)
def test_every_launcher_consumes_the_grant(name: str) -> None:
    code = _strip_comments((SCRIPTS / name).read_text(encoding="utf-8"))
    assert "hapax_consume_launch_capability_descriptors" in code, (
        f"{name} never clears inherited capability descriptors — a claim it writes "
        "can record the route of the pane it was started from"
    )
    bad = [
        line.strip()
        for line in code.splitlines()
        if "hapax_consume_launch_capability_descriptors" in line and "$(" in line
    ]
    assert not bad, (
        f"{name} calls the helper inside a command substitution: {bad} — the unset "
        "happens in a subshell and the descriptors reach the child anyway"
    )


@pytest.mark.parametrize("name", LAUNCHERS)
def test_only_a_dispatched_launcher_names_an_addressee(name: str) -> None:
    """An addressee is a claim that something legitimately pins this launcher.

    Passing one where nothing does would let any ancestor exporting the right
    string hand this launcher its own descriptors.
    """
    code = _strip_comments((SCRIPTS / name).read_text(encoding="utf-8"))
    calls = [
        line.strip()
        for line in code.splitlines()
        if line.strip().startswith("hapax_consume_launch_capability_descriptors")
    ]
    assert calls, f"{name} has no call to pin"
    expected = PINNED_LAUNCHERS.get(name)
    for call in calls:
        argument = call.split(maxsplit=1)[1] if " " in call else ""
        assert argument == (expected or ""), (
            f"{name} consumes the grant as {argument!r}; expected {expected or 'no addressee'}"
        )


def test_the_dispatcher_addresses_the_launcher_it_pins() -> None:
    """The two halves of the grant must name the same launcher.

    A pin the launcher does not answer to is silently equivalent to no pin: the
    route is cleared and the lane records no shape. That is safe but wrong, and
    nothing else would notice.
    """
    code = _strip_comments((SCRIPTS / "hapax-methodology-dispatch").read_text(encoding="utf-8"))
    for addressee in PINNED_LAUNCHERS.values():
        assert f'"{addressee}"' in code, (
            f"hapax-methodology-dispatch never addresses a pin to {addressee}"
        )
    assert "_scrub_capability_descriptors" not in code, (
        "the scrub is back alongside the pin — two mitigations for one hazard, and "
        "the scrub still cannot see a by-hand launch"
    )


class TestWhatTheChildReceives:
    """Run the launchers to their harness and read the environment it got.

    Source pins cannot see this. Round 12's finding was exactly that: in-memory
    mutations replacing the exported HAPAX_SESSION_ID with a constant in
    hapax-codex-headless and hapax-vibe left all 25 source conformance checks
    passing. A stub harness on PATH observes what the child actually receives.
    """

    #: Records the environment it was handed, and always answers the Codex saved-auth
    #: probe. That probe re-runs the same binary with a deliberately narrow env (no
    #: STUB_OUT) and demands the sentinel back, so a stub that only wrote a file made
    #: hapax-codex refuse before ever reaching its real exec.
    STUB = (
        "#!/bin/sh\n"
        'if [ -n "${STUB_OUT:-}" ]; then\n'
        '  { printf "sid=%s\\n" "${HAPAX_SESSION_ID:-}"\n'
        '    printf "route=%s\\n" "${HAPAX_CAPABILITY_ROUTE:-}"\n'
        '    printf "capmodel=%s\\n" "${HAPAX_CAPABILITY_MODEL:-}"\n'
        '    printf "harness=%s\\n" "${HAPAX_AGENT_INTERFACE:-}"\n'
        '    printf "pinned=%s\\n" "${HAPAX_CAPABILITY_PINNED:-}"\n'
        '  } > "$STUB_OUT"\n'
        "fi\n"
        "printf '%s\\n' "
        '\'{"type":"item.completed","item":{"type":"agent_message",'
        '"text":"HAPAX_CODEX_EXEC_AUTH_OK"}}\'\n'
    )

    def _stub_dir(self, tmp_path: Path) -> Path:
        stub_dir = tmp_path / "bin"
        stub_dir.mkdir(parents=True, exist_ok=True)
        for harness in ("claude", "codex", "vibe", "kimi"):
            stub = stub_dir / harness
            stub.write_text(self.STUB, encoding="utf-8")
            stub.chmod(0o755)
        return stub_dir

    def _run(self, name: str, tmp_path: Path, extra_env: dict[str, str]) -> dict[str, str]:
        """Drive one launcher to its harness; return the child's observed env."""
        stub_dir = self._stub_dir(tmp_path)
        home = tmp_path / "home"
        (home / ".cache" / "hapax").mkdir(parents=True, exist_ok=True)
        workdir = tmp_path / "wt"
        workdir.mkdir(parents=True, exist_ok=True)
        # hapax-claude-headless refuses a mutating launch it cannot claim through.
        claim_stub = workdir / "scripts" / "cc-claim"
        claim_stub.parent.mkdir(parents=True, exist_ok=True)
        claim_stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        claim_stub.chmod(0o755)
        out = tmp_path / f"out-{name}"

        env = _clean_env()
        env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
        env["HOME"] = str(home)
        env["STUB_OUT"] = str(out)
        env["KIMI_BIN"] = str(stub_dir / "kimi")
        # hapax-vibe refuses without one; the stub harness never reads it.
        env["MISTRAL_API_KEY"] = "stub"  # pragma: allowlist secret
        env["HAPAX_KIMI_WORKDIR"] = str(workdir)
        env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
        # The two headless launchers refuse without a governed enable; that refusal
        # is a different subject, tested where it lives.
        env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
        env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
        env["HAPAX_CLAUDE_HEADLESS_WORKDIR"] = str(workdir)
        env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
        # The council dir supplies the codex hook adapter; the stub HOME has none.
        env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
        # hapax-claude-headless takes a per-lane launcher lock under XDG_RUNTIME_DIR.
        # Left at the real one, the second run of a pair refuses as a duplicate.
        runtime = tmp_path / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        env["XDG_RUNTIME_DIR"] = str(runtime)
        env["HAPAX_CLAUDE_HEADLESS_PIPE_DIR"] = str(runtime / "hapax-claude")
        env.update(extra_env)

        result = subprocess.run(
            ["bash", str(SCRIPTS / name), *_DRIVE_ARGS[name](workdir)],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        # FAIL, never skip: a launcher that cannot reach its harness is itself the
        # thing that would hide a broken identity path.
        assert out.exists(), (
            f"{name} never reached its harness, so nothing was observed: "
            f"rc={result.returncode}\n{result.stderr.strip()[-600:]}"
        )
        observed: dict[str, str] = {}
        for line in out.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            observed[key] = value
        return observed

    @pytest.mark.parametrize("name", sorted(_DRIVABLE))
    def test_the_child_gets_a_freshly_minted_identity(self, name: str, tmp_path: Path) -> None:
        """An ambient id must not survive into the child, and must not repeat."""
        ambient = "041482e9-0535-4502-a3f2-100149a03a8c"
        seen = []
        for i in range(2):
            observed = self._run(name, tmp_path / f"run{i}", {"HAPAX_SESSION_ID": ambient})
            assert observed["sid"] != ambient, (
                f"{name} handed its child an ambient session id — every lane "
                "started from this pane keys one claim file"
            )
            assert is_claim_keyable_session_id(observed["sid"]), (
                f"{name} exported an id cc-claim will refuse: {observed['sid']!r}"
            )
            seen.append(observed["sid"])
        assert seen[0] != seen[1], (
            f"{name} handed both launches the SAME identity ({seen[0]}) — a launcher "
            "can mint correctly and still export a constant"
        )

    @pytest.mark.parametrize("name", sorted(_DRIVABLE))
    def test_the_child_does_not_inherit_another_launch_s_descriptors(
        self, name: str, tmp_path: Path
    ) -> None:
        """Round 12's reproduction, run through each launcher."""
        observed = self._run(
            name,
            tmp_path,
            {
                "HAPAX_CAPABILITY_ROUTE": "codex.headless.full",
                "HAPAX_CAPABILITY_MODEL": "gpt-5.3-codex",
            },
        )
        shape = capability_shape_from_env(
            {
                "HAPAX_AGENT_INTERFACE": observed["harness"],
                "HAPAX_CAPABILITY_ROUTE": observed["route"],
                "HAPAX_CAPABILITY_MODEL": observed["capmodel"],
            }
        )
        assert shape["route"] is None, (
            f"{name} would record route={shape['route']} for a launch that never ran on it"
        )
        assert shape["model_family"] is None, (
            f"{name} would record model_family={shape['model_family']} for a launch "
            "that never ran on it"
        )

    @pytest.mark.parametrize("name", sorted(set(PINNED_LAUNCHERS) & _DRIVABLE))
    def test_an_addressed_route_does_reach_the_child(self, name: str, tmp_path: Path) -> None:
        """The other direction: clearing everything would be safe and useless.

        item 3's whole point is that a capability number carries its condition
        vector, so a dispatched lane must still record one.
        """
        observed = self._run(
            name,
            tmp_path,
            {
                "HAPAX_CAPABILITY_PINNED": PINNED_LAUNCHERS[name],
                "HAPAX_CAPABILITY_ROUTE": "codex.headless.full",
            },
        )
        assert observed["route"] == "codex.headless.full", (
            f"{name} dropped a route addressed to it — a dispatched lane records no "
            "capability shape at all"
        )
        assert observed["pinned"] == "", (
            f"{name} passed the grant on to its own child — it authorises one hop"
        )


class TestTheRunnerCleansToo:
    """The tmux boundary: the runner does NOT inherit the launcher's environment.

    `tmux new-session` hands the runner the SERVER's environment, which can be days
    old. So a launcher that cleans its own shell has cleaned the wrong one, and the
    descriptor tests all use `--terminal none`, the path with no runner at all.
    Review round 16 executed the shipped Claude runner with stale server descriptors
    and watched `route=codex.headless.full` reach the child.

    These run the generated runner under an environment the launcher never saw.
    """

    RUNNER_DIRS = {
        "hapax-claude": "claude-spawns",
        "hapax-kimi": "kimi-spawns",
        "hapax-vibe": "vibe-spawns",
    }

    @pytest.mark.parametrize("name", sorted(RUNNER_DIRS))
    def test_a_stale_server_environment_does_not_reach_the_harness(
        self, name: str, tmp_path: Path
    ) -> None:
        stub_dir = tmp_path / "bin"
        stub_dir.mkdir(parents=True, exist_ok=True)
        stub = (
            "#!/bin/sh\n"
            '{ printf "route=%s\\n" "${HAPAX_CAPABILITY_ROUTE:-}"\n'
            '  printf "capmodel=%s\\n" "${HAPAX_CAPABILITY_MODEL:-}"\n'
            '  printf "pinned=%s\\n" "${HAPAX_CAPABILITY_PINNED:-}"\n'
            '  printf "sidpin=%s\\n" "${HAPAX_SESSION_ID_PINNED:-}"\n'
            '} > "$STUB_OUT"\n'
        )
        for harness in ("claude", "kimi", "vibe"):
            (stub_dir / harness).write_text(stub, encoding="utf-8")
            (stub_dir / harness).chmod(0o755)

        home = tmp_path / "home"
        (home / ".cache" / "hapax").mkdir(parents=True, exist_ok=True)
        workdir = tmp_path / "wt"
        workdir.mkdir(parents=True, exist_ok=True)
        out = tmp_path / "out.txt"

        # A tmux STUB that only records: the runner must be executed separately,
        # under a DIFFERENT environment, which is the whole point.
        record = tmp_path / "tmux.txt"
        (stub_dir / "tmux").write_text(
            "#!/bin/sh\n"
            'case "$1" in has-session) exit 1 ;; esac\n'
            'for a in "$@"; do last="$a"; done\n'
            'printf "%s\\n" "$last" >> "$TMUX_RECORD"\n'
            "exit 0\n",
            encoding="utf-8",
        )
        (stub_dir / "tmux").chmod(0o755)

        launch_env = _clean_env()
        launch_env["PATH"] = f"{stub_dir}:{launch_env.get('PATH', '')}"
        launch_env["HOME"] = str(home)
        launch_env["TMUX_RECORD"] = str(record)
        launch_env["KIMI_BIN"] = str(stub_dir / "kimi")
        launch_env["MISTRAL_API_KEY"] = "stub"  # pragma: allowlist secret
        launch_env["HAPAX_KIMI_WORKDIR"] = str(workdir)
        launch_env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
        launch_env["HAPAX_SDLC_SLICE_ATTACH"] = "0"

        args = {
            "hapax-claude": [
                "--role",
                "zeta",
                "--terminal",
                "tmux",
                "--cd",
                str(workdir),
                "--readonly",
            ],
            "hapax-kimi": ["zeta"],
            "hapax-vibe": [
                "--session",
                "vbe-9",
                "--terminal",
                "tmux",
                "--cd",
                str(workdir),
                "--no-claim",
            ],
        }[name]
        result = subprocess.run(
            ["bash", str(SCRIPTS / name), *args],
            env=launch_env,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        assert record.is_file(), (
            f"{name} never reached its tmux spawn, so no runner was written: "
            f"rc={result.returncode}\n{result.stderr.strip()[-600:]}"
        )
        runner = Path(record.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert runner.is_file(), f"the recorded runner path does not exist: {runner}"

        # The stale server environment. The launcher never saw these — they are what
        # a long-lived tmux server still carries from whatever started it.
        server_env = dict(launch_env)
        server_env["STUB_OUT"] = str(out)
        server_env["HAPAX_CAPABILITY_ROUTE"] = "codex.headless.full"
        server_env["HAPAX_CAPABILITY_MODEL"] = "gpt-6-astra"
        server_env["HAPAX_CAPABILITY_PINNED"] = "hapax-codex-headless"
        server_env["HAPAX_SESSION_ID_PINNED"] = "hapax-codex"
        run = subprocess.run(
            ["bash", str(runner)],
            env=server_env,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        assert out.is_file(), (
            f"{name}'s runner never reached its harness: rc={run.returncode}\n"
            f"{run.stderr.strip()[-600:]}"
        )
        observed: dict[str, str] = {}
        for line in out.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            observed[key] = value

        assert observed["route"] == "", (
            f"{name}'s runner handed the harness a stale server route "
            f"({observed['route']}) — it would be recorded as this launch's"
        )
        assert observed["capmodel"] == "", observed
        assert observed["pinned"] == "" and observed["sidpin"] == "", (
            f"{name}'s runner passed a stale grant through to the harness: {observed}"
        )


def _extract_bash_function(source: Path, name: str) -> str:
    """The shipped text of one top-level bash function, by name.

    Both headless launchers build their SSH payload in a `python3` heredoc inside a
    top-level function. Running that function is the only way to see what actually
    crosses the boundary; asserting on the source would be asserting on a list of
    strings, which is what let the claude path's allowlist and the codex path's
    diverge in the first place.
    """
    import re

    lines = source.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    except StopIteration:  # pragma: no cover - a rename should fail loudly
        raise AssertionError(f"{source.name} has no top-level function {name}()") from None

    # Skip heredoc bodies when looking for the closing brace. The payload builders
    # embed a Python dict literal whose own `}` sits at column 0, so a naive scan
    # for the first unindented `}` truncates the function mid-heredoc and the
    # extracted text will not parse.
    end = None
    heredoc: str | None = None
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if heredoc is not None:
            if line.strip() == heredoc:
                heredoc = None
            continue
        opener = re.search(r"<<-?'?([A-Za-z_][A-Za-z0-9_]*)'?", line)
        if opener:
            heredoc = opener.group(1)
            continue
        if line == "}":
            end = i
            break
    assert end is not None, f"no closing brace found for {name}() in {source.name}"
    return "\n".join(lines[start : end + 1])


class TestWhatCrossesTheSshBoundary:
    """Remote execution starts the harness directly — no launcher runs over there.

    So whatever the payload omits is simply not recorded by the remote lane's
    claims. The claude path forwarded the descriptors; the codex path did not, and
    round 13 measured that neither reached its payload. These run both builders.
    """

    def _payload_env(self, script: str, preamble: str, call: str, env: dict[str, str]) -> dict:
        import base64
        import json

        full = "\n".join(["set -euo pipefail", preamble, script, call])
        merged = _clean_env()
        merged.update(env)
        result = subprocess.run(
            ["bash", "-c", full],
            env=merged,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, f"payload builder failed: {result.stderr}"
        payload = json.loads(base64.b64decode(result.stdout.strip()))
        return payload.get("env", {})

    def test_codex_remote_exec_carries_the_condition_vector(self) -> None:
        script = _extract_bash_function(SCRIPTS / "hapax-codex-headless", "remote_exec_payload_b64")
        env = self._payload_env(
            script,
            preamble="\n".join(
                [
                    'WORKDIR="/tmp/wt"',
                    'DISPATCH_HOST_REQUESTED="appendix"',
                    'LOGOS_BASE_URL="http://localhost:8051"',
                    'COCKPIT_BASE_URL="http://localhost:8050"',
                    'SESSION="cx-green"',
                    'CODEX_TASK="task-a"',
                ]
            ),
            call='remote_exec_payload_b64 "/tmp/proof" codex exec',
            env={
                "HAPAX_CAPABILITY_ROUTE": "codex.headless.full",
                "HAPAX_CAPABILITY_MODEL": "gpt-5.3-codex",
                "HAPAX_SESSION_ID": "ef3687f5-601c-4a82-9c6e-d97de6dce2c2",
            },
        )
        assert env.get("HAPAX_CAPABILITY_ROUTE") == "codex.headless.full", (
            "the remote codex lane records no route, so every claim it writes has "
            f"no condition vector: {sorted(env)}"
        )
        assert env.get("HAPAX_CAPABILITY_MODEL") == "gpt-5.3-codex"

    def test_claude_remote_exec_carries_the_condition_vector(self) -> None:
        script = _extract_bash_function(SCRIPTS / "hapax-claude-headless", "remote_payload_b64")
        env = self._payload_env(
            script,
            preamble="",
            call=(
                'remote_payload_b64 exec "/tmp/wt" "http://localhost:8051" '
                '"appendix" "/tmp/proof" claude'
            ),
            env={
                "HAPAX_CAPABILITY_ROUTE": "claude.headless.opus",
                "HAPAX_CAPABILITY_MODEL": "opus",
                "HAPAX_SESSION_ID": "ef3687f5-601c-4a82-9c6e-d97de6dce2c2",
            },
        )
        assert env.get("HAPAX_CAPABILITY_ROUTE") == "claude.headless.opus", (
            f"the remote claude lane records no route: {sorted(env)}"
        )
        assert env.get("HAPAX_CAPABILITY_MODEL") == "opus"

    def test_an_absent_descriptor_is_omitted_rather_than_sent_empty(self) -> None:
        """An empty string would render as `route=` — a recorded emptiness.

        Both builders filter falsey values, and both must keep doing so: the whole
        contract of this field is that an unanswerable one stays unrecorded.
        """
        script = _extract_bash_function(SCRIPTS / "hapax-codex-headless", "remote_exec_payload_b64")
        env = self._payload_env(
            script,
            preamble="\n".join(
                [
                    'WORKDIR="/tmp/wt"',
                    'DISPATCH_HOST_REQUESTED=""',
                    'LOGOS_BASE_URL="http://localhost:8051"',
                    'COCKPIT_BASE_URL="http://localhost:8050"',
                    'SESSION="cx-green"',
                    'CODEX_TASK="task-a"',
                ]
            ),
            call='remote_exec_payload_b64 "/tmp/proof" codex exec',
            env={"HAPAX_CAPABILITY_ROUTE": "", "HAPAX_CAPABILITY_MODEL": ""},
        )
        assert not env.get("HAPAX_CAPABILITY_ROUTE")
        assert not env.get("HAPAX_CAPABILITY_MODEL")
