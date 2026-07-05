from __future__ import annotations

import os
import subprocess
from pathlib import Path

from shared.operator_attestation import expected_operator_attestation_ref

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_LAUNCHER = REPO_ROOT / "scripts" / "hapax-codex"
CLAUDE_LAUNCHER = REPO_ROOT / "scripts" / "hapax-claude"
TEST_HMAC_KEY = "test-crow-chat-hmac-key"


def _base_env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
    for key in (
        "CODEX_THREAD_NAME",
        "CODEX_ROLE",
        "CODEX_SESSION_NAME",
        "CODEX_SESSION",
        "CLAUDE_ROLE",
        "HAPAX_AGENT_NAME",
        "HAPAX_AGENT_ROLE",
        "HAPAX_SESSION_ID",
        "HAPAX_PARENT_AGENT_INTERFACE",
        "HAPAX_PARENT_AGENT_NAME",
    ):
        env.pop(key, None)
    return env


def _fake_codex(bin_dir: Path, env_file: Path) -> None:
    fake = bin_dir / "codex"
    fake.write_text(
        f"""#!/usr/bin/env bash
printf 'origin=%s\\n' "${{HAPAX_METHODOLOGY_ORIGIN_SURFACE:-}}" > {env_file}
printf 'ref=%s\\n' "${{HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF:-}}" >> {env_file}
printf 'required=%s\\n' "${{HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION:-}}" >> {env_file}
printf 'hmac=%s\\n' "${{HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY:-}}" >> {env_file}
exit 0
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)


def _fake_claude(bin_dir: Path, marker: Path) -> None:
    fake = bin_dir / "claude"
    fake.write_text(
        f"#!/usr/bin/env bash\nprintf 'claude-ran\\n' > {marker}\nexit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)


def _fake_tmux(bin_dir: Path, log_path: Path) -> None:
    fake = bin_dir / "tmux"
    fake.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> {log_path}
if [ "${{1:-}}" = "has-session" ]; then
  exit 1
fi
exit 0
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)


def test_hapax_codex_rejects_taskless_launch_when_g12_enforced(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION"] = "1"
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    _fake_codex(tmp_path / "bin", tmp_path / "codex-env.txt")

    result = subprocess.run(
        [
            str(CODEX_LAUNCHER),
            "--session",
            "cx-green",
            "--cd",
            str(workdir),
            "--terminal",
            "none",
            "--no-claim",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 18
    assert "operator_attestation_task_required_for_dispatch" in result.stderr
    assert "next action:" in result.stderr


def test_hapax_codex_valid_attestation_scrubs_hmac_before_worker(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    ref = expected_operator_attestation_ref(
        origin_surface="crow_chat",
        task_id="task-x",
        lane="cx-green",
        hmac_key=TEST_HMAC_KEY,
    )
    env.update(
        {
            "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
            "HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY": TEST_HMAC_KEY,
            "HAPAX_METHODOLOGY_ORIGIN_SURFACE": "crow_chat",
            "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF": ref,
        }
    )
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    env_file = tmp_path / "codex-env.txt"
    _fake_codex(tmp_path / "bin", env_file)

    result = subprocess.run(
        [
            str(CODEX_LAUNCHER),
            "--session",
            "cx-green",
            "--cd",
            str(workdir),
            "--terminal",
            "none",
            "--task",
            "task-x",
            "--no-claim",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    worker_env = env_file.read_text(encoding="utf-8")
    assert "origin=crow_chat" in worker_env
    assert f"ref={ref}" in worker_env
    assert "required=1" in worker_env
    assert "hmac=" in worker_env
    assert TEST_HMAC_KEY not in worker_env


def test_hapax_codex_tmux_runner_propagates_attestation_for_inner_gate(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["HAPAX_CODEX_TERMINAL"] = "tmux"
    ref = expected_operator_attestation_ref(
        origin_surface="crow_chat",
        task_id="task-x",
        lane="cx-green",
        hmac_key=TEST_HMAC_KEY,
    )
    env.update(
        {
            "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
            "HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY": TEST_HMAC_KEY,
            "HAPAX_METHODOLOGY_ORIGIN_SURFACE": "crow_chat",
            "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF": ref,
        }
    )
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    tmux_log = tmp_path / "tmux.log"
    _fake_codex(tmp_path / "bin", tmp_path / "codex-env.txt")
    _fake_tmux(tmp_path / "bin", tmux_log)

    result = subprocess.run(
        [
            str(CODEX_LAUNCHER),
            "--session",
            "cx-green",
            "--cd",
            str(workdir),
            "--task",
            "task-x",
            "--terminal",
            "tmux",
            "--no-claim",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    runner = Path(tmux_log.read_text(encoding="utf-8").splitlines()[-1].split()[-1])
    runner_text = runner.read_text(encoding="utf-8")
    assert "HAPAX_METHODOLOGY_ORIGIN_SURFACE=crow_chat" in runner_text
    assert "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF=" in runner_text
    assert "HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY=" in runner_text


def test_hapax_claude_readonly_skips_g12_attestation_gate(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION"] = "1"
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    marker = tmp_path / "claude-ran.txt"
    _fake_claude(tmp_path / "bin", marker)

    result = subprocess.run(
        [
            str(CLAUDE_LAUNCHER),
            "--role",
            "dev",
            "--cd",
            str(workdir),
            "--terminal",
            "none",
            "--readonly",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert marker.read_text(encoding="utf-8") == "claude-ran\n"
