from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "hapax-claude-reviewer"


def _fake_claude(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "Path = __import__('pathlib').Path\n"
        "Path(os.environ['HAPAX_FAKE_CLAUDE_ARGV']).write_text(\n"
        "    json.dumps(sys.argv[1:]), encoding='utf-8'\n"
        ")\n"
        "Path(os.environ['HAPAX_FAKE_CLAUDE_STDIN']).write_text(\n"
        "    sys.stdin.read(), encoding='utf-8'\n"
        ")\n"
        "print('```yaml')\n"
        "print('verdict: accept')\n"
        "print('findings: []')\n"
        "print('checklist: {}')\n"
        "print('```')\n",
        encoding="utf-8",
    )
    path.chmod(0o700)


def test_claude_reviewer_pins_opus_and_disables_tools(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    argv_path = tmp_path / "argv.json"
    stdin_path = tmp_path / "stdin.txt"
    _fake_claude(fake)

    env = {
        **os.environ,
        "HAPAX_FAKE_CLAUDE_ARGV": str(argv_path),
        "HAPAX_FAKE_CLAUDE_STDIN": str(stdin_path),
    }
    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(fake)],
        input="review packet",
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "```yaml\nverdict: accept\nfindings: []\nchecklist: {}\n```\n"
    assert stdin_path.read_text(encoding="utf-8") == "review packet"
    argv = json.loads(argv_path.read_text(encoding="utf-8"))
    assert argv[:6] == ["-p", "--model", "opus", "--allowedTools", "", "--append-system-prompt"]
    system_prompt = argv[6]
    assert "exactly one fenced yaml" in system_prompt
    assert "invalid-output" in system_prompt
    assert "Do all reasoning silently" in system_prompt


def test_claude_reviewer_rejects_model_override(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    _fake_claude(fake)

    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(fake), "--model", "sonnet"],
        input="review packet",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 64
    assert "pinned to opus" in result.stderr
