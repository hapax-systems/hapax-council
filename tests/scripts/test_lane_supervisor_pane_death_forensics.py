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
#: the only way to pin "capture before kill". ``list-panes`` answers according to
#: its own ``-F`` format, because the supervisor asks it three different questions.
_FAKE_TMUX = """
#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$TMUX_CALL_LOG"
cmd="${1:-}"; shift || true
case "$cmd" in
  has-session)
    [ "${FAKE_TMUX_SESSION_EXISTS:-0}" = "1" ] && exit 0
    exit 1
    ;;
  list-panes)
    fmt=""; all_windows=0
    while [ "$#" -gt 0 ]; do
      case "$1" in
        -F) fmt="${2:-}"; shift 2 ;;
        -s) all_windows=1; shift ;;
        *) shift ;;
      esac
    done
    # Honour -s the way tmux does: without it, only the CURRENT window's panes are
    # listed. Dropping -s is a real regression (a lane whose active window died would
    # read as alive on the strength of another window), so the fake must be able to
    # show it rather than papering over it.
    emit() { if [ "$all_windows" = "1" ]; then printf '%s\\n' "$@"; else printf '%s\\n' "${1-}"; fi; }
    case "$fmt" in
      *'#{pane_dead}'*) emit ${FAKE_TMUX_PANE_DEAD-} ;;
      *'#{pane_id}'*)   emit ${FAKE_TMUX_PANE_IDS-} ;;
      *)                printf 'status= signal=9\\n' ;;
    esac
    exit 0
    ;;
  display-message)
    printf 'pane: %%0 pane_dead=1 pane_dead_status= pane_dead_signal=9'
    printf ' pane_dead_time=1789532946 pane_start_command="fake-runner"\\n'
    exit 0
    ;;
  capture-pane) printf 'FAKE-SCROLLBACK-LINE\\n'; exit 0 ;;
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

    The dead window is listed first on purpose: this also pins ``list-panes -s``.
    Without ``-s`` tmux reports only the session's CURRENT window, so a supervisor
    that dropped the flag would see just the corpse and respawn over a live lane.
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
    _run(b["env"])
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
    )
    _run(b["env"])
    logs = sorted(Path(b["pane_logs"]).glob("*.log"))
    assert len(logs) == 1, [p.name for p in logs]
    assert "session: hapax-codex-delta" in logs[0].read_text(encoding="utf-8")


# ── real tmux, private socket ────────────────────────────────────────────────


def _tmux_version() -> tuple[int, int] | None:
    exe = shutil.which("tmux")
    if not exe:
        return None
    out = subprocess.run([exe, "-V"], capture_output=True, text=True).stdout
    m = re.search(r"(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


_TMUX_VERSION = _tmux_version()
requires_tmux_32 = pytest.mark.skipif(
    _TMUX_VERSION is None or _TMUX_VERSION < (3, 2),
    reason="needs tmux >= 3.2 for `remain-on-exit failed`",
)


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


@requires_tmux_32
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


@requires_tmux_32
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


@requires_tmux_32
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


@requires_tmux_32
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
