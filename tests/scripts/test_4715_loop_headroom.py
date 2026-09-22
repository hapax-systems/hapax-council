"""4715 repair item 4: headroom gating tested through the real launch loop.

Review finding: test_d3_headroom only exercises launch_headroom_budget(); the
launch loop's own budget decrement/break was untested. These drive
scripts/hapax-lane-idle-watchdog end-to-end with a fake launcher and a
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
    state = tmp_path / "state"
    calls = tmp_path / "calls"
    for d in (home, bin_dir, state, calls):
        d.mkdir(parents=True, exist_ok=True)
    _write_executable(
        bin_dir / "tmux",
        """
        #!/usr/bin/env bash
        # has-session always fails so the watchdog wants to launch.
        case "${1:-}" in
          has-session) exit 1 ;;
          *) exit 0 ;;
        esac
        """,
    )
    calls_txt = str(calls / "calls.txt")
    _write_executable(
        bin_dir / "fake-claude",
        (f'#!/usr/bin/env bash\nprintf \'LAUNCHED %s\\n\' "$*" >> "{calls_txt}"\n'),
    )
    for role in ("alpha", "beta", "gamma"):
        (home / "projects" / f"hapax-council--{role}").mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(home),
        "HAPAX_REQUIRED_CLAUDE_LANES": "alpha beta gamma",
        "HAPAX_REQUIRED_CODEX_LANES": "",
        "CLAUDE_LAUNCHER": str(bin_dir / "fake-claude"),
        "HAPAX_LOCAL_DEV_MAINTENANCE_MODE": "local",
        "HAPAX_SUPERVISOR_CLAUDE_LANES": "alpha beta gamma",
        "NTFY_URL": "http://127.0.0.1:1",
        "NTFY_TOPIC": "test",
    }
    env.update(overrides)
    return env


def _run_watchdog(env: dict[str, str], load1: str, nproc: str = "8") -> str:
    """Run the watchdog once with a stubbed nproc and load average."""
    wrapper = Path(env["HOME"]) / "run-watchdog.sh"
    wrapper.write_text(
        textwrap.dedent(
            f"""
            #!/usr/bin/env bash
            nproc() {{ echo {nproc}; }}
            cut() {{
              if [ "${{1:-}}" = "-d" ]; then echo "{load1} 1.00 1.00"; else command cut "$@"; fi
            }}
            exec bash "{WATCHDOG}"
            """
        ).lstrip(),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    result = subprocess.run(
        ["bash", str(wrapper)],
        capture_output=True,
        text=True,
        env=env,
        timeout=45,
        check=False,
    )
    return result.stdout + result.stderr


def test_real_loop_launches_zero_when_headroom_zero(tmp_path: Path) -> None:
    """Saturated host: the loop must not launch any of the candidate pool."""
    env = _base(tmp_path)
    out = _run_watchdog(env, load1="32.00", nproc="4")
    calls = Path(env["HOME"]) / "calls.txt"
    assert not calls.exists() or calls.read_text(encoding="utf-8").strip() == "", out
    assert "LAUNCHING" not in out, out
    assert "launch headroom budget=0" in out, out


def test_real_loop_respects_budget_cap_of_two(tmp_path: Path) -> None:
    """Very idle host with 3 missing lanes: at most 2 launches in one tick."""
    env = _base(tmp_path)
    out = _run_watchdog(env, load1="0.01", nproc="32")
    calls = Path(env["HOME"]) / "calls.txt"
    launched = calls.read_text(encoding="utf-8").strip().splitlines() if calls.exists() else []
    assert 1 <= len(launched) <= 2, (launched, out)
    assert "launch headroom budget=2" in out, out


def test_real_loop_logs_budget_and_pool(tmp_path: Path) -> None:
    """The witness line must name the budget and the candidate pool."""
    env = _base(tmp_path)
    out = _run_watchdog(env, load1="1.00", nproc="4")
    assert "launch headroom budget=" in out, out
    assert "alpha beta gamma" in out, out
