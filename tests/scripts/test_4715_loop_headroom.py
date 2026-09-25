"""4715 repair item 4: headroom gating tested through the real launch loop.

Review finding: test_d3_headroom only exercises launch_headroom_budget(); the
launch loop's own budget decrement/break was untested. These drive
scripts/hapax-lane-idle-watchdog end-to-end with a fake launcher placed at the
path the watchdog actually execs (~/.local/bin/hapax-claude) and a
controllable load, and assert the loop honors the budget.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WATCHDOG = REPO_ROOT / "scripts" / "hapax-lane-idle-watchdog"


def _write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _base(tmp_path: Path, **overrides: str) -> dict[str, str]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "calls"
    for d in (home, bin_dir, calls, home / ".local" / "bin", home / ".cache" / "hapax"):
        d.mkdir(parents=True, exist_ok=True)
    _write_executable(
        bin_dir / "tmux",
        """
        #!/usr/bin/env bash
        case "${1:-}" in
          has-session) exit 1 ;;
          *) exit 0 ;;
        esac
        """,
    )
    calls_txt = str(calls / "calls.txt")
    fake = f'#!/usr/bin/env bash\nprintf \'LAUNCHED %s\\n\' "$*" >> "{calls_txt}"\n'
    # The watchdog hardcodes CLAUDE_LAUNCHER=$HOME/.local/bin/hapax-claude â€”
    # place the fake there so the real loop path is exercised.
    _write_executable(home / ".local" / "bin" / "hapax-claude", fake)
    _write_executable(bin_dir / "fake-claude", fake)
    for role in ("alpha", "beta", "gamma"):
        (home / "projects" / f"hapax-council--{role}").mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(home),
        "HAPAX_REQUIRED_CLAUDE_LANES": "alpha beta gamma",
        "HAPAX_REQUIRED_CODEX_LANES": "",
        "HAPAX_LOCAL_DEV_MAINTENANCE_MODE": "local",
        "HAPAX_SUPERVISOR_CLAUDE_LANES": "alpha beta gamma",
        "HAPAX_SDLC_PRESSURE_GATE_OFF": "1",
        "HAPAX_RECOVERY_GOVERNOR_OFF": "1",
        "NTFY_URL": "http://127.0.0.1:1",
        "NTFY_TOPIC": "test",
    }
    env.update(overrides)
    return env


def _run_watchdog(env: dict[str, str], load1: str, nproc: str = "8") -> str:
    """Run the watchdog once with env-overridable load/nproc observation."""
    load_path = Path(env["HOME"]) / "fake-loadavg"
    load_path.write_text(f"{load1} 1.00 1.00\n", encoding="utf-8")
    env = dict(env)
    env["HAPAX_LOADAVG_PATH"] = str(load_path)
    env["HAPAX_NPROC"] = nproc
    result = subprocess.run(
        ["bash", str(WATCHDOG)],
        capture_output=True,
        text=True,
        env=env,
        timeout=45,
        check=False,
    )
    return result.stdout + result.stderr


def _launched(env: dict[str, str]) -> list[str]:
    calls = Path(env["HOME"]).parent / "calls" / "calls.txt"
    if not calls.exists():
        calls = Path(env["HOME"]) / "calls.txt"
    if not calls.exists():
        # _base writes to tmp_path/calls/calls.txt
        for cand in Path(env["HOME"]).parent.rglob("calls.txt"):
            calls = cand
            break
    return calls.read_text(encoding="utf-8").strip().splitlines() if calls.exists() else []


def test_real_loop_launches_zero_when_headroom_zero(tmp_path: Path) -> None:
    env = _base(tmp_path)
    out = _run_watchdog(env, load1="32.00", nproc="4")
    assert "launch headroom budget=0" in out, out
    assert "LAUNCHING" not in out, out
    assert _launched(env) == [], out


def test_real_loop_respects_budget_cap_of_two(tmp_path: Path) -> None:
    env = _base(tmp_path)
    out = _run_watchdog(env, load1="0.01", nproc="32")
    assert "launch headroom budget=2" in out, out
    launched = _launched(env)
    launching_lines = [ln for ln in out.splitlines() if "LAUNCHING" in ln]
    assert len(launching_lines) <= 2, (launching_lines, out)
    assert len(launched) <= 2, (launched, out)


def test_real_loop_logs_budget_and_pool(tmp_path: Path) -> None:
    env = _base(tmp_path)
    out = _run_watchdog(env, load1="1.00", nproc="4")
    assert "launch headroom budget=" in out, out
    assert "alpha beta gamma" in out, out
