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
        "argv = sys.argv[1:]\n"
        "required_pairs = {\n"
        "    '--model': 'opus',\n"
        "    '--tools': '',\n"
        "    '--allowedTools': '',\n"
        "    '--permission-mode': 'manual',\n"
        "    '--mcp-config': '{\"mcpServers\":{}}',\n"
        "}\n"
        "for key, value in required_pairs.items():\n"
        "    if key not in argv or argv[argv.index(key) + 1] != value:\n"
        "        print(f'missing required pair {key}={value!r}', file=sys.stderr)\n"
        "        sys.exit(13)\n"
        "for flag in ('--safe-mode', '--disable-slash-commands', '--no-session-persistence', '--strict-mcp-config'):\n"
        "    if flag not in argv:\n"
        "        print(f'missing required flag {flag}', file=sys.stderr)\n"
        "        sys.exit(13)\n"
        "if '--disallowedTools' not in argv:\n"
        "    print('missing disallowed tools', file=sys.stderr)\n"
        "    sys.exit(13)\n"
        "Path(os.environ['HAPAX_FAKE_CLAUDE_ARGV']).write_text(\n"
        "    json.dumps(argv), encoding='utf-8'\n"
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
    assert argv[:3] == ["-p", "--model", "opus"]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--allowedTools") + 1] == ""
    disallowed = argv[argv.index("--disallowedTools") + 1]
    assert "Bash" in disallowed
    assert "Read" in disallowed
    assert argv[argv.index("--permission-mode") + 1] == "manual"
    assert "--safe-mode" in argv
    assert "--disable-slash-commands" in argv
    assert "--no-session-persistence" in argv
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert "--strict-mcp-config" in argv
    system_prompt = argv[argv.index("--append-system-prompt") + 1]
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
    assert "with --model opus" in result.stderr


def test_claude_reviewer_omits_child_stdout_on_nonzero_exit(tmp_path: Path) -> None:
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('quota wall text that must not become review stdout')\n"
        "print('rate limited', file=sys.stderr)\n"
        "sys.exit(42)\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)

    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(fake)],
        input="review packet",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 42
    assert result.stdout == ""
    assert "rate limited" in result.stderr
    assert "stdout omitted" in result.stderr
