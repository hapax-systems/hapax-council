"""Path-coverage tests for ``scripts/hapax-post-merge-deploy``."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-post-merge-deploy"


def _coverage(paths: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), "--report-coverage-stdin"],
        input="\n".join(paths) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _repo_with_merge_commit(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    _git(repo, "switch", "-c", "trace-branch")
    script_path = repo / "scripts" / "hapax-demo"
    script_path.parent.mkdir()
    script_path.write_text("#!/bin/sh\necho demo\n", encoding="utf-8")
    _git(repo, "add", "scripts/hapax-demo")
    _git(repo, "commit", "-m", "add deployable script")
    _git(repo, "switch", "main")
    main_script_path = repo / "scripts" / "hapax-main-only"
    main_script_path.parent.mkdir(exist_ok=True)
    main_script_path.write_text("#!/bin/sh\necho main\n", encoding="utf-8")
    _git(repo, "add", "scripts/hapax-main-only")
    _git(repo, "commit", "-m", "add main-only deployable script")
    _git(repo, "merge", "--no-ff", "trace-branch", "-m", "merge trace branch")
    return repo, _git(repo, "rev-parse", "HEAD")


def _repo_with_linear_commit(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    for relative, body in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add deployable files")
    return repo, _git(repo, "rev-parse", "HEAD")


def _fake_systemctl(tmp_path: Path) -> tuple[Path, Path]:
    calls = tmp_path / "systemctl-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "systemctl"
    fake.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\nexit 0\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return bin_dir, calls


def test_dry_run_writes_bounded_post_merge_trace(tmp_path: Path) -> None:
    repo, sha = _repo_with_merge_commit(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        "HAPAX_POST_MERGE_TRACE_MAX_RECORDS": "2",
    }

    for _ in range(3):
        result = subprocess.run(
            [str(SCRIPT), "--dry-run", sha],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        assert "dry-run: post-merge deploy trace written" in result.stdout

    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]

    assert len(records) == 2
    assert records[-1]["event"] == "post_merge_deploy"
    assert records[-1]["sha"] == sha
    assert records[-1]["mode"] == "dry_run"
    assert records[-1]["status"] == "dry_run"
    assert records[-1]["changed_files"] == ["scripts/hapax-demo"]
    assert records[-1]["deploy_groups"]["hapax_scripts"] == ["scripts/hapax-demo"]
    assert records[-1]["manual_deploy_needed"] is True
    assert records[-1]["manual_deploy_executed"] is False


def test_systemd_coverage_includes_dropins_presets_and_source_overrides() -> None:
    result = _coverage(
        [
            "systemd/units/hapax-datacite-mirror.service",
            "systemd/units/hapax-datacite-mirror.timer",
            "systemd/units/hapax-build-reload.path",
            "systemd/units/hapax-visual-stack.target",
            "systemd/hapax-rebuild-logos.service",
            "systemd/hapax-rebuild-logos.timer",
            "systemd/hapax-build-reload.path",
            "systemd/units/pipewire.service.d/cpu-affinity.conf",
            "systemd/user-preset.d/hapax.preset",
            "systemd/scripts/install-units.sh",
            "systemd/overrides/audio-stability/README.md",
            "systemd/overrides/audio-stability/pipewire-cpu-affinity.conf",
            "systemd/watchdogs/scout-watchdog",
            "systemd/README.md",
            "systemd/expected-timers.yaml",
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "ok: all systemd/** paths" in result.stdout


def test_systemd_coverage_still_flags_unknown_systemd_paths() -> None:
    result = _coverage(["systemd/uncovered/example.conf"])

    assert result.returncode == 1
    assert "systemd/uncovered/example.conf" in result.stderr


def test_system_scoped_units_skip_user_deploy_and_clean_stale_copy(tmp_path: Path) -> None:
    unit_path = "systemd/units/hapax-l12-critical-usb-guard.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "# Hapax-Install-Scope: system\n"
                "Description=System scoped guard\n"
                "\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=/usr/local/bin/hapax-l12-critical-usb-guard\n"
            )
        },
    )
    home = tmp_path / "home"
    stale_user_unit = home / ".config" / "systemd" / "user" / "hapax-l12-critical-usb-guard.service"
    stale_user_unit.parent.mkdir(parents=True)
    stale_user_unit.write_text("stale\n", encoding="utf-8")
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "system-scoped systemd units changed" in result.stdout
    assert not stale_user_unit.exists()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user disable --now hapax-l12-critical-usb-guard.service" in calls
    assert "--user daemon-reload" in calls
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["systemd_system_units"] == [unit_path]
    assert record["deploy_groups"]["systemd_units"] == []


def test_user_scoped_units_still_deploy_to_user_dir(tmp_path: Path) -> None:
    unit_path = "systemd/units/hapax-user-demo.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "Description=User scoped demo\n"
                "\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=%h/.local/bin/hapax-demo\n"
            )
        },
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    installed = home / ".config" / "systemd" / "user" / "hapax-user-demo.service"
    assert installed.read_text(encoding="utf-8") == (
        "[Unit]\n"
        "Description=User scoped demo\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "ExecStart=%h/.local/bin/hapax-demo\n"
    )
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["systemd_units"] == [unit_path]
    assert record["deploy_groups"]["systemd_system_units"] == []


def test_hapax_runtime_config_deploys_to_user_config_and_restarts_reconciler(
    tmp_path: Path,
) -> None:
    config_path = "config/hapax/audio-link-map.conf"
    body = "source:output_FL|target:input_FL\n"
    repo, sha = _repo_with_linear_commit(tmp_path, {config_path: body})
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    installed = home / ".config" / "hapax" / "audio-link-map.conf"
    assert installed.read_text(encoding="utf-8") == body
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user restart hapax-audio-reconciler.service" in calls
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["hapax_runtime_config"] == [config_path]


def test_deploy_rejects_commit_ranges_before_touching_targets() -> None:
    result = subprocess.run(
        [str(SCRIPT), "HEAD..HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "expected a single commit SHA/ref" in result.stderr


def test_coverage_rejects_commit_ranges_before_touching_targets() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--report-coverage", "HEAD..HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "expected a single commit SHA/ref" in result.stderr


def test_real_deploy_invokes_smoke_runner_with_sha(tmp_path: Path) -> None:
    """The smoke runner is wired into the deploy chain (cc-task
    post-merge-smoke-deploy-wiring). After deploy actions complete,
    ``$REPO/scripts/hapax-post-merge-smoke <sha>`` is invoked. We stub
    the smoke script with a recorder so the test can assert it ran
    with the right SHA, without depending on the live smoke logic."""
    repo, sha = _repo_with_merge_commit(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    smoke_recorder = tmp_path / "smoke-call-record.txt"

    smoke_stub = repo / "scripts" / "hapax-post-merge-smoke"
    smoke_stub.write_text(
        f'#!/bin/sh\nprintf "smoke-invoked sha=%s\\n" "$1" > "{smoke_recorder}"\nexit 0\n',
        encoding="utf-8",
    )
    smoke_stub.chmod(0o755)

    env = {
        **os.environ,
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert smoke_recorder.exists(), "smoke runner was not invoked"
    assert smoke_recorder.read_text(encoding="utf-8").strip() == f"smoke-invoked sha={sha}"


def test_real_deploy_smoke_failure_does_not_block_trace(tmp_path: Path) -> None:
    """If the smoke runner exits non-zero (defying its own contract),
    the deploy script must still write its post-merge trace and exit
    cleanly. The `|| true` guard around the smoke invocation is the
    contract this test pins."""
    repo, sha = _repo_with_merge_commit(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"

    smoke_stub = repo / "scripts" / "hapax-post-merge-smoke"
    smoke_stub.write_text("#!/bin/sh\necho smoke-broken >&2\nexit 1\n", encoding="utf-8")
    smoke_stub.chmod(0o755)

    env = {
        **os.environ,
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert trace_path.exists(), "post-merge trace was not written"
    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["status"] == "completed"


def test_real_deploy_with_no_smoke_script_is_a_no_op(tmp_path: Path) -> None:
    """If ``scripts/hapax-post-merge-smoke`` is absent (e.g. on a repo
    that hasn't yet adopted the smoke runner), the deploy script
    silently skips smoke and completes normally — backward-compatible
    with the pre-#2148 deploy chain."""
    repo, sha = _repo_with_merge_commit(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"

    smoke_stub = repo / "scripts" / "hapax-post-merge-smoke"
    assert not smoke_stub.exists(), "fixture should not include smoke script"

    env = {
        **os.environ,
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert trace_path.exists()
