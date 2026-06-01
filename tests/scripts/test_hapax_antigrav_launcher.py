"""Tests for the Hapax Antigrav/agy launcher."""

from __future__ import annotations

import json
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


def test_launcher_wires_agy_pretooluse_gate(tmp_path: Path) -> None:
    # agy loads Claude-compatible hooks from $HOME/.gemini/antigravity-cli/hooks.json
    # (verified via strace). The launcher must deploy that file so an agy
    # run_command/write_to_file/replace_file_content call is translated by the
    # adapter and gated by cc-task-gate — closing the Antigrav enforcing-gate P0.
    env = _base_env(tmp_path)
    workdir = tmp_path / "projects" / "hapax-council--antigrav"
    workdir.mkdir(parents=True)

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "antigrav",
            "--cd",
            str(workdir),
            "--no-claim",
            "--no-open",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr

    hooks_json = Path(env["HOME"]) / ".gemini" / "antigravity-cli" / "hooks.json"
    assert hooks_json.is_file(), f"hooks.json not deployed; stderr={result.stderr}"

    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    pre = data["hooks"]["PreToolUse"]
    assert pre, "PreToolUse must register at least one hook"
    entry = pre[0]
    matcher = entry["matcher"]
    # Matcher targets agy's native mutation tool names (the gate runs pre-translation).
    assert "run_command" in matcher
    assert "write_to_file" in matcher
    assert "replace_file_content" in matcher

    command = entry["hooks"][0]["command"]
    assert entry["hooks"][0]["type"] == "command"
    assert "antigrav-hook-adapter.sh" in command
    assert "cc-task-gate.sh" in command
    # Adapter + delegate resolve under COUNCIL_DIR so the gate stays repo-sourced.
    assert str(REPO_ROOT) in command


def test_launcher_preserves_foreign_hooks_json(tmp_path: Path) -> None:
    # A hand-rolled hooks.json that Hapax did not author must not be clobbered.
    env = _base_env(tmp_path)
    workdir = tmp_path / "projects" / "hapax-council--antigrav"
    workdir.mkdir(parents=True)
    cfg_dir = Path(env["HOME"]) / ".gemini" / "antigravity-cli"
    cfg_dir.mkdir(parents=True)
    foreign = cfg_dir / "hooks.json"
    foreign.write_text('{"hooks": {"PreToolUse": []}, "operator": "custom"}\n', encoding="utf-8")

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--session",
            "antigrav",
            "--cd",
            str(workdir),
            "--no-claim",
            "--no-open",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert foreign.read_text(encoding="utf-8") == (
        '{"hooks": {"PreToolUse": []}, "operator": "custom"}\n'
    )
    assert "not overwriting" in result.stderr


def test_wire_hooks_only_wires_gate_without_launching_ide(tmp_path: Path) -> None:
    # --wire-hooks-only activates the agy enforcing gate (writes hooks.json) and
    # exits WITHOUT provisioning a worktree, refreshing AGENTS.md, or launching
    # the agy IDE/tmux lane. This is the path that turns the gate on live without
    # popping an unsolicited Antigravity window.
    env = _base_env(tmp_path)
    bin_dir = Path(env["PATH"].split(":", 1)[0])
    agy_log = tmp_path / "agy.log"
    tmux_log = tmp_path / "tmux.log"
    _write_executable(
        bin_dir / "agy",
        f"#!/usr/bin/env bash\nprintf 'CALLED %s\\n' \"$@\" >> {agy_log}\n",
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

    result = subprocess.run(
        [str(LAUNCHER), "--wire-hooks-only", "--cd", str(workdir)],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "wired agy PreToolUse gate" in result.stderr

    hooks_json = Path(env["HOME"]) / ".gemini" / "antigravity-cli" / "hooks.json"
    assert hooks_json.is_file(), f"hooks.json not deployed; stderr={result.stderr}"
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    entry = data["hooks"]["PreToolUse"][0]
    assert "antigrav-hook-adapter.sh" in entry["hooks"][0]["command"]
    assert "cc-task-gate.sh" in entry["hooks"][0]["command"]

    # No IDE / tmux launch — the gate is wired with no unsolicited window.
    assert not agy_log.exists(), (
        f"agy must not launch under --wire-hooks-only; stderr={result.stderr}"
    )
    assert not tmux_log.exists(), (
        f"tmux must not launch under --wire-hooks-only; stderr={result.stderr}"
    )
    # No worktree-provisioning side effects (AGENTS.md/rules not refreshed).
    assert not (workdir / ".agents").exists(), "wire-only must not refresh AGENTS rules"


def test_wire_hooks_only_fails_closed_on_foreign_hooks(tmp_path: Path) -> None:
    # If a non-Hapax hooks.json already exists, wire-only must refuse to clobber
    # it and surface a non-zero exit (fail-closed), leaving the file untouched.
    env = _base_env(tmp_path)
    bin_dir = Path(env["PATH"].split(":", 1)[0])
    _write_executable(bin_dir / "agy", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(bin_dir / "tmux", "#!/usr/bin/env bash\nexit 0\n")
    cfg_dir = Path(env["HOME"]) / ".gemini" / "antigravity-cli"
    cfg_dir.mkdir(parents=True)
    foreign = cfg_dir / "hooks.json"
    original = '{"hooks": {"PreToolUse": []}, "operator": "custom"}\n'
    foreign.write_text(original, encoding="utf-8")
    workdir = tmp_path / "projects" / "hapax-council--antigrav"
    workdir.mkdir(parents=True)

    result = subprocess.run(
        [str(LAUNCHER), "--wire-hooks-only", "--cd", str(workdir)],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode != 0, "wire-only must fail closed on a foreign hooks.json"
    assert "not overwriting" in result.stderr
    assert foreign.read_text(encoding="utf-8") == original


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
