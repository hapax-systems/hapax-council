from __future__ import annotations

import os
import subprocess
from pathlib import Path

from shared.operator_attestation import expected_operator_attestation_ref

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_LAUNCHER = REPO_ROOT / "scripts" / "hapax-codex"
CODEX_HEADLESS = REPO_ROOT / "scripts" / "hapax-codex-headless"
CLAUDE_LAUNCHER = REPO_ROOT / "scripts" / "hapax-claude"
CLAUDE_HEADLESS = REPO_ROOT / "scripts" / "hapax-claude-headless"
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


def _fake_claude_env(bin_dir: Path, env_file: Path, claim_file: Path | None = None) -> None:
    fake = bin_dir / "claude"
    clear_claim = f': > "{claim_file}"\n' if claim_file is not None else ""
    fake.write_text(
        f"""#!/usr/bin/env bash
printf 'origin=%s\\n' "${{HAPAX_METHODOLOGY_ORIGIN_SURFACE:-}}" > {env_file}
printf 'ref=%s\\n' "${{HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF:-}}" >> {env_file}
printf 'required=%s\\n' "${{HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION:-}}" >> {env_file}
printf 'hmac=%s\\n' "${{HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY:-}}" >> {env_file}
{clear_claim}exit 0
""",
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
    env["HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION"] = "True"
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


def test_hapax_codex_validates_g12_before_codex_native_worktree_creation(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env["HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION"] = "1"
    _fake_codex(tmp_path / "bin", tmp_path / "codex-env.txt")
    expected_worktree = Path(env["HOME"]) / "projects" / "hapax-council--cx-green"

    result = subprocess.run(
        [
            str(CODEX_LAUNCHER),
            "--session",
            "cx-green",
            "--slot",
            "beta",
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
    assert not expected_worktree.exists()


def test_hapax_codex_validates_g12_before_remote_dispatch_preflight(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env["HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION"] = "1"
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"
    ssh_marker = tmp_path / "ssh-ran.txt"
    fake_ssh = tmp_path / "bin" / "ssh"
    fake_ssh.write_text(
        f"#!/usr/bin/env bash\nprintf 'ssh-ran\\n' > {ssh_marker}\nexit 0\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
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
    assert not ssh_marker.exists()


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


def test_hapax_codex_tmux_runner_propagates_attestation_without_hmac_key(
    tmp_path: Path,
) -> None:
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
    tmux_env = tmp_path / "tmux-env.txt"
    _fake_codex(tmp_path / "bin", tmp_path / "codex-env.txt")
    fake_tmux = tmp_path / "bin" / "tmux"
    fake_tmux.write_text(
        f"""#!/usr/bin/env bash
if [ "${{1:-}}" = "has-session" ]; then
  exit 1
fi
if [ "${{1:-}}" = "new-session" ]; then
  printf '%s\\n' "$*" >> {tmux_log}
  printf 'hmac=%s\\n' "${{HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY:-}}" > {tmux_env}
  printf 'operator_hmac=%s\\n' "${{HAPAX_OPERATOR_ATTESTATION_HMAC_KEY:-}}" >> {tmux_env}
  printf 'breakglass_hmac=%s\\n' "${{HAPAX_G12_BREAKGLASS_HMAC_KEY:-}}" >> {tmux_env}
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_tmux.chmod(0o755)

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
    tmux_launch_env = tmux_env.read_text(encoding="utf-8")
    assert "hmac=\n" in tmux_launch_env
    assert "operator_hmac=\n" in tmux_launch_env
    assert "breakglass_hmac=\n" in tmux_launch_env
    assert TEST_HMAC_KEY not in tmux_launch_env
    runner = Path(tmux_log.read_text(encoding="utf-8").splitlines()[-1].split()[-1])
    runner_text = runner.read_text(encoding="utf-8")
    assert "HAPAX_METHODOLOGY_ORIGIN_SURFACE=crow_chat" in runner_text
    assert "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF=" in runner_text
    assert "unset HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY" in runner_text
    assert "unset HAPAX_OPERATOR_ATTESTATION_HMAC_KEY" in runner_text
    assert "unset HAPAX_G12_BREAKGLASS_HMAC_KEY" in runner_text
    assert "HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY=" not in runner_text
    assert "HAPAX_OPERATOR_ATTESTATION_HMAC_KEY=" not in runner_text
    assert "HAPAX_G12_BREAKGLASS_HMAC_KEY=" not in runner_text
    assert TEST_HMAC_KEY not in runner_text

    runner_result = subprocess.run(
        [str(runner)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert runner_result.returncode == 0, runner_result.stderr
    worker_env = (tmp_path / "codex-env.txt").read_text(encoding="utf-8")
    assert "origin=crow_chat" in worker_env
    assert f"ref={ref}" in worker_env
    assert "required=1" in worker_env
    assert "hmac=" in worker_env
    assert TEST_HMAC_KEY not in worker_env


def test_hapax_codex_headless_remote_payload_carries_attestation_without_hmac(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    home = Path(env["HOME"])
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    env_file = tmp_path / "codex-headless-env.txt"
    ref = expected_operator_attestation_ref(
        origin_surface="crow_chat",
        task_id="task-x",
        lane="cx-green",
        hmac_key=TEST_HMAC_KEY,
    )
    env.update(
        {
            "HAPAX_CODEX_HEADLESS_ALLOW": "1",
            "HAPAX_CODEX_HEADLESS_WORKDIR": str(workdir),
            "HAPAX_DISPATCH_HOST": "appendix-remote",
            "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
            "HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY": TEST_HMAC_KEY,
            "HAPAX_METHODOLOGY_ORIGIN_SURFACE": "crow_chat",
            "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF": ref,
        }
    )
    _fake_codex(tmp_path / "bin", env_file)
    fake_ssh = tmp_path / "bin" / "ssh"
    fake_ssh.write_text(
        """#!/usr/bin/env bash
remote_cmd="${@: -1}"
exec env \
  -u HAPAX_METHODOLOGY_ORIGIN_SURFACE \
  -u HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF \
  -u HAPAX_METHODOLOGY_REQUIRE_CROW_CHAT_ATTESTATION \
  -u HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION \
  -u HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY \
  -u HAPAX_OPERATOR_ATTESTATION_HMAC_KEY \
  -u HAPAX_G12_BREAKGLASS_HMAC_KEY \
  bash -c "$remote_cmd"
""",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)

    result = subprocess.run(
        [
            str(CODEX_HEADLESS),
            "--task",
            "task-x",
            "--no-claim",
            "--force",
            "cx-green",
            "governed prompt",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    worker_env = env_file.read_text(encoding="utf-8")
    assert "origin=crow_chat" in worker_env
    assert f"ref={ref}" in worker_env
    assert "required=1" in worker_env
    assert "hmac=" in worker_env
    assert TEST_HMAC_KEY not in worker_env


def test_hapax_claude_readonly_skips_g12_attestation_gate(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION"] = "1"
    env["HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY"] = TEST_HMAC_KEY
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    env_file = tmp_path / "claude-readonly-env.txt"
    _fake_claude_env(tmp_path / "bin", env_file)

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
    worker_env = env_file.read_text(encoding="utf-8")
    assert "hmac=" in worker_env
    assert TEST_HMAC_KEY not in worker_env


def test_hapax_claude_validates_g12_before_worktree_claim(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION"] = "1"
    workdir = tmp_path / "worktree"
    (workdir / "scripts").mkdir(parents=True)
    claim_marker = tmp_path / "claim-ran.txt"
    cc_claim = workdir / "scripts" / "cc-claim"
    cc_claim.write_text(
        f"#!/usr/bin/env bash\nprintf 'claim-ran\\n' > {claim_marker}\nexit 0\n",
        encoding="utf-8",
    )
    cc_claim.chmod(0o755)
    _fake_claude(tmp_path / "bin", tmp_path / "claude-ran.txt")

    result = subprocess.run(
        [
            str(CLAUDE_LAUNCHER),
            "--role",
            "dev",
            "--cd",
            str(workdir),
            "--terminal",
            "none",
            "--task",
            "task-x",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 18
    assert "crow_chat_origin_required_for_dispatch" in result.stderr
    assert not claim_marker.exists()


def test_hapax_claude_non_readonly_rejects_taskless_when_g12_enforced(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env["HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION"] = "1"
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    _fake_claude(tmp_path / "bin", tmp_path / "claude-ran.txt")

    result = subprocess.run(
        [
            str(CLAUDE_LAUNCHER),
            "--role",
            "dev",
            "--cd",
            str(workdir),
            "--terminal",
            "none",
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


def test_hapax_claude_headless_valid_attestation_scrubs_hmac_before_worker(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    home = Path(env["HOME"])
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n", encoding="utf-8")
    env_file = tmp_path / "claude-headless-env.txt"
    ref = expected_operator_attestation_ref(
        origin_surface="crow_chat",
        task_id="task-x",
        lane="beta",
        hmac_key=TEST_HMAC_KEY,
    )
    env.update(
        {
            "HAPAX_CLAUDE_HEADLESS_ALLOW": "1",
            "HAPAX_CLAUDE_HEADLESS_PIPE_DIR": str(tmp_path / "pipe"),
            "HAPAX_G12_REQUIRE_CROW_CHAT_ATTESTATION": "1",
            "HAPAX_CROW_CHAT_OPERATOR_HMAC_KEY": TEST_HMAC_KEY,
            "HAPAX_METHODOLOGY_ORIGIN_SURFACE": "crow_chat",
            "HAPAX_METHODOLOGY_OPERATOR_ATTESTATION_REF": ref,
        }
    )
    _fake_claude_env(tmp_path / "bin", env_file, claim_file)

    result = subprocess.run(
        [str(CLAUDE_HEADLESS), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    worker_env = env_file.read_text(encoding="utf-8")
    assert "origin=crow_chat" in worker_env
    assert f"ref={ref}" in worker_env
    assert "required=1" in worker_env
    assert "hmac=" in worker_env
    assert TEST_HMAC_KEY not in worker_env
