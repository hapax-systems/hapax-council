"""Regression tests for the visible Claude launcher and coordinator targeting."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tests.scripts.launcher_activation_fixture import install_launcher_activation

REPO_ROOT = Path(__file__).parent.parent.parent
LAUNCHER = REPO_ROOT / "scripts" / "hapax-claude"
SEND = REPO_ROOT / "scripts" / "hapax-claude-send"
HEALTH = REPO_ROOT / "scripts" / "hapax-claude-health"


def _write_exe(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _env(tmp_path: Path, bin_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["XDG_CACHE_HOME"] = str(tmp_path / ".cache")
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env


def _visible_launcher_fixture(
    tmp_path: Path,
) -> tuple[dict[str, str], Path, Path, Path]:
    bin_dir = tmp_path / "launcher-bin"
    workdir = tmp_path / "worktree"
    home = tmp_path / "launcher-home"
    for path in (bin_dir, workdir / "scripts", home):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    for name in tuple(env):
        if name.startswith("HAPAX_CLAIM_DISPATCH_") or name in {
            "CLAUDE_ROLE",
            "HAPAX_AGENT_INTERFACE",
            "HAPAX_AGENT_NAME",
            "HAPAX_AGENT_ROLE",
            "HAPAX_DISPATCH_CLAIM_SWEEP",
            "HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID",
            "HAPAX_METHODOLOGY_DISPATCH_TASK",
            "HAPAX_SESSION_ID",
            "HAPAX_WORKTREE_ROLE",
        }:
            env.pop(name)
    env.update(
        {
            "HOME": str(home),
            "XDG_CACHE_HOME": str(tmp_path / "launcher-cache"),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HAPAX_COUNCIL_DIR": str(workdir),
            "HAPAX_CLAUDE_EFFORT": "",
            "HAPAX_CLAUDE_SKIP_PERMS": "0",
            "HAPAX_SESSION_ID": "visible-session-test",
        }
    )
    env.update(install_launcher_activation(home))
    _write_exe(workdir / "scripts" / "hapax-relay-retire", "#!/usr/bin/env bash\nexit 0\n")
    return env, bin_dir, workdir, home


def _write_visible_claim(workdir: Path, log_path: Path) -> Path:
    claim = workdir / "scripts" / "cc-claim"
    _write_exe(
        claim,
        f"""#!/usr/bin/env bash
case "${{1:-}}" in
  --dispatch-protocol-version)
    printf '%s\\n' 'hapax-claim-dispatch-v1'
    exit 0
    ;;
  --verify-dispatch-binding)
    printf 'verify %s\\n' "${{2:-}}" >> {log_path}
    exit "${{HAPAX_FAKE_CC_CLAIM_VERIFY_RC:-0}}"
    ;;
esac
printf 'claim %s %s %s\\n' "$HAPAX_AGENT_NAME" "$HAPAX_SESSION_ID" "$1" >> {log_path}
mkdir -p "$HOME/.cache/hapax"
printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-$HAPAX_AGENT_NAME"
printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-$HAPAX_AGENT_NAME-$HAPAX_SESSION_ID"
""",
    )
    return claim


def _read_environment(path: Path) -> dict[str, str]:
    return {
        key: value
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
        for key, value in [line.split("=", 1)]
    }


def test_visible_claude_same_task_cache_requires_exact_dispatch_binding(tmp_path: Path) -> None:
    env, bin_dir, workdir, home = _visible_launcher_fixture(tmp_path)
    worker_env = tmp_path / "worker-env.txt"
    claim_log = tmp_path / "claim.log"
    path_claim_used = tmp_path / "path-claim-used"
    _write_visible_claim(workdir, claim_log)
    _write_exe(bin_dir / "claude", f"#!/usr/bin/env bash\nenv | sort > {worker_env}\n")
    _write_exe(bin_dir / "cc-claim", f"#!/usr/bin/env bash\ntouch {path_claim_used}\nexit 99\n")
    env["HAPAX_CLAIM_DISPATCH_MESSAGE_ID"] = "dispatch-message"
    env["HAPAX_FAKE_CC_CLAIM_VERIFY_RC"] = "23"

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--role",
            "beta",
            "--cd",
            str(workdir),
            "--terminal",
            "none",
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 18
    assert "exact dispatch binding verification failed" in result.stderr
    claim_lines = claim_log.read_text(encoding="utf-8").splitlines()
    assert claim_lines[-1] == "verify demo-task"
    claim_parts = claim_lines[0].split()
    assert claim_parts[:2] == ["claim", "beta"]
    assert claim_parts[2] != "visible-session-test"
    assert claim_parts[3] == "demo-task"
    assert not worker_env.exists()
    assert not path_claim_used.exists()


def test_visible_claude_refuses_legacy_only_claim_inheritance(tmp_path: Path) -> None:
    env, bin_dir, workdir, home = _visible_launcher_fixture(tmp_path)
    worker_env = tmp_path / "worker-env.txt"
    claim_log = tmp_path / "claim.log"
    _write_visible_claim(workdir, claim_log)
    _write_exe(bin_dir / "claude", f"#!/usr/bin/env bash\nenv | sort > {worker_env}\n")
    claim_cache = home / ".cache" / "hapax"
    claim_cache.mkdir(parents=True, exist_ok=True)
    (claim_cache / "cc-active-task-beta").write_text("demo-task\n", encoding="utf-8")

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--role",
            "beta",
            "--cd",
            str(workdir),
            "--terminal",
            "none",
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 16
    assert "incomplete or divergent role/session claim projection" in result.stderr
    assert not claim_log.exists()
    assert not worker_env.exists()


def test_visible_claude_refuses_stale_activation_identity(tmp_path: Path) -> None:
    env, bin_dir, workdir, _home = _visible_launcher_fixture(tmp_path)
    worker_env = tmp_path / "worker-env.txt"
    _write_exe(bin_dir / "claude", f"#!/usr/bin/env bash\nenv | sort > {worker_env}\n")
    receipt = Path(env["HAPAX_SOURCE_ACTIVATION_RECEIPT"])
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["active_source_head"] = "764a645ba37af239cd1068e6a9fbe4a4467f2876"
    receipt.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--role",
            "beta",
            "--cd",
            str(workdir),
            "--terminal",
            "none",
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 14
    assert "refusing unverified source-activation cc-claim" in result.stderr
    assert not worker_env.exists()


def test_visible_claude_tmux_runner_propagates_governed_environment(tmp_path: Path) -> None:
    env, bin_dir, workdir, _home = _visible_launcher_fixture(tmp_path)
    worker_env = tmp_path / "worker-env.txt"
    claim_log = tmp_path / "claim.log"
    path_claim_used = tmp_path / "path-claim-used"
    _write_visible_claim(workdir, claim_log)
    _write_exe(
        bin_dir / "claude", '#!/usr/bin/env bash\nenv | sort > "$HAPAX_TEST_CLAUDE_ENV_LOG"\n'
    )
    _write_exe(bin_dir / "cc-claim", f"#!/usr/bin/env bash\ntouch {path_claim_used}\nexit 99\n")
    _write_exe(
        bin_dir / "tmux",
        """#!/usr/bin/env bash
case "${1:-}" in
  has-session)
    exit 1
    ;;
  new-session)
    runner="${@: -1}"
    env -i \\
      HOME="$HOME" \\
      PATH="$PATH" \\
      XDG_CACHE_HOME="$XDG_CACHE_HOME" \\
      HAPAX_TEST_CLAUDE_ENV_LOG="$HAPAX_TEST_CLAUDE_ENV_LOG" \\
      "$runner"
    ;;
esac
""",
    )
    binding_env = {
        "HAPAX_CLAIM_DISPATCH_AUTHORITY_CASE": "CASE-TEST-001",
        "HAPAX_CLAIM_DISPATCH_BINDING_HASH": "binding-hash",
        "HAPAX_CLAIM_DISPATCH_CLAIM_PROJECTION_SHA256": "claim-sha",
        "HAPAX_CLAIM_DISPATCH_IDEMPOTENCY_KEY": "idempotency-key",
        "HAPAX_CLAIM_DISPATCH_LANE_GENERATION": "lane-generation",
        "HAPAX_CLAIM_DISPATCH_LANE_PID": "123",
        "HAPAX_CLAIM_DISPATCH_LANE_PID_GENERATION": "pid-generation",
        "HAPAX_CLAIM_DISPATCH_LANE_SESSION": "hapax-claude-beta",
        "HAPAX_CLAIM_DISPATCH_MESSAGE_ID": "dispatch-message",
        "HAPAX_CLAIM_DISPATCH_MODE": "interactive",
        "HAPAX_CLAIM_DISPATCH_PARENT_SPEC": "/tmp/parent-spec.md",
        "HAPAX_CLAIM_DISPATCH_PARENT_SPEC_SHA256": "parent-sha",
        "HAPAX_CLAIM_DISPATCH_PLATFORM": "claude",
        "HAPAX_CLAIM_DISPATCH_PROFILE": "full",
        "HAPAX_CLAIM_DISPATCH_RELAY_PROJECTION_SHA256": "relay-sha",
        "HAPAX_CLAIM_DISPATCH_TASK_PATH": "/tmp/demo-task.md",
        "HAPAX_CLAIM_DISPATCH_TASK_SHA256": "task-sha",
    }
    env.update(binding_env)
    env.update(
        {
            "HAPAX_CLAIM_LEASE_TTL_SECS": "0",
            "HAPAX_DISPATCH_CLAIM_SWEEP": "0",
            "HAPAX_IDLE_UPDATE_SECONDS": "321",
            "HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID": "dispatch-message",
            "HAPAX_TEST_CLAUDE_ENV_LOG": str(worker_env),
        }
    )

    result = subprocess.run(
        [
            str(LAUNCHER),
            "--role",
            "beta",
            "--cd",
            str(workdir),
            "--terminal",
            "tmux",
            "--task",
            "demo-task",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "hapax-claude-beta"
    claim_lines = claim_log.read_text(encoding="utf-8").splitlines()
    assert claim_lines[-1] == "verify demo-task"
    claim_parts = claim_lines[0].split()
    assert claim_parts[:2] == ["claim", "beta"]
    minted_session_id = claim_parts[2]
    assert minted_session_id != "visible-session-test"
    assert claim_parts[3] == "demo-task"
    assert not path_claim_used.exists()

    observed = _read_environment(worker_env)
    for name, value in binding_env.items():
        assert observed[name] == value
    assert observed["HAPAX_METHODOLOGY_DISPATCH_TASK"] == "demo-task"
    assert observed["HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID"] == "dispatch-message"
    assert observed["HAPAX_DISPATCH_CLAIM_SWEEP"] == "0"
    assert observed["HAPAX_CLAIM_LEASE_TTL_SECS"] == "0"
    assert observed["HAPAX_AGENT_INTERFACE"] == "claude"
    assert observed["HAPAX_AGENT_NAME"] == "beta"
    assert observed["HAPAX_AGENT_ROLE"] == "beta"
    assert observed["CLAUDE_ROLE"] == "beta"
    assert observed["HAPAX_WORKTREE_ROLE"] == "beta"
    assert observed["HAPAX_SESSION_ID"] == minted_session_id
    assert observed["HAPAX_IDLE_UPDATE_SECONDS"] == "321"
    assert observed["PATH"].split(":", 1)[0] == str(workdir / "scripts")


def test_send_rejects_stale_tmux_shell_as_claude_target(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "tmux.log"
    _write_exe(
        bin_dir / "tmux",
        f"""#!/usr/bin/env bash
echo "$*" >> {log}
case "$1" in
  has-session) exit 0 ;;
  display-message) echo fish; exit 0 ;;
  *) exit 0 ;;
esac
""",
    )
    _write_exe(bin_dir / "hyprctl", "#!/usr/bin/env bash\nprintf '[]\\n'\n")

    result = subprocess.run(
        [
            "bash",
            str(SEND),
            "--session",
            "alpha",
            "--transport",
            "auto",
            "--no-submit",
            "--",
            "msg",
        ],
        capture_output=True,
        text=True,
        env=_env(tmp_path, bin_dir),
        timeout=5,
    )

    assert result.returncode == 11
    assert "pane_current_command=fish" in result.stderr
    assert "load-buffer" not in log.read_text(encoding="utf-8")


def test_send_falls_back_to_visible_foot_title_when_tmux_is_absent(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sent = tmp_path / "sent.txt"
    shortcuts = tmp_path / "shortcuts.log"
    _write_exe(
        bin_dir / "tmux",
        """#!/usr/bin/env bash
case "$1" in
  has-session) exit 1 ;;
  *) exit 1 ;;
esac
""",
    )
    _write_exe(
        bin_dir / "hyprctl",
        f"""#!/usr/bin/env bash
if [ "$1" = "clients" ]; then
  cat <<'JSON'
[{{"class":"foot","title":"✳ alpha","address":"0xabc","at":[0,0],"size":[1200,800]}}]
JSON
  exit 0
fi
if [ "$1" = "dispatch" ]; then
  echo "$*" >> {shortcuts}
  echo ok
  exit 0
fi
if [ "$1" = "activewindow" ]; then
  echo '{{"address":"0xabc"}}'
  exit 0
fi
exit 1
""",
    )
    _write_exe(bin_dir / "wl-copy", f"#!/usr/bin/env bash\ncat > {sent}\n")
    _write_exe(bin_dir / "wl-paste", "#!/usr/bin/env bash\nexit 1\n")

    result = subprocess.run(
        [
            "bash",
            str(SEND),
            "--session",
            "alpha",
            "--transport",
            "auto",
            "--no-submit",
            "--",
            "msg",
        ],
        capture_output=True,
        text=True,
        env=_env(tmp_path, bin_dir),
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert sent.read_text(encoding="utf-8") == "msg"
    assert "sendshortcut" in shortcuts.read_text(encoding="utf-8")


def test_health_reports_visible_title_and_stale_tmux(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_exe(
        bin_dir / "tmux",
        """#!/usr/bin/env bash
case "$1" in
  has-session) exit 0 ;;
  display-message) echo fish; exit 0 ;;
  *) exit 1 ;;
esac
""",
    )
    _write_exe(
        bin_dir / "hyprctl",
        """#!/usr/bin/env bash
cat <<'JSON'
[{"class":"foot","title":"✳ alpha","address":"0xabc"}]
JSON
""",
    )

    result = subprocess.run(
        [str(HEALTH), "alpha"],
        capture_output=True,
        text=True,
        env=_env(tmp_path, bin_dir),
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "alpha: tmux=False foot=True" in result.stdout
    assert "stale_tmux_not_claude:fish" in result.stdout


def _fast_fail_targeting(bin_dir: Path) -> None:
    # tmux has no session, hyprctl no windows -> targeting fails fast (no hang) AFTER the role gate.
    _write_exe(
        bin_dir / "tmux",
        '#!/usr/bin/env bash\ncase "$1" in has-session) exit 1 ;; *) exit 0 ;; esac\n',
    )
    _write_exe(bin_dir / "hyprctl", "#!/usr/bin/env bash\nprintf '[]\\n'\n")


def test_send_accepts_dev_interactive_pool_roles(tmp_path: Path) -> None:
    # The hapax-dev interactive pool (dev, dev2..devN) must pass the role gate — keeping
    # hapax-claude-send in sync with hapax-dev's CLAUDE_POOL so review-team auto-wakes reach dev lanes.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fast_fail_targeting(bin_dir)
    for role in ("dev", "dev2", "dev3", "dev5"):
        result = subprocess.run(
            [
                "bash",
                str(SEND),
                "--session",
                role,
                "--transport",
                "auto",
                "--no-submit",
                "--",
                "msg",
            ],
            capture_output=True,
            text=True,
            env=_env(tmp_path, bin_dir),
            timeout=5,
        )
        assert "invalid role" not in result.stderr, (role, result.returncode, result.stderr)
        # assert the role gate PASSED (took a later path), not merely that stderr lacks the string:
        # the invalid-role path exits 2, so a passing gate must NOT exit 2.
        assert result.returncode != 2, (role, result.returncode, result.stderr)


def test_send_rejects_unknown_role(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fast_fail_targeting(bin_dir)
    result = subprocess.run(
        [
            "bash",
            str(SEND),
            "--session",
            "boguslane",
            "--transport",
            "auto",
            "--no-submit",
            "--",
            "msg",
        ],
        capture_output=True,
        text=True,
        env=_env(tmp_path, bin_dir),
        timeout=5,
    )
    assert result.returncode == 2
    assert "invalid role 'boguslane'" in result.stderr


def test_send_rejects_retired_antigrav_role(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fast_fail_targeting(bin_dir)
    result = subprocess.run(
        [
            "bash",
            str(SEND),
            "--session",
            "antigrav",
            "--transport",
            "auto",
            "--no-submit",
            "--",
            "msg",
        ],
        capture_output=True,
        text=True,
        env=_env(tmp_path, bin_dir),
        timeout=5,
    )
    assert result.returncode == 2
    assert "invalid role 'antigrav'" in result.stderr


def test_send_rejects_retired_antigrav_role_even_when_allowlisted(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fast_fail_targeting(bin_dir)
    for role in (
        "agy",
        "agy-2",
        "antigrav",
        "antigravity",
        "antigravity-2",
        "gemini-cli",
        "gemini-cli-2",
    ):
        env = _env(tmp_path, bin_dir)
        env["HAPAX_CLAUDE_SEND_ROLE_ALLOWLIST"] = f"alpha {role}"
        result = subprocess.run(
            [
                "bash",
                str(SEND),
                "--session",
                role,
                "--transport",
                "auto",
                "--no-submit",
                "--",
                "msg",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )
        assert result.returncode == 2
        assert f"invalid role '{role}'" in result.stderr
        assert "retired/excised send targets cannot be allowlisted" in result.stderr
        assert "agy.review.direct" in result.stderr


def test_send_rejects_dev_lookalikes_not_in_pool(tmp_path: Path) -> None:
    # the dev pattern is digits-only (dev / dev<1-2 digits>) — NOT a `dev*` superset, so
    # look-alikes with trailing junk are rejected (e.g. dev2foo, devel, dev-2).
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fast_fail_targeting(bin_dir)
    for role in ("dev2foo", "devel", "dev-2", "dev99x"):
        result = subprocess.run(
            [
                "bash",
                str(SEND),
                "--session",
                role,
                "--transport",
                "auto",
                "--no-submit",
                "--",
                "msg",
            ],
            capture_output=True,
            text=True,
            env=_env(tmp_path, bin_dir),
            timeout=5,
        )
        assert result.returncode == 2, (role, result.returncode, result.stderr)
        assert f"invalid role '{role}'" in result.stderr, (role, result.stderr)
