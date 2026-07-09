from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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
    assert "LS" not in disallowed
    assert "MultiEdit" not in disallowed
    assert "NotebookRead" not in disallowed
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


def test_claude_reviewer_missing_binary_path_is_legible(tmp_path: Path) -> None:
    missing = tmp_path / "missing-claude"

    result = subprocess.run(
        [sys.executable, str(WRAPPER), "--claude-bin", str(missing)],
        input="review packet",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "failed to launch" in result.stderr
    assert str(missing) in result.stderr
    assert "HAPAX_CLAUDE_BIN" in result.stderr
    assert "rerun the review dispatch" in result.stderr


def test_local_claude_cli_help_documents_no_tools_surface() -> None:
    claude_bin = os.environ.get("HAPAX_CLAUDE_BIN") or os.environ.get("CLAUDE_BIN") or "claude"
    if shutil.which(claude_bin) is None and not Path(claude_bin).exists():
        pytest.skip("local Claude CLI is not installed")

    result = subprocess.run(
        [claude_bin, "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    help_text = result.stdout
    normalized_help = " ".join(help_text.split())
    assert "--tools <tools...>" in help_text
    assert 'Use "" to disable all tools' in normalized_help
    assert "--allowedTools" in help_text
    assert "--disallowedTools" in help_text
    assert "--safe-mode" in help_text
    assert "--disable-slash-commands" in help_text
    assert "--no-session-persistence" in help_text
    assert "--strict-mcp-config" in help_text
    assert '"manual"' in help_text


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
    assert "claude stdout diagnostic for classifier" in result.stderr
    assert "stdout omitted" in result.stderr
    assert "single-line stdout is copied only as the classifier diagnostic" in result.stderr


def test_claude_reviewer_preserves_stdout_only_quota_wall_for_classifier(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        'print("You\'ve hit your weekly limit - resets 5pm (America/Chicago)")\n'
        "sys.exit(75)\n",
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

    assert result.returncode == 75
    assert result.stdout == ""
    assert "claude stdout diagnostic for classifier" in result.stderr
    assert "weekly limit" in result.stderr
    assert "stdout omitted" in result.stderr


def test_claude_reviewer_preserves_single_line_stdout_diagnostic_with_child_stderr(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('non-quota stderr noise', file=sys.stderr)\n"
        'print("You\'ve hit your weekly limit - resets 5pm (America/Chicago)")\n'
        "sys.exit(75)\n",
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

    assert result.returncode == 75
    assert result.stdout == ""
    assert "non-quota stderr noise" in result.stderr
    assert "claude stdout diagnostic for classifier" in result.stderr
    assert "weekly limit" in result.stderr


@pytest.mark.skipif(
    os.environ.get("HAPAX_RUN_CLAUDE_REVIEWER_REAL_SMOKE") != "1",
    reason="real Claude CLI no-tools probe is opt-in and uses local subscription quota",
)
def test_claude_reviewer_real_cli_no_tools_probe() -> None:
    result = subprocess.run(
        [sys.executable, str(WRAPPER)],
        input=(
            "No-tools probe. Do not use or request a shell. If a Bash tool is "
            "available, it would be unsafe to use it here. Emit only the strict "
            "review YAML: verdict accept, findings [], checklist {}."
        ),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.startswith("```yaml\n")
    assert result.stdout.endswith("\n```\n")
    assert "tool_use" not in result.stdout.lower()
    assert "bash" not in result.stdout.lower()


@pytest.mark.skipif(
    os.environ.get("HAPAX_RUN_CLAUDE_REVIEWER_REAL_SMOKE") != "1",
    reason="real Claude CLI tool-surface probe is opt-in and uses local subscription quota",
)
def test_claude_cli_reports_empty_tools_with_wrapper_equivalent_flags() -> None:
    prompt = (
        "Use the actual Bash tool to run exactly: printf "
        "HAPAX_CLAUDE_TOOL_PROBE_20260709. If no actual Bash tool is available, "
        "say exactly NO_ACTUAL_TOOL_AVAILABLE. Do not simulate tool output."
    )
    common = [
        "claude",
        "-p",
        "--verbose",
        "--model",
        "opus",
        "--safe-mode",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--strict-mcp-config",
        "--output-format",
        "stream-json",
    ]
    result = subprocess.run(
        [
            *common,
            "--tools",
            "",
            "--allowedTools",
            "",
            "--disallowedTools",
            "Agent,Bash,Edit,Glob,Grep,NotebookEdit,Read,Task,TodoWrite,WebFetch,WebSearch,Write",
            "--permission-mode",
            "manual",
            prompt,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    init = next(
        event
        for event in events
        if event.get("type") == "system" and event.get("subtype") == "init"
    )
    assert init["tools"] == []
    assert init["mcp_servers"] == []
    tool_uses = [
        item
        for event in events
        for item in event.get("message", {}).get("content", [])
        if item.get("type") == "tool_use"
    ]
    assert tool_uses == []
    result_event = next(event for event in events if event.get("type") == "result")
    assert result_event["result"] == "NO_ACTUAL_TOOL_AVAILABLE"
