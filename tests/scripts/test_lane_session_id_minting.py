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


def _launch_session_id(env_overrides: dict[str, str]) -> str:
    """Run agent-role.sh ``hapax_launch_session_id`` under a controlled env."""
    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
    env.update(env_overrides)
    result = subprocess.run(
        ["bash", "-c", f'. "{AGENT_ROLE}"; hapax_launch_session_id'],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"helper failed: {result.stderr}"
    return result.stdout.strip()


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
        got = _launch_session_id({"HAPAX_SESSION_ID": pinned, "HAPAX_SESSION_ID_PINNED": "1"})
        assert got == pinned, (
            "a re-exec'd inner launcher minted a second id — it orphans the outer's "
            "session-role marker and any claim the outer already wrote"
        )

    def test_pin_without_an_id_still_mints(self) -> None:
        """The pin is not a license to return empty; it only selects a source."""
        got = _launch_session_id({"HAPAX_SESSION_ID_PINNED": "1"})
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
            {"HAPAX_SESSION_ID": "../../etc/passwd", "HAPAX_SESSION_ID_PINNED": "1"}
        )
        assert got != "../../etc/passwd"
        assert is_claim_keyable_session_id(got)


# --- Launcher conformance ----------------------------------------------------
# The behavioural contract above is carried by the helper; these pins assert the
# launchers actually route through it. Without them the helper can be correct
# while every launcher keeps its own inheriting copy — which is exactly the state
# this task found (hapax-claude-headless had the fix from #3875; five siblings
# never adopted it).

#: Launchers that start a NEW lane and must therefore mint.
MINTING_LAUNCHERS = (
    "hapax-claude",
    "hapax-claude-headless",
    "hapax-codex",
    "hapax-codex-headless",
    "hapax-vibe",
    "hapax-kimi",
)

#: The bare inheriting form the defect consisted of: `${HAPAX_SESSION_ID:-...}`
#: (parameter expansion with a default) anywhere a launch identity is computed.
_INHERITING_FORM = re.compile(r"SESSION_UUID=.*\$\{HAPAX_SESSION_ID:-")


@pytest.mark.parametrize("name", MINTING_LAUNCHERS)
def test_launcher_does_not_inherit_ambient_session_id(name: str) -> None:
    script = SCRIPTS / name
    assert script.is_file(), f"missing launcher {script}"
    text = script.read_text(encoding="utf-8")
    offenders = [line.strip() for line in text.splitlines() if _INHERITING_FORM.search(line)]
    assert not offenders, (
        f"{name} computes its launch identity from an ambient HAPAX_SESSION_ID: "
        f"{offenders} — use hapax_launch_session_id so inheritance requires an "
        "explicit HAPAX_SESSION_ID_PINNED=1"
    )


@pytest.mark.parametrize("name", MINTING_LAUNCHERS)
def test_launcher_routes_through_the_shared_helper(name: str) -> None:
    """A launcher that hand-rolls minting drifts from the helper's contract."""
    text = (SCRIPTS / name).read_text(encoding="utf-8")
    assert "hapax_launch_session_id" in text, (
        f"{name} does not call hapax_launch_session_id — its session identity is "
        "not governed by the tested helper"
    )


def test_codex_runner_pins_the_id_it_propagates() -> None:
    """The one legitimate inheritor must say so explicitly.

    hapax-codex's tmux runner re-execs hapax-codex. It already exports
    HAPAX_SESSION_ID; after this change that export alone is no longer honoured,
    so it must also export the pin or the inner process mints a divergent id.
    """
    text = (SCRIPTS / "hapax-codex").read_text(encoding="utf-8")
    assert "HAPAX_SESSION_ID_PINNED" in text, (
        "hapax-codex re-execs itself but does not pin the id it propagates — the "
        "inner launcher will mint a fresh one and orphan the outer's marker"
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
