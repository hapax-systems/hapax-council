"""Tests for scripts/hapax-post-merge-smoke.

Per cc-task ``post-merge-smoke-runner`` (WSJF 6.5, 2026-05-02).
Verifies the active gates:

- services-restarted (systemd/units/*.service in diff → unit must be active,
  except successful timer-backed oneshots, which should exit)
- broadcast-healthy (audio-routing surface diff → world-surface row OK in 30s)
- m8-midi-clock-peer (midi_clock.py diff → M8 tempo signal present, if M8 connected)

The dependent-component gate (wgpu/visual diff → hapax-imagination active)
was retired with the Tauri/WebKit hapax-logos decommission per cc-task
``hapax-logos-decommission-cleanup``. The hapax-imagination binary's
provenance is now covered by scripts/smoke-test.sh.

Each gate is exercised via a per-test git fixture that constructs the
diff shape that triggers it. systemctl / journalctl are stubbed on
PATH so the tests don't touch real services.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE = REPO_ROOT / "scripts" / "hapax-post-merge-smoke"


def _run(
    sha: str,
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
    stubs: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the smoke script with optional stub binaries on PATH."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(cwd),
        "REPO_ROOT": str(cwd),
        "HAPAX_SMOKE_OFF": "0",
    }
    if stubs:
        bin_dir = cwd / "_stubs"
        bin_dir.mkdir(parents=True, exist_ok=True)
        for name, body in stubs.items():
            stub = bin_dir / name
            stub.write_text(f"#!/usr/bin/env bash\n{body}\n")
            stub.chmod(0o755)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SMOKE), sha],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def _make_repo(tmp_path: Path) -> Path:
    """Init a git repo with two commits so SHA^1 resolves."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GIT_TERMINAL_PROMPT": "0"}
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.email", "t@x"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    (tmp_path / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=tmp_path, check=True, env=env)
    return tmp_path


def _commit_files(repo: Path, files: dict[str, str]) -> str:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(repo), "GIT_TERMINAL_PROMPT": "0"}
    for path, body in files.items():
        full = repo / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(body)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "test"], cwd=repo, check=True, env=env)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return sha


# ── Master kill switch ─────────────────────────────────────────────


class TestKillSwitch:
    def test_smoke_off_short_circuits(self, tmp_path: Path) -> None:
        """`HAPAX_SMOKE_OFF=1` → exit 0 silent."""
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"systemd/units/x.service": "[Unit]\n"})
        result = _run(sha, cwd=repo, extra_env={"HAPAX_SMOKE_OFF": "1"})
        assert result.returncode == 0
        assert result.stderr == ""

    def test_invalid_sha_exits_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run("not-a-sha-deadbeef", cwd=repo)
        assert result.returncode == 0


# ── Gate: services-restarted ───────────────────────────────────────


class TestServicesRestartedGate:
    def test_inactive_unit_records_failure(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"systemd/units/foo.service": "[Unit]\n"})
        # systemctl returns non-zero for inactive
        result = _run(
            sha,
            cwd=repo,
            stubs={"systemctl": "exit 3"},
        )
        assert result.returncode == 0
        assert "services-restarted" in result.stderr
        assert "foo.service not active" in result.stderr

    def test_active_unit_passes_silently(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"systemd/units/foo.service": "[Unit]\n"})
        result = _run(
            sha,
            cwd=repo,
            stubs={"systemctl": "exit 0"},
        )
        assert result.returncode == 0
        assert "services-restarted" not in result.stderr

    def test_template_unit_file_passes_without_active_instance(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/hapax-claude-lane@.service": "[Unit]\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={"systemctl": "exit 3"},
        )

        assert result.returncode == 0
        assert "services-restarted" not in result.stderr
        assert "hapax-claude-lane@.service" not in result.stderr

    def test_successful_oneshot_inactive_unit_passes_silently(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/foo.service": "[Service]\nType=oneshot\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": """
if [ "$2" = "is-active" ]; then exit 3; fi
if [ "$2" = "show" ]; then
  case "$5" in
    Type) echo oneshot ;;
    Result) echo success ;;
    ExecMainStatus) echo 0 ;;
  esac
  exit 0
fi
exit 1
""",
            },
        )
        assert result.returncode == 0
        assert "services-restarted" not in result.stderr

    def test_failed_oneshot_inactive_unit_records_failure(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/foo.service": "[Service]\nType=oneshot\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": """
if [ "$2" = "is-active" ]; then exit 3; fi
if [ "$2" = "show" ]; then
  case "$5" in
    Type) echo oneshot ;;
    Result) echo failed ;;
    ExecMainStatus) echo 1 ;;
  esac
  exit 0
fi
exit 1
""",
            },
        )
        assert result.returncode == 0
        assert "services-restarted" in result.stderr
        assert "foo.service not active" in result.stderr

    def test_disabled_install_only_service_passes_silently(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/foo.service": "[Service]\nType=notify\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": """
if [ "$2" = "is-active" ]; then exit 3; fi
if [ "$2" = "show" ]; then
  case "$5" in
    Type) echo notify ;;
    Result) echo success ;;
    ExecMainStatus) echo 0 ;;
    UnitFileState) echo disabled ;;
  esac
  exit 0
fi
exit 1
""",
            },
        )
        assert result.returncode == 0
        assert "services-restarted" not in result.stderr

    def test_disabled_failed_service_records_failure(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"systemd/units/foo.service": "[Service]\nType=notify\n"},
        )
        result = _run(
            sha,
            cwd=repo,
            stubs={
                "systemctl": """
if [ "$2" = "is-active" ]; then exit 3; fi
if [ "$2" = "show" ]; then
  case "$5" in
    Type) echo notify ;;
    Result) echo failed ;;
    ExecMainStatus) echo 1 ;;
    UnitFileState) echo disabled ;;
  esac
  exit 0
fi
exit 1
""",
            },
        )
        assert result.returncode == 0
        assert "services-restarted" in result.stderr
        assert "foo.service not active" in result.stderr

    def test_no_unit_diff_skips_gate(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"agents/foo.py": "x = 1\n"})
        result = _run(sha, cwd=repo)
        assert result.returncode == 0
        assert "services-restarted" not in result.stderr


# ── Gate: broadcast-healthy ────────────────────────────────────────


class TestBroadcastHealthyGate:
    def test_dryrun_announces_gate(self, tmp_path: Path) -> None:
        """Dry-run path: gate prints which gate would fire, no real check."""
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"agents/studio_compositor/foo.py": "x = 1\n"},
        )
        result = _run(sha, cwd=repo, extra_env={"HAPAX_SMOKE_DRYRUN": "1"})
        assert result.returncode == 0
        assert "broadcast-healthy" in result.stdout

    def test_no_audio_diff_skips_gate(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(repo, {"agents/foo.py": "x = 1\n"})
        result = _run(sha, cwd=repo, extra_env={"HAPAX_SMOKE_DRYRUN": "1"})
        assert result.returncode == 0
        assert "broadcast-healthy" not in result.stdout

    def test_voice_router_diff_triggers_gate(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"shared/voice_output_router.py": "VoiceRole = 'x'\n"},
        )
        result = _run(sha, cwd=repo, extra_env={"HAPAX_SMOKE_DRYRUN": "1"})
        assert "broadcast-healthy" in result.stdout

    def test_broadcast_health_module_diff_triggers_gate(self, tmp_path: Path) -> None:
        """broadcast_audio_health.py is the producer the gate watches; its
        own diffs must fire the gate (regression risk to the producer)."""
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"shared/broadcast_audio_health.py": "DEFAULT = 'x'\n"},
        )
        result = _run(sha, cwd=repo, extra_env={"HAPAX_SMOKE_DRYRUN": "1"})
        assert "broadcast-healthy" in result.stdout


# ── Gate: m8-midi-clock-peer ───────────────────────────────────────


class TestM8MidiClockPeerGate:
    def test_midi_clock_diff_triggers_gate(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"agents/hapax_daimonion/backends/midi_clock.py": "x=1\n"},
        )
        result = _run(sha, cwd=repo, extra_env={"HAPAX_SMOKE_DRYRUN": "1"})
        assert "m8-midi-clock-peer" in result.stdout

    def test_skips_when_m8_absent(self, tmp_path: Path) -> None:
        """`amidi` present but no M8 device listed → skip silent."""
        repo = _make_repo(tmp_path)
        sha = _commit_files(
            repo,
            {"agents/hapax_daimonion/backends/midi_clock.py": "x=1\n"},
        )
        result = _run(sha, cwd=repo, stubs={"amidi": "exit 0"})
        assert "m8-midi-clock-peer" not in result.stderr


# ── Script integrity ───────────────────────────────────────────────


class TestScriptIntegrity:
    def test_script_is_executable(self) -> None:
        assert os.access(SMOKE, os.X_OK)

    def test_script_uses_strict_bash(self) -> None:
        body = SMOKE.read_text(encoding="utf-8")
        assert body.startswith("#!/usr/bin/env bash")
        assert "set -uo pipefail" in body or "set -euo pipefail" in body

    def test_script_documents_kill_switches(self) -> None:
        body = SMOKE.read_text(encoding="utf-8")
        assert "HAPAX_SMOKE_OFF" in body
        assert "HAPAX_SMOKE_DRYRUN" in body

    def test_script_always_exits_zero(self) -> None:
        """Smoke is informational; never block the deploy chain."""
        body = SMOKE.read_text(encoding="utf-8")
        # Body must end with `exit 0` (last non-blank, non-comment line).
        for line in reversed(body.splitlines()):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            assert stripped == "exit 0", f"last executable line must be `exit 0`: {line!r}"
            break

    def test_script_uses_ntfy_on_failure(self) -> None:
        body = SMOKE.read_text(encoding="utf-8")
        assert "NTFY_TOPIC" in body
        assert "ntfy.sh" in body
