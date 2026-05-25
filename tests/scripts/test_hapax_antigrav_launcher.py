"""Tests for the Hapax Antigrav/agy launcher."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "hapax-antigrav"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _base_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
            "HAPAX_VIBE_WORKTREE_ROOT": str(tmp_path / "projects"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        }
    )
    return env


def test_launcher_uses_agy_and_writes_canonical_agents_rules(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    bin_dir = Path(env["PATH"].split(":", 1)[0])
    agy_log = tmp_path / "agy.log"
    tmux_log = tmp_path / "tmux.log"
    _write_executable(
        bin_dir / "agy",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" >> {agy_log}\n",
    )
    _write_executable(
        bin_dir / "tmux",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {tmux_log}
if [ "$1" = "has-session" ]; then
  exit 1
fi
exit 0
""",
    )
    workdir = tmp_path / "projects" / "hapax-council--antigrav"
    workdir.mkdir(parents=True)
    prompt = tmp_path / "dispatch.md"
    prompt.write_text("SDLC GOVERNED DISPATCH.\nTask: test-task\n", encoding="utf-8")

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "antigrav",
            "--task",
            "test-task",
            "--cd",
            str(workdir),
            "--inflection",
            str(prompt),
            "--no-claim",
            "--terminal",
            "tmux",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "using Antigravity CLI" in result.stderr
    assert "launched agy in tmux session hapax-antigrav-antigrav" in result.stderr
    assert "new-session" in tmux_log.read_text(encoding="utf-8")
    assert "test-task" in tmux_log.read_text(encoding="utf-8")
    assert (workdir / ".agents" / "rules" / "hapax-antigrav-lane.md").is_file()
    assert (workdir / ".agents" / "workflows" / "governed-dispatch-first.md").is_file()
    compat = workdir / ".agent" / "rules" / "hapax-antigrav-lane.md"
    assert compat.is_file()
    assert "Compatibility Pointer" in compat.read_text(encoding="utf-8")
    rule_text = (workdir / ".agents" / "rules" / "hapax-antigrav-lane.md").read_text(
        encoding="utf-8"
    )
    assert "self-claim highest" not in rule_text.lower()
    run_scripts = sorted(
        (Path(env["XDG_CACHE_HOME"]) / "hapax" / "antigrav-spawns").glob("*-run.sh")
    )
    assert run_scripts
    run_text = run_scripts[-1].read_text(encoding="utf-8")
    assert str(bin_dir / "agy") in run_text
    assert "--prompt-interactive" in run_text


def test_launcher_env_override_missing_fails_closed(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["HAPAX_ANTIGRAV_BIN"] = str(tmp_path / "missing-agy")
    workdir = tmp_path / "projects" / "hapax-council--antigrav"
    workdir.mkdir(parents=True)

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "antigrav",
            "--cd",
            str(workdir),
            "--terminal",
            "current",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 4
    assert "Antigravity CLI not found" in result.stderr
