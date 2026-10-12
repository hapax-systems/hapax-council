"""Native JSON response values reach isolated adapter consumers without loss."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ADAPTER = Path(__file__).resolve().parents[2] / "hooks/scripts/codex-hook-adapter.sh"
TEXT = 'fixture "quoted" \\ λ\t\x00\n\n'
LARGE = TEXT * 12000


def _run(
    tmp_path: Path, response_fields: dict, *, phase: str = "PostToolUse", hook_exit: int = 0
) -> tuple[subprocess.CompletedProcess, dict, Path]:
    # Only these fixture consumers exist: no live hook, socket or command runs.
    scripts = tmp_path / "hooks/scripts"
    scripts.mkdir(parents=True)
    adapter = scripts / ADAPTER.name
    shutil.copy2(ADAPTER, adapter)
    first, second = (
        ("host-power-command-guard.sh", "cc-task-gate.sh")
        if phase == "PreToolUse"
        else ("axiom-audit.sh", "doc-update-advisory.sh")
    )
    for name, capture, status in (
        (first, "first.json", hook_exit),
        (second, "second.json", 0),
    ):
        hook = scripts / name
        hook.write_text(
            '#!/usr/bin/env bash\ncat > "${BASH_SOURCE[0]%/*}/' + capture + '"\n'
            "printf '%s\\n' 'fixture decision'\n"
            f"exit {status}\n"
        )
        hook.chmod(0o755)
    payload = {
        "session_id": "response-fixture-session",
        "cwd": str(tmp_path),
        "tool_name": "exec_command",
        "tool_input": {"cmd": "fixture-not-executed\n\n"},
        **response_fields,
    }
    result = subprocess.run(
        ["bash", str(adapter), phase],
        input=json.dumps(payload).encode(),
        capture_output=True,
        env={"PATH": os.environ["PATH"], "HAPAX_AGENT_NAME": "test-response", "LANG": "C.UTF-8"},
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, (result.returncode, result.stderr)
    return result, json.loads((scripts / "first.json").read_bytes()), scripts / "second.json"


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        pytest.param({"tool_response": TEXT}, TEXT, id="string"),
        pytest.param({"tool_response": ""}, "", id="empty-string"),
        pytest.param({"tool_response": 42}, "42", id="number"),
        pytest.param({"tool_response": False}, "false", id="false"),
        pytest.param({"tool_response": True}, "true", id="true"),
        pytest.param({"tool_response": ["λ", 0, False, None]}, '["λ",0,false,null]', id="array"),
        pytest.param({"tool_response": {"other": [1, "λ"]}}, '{"other":[1,"λ"]}', id="object"),
        pytest.param({"tool_response": None}, "", id="null"),
        pytest.param({}, "", id="missing"),
        pytest.param({"tool_response": {"output": TEXT, "stdout": "unused"}}, TEXT, id="output"),
        pytest.param({"tool_response": {"stdout": TEXT}}, TEXT, id="stdout"),
        pytest.param({"tool_response": {"output": None, "stdout": TEXT}}, TEXT, id="null-output"),
        pytest.param(
            {"tool_response": {"output": False, "stdout": "unused"}}, "false", id="false-output"
        ),
        pytest.param({"tool_response": {"stdout": False}}, "false", id="false-stdout"),
        pytest.param({"tool_response": {"output": [1, "λ"]}}, '[1,"λ"]', id="json-output"),
        pytest.param({"tool_response": {"output": "", "stdout": "unused"}}, "", id="empty-output"),
        pytest.param({"tool_response": "unused", "tool_output": TEXT}, TEXT, id="top-output"),
        pytest.param({"tool_response": "unused", "tool_output": False}, "false", id="top-false"),
        pytest.param({"tool_response": TEXT, "tool_output": None}, TEXT, id="top-null"),
    ],
)
def test_response_value_normalizes_without_loss(
    tmp_path: Path, fields: dict, expected: str
) -> None:
    result, event, following = _run(tmp_path, fields)
    assert json.loads(result.stdout)["continue"] is True
    assert event == {
        "hook_event_name": "PostToolUse",
        "session_id": "response-fixture-session",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "fixture-not-executed\n\n"},
        "tool_output": expected,
        "tool_response": {"output": expected},
    }
    assert event["tool_output"].encode() == expected.encode()
    assert json.loads(following.read_bytes()) == event


@pytest.mark.parametrize("form", ["scalar", "output", "stdout"])
def test_large_response_stays_on_stdin_and_preserves_bytes(tmp_path: Path, form: str) -> None:
    assert len(LARGE.encode()) > 128 * 1024
    response = LARGE if form == "scalar" else {form: LARGE}
    result, event, following = _run(tmp_path, {"tool_response": response})
    assert json.loads(result.stdout)["continue"] is True
    assert event["tool_output"].encode() == LARGE.encode()
    assert event["tool_response"]["output"].encode() == LARGE.encode()
    assert json.loads(following.read_bytes()) == event


@pytest.mark.parametrize("phase", ["PreToolUse", "PostToolUse"])
@pytest.mark.parametrize("hook_exit", [0, 2, 7])
def test_scalar_response_preserves_hook_decision_and_chain(
    tmp_path: Path, phase: str, hook_exit: int
) -> None:
    result, event, following = _run(
        tmp_path, {"tool_response": TEXT}, phase=phase, hook_exit=hook_exit
    )
    assert event["tool_output"] == TEXT
    assert event["hook_event_name"] == phase
    decision = json.loads(result.stdout)
    if hook_exit:
        assert decision["decision"] == "block"
        assert f"exited {hook_exit}" in decision["reason"]
        assert "fixture decision" in decision["reason"]
        assert not following.exists(), "a blocked chain must stop before the next consumer"
    else:
        assert decision["continue"] is True
        assert "fixture decision" in decision["systemMessage"]
        assert json.loads(following.read_bytes()) == event
