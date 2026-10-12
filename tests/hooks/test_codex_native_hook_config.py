"""Ask the installed Codex parser what the shared launcher actually registers.

No model turn, hook execution, or trust mutation occurs. Set
HAPAX_CODEX_NATIVE_TEST_BIN to select a particular installed CLI for the witness.
"""

from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "hooks/scripts/codex-hook-adapter.sh"
EVENTS = ["sessionStart", "preToolUse", "postToolUse", "stop"]


def native_hooks(tmp_path: Path) -> list[dict]:
    binary = os.environ.get("HAPAX_CODEX_NATIVE_TEST_BIN") or shutil.which("codex")
    if not binary:
        pytest.skip("native Codex CLI unavailable; native parsing remains unobserved")
    env = {
        "HOME": str(tmp_path),
        "CODEX_HOME": str(tmp_path / ".codex"),
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "TMPDIR": str(tmp_path),
    }
    Path(env["CODEX_HOME"]).mkdir()
    binding = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; bind_codex_common_config "$2" "$2" "$3" '
            'http://localhost:8051; printf "%s\\0" "${CODEX_COMMON_CONFIG_ARGS[@]}"',
            "native-hook-test",
            str(ROOT / "scripts/capability-execution.sh"),
            str(tmp_path),
            str(ADAPTER),
        ],
        env=env,
        capture_output=True,
        check=True,
        timeout=10,
    )
    args = binding.stdout.decode().rstrip("\0").split("\0")
    with subprocess.Popen(
        [binary, "app-server", *args],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    ) as process:
        assert process.stdin is not None
        assert process.stdout is not None

        def send(message: dict) -> None:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "hapax-hook-parser-test", "version": "1"},
                    "capabilities": {"experimentalApi": True},
                },
            }
        )
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if not selector.select(timeout=0.5):
                        continue
                    line = process.stdout.readline()
                    assert line, "native app-server exited before listing hooks"
                    message = json.loads(line)
                    assert "error" not in message, message
                    if message.get("id") == 1:
                        send({"method": "initialized", "params": {}})
                        send(
                            {
                                "id": 2,
                                "method": "hooks/list",
                                "params": {"cwds": [str(tmp_path)]},
                            }
                        )
                    if message.get("id") == 2:
                        entry = message["result"]["data"][0]
                        assert not entry["errors"], entry
                        return entry["hooks"]
            pytest.fail("native hook-list response timed out")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize("event", EVENTS)
def test_shared_binding_registers_native_hook(tmp_path: Path, event: str) -> None:
    hooks = [hook for hook in native_hooks(tmp_path) if hook["eventName"] == event]
    assert len(hooks) == 1, f"expected one native {event} handler, got {hooks}"
    hook = hooks[0]
    assert hook["handlerType"] == "command"
    assert hook["command"] == str(ADAPTER)
    assert hook["enabled"] is True
    assert hook["timeoutSec"] == 20
    # Parsing must not silently grant trust in a fresh native configuration.
    assert hook["trustStatus"] == "untrusted"
