"""Tests for the dead-pane forensics leg of the FM-11 lane supervisor.

The gap these pin: on 2026-09-16T01:19:34Z a lane's claude died leaving no
coredump, no kernel line, no oomd record and no killer — and tmux tore the pane
down with the process, so there was nothing left to interrogate. The cause was
not merely unknown, it was *unmeasurable*.

Two changes close it, and neither is correct alone:

1. The launchers (``hapax-claude``, ``hapax-codex``) set ``remain-on-exit
   failed`` on the lane window, so a signal death or a non-zero exit RETAINS the
   pane with its status, signal and scrollback intact. A clean exit still closes
   it, so an orderly stop is never mistaken for a death.
2. The supervisor stops treating ``has-session`` as liveness. A retained dead
   pane keeps the SESSION alive, so change (1) on its own would make every dead
   lane look healthy to the supervisor and it would never respawn — FM-11
   defeated by the very change meant to make deaths legible. ``guard`` now reads
   the corpse into ``~/.cache/hapax/tmux-pane-exits/`` and kills the session
   only afterwards, so the launcher can start again.

The ordering is the substance of the fix: kill the session first and the
evidence is gone exactly as it was before any of this existed.

Real-tmux cases run on a PRIVATE socket (``tmux -L <probe>``) via a wrapper on
PATH — never against the live lanes' default server.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"
CLAUDE_LAUNCHER = REPO_ROOT / "scripts" / "hapax-claude"
CODEX_LAUNCHER = REPO_ROOT / "scripts" / "hapax-codex"


# ── helpers ──────────────────────────────────────────────────────────────────


def _write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _write_recorder(path: Path, log: Path) -> None:
    _write_executable(path, f'#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "{log}"\n')


#: A scriptable fake tmux. Every invocation is appended to ``$TMUX_CALL_LOG`` so a
#: test can assert not just WHICH tmux commands ran but in what ORDER — which is
#: the only way to pin "capture before kill".
#:
#: It models three things real tmux does that a naive stub would hide:
#:
#: * Target resolution. ``=name`` is exact; a BARE name also prefix-matches, so a
#:   bare target for a missing lane resolves to a sibling whose name extends it
#:   (measured on tmux 3.7c: with only ``hapax-claude-delta-2`` running,
#:   ``has-session -t hapax-claude-delta`` succeeded and a bare ``kill-session``
#:   killed the sibling). The sibling exists when ``FAKE_TMUX_SIBLING_EXISTS=1``.
#: * ``list-panes -a`` lists EVERY session's panes; without ``-a`` only one window's.
#:   The sibling's pane is live unless ``FAKE_TMUX_SIBLING_PANE_DEAD`` says otherwise,
#:   so a supervisor that forgets to filter on the exact session name reads a dead
#:   lane as alive on the strength of its neighbour.
#: * ``FAKE_TMUX_FAIL="display-message capture-pane"`` makes those commands fail, to
#:   exercise the fallback strings in the forensics log.
_FAKE_TMUX = r"""
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$TMUX_CALL_LOG"
cmd="${1:-}"; shift || true
lane="${FAKE_TMUX_SESSION_NAME:-hapax-claude-delta}"
sibling="$lane-2"
fail_on() { case " ${FAKE_TMUX_FAIL:-} " in *" $1 "*) return 0 ;; esac; return 1; }
target_of() { while [ "$#" -gt 0 ]; do case "$1" in -t) printf '%s\n' "${2:-}"; return 0 ;; esac; shift; done; return 1; }
resolve() {  # <target> -> session name on stdout, or non-zero
  case "$1" in
    "=$lane"|"=$lane:")
      [ "${FAKE_TMUX_SESSION_EXISTS:-0}" = "1" ] && { printf '%s\n' "$lane"; return 0; }; return 1 ;;
    "$lane"|"$lane:")
      [ "${FAKE_TMUX_SESSION_EXISTS:-0}" = "1" ] && { printf '%s\n' "$lane"; return 0; }
      [ "${FAKE_TMUX_SIBLING_EXISTS:-0}" = "1" ] && { printf '%s\n' "$sibling"; return 0; }
      return 1 ;;
    "=$sibling"|"$sibling"|"=$sibling:"|"$sibling:")
      [ "${FAKE_TMUX_SIBLING_EXISTS:-0}" = "1" ] && { printf '%s\n' "$sibling"; return 0; }; return 1 ;;
    *) return 1 ;;
  esac
}
case "$cmd" in
  has-session)
    resolve "$(target_of "$@")" >/dev/null && exit 0
    exit 1
    ;;
  kill-session)
    r="$(resolve "$(target_of "$@")")" || exit 1
    printf 'killed %s\n' "$r" >> "$TMUX_CALL_LOG"
    exit 0
    ;;
  list-panes)
    fmt=""; all=0; tgt=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        -F) fmt="${2:-}"; shift 2 ;;
        -a) all=1; shift ;;
        -t) tgt="${2:-}"; shift 2 ;;
        *) shift ;;
      esac
    done
    row() { case "$fmt" in *'#{session_name}'*) printf '%s\t%s\n' "$1" "$2" ;; *) printf '%s\n' "$2" ;; esac; }
    lane_values() {
      case "$fmt" in
        *'#{pane_dead}'*) printf '%s\n' ${FAKE_TMUX_PANE_DEAD-} ;;
        *'#{pane_id}'*)   printf '%s\n' ${FAKE_TMUX_PANE_IDS-} ;;
        *)                printf 'status= signal=9\n' ;;
      esac
    }
    sibling_value() {
      case "$fmt" in
        *'#{pane_dead}'*) printf '%s\n' "${FAKE_TMUX_SIBLING_PANE_DEAD:-0}" ;;
        *'#{pane_id}'*)   printf '%%9\n' ;;
        *)                printf 'status= signal=\n' ;;
      esac
    }
    if [ "$all" = "1" ]; then
      if [ "${FAKE_TMUX_SESSION_EXISTS:-0}" = "1" ]; then
        while IFS= read -r v; do [ -n "$v" ] && row "$lane" "$v"; done <<< "$(lane_values)"
      fi
      if [ "${FAKE_TMUX_SIBLING_EXISTS:-0}" = "1" ]; then
        row "$sibling" "$(sibling_value)"
      fi
      exit 0
    fi
    # Without -a tmux reports ONE window's panes (the target's current window).
    # Reading only that is a real regression — a lane whose active window died
    # would read as alive on the strength of another — so the fake shows it.
    r="$(resolve "$tgt")" || exit 1
    if [ "$r" = "$lane" ]; then
      v="$(lane_values | head -1)"; [ -n "$v" ] && row "$lane" "$v"
    else
      row "$sibling" "$(sibling_value)"
    fi
    exit 0
    ;;
  display-message)
    fail_on display-message && exit 1
    printf 'pane: %%0 pane_dead=1 pane_dead_status= pane_dead_signal=9'
    printf ' pane_dead_time=1789532946 pane_start_command="fake-runner"\n'
    exit 0
    ;;
  capture-pane)
    fail_on capture-pane && exit 1
    printf 'FAKE-SCROLLBACK-LINE\n'
    exit 0
    ;;
  *) exit 0 ;;
esac
"""


def _base(tmp_path: Path, **overrides: str) -> dict[str, object]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "calls"
    pane_logs = tmp_path / "pane-exits"
    for d in (home / "projects", bin_dir, calls, pane_logs):
        d.mkdir(parents=True, exist_ok=True)

    tmux_call_log = tmp_path / "tmux-calls.txt"
    _write_executable(bin_dir / "tmux", _FAKE_TMUX)
    _write_recorder(bin_dir / "hapax-claude", calls / "claude.txt")
    _write_recorder(bin_dir / "hapax-codex", calls / "codex.txt")
    _write_recorder(bin_dir / "hapax-claude-headless", calls / "claude-headless.txt")

    env = os.environ.copy()
    # The lane's own identity and dispatch-host env leak into fixtures and change
    # the branch under test (HAPAX_DISPATCH_HOST=local flips the supervisor into
    # appendix-only maintenance, which suppresses the very respawn we assert).
    for leaky in (
        "CLAUDE_ROLE",
        "HAPAX_AGENT_NAME",
        "HAPAX_AGENT_ROLE",
        "HAPAX_DISPATCH_HOST",
        "HAPAX_DEFAULT_DISPATCH_HOST",
        "TMUX",
        "TMUX_PANE",
    ):
        env.pop(leaky, None)
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HAPAX_SUPERVISOR_STATE_DIR": str(tmp_path / "state"),
            "HAPAX_SUPERVISOR_RUNTIME_DIR": str(tmp_path / "runtime"),
            "HAPAX_SUPERVISOR_WORKTREE_ROOT": str(home / "projects"),
            "HAPAX_SUPERVISOR_VAULT_ROOT": str(home / "vault"),
            "HAPAX_SUPERVISOR_CLAUDE_LANES": "delta",
            "HAPAX_SUPERVISOR_CODEX_LANES": "",
            "HAPAX_SUPERVISOR_ANTIGRAV_LANES": "",
            "HAPAX_SUPERVISOR_RESTART_COOLDOWN_S": "0",
            "HAPAX_SUPERVISOR_PROC_SCAN_LAUNCHERS": "0",
            "HAPAX_SUPERVISOR_ADMISSION_CMD": "echo open",
            "HAPAX_LOCAL_DEV_MAINTENANCE_MODE": "local",
            "HAPAX_CLAUDE_BIN": str(bin_dir / "hapax-claude"),
            "HAPAX_CODEX_BIN": str(bin_dir / "hapax-codex"),
            "HAPAX_CLAUDE_HEADLESS_BIN": str(bin_dir / "hapax-claude-headless"),
            "HAPAX_PANE_EXIT_LOG_DIR": str(pane_logs),
            "TMUX_CALL_LOG": str(tmux_call_log),
            "FAKE_TMUX_SESSION_EXISTS": "0",
            "FAKE_TMUX_PANE_DEAD": "",
            "FAKE_TMUX_PANE_IDS": "%0",
            "FAKE_TMUX_SIBLING_EXISTS": "0",
            "FAKE_TMUX_SIBLING_PANE_DEAD": "0",
            "FAKE_TMUX_FAIL": "",
        }
    )
    env.update(overrides)
    (home / "projects" / "hapax-council--delta").mkdir(parents=True, exist_ok=True)
    return {
        "env": env,
        "calls": calls,
        "pane_logs": pane_logs,
        "tmux_calls": tmux_call_log,
    }


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SUPERVISOR)], env=env, capture_output=True, text=True, timeout=60)


def _respawned(calls: Path) -> bool:
    p = calls / "claude.txt"
    return p.exists() and bool(p.read_text(encoding="utf-8").strip())


def _tmux_calls(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _target_in(argv: list[str]) -> str | None:
    """The value of the invocation's ``-t``, or None when it carries no target."""
    for i, tok in enumerate(argv):
        if tok == "-t" and i + 1 < len(argv):
            return argv[i + 1]
    return None


def _killed_sessions(path: Path) -> list[str]:
    """Which sessions the fake tmux actually killed — AFTER target resolution, so
    a bare target that prefix-matched a sibling shows up as the sibling's name."""
    return [c.split(" ", 1)[1] for c in _tmux_calls(path) if c.startswith("killed ")]


#: A recording tmux for driving the REAL launchers end to end. Every invocation is
#: one ``--``-delimited block in ``$TMUX_CALL_LOG``; ``new-session`` and
#: ``set-option`` exit with the status the test asks for, so the launcher's own
#: failure handling is what gets exercised, not a stub's.
_LAUNCHER_FAKE_TMUX = r"""
#!/usr/bin/env bash
{ printf -- '--\n'; printf '%s\n' "$@"; } >> "$TMUX_CALL_LOG"
case "${1:-}" in
  has-session) exit 1 ;;
  new-session) exit "${FAKE_TMUX_NEW_SESSION_RC:-0}" ;;
  set-option)  exit "${FAKE_TMUX_SET_OPTION_RC:-0}" ;;
  *) exit 0 ;;
esac
"""


def _launcher_invocations(log: Path) -> list[list[str]]:
    blocks: list[list[str]] = []
    for line in log.read_text(encoding="utf-8").splitlines() if log.exists() else []:
        if line == "--":
            blocks.append([])
        elif blocks:
            blocks[-1].append(line)
    return blocks


def _claude_launcher_env(tmp_path: Path, **overrides: str) -> tuple[dict[str, str], Path]:
    """Enough environment for ``scripts/hapax-claude`` to reach its terminal branch
    with every external it touches faked: ``claude``, ``tmux``, ``footclient``."""
    home = tmp_path / "home"
    bin_dir = tmp_path / "launcher-bin"
    workdir = tmp_path / "worktree"
    for d in (home, bin_dir, workdir):
        d.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "launcher-tmux-calls.txt"
    _write_executable(bin_dir / "claude", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(bin_dir / "footclient", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(bin_dir / "tmux", _LAUNCHER_FAKE_TMUX)
    env = os.environ.copy()
    for leaky in ("CLAUDE_ROLE", "HAPAX_AGENT_NAME", "HAPAX_AGENT_ROLE", "TMUX", "TMUX_PANE"):
        env.pop(leaky, None)
    env.update(
        {
            "HOME": str(home),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
            "HAPAX_CLAUDE_TERMINAL": "none",
            "TMUX_CALL_LOG": str(log),
        }
    )
    env.update(overrides)
    return env, log


def _run_claude_launcher(env: dict[str, str], terminal: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(CLAUDE_LAUNCHER),
            "--role",
            "delta",
            "--cd",
            str(Path(env["HOME"]).parent / "worktree"),
            "--terminal",
            terminal,
            "--readonly",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


_REMAIN_ON_EXIT_CALL = [
    "set-option",
    "-w",
    "-t",
    "=hapax-claude-delta:",
    "remain-on-exit",
    "failed",
]


# ── liveness: a retained corpse is not a live lane ───────────────────────────


def test_session_of_only_dead_panes_is_dead_and_respawns(tmp_path: Path) -> None:
    """The FM-11 pin. ``has-session`` succeeds — the dead pane is holding the
    session open — but every pane reports ``pane_dead=1``, so the lane is DEAD
    and must be respawned. Under the old ``has-session``-only liveness this lane
    reads as healthy forever and never restarts."""
    b = _base(tmp_path, FAKE_TMUX_SESSION_EXISTS="1", FAKE_TMUX_PANE_DEAD="1")
    res = _run(b["env"])
    assert res.returncode == 0, res.stderr
    assert _respawned(b["calls"]), (
        "a session whose only pane is dead was treated as a live lane: " + res.stderr
    )


def test_one_live_pane_keeps_the_lane_alive(tmp_path: Path) -> None:
    """A lane with a dead window and a live one is still a lane. It must not be
    respawned on top of itself, and its session must not be killed.

    The dead window is listed first on purpose: this also pins the server-wide
    ``list-panes -a`` read. Without ``-a`` tmux reports only ONE window's panes, so a
    supervisor that dropped the flag would see just the corpse and respawn over a
    live lane.
    """
    b = _base(tmp_path, FAKE_TMUX_SESSION_EXISTS="1", FAKE_TMUX_PANE_DEAD="1 0")
    res = _run(b["env"])
    assert res.returncode == 0, res.stderr
    assert not _respawned(b["calls"]), "respawned a lane that still had a live pane"
    assert not any(c.startswith("kill-session") for c in _tmux_calls(b["tmux_calls"]))


def test_unreadable_pane_list_fails_open(tmp_path: Path) -> None:
    """A tmux too old for ``#{pane_dead}``, or a race with teardown, yields no
    pane list at all. That is not evidence of death: fall back to the old
    ``has-session`` answer. Failing OPEN leaves a working lane running; failing
    closed would respawn a second claude on top of a live one."""
    b = _base(tmp_path, FAKE_TMUX_SESSION_EXISTS="1", FAKE_TMUX_PANE_DEAD="")
    res = _run(b["env"])
    assert res.returncode == 0, res.stderr
    assert not _respawned(b["calls"]), "an unreadable pane list was read as a dead lane"


# ── forensics: read the corpse, then clear it ────────────────────────────────


def test_forensics_log_is_written_with_the_four_fields(tmp_path: Path) -> None:
    b = _base(tmp_path, FAKE_TMUX_SESSION_EXISTS="1", FAKE_TMUX_PANE_DEAD="1")
    res = _run(b["env"])
    logs = sorted(Path(b["pane_logs"]).glob("*.log"))
    assert len(logs) == 1, f"expected one forensics log, got {[p.name for p in logs]}"
    assert re.fullmatch(r"\d{8}T\d{6}Z-delta\.log", logs[0].name), logs[0].name
    text = logs[0].read_text(encoding="utf-8")
    for field in (
        "pane_dead_status=",
        "pane_dead_signal=",
        "pane_dead_time=",
        "pane_start_command=",
    ):
        assert field in text, f"{field} missing from the forensics log:\n{text}"
    assert "FAKE-SCROLLBACK-LINE" in text, f"scrollback not captured:\n{text}"
    assert "session: hapax-claude-delta" in text
    assert f"forensics in {logs[0]}" in res.stdout + res.stderr, (
        "the supervisor did not tell the operator where the evidence is"
    )


def test_capture_precedes_kill_session(tmp_path: Path) -> None:
    """The ordering IS the fix. Killing the session first destroys the pane and
    with it every field above — the exact blindness this change removes."""
    b = _base(tmp_path, FAKE_TMUX_SESSION_EXISTS="1", FAKE_TMUX_PANE_DEAD="1")
    _run(b["env"])
    calls = _tmux_calls(b["tmux_calls"])
    kills = [i for i, c in enumerate(calls) if c.startswith("kill-session")]
    captures = [i for i, c in enumerate(calls) if c.startswith("capture-pane")]
    assert kills, f"the dead session was never killed, so the lane cannot relaunch: {calls}"
    assert captures, f"the pane was never captured: {calls}"
    assert max(captures) < min(kills), f"kill-session ran before capture-pane: {calls}"


def test_guard_never_captures_a_lane_it_found_alive(tmp_path: Path) -> None:
    """The caller-side pin: a live lane is never routed into the forensics path at
    all. (``capture_dead_pane``'s own refusal to kill a live session is a separate
    invariant covering the window between the two checks — see
    ``test_capture_refuses_a_session_that_came_back_to_life``.)"""
    b = _base(tmp_path, FAKE_TMUX_SESSION_EXISTS="1", FAKE_TMUX_PANE_DEAD="0")
    _run(b["env"])
    calls = _tmux_calls(b["tmux_calls"])
    assert not any(c.startswith("kill-session") for c in calls), calls
    assert not any(c.startswith("capture-pane") for c in calls), calls
    assert not list(Path(b["pane_logs"]).glob("*.log"))


def test_dry_run_describes_without_destroying(tmp_path: Path) -> None:
    """A dry run must not destroy the thing it is describing."""
    b = _base(
        tmp_path,
        FAKE_TMUX_SESSION_EXISTS="1",
        FAKE_TMUX_PANE_DEAD="1",
        HAPAX_SUPERVISOR_DRY_RUN="1",
    )
    res = _run(b["env"])
    assert "WOULD respawn" in (res.stdout + res.stderr)
    assert not any(c.startswith("kill-session") for c in _tmux_calls(b["tmux_calls"]))
    assert not list(Path(b["pane_logs"]).glob("*.log"))
    assert not _respawned(b["calls"])


def test_retention_prunes_only_logs_past_the_window(tmp_path: Path) -> None:
    b = _base(
        tmp_path,
        FAKE_TMUX_SESSION_EXISTS="1",
        FAKE_TMUX_PANE_DEAD="1",
        HAPAX_PANE_EXIT_RETENTION_DAYS="30",
    )
    pane_logs = Path(b["pane_logs"])
    stale = pane_logs / "20200101T000000Z-ancient.log"
    recent = pane_logs / "20990101T000000Z-recent.log"
    for f in (stale, recent):
        f.write_text("x\n", encoding="utf-8")
    old = time.time() - 40 * 86400
    os.utime(stale, (old, old))

    _run(b["env"])

    assert not stale.exists(), "a 40-day-old forensics log survived a 30-day retention"
    assert recent.exists(), "retention deleted a log inside the window"
    assert len(list(pane_logs.glob("*-delta.log"))) == 1, "this run's own capture was pruned"


def test_codex_lane_captures_its_own_session_name(tmp_path: Path) -> None:
    b = _base(
        tmp_path,
        FAKE_TMUX_SESSION_EXISTS="1",
        FAKE_TMUX_PANE_DEAD="1",
        HAPAX_SUPERVISOR_CLAUDE_LANES="",
        HAPAX_SUPERVISOR_CODEX_LANES="delta",
        # The fake resolves targets by exact name, so it has to know the codex
        # lane's session is the one that exists.
        FAKE_TMUX_SESSION_NAME="hapax-codex-delta",
    )
    _run(b["env"])
    logs = sorted(Path(b["pane_logs"]).glob("*.log"))
    assert len(logs) == 1, [p.name for p in logs]
    assert "session: hapax-codex-delta" in logs[0].read_text(encoding="utf-8")


# ── exact names: a sibling whose name extends the lane's is not the lane ──────


def test_a_dead_prefix_named_sibling_is_neither_captured_nor_killed(tmp_path: Path) -> None:
    """Lane ``delta`` is MISSING; ``hapax-claude-delta-2`` exists with only dead panes.

    tmux resolves a bare target by exact name, then prefix, then fnmatch (measured on
    3.7c), so an unanchored ``has-session``/``kill-session`` would find the sibling,
    read its corpse as ``delta``'s, write ``delta``'s certificate from the wrong
    session and kill a session the supervisor does not own. Every target must be
    ``=name``: delta is simply absent, so it is relaunched and nothing is killed.
    """
    b = _base(
        tmp_path,
        FAKE_TMUX_SESSION_EXISTS="0",
        FAKE_TMUX_SIBLING_EXISTS="1",
        FAKE_TMUX_SIBLING_PANE_DEAD="1",
    )
    res = _run(b["env"])
    assert res.returncode == 0, res.stderr
    assert _respawned(b["calls"]), "a missing lane was not relaunched: " + res.stderr
    assert _killed_sessions(b["tmux_calls"]) == [], (
        "a bare tmux target prefix-matched the sibling: " + str(_tmux_calls(b["tmux_calls"]))
    )
    assert not list(Path(b["pane_logs"]).glob("*.log")), "wrote delta's certificate from a sibling"


def test_a_live_sibling_does_not_stand_in_for_a_dead_lane(tmp_path: Path) -> None:
    """Lane ``delta`` is a corpse; ``hapax-claude-delta-2`` is alive next to it.

    ``=name`` does not anchor ``list-panes`` (measured: ``-s -t =name`` still reported
    the sibling), so the pane list is read server-wide and filtered on the EXACT
    session name. Drop the filter and the sibling's live pane makes the corpse read
    as alive: never respawned, never captured.
    """
    b = _base(
        tmp_path,
        FAKE_TMUX_SESSION_EXISTS="1",
        FAKE_TMUX_PANE_DEAD="1",
        FAKE_TMUX_SIBLING_EXISTS="1",
        FAKE_TMUX_SIBLING_PANE_DEAD="0",
    )
    res = _run(b["env"])
    assert res.returncode == 0, res.stderr
    assert _respawned(b["calls"]), "the sibling's live pane was counted as the lane's"
    assert _killed_sessions(b["tmux_calls"]) == ["hapax-claude-delta"]
    logs = list(Path(b["pane_logs"]).glob("*-delta.log"))
    assert len(logs) == 1 and "%9" not in logs[0].read_text(encoding="utf-8"), (
        "the sibling's pane was captured into delta's certificate"
    )


def test_every_session_target_the_supervisor_emits_is_exact_matched(tmp_path: Path) -> None:
    """The anchor stated as a PROPERTY of the run, not as one more scenario.

    The two scenarios above pin the anchors that happen to be load-bearing today:
    drop either ``has-session`` anchor or the pane-list filter and one of them reds.
    ``kill-session`` is not among them — it is reached only after an anchored
    ``has-session`` has already confirmed the exact session exists, so reverting it
    to a bare target is behaviour-preserving against a fake and reds nothing
    (measured: the whole file stays green). That leaves the destructive write the
    review's critical is actually about resting on an unpinned comment, and a later
    edit could unanchor it silently — the anchors would then be one TOCTOU window
    (session dies between the check and the kill) away from killing a sibling.

    So assert the shape of every target the supervisor emits, which no single
    scenario can: session-scoped subcommands are always ``=name``, and ``list-panes``
    is never given a session target at all, because ``=`` does NOT anchor it
    (measured on 3.7c: ``-s -t =name`` still reported the sibling's panes).
    A new unanchored call site reds here even if no scenario reaches it.
    """
    b = _base(
        tmp_path,
        FAKE_TMUX_SESSION_EXISTS="1",
        FAKE_TMUX_PANE_DEAD="1",
        FAKE_TMUX_SIBLING_EXISTS="1",
        FAKE_TMUX_SIBLING_PANE_DEAD="0",
    )
    res = _run(b["env"])
    assert res.returncode == 0, res.stderr

    anchored = {"has-session", "kill-session"}
    seen: set[str] = set()
    for call in _tmux_calls(b["tmux_calls"]):
        argv = call.split()
        if not argv:
            continue
        sub, target = argv[0], _target_in(argv)
        if sub in anchored:
            seen.add(sub)
            assert target is not None and target.startswith("="), (
                f"{sub} used the bare target {target!r}; tmux resolves a bare target by "
                f"exact name, then PREFIX, then fnmatch, so this can act on a sibling "
                f'session the supervisor does not own. Use -t "=$session". Call: {call}'
            )
        if sub == "list-panes":
            assert target is None, (
                "list-panes was given a session target; `=` does not anchor it "
                f"(measured), so it must read server-wide with -a and filter on the "
                f"exact session name. Call: {call}"
            )

    # Guard the guard: a run that emitted neither would pass vacuously.
    assert seen == anchored, f"scenario did not exercise {anchored - seen}"


def test_every_supervised_kind_has_its_corpse_cleared() -> None:
    """Liveness was broadened for every kind; corpse-clearing must not lag behind it.

    ``tmux_session_alive`` now means "has a LIVE pane", so a session of only dead
    panes reads DEAD on every tick. That is only safe for a kind whose corpse is also
    KILLED — the launchers refuse to start over an existing session, so a kind with
    the new predicate and no ``capture_dead_pane`` arm would fail to respawn forever.

    Measured today, the asymmetry the review flagged is not reachable: ``guard`` is
    invoked with exactly ``claude`` and ``codex`` (the P0 drain appends to
    ``CODEX_LANES``, still kind ``codex``), and ``HAPAX_SUPERVISOR_ANTIGRAV_LANES`` is
    force-cleared with a refusal on stderr, so the third kind named in the review does
    not exist. This pins the invariant rather than the count, so adding a kind without
    an arm reds here instead of looping in production.
    """
    src = "\n".join(
        line
        for line in SUPERVISOR.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    guarded = set(re.findall(r'\bguard\s+"\$lane"\s+(\w+)', src))
    cleared = set(re.findall(r'\bcapture_dead_pane\s+"\$lane"\s+"hapax-(\w+)-\$lane"', src))

    assert guarded, "found no guard invocations — the parse, not the script, is wrong"
    assert guarded <= cleared, (
        f"supervised kind(s) {sorted(guarded - cleared)} get the pane-dead liveness "
        f"predicate but no capture_dead_pane arm: their sessions would read DEAD every "
        f"tick with nothing clearing the corpse, and the launcher refuses to start over "
        f"an existing session — a permanent respawn-failure loop. Add the arm in guard, "
        f"or keep that kind off tmux_session_alive."
    )


@pytest.mark.parametrize("launcher", ["hapax-claude", "hapax-codex"])
def test_launchers_never_target_a_session_by_bare_name(launcher: str) -> None:
    """The same anchor invariant on the launcher side, where one target carries the operator.

    ``attach-session`` was the call site the first pass missed: it is what a foot launch
    hands the human. Measured on 3.7c with only ``hapax-probe-delta-2`` running,
    ``attach-session -t hapax-probe-delta`` resolved to the sibling (it reached
    "open terminal failed") while ``-t =hapax-probe-delta`` said "can't find session" —
    so an unanchored attach types the operator's keystrokes into another lane's pane
    whenever this lane's session is gone and a longer-named one is not.

    ``list-panes`` is excluded on purpose and asserted separately: ``=`` does NOT anchor
    it, so the correct form is a server-wide listing filtered on the exact name, and an
    anchored ``-t`` there would be a false reassurance.
    """
    src = "\n".join(
        line
        for line in (REPO_ROOT / "scripts" / launcher).read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    bare = re.findall(r'(\S+)\s+-t\s+"\$TMUX_NAME"', src)
    assert not bare, (
        f"{launcher}: {sorted(set(bare))} target the session by BARE name. tmux resolves a "
        f'bare target by exact name, then PREFIX, then fnmatch. Use -t "=$TMUX_NAME" '
        f'(or "=$TMUX_NAME:" for a window option); for list-panes, where `=` does not '
        f"anchor, read server-wide with -a and filter on the exact session name."
    )
    assert re.search(r"list-panes\s+-a\b", src) or "list-panes" not in src, (
        f"{launcher}: list-panes must read server-wide with -a and filter on the exact "
        f"session name — `=` does not anchor it (measured)."
    )


# ── failure paths inside the capture ─────────────────────────────────────────


def test_inspection_failures_are_recorded_and_never_block_the_kill(tmp_path: Path) -> None:
    """``display-message`` and ``capture-pane`` can fail (a pane torn down between the
    listing and the read). The log says so in place of the missing fields, and the
    corpse is still cleared so the lane can relaunch."""
    b = _base(
        tmp_path,
        FAKE_TMUX_SESSION_EXISTS="1",
        FAKE_TMUX_PANE_DEAD="1",
        FAKE_TMUX_FAIL="display-message capture-pane",
    )
    res = _run(b["env"])
    assert res.returncode == 0, res.stderr
    logs = sorted(Path(b["pane_logs"]).glob("*-delta.log"))
    assert len(logs) == 1, [p.name for p in logs]
    text = logs[0].read_text(encoding="utf-8")
    assert "<display-message failed>" in text, text
    assert "<capture-pane failed>" in text, text
    assert _killed_sessions(b["tmux_calls"]) == ["hapax-claude-delta"]
    assert _respawned(b["calls"])


def test_unwritable_log_dir_is_reported_not_asserted(tmp_path: Path) -> None:
    """The capture is best-effort by design, so the message that follows it may not
    claim a file it did not verify. With the log directory unusable the supervisor
    must say the forensics were NOT written, name the next action, and still clear
    the corpse — a respawn is never blocked by forensics failing."""
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("", encoding="utf-8")
    b = _base(
        tmp_path,
        FAKE_TMUX_SESSION_EXISTS="1",
        FAKE_TMUX_PANE_DEAD="1",
        HAPAX_PANE_EXIT_LOG_DIR=str(blocked),
    )
    res = _run(b["env"])
    out = res.stdout + res.stderr
    assert res.returncode == 0, res.stderr
    assert "forensics NOT written" in out, out
    assert "next:" in out, out
    assert "forensics in " not in out, "claimed a certificate that was never written: " + out
    assert _killed_sessions(b["tmux_calls"]) == ["hapax-claude-delta"]
    assert _respawned(b["calls"])


# ── the launchers' CALL SITES, not just the helper body ──────────────────────


@pytest.mark.parametrize("terminal", ["tmux", "foot"])
def test_hapax_claude_launcher_sets_remain_on_exit_after_new_session(
    tmp_path: Path, terminal: str
) -> None:
    """Drive the real ``hapax-claude`` to its ``tmux)`` and ``foot)`` branches with
    ``claude``, ``tmux`` and ``footclient`` faked. The helper is proven against a real
    server elsewhere; this pins that each branch actually CALLS it — reverting the
    call sites to an inline ``new-session`` leaves the helper defined-but-unused and
    would otherwise be caught by nothing."""
    env, log = _claude_launcher_env(tmp_path)
    res = _run_claude_launcher(env, terminal)
    assert res.returncode == 0, res.stderr
    blocks = _launcher_invocations(log)
    new_session = [
        i
        for i, b in enumerate(blocks)
        if b[:4] == ["new-session", "-d", "-s", "hapax-claude-delta"]
    ]
    assert new_session, f"{terminal}: no new-session recorded: {blocks}"
    assert _REMAIN_ON_EXIT_CALL in blocks[new_session[0] + 1 :], (
        f"{terminal}: the launcher never set remain-on-exit after new-session: {blocks}"
    )
    if terminal == "tmux":
        assert res.stdout.strip() == "hapax-claude-delta"


def test_hapax_claude_launcher_fails_open_when_set_option_fails(tmp_path: Path) -> None:
    """Losing the forensics option is bad; refusing to launch the lane over it is
    worse; losing it SILENTLY is how the original gap survived. So: exit 0, the
    session name still printed, and a warning that names the next action."""
    env, log = _claude_launcher_env(tmp_path, FAKE_TMUX_SET_OPTION_RC="1")
    res = _run_claude_launcher(env, "tmux")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "hapax-claude-delta"
    assert "could not set remain-on-exit on hapax-claude-delta" in res.stderr, res.stderr
    assert "next:" in res.stderr and "tmux -V" in res.stderr, res.stderr
    assert _REMAIN_ON_EXIT_CALL in _launcher_invocations(log)


def test_hapax_claude_launcher_propagates_new_session_failure(tmp_path: Path) -> None:
    """A failed ``new-session`` must fail the launch with its own status and must not
    go on to set options on a session that does not exist."""
    env, log = _claude_launcher_env(tmp_path, FAKE_TMUX_NEW_SESSION_RC="7")
    res = _run_claude_launcher(env, "tmux")
    assert res.returncode != 0, "a failed new-session was reported as a successful launch"
    assert res.stdout.strip() != "hapax-claude-delta"
    assert not any(b[:1] == ["set-option"] for b in _launcher_invocations(log))


# ── real tmux, private socket ────────────────────────────────────────────────


def _tmux_version() -> tuple[int, int] | None:
    exe = shutil.which("tmux")
    if not exe:
        return None
    out = subprocess.run([exe, "-V"], capture_output=True, text=True).stdout
    m = re.search(r"(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


_TMUX_VERSION = _tmux_version()


def _require_real_tmux() -> None:
    """Skip without tmux >= 3.2 — unless ``HAPAX_TEST_REQUIRE_TMUX=1``, in which case
    FAIL. The real-tmux cases are the durable witness for the task's exit predicate;
    a run that silently skipped them would report green on fake-tmux stubs alone and
    be indistinguishable from one that exercised a real server."""
    if _TMUX_VERSION is not None and _TMUX_VERSION >= (3, 2):
        return
    reason = f"needs tmux >= 3.2 for `remain-on-exit failed` (found {_TMUX_VERSION})"
    if os.environ.get("HAPAX_TEST_REQUIRE_TMUX") == "1":
        pytest.fail("HAPAX_TEST_REQUIRE_TMUX=1 but the real-tmux witness cannot run: " + reason)
    pytest.skip(reason)


class ProbeServer:
    """A tmux server on a private socket, reached through a ``tmux`` shim on PATH.

    The shim is what lets the REAL supervisor and the REAL launcher helper run
    unmodified against a throwaway server: the live lanes' default socket is
    never touched.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.socket = f"hapax-probe-{os.getpid()}-{tmp_path.name}"
        self.bin_dir = tmp_path / "probe-bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.real = shutil.which("tmux")
        _write_executable(
            self.bin_dir / "tmux",
            f'#!/usr/bin/env bash\nexec {self.real} -L {self.socket} -f /dev/null "$@"\n',
        )

    def __call__(self, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.real, "-L", self.socket, "-f", "/dev/null", *args],
            capture_output=True,
            text=True,
            check=check,
            timeout=30,
        )

    def kill(self) -> None:
        self("kill-server")


@pytest.fixture()
def probe(tmp_path: Path):
    _require_real_tmux()
    server = ProbeServer(tmp_path)
    try:
        yield server
    finally:
        server.kill()


def _wait_for(predicate, timeout: float = 10.0, interval: float = 0.1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_launcher_helper_retains_a_sigkilled_pane(tmp_path: Path, probe: ProbeServer) -> None:
    """Run the launcher's OWN ``tmux_new_lane_session`` body — extracted from the
    shipped script, not reimplemented — and SIGKILL what it started.

    This is the transcript the whole change rests on: the pane survives its
    process, carrying the signal, the start command and the scrollback.
    """
    for launcher in (CLAUDE_LAUNCHER, CODEX_LAUNCHER):
        session = f"probe-{launcher.name}"
        marker = f"FORENSIC-MARKER-{launcher.name.upper()}"
        runner = tmp_path / f"runner-{launcher.name}.sh"
        _write_executable(runner, f"#!/usr/bin/env bash\necho {marker}\nsleep 300\n")

        body = subprocess.run(
            ["sed", "-n", "/^tmux_new_lane_session()/,/^}/p", str(launcher)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "remain-on-exit failed" in body, f"{launcher.name} has no remain-on-exit call"

        script = (
            f"TMUX_BIN={probe.bin_dir / 'tmux'}\n"
            f"TMUX_NAME={session}\nWORKDIR={tmp_path}\nRUNNER={runner}\n"
            f"{body}\ntmux_new_lane_session\n"
        )
        res = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
        assert res.returncode == 0, f"{launcher.name}: {res.stderr}"

        opt = probe("show-options", "-w", "-t", session, "-v", "remain-on-exit").stdout.strip()
        assert opt == "failed", f"{launcher.name} left remain-on-exit={opt!r}"

        assert _wait_for(lambda: marker in probe("capture-pane", "-p", "-t", session).stdout)
        pid = probe("list-panes", "-t", session, "-F", "#{pane_pid}").stdout.strip()
        os.kill(int(pid), 9)

        assert _wait_for(
            lambda: probe("list-panes", "-t", session, "-F", "#{pane_dead}").stdout.strip() == "1"
        ), f"{launcher.name}: the pane did not survive its process"
        assert probe("has-session", "-t", session).returncode == 0
        fields = probe(
            "list-panes",
            "-t",
            session,
            "-F",
            "#{pane_dead_signal}|#{pane_start_command}",
        ).stdout.strip()
        signal, _, start_command = fields.partition("|")
        assert signal == "9", f"{launcher.name}: lost the death signal ({fields!r})"
        assert runner.name in start_command, f"{launcher.name}: lost the start command ({fields!r})"
        assert marker in probe("capture-pane", "-p", "-S", "-60", "-t", session).stdout


def test_clean_exit_is_not_mistaken_for_a_death(tmp_path: Path, probe: ProbeServer) -> None:
    """``failed``, not ``on``. An orderly stop must still close its pane, or every
    normal shutdown would leave a corpse for the supervisor to respawn over."""
    runner = tmp_path / "clean.sh"
    _write_executable(runner, "#!/usr/bin/env bash\ntrue\n")
    body = subprocess.run(
        ["sed", "-n", "/^tmux_new_lane_session()/,/^}/p", str(CLAUDE_LAUNCHER)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    script = (
        f"TMUX_BIN={probe.bin_dir / 'tmux'}\nTMUX_NAME=probe-clean\n"
        f"WORKDIR={tmp_path}\nRUNNER={runner}\n{body}\ntmux_new_lane_session\n"
    )
    subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=True)
    assert _wait_for(lambda: probe("has-session", "-t", "probe-clean").returncode != 0), (
        "a clean exit left a retained pane — `remain-on-exit on` would do this, `failed` must not"
    )


def test_supervisor_reads_a_real_corpse_then_relaunches_it(
    tmp_path: Path, probe: ProbeServer
) -> None:
    """End to end against a real tmux server: a real SIGKILL, the real supervisor,
    and the log the operator would actually read the next morning."""
    b = _base(tmp_path)
    env = dict(b["env"])
    env["PATH"] = f"{probe.bin_dir}:{env['PATH']}"
    env.pop("TMUX_CALL_LOG", None)

    runner = tmp_path / "lane-runner.sh"
    _write_executable(runner, "#!/usr/bin/env bash\necho REAL-CORPSE-MARKER\nsleep 300\n")
    session = "hapax-claude-delta"
    probe("new-session", "-d", "-s", session, "-c", str(tmp_path), str(runner), check=True)
    probe("set-option", "-w", "-t", session, "remain-on-exit", "failed", check=True)
    assert _wait_for(
        lambda: "REAL-CORPSE-MARKER" in probe("capture-pane", "-p", "-t", session).stdout
    )

    pid = int(probe("list-panes", "-t", session, "-F", "#{pane_pid}").stdout.strip())
    os.kill(pid, 9)
    assert _wait_for(
        lambda: probe("list-panes", "-t", session, "-F", "#{pane_dead}").stdout.strip() == "1"
    )
    # Precondition for the whole test: the corpse still looks alive to has-session.
    assert probe("has-session", "-t", session).returncode == 0

    res = _run(env)
    assert res.returncode == 0, res.stderr

    logs = sorted(Path(b["pane_logs"]).glob("*-delta.log"))
    assert len(logs) == 1, f"{[p.name for p in logs]} / {res.stderr}"
    text = logs[0].read_text(encoding="utf-8")
    assert "pane_dead_signal=9" in text, text
    assert "REAL-CORPSE-MARKER" in text, text
    assert runner.name in text, text

    assert probe("has-session", "-t", session).returncode != 0, (
        "the corpse session survived the capture, so the launcher cannot start over it"
    )
    assert _respawned(b["calls"]), "the lane was never relaunched after its corpse was cleared"


def test_capture_refuses_a_session_that_came_back_to_life(
    tmp_path: Path, probe: ProbeServer
) -> None:
    """``capture_dead_pane`` re-checks liveness itself, and this is not a second
    guard on the same hazard.

    ``guard`` decides the lane is dead, then runs cooldown, burst, maintenance and
    a python backlog probe before reaching the capture — seconds in which an
    operator can relaunch the lane by hand. The caller's answer is stale by then;
    the function is about to run ``kill-session``, so it asks again at the moment
    of use. Reached through ``guard`` this branch is unreachable by construction,
    which is exactly why it is tested directly.
    """
    session = "hapax-claude-revived"
    probe("new-session", "-d", "-s", session, "sleep 300", check=True)
    probe("set-option", "-w", "-t", session, "remain-on-exit", "failed", check=True)
    assert _wait_for(
        lambda: probe("list-panes", "-t", session, "-F", "#{pane_dead}").stdout.strip() == "0"
    )

    out_dir = tmp_path / "pane-exits"
    out_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join(
        subprocess.run(
            ["sed", "-n", f"/^{fn}()/,/^}}/p", str(SUPERVISOR)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for fn in ("tmux_has_live_pane", "capture_dead_pane")
    )
    script = (
        f'PATH="{probe.bin_dir}:$PATH"\n'
        f'PANE_EXIT_LOG_DIR="{out_dir}"\nPANE_EXIT_RETENTION_DAYS=30\n'
        "log() { :; }\n"
        f"{body}\ncapture_dead_pane revived {session}\n"
    )
    res = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr

    assert probe("has-session", "-t", session).returncode == 0, (
        "capture_dead_pane killed a session that had a LIVE pane"
    )
    assert not list(out_dir.glob("*.log")), "wrote a death certificate for a living lane"


def test_supervisor_never_kills_a_prefix_named_sibling(tmp_path: Path, probe: ProbeServer) -> None:
    """Real tmux: ``hapax-claude-delta-2`` is a retained corpse and ``hapax-claude-delta``
    does not exist. A bare ``-t hapax-claude-delta`` resolves to the sibling by
    prefix (measured on 3.7c); the anchored targets must leave it alone, write no
    certificate for delta, and relaunch delta because it is simply missing."""
    b = _base(tmp_path)
    env = dict(b["env"])
    env["PATH"] = f"{probe.bin_dir}:{env['PATH']}"
    env.pop("TMUX_CALL_LOG", None)

    sibling = "hapax-claude-delta-2"
    probe("new-session", "-d", "-s", sibling, "sleep 300", check=True)
    probe("set-option", "-w", "-t", f"={sibling}:", "remain-on-exit", "failed", check=True)
    pid = int(probe("list-panes", "-t", sibling, "-F", "#{pane_pid}").stdout.strip())
    os.kill(pid, 9)
    assert _wait_for(
        lambda: probe("list-panes", "-t", sibling, "-F", "#{pane_dead}").stdout.strip() == "1"
    )
    # The hazard, stated as a precondition: a bare target finds the sibling.
    assert probe("has-session", "-t", "hapax-claude-delta").returncode == 0

    res = _run(env)
    assert res.returncode == 0, res.stderr

    assert probe("has-session", "-t", f"={sibling}").returncode == 0, (
        "the supervisor killed a session whose name merely extends the lane's"
    )
    assert not list(Path(b["pane_logs"]).glob("*.log")), (
        "wrote delta's certificate from the sibling"
    )
    assert _respawned(b["calls"]), "a missing lane was not relaunched"
