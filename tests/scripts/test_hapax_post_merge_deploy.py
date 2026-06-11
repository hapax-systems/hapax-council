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


def _repo_with_quake_asset_commit(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    installer = repo / "scripts" / "install-darkplaces-screwm-assets.sh"
    installer.parent.mkdir(parents=True)
    installer.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"${DARKPLACES_GAME_ROOT:-$HOME/.darkplaces}\" "
        '>> "$HAPAX_INSTALL_CALLS"\n',
        encoding="utf-8",
    )
    _git(repo, "add", "scripts/install-darkplaces-screwm-assets.sh")
    _git(repo, "commit", "-m", "base quake installer")
    asset = repo / "assets" / "quake" / "maps" / "screwm.bsp"
    asset.parent.mkdir(parents=True)
    asset.write_text("compiled bsp bytes\n", encoding="utf-8")
    _git(repo, "add", "assets/quake/maps/screwm.bsp")
    _git(repo, "commit", "-m", "update screwm map asset")
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


def _fake_audio_safe_restart(
    bin_dir: Path, tmp_path: Path, *, exit_code: int = 0
) -> tuple[Path, Path]:
    calls = tmp_path / "audio-safe-restart-calls.txt"
    fake = bin_dir / "hapax-audio-safe-restart"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_AUDIO_SAFE_RESTART_CALLS"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake, calls


def _fake_systemctl_with_compositor_state(
    tmp_path: Path, *, compositor_active: bool
) -> tuple[Path, Path]:
    """A fake ``systemctl`` whose ``is-active --quiet studio-compositor.service``
    reports the configured liveness; every other call exits 0.

    This lets the deploy reach the audio-safe restart for a changed audio unit
    (the changed unit's own ``is-active`` probe returns 0 → active → restart)
    while the test independently chooses whether a *live broadcast* is on the
    line — i.e. whether ``studio-compositor.service`` is active.
    """
    calls = tmp_path / "systemctl-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "systemctl"
    # systemctl is-active exits 0 when active, 3 when inactive/dead.
    compositor_rc = 0 if compositor_active else 3
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'case "$*" in\n'
        f"    *is-active*studio-compositor.service*) exit {compositor_rc} ;;\n"
        "esac\n"
        "exit 0\n",
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
    assert records[-1]["avsdlc"]["gate_point"] == "S9 post-merge production witness"
    assert records[-1]["avsdlc"]["runtime_media_witness_required"] is True
    assert records[-1]["avsdlc"]["runtime_media_witness_groups"] == ["hapax_scripts"]


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


def test_systemd_coverage_includes_slice_units() -> None:
    # hapax-sdlc.slice (the SDLC resource-shielding slice) must be deploy-covered;
    # a .slice falling outside the case-globs is the absence-class deploy bug.
    result = _coverage(["systemd/units/hapax-sdlc.slice"])

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


def test_quake_asset_changes_install_and_restart_active_darkplaces(tmp_path: Path) -> None:
    repo, sha = _repo_with_quake_asset_commit(tmp_path)
    home = tmp_path / "home"
    game_root = tmp_path / "darkplaces"
    install_calls = tmp_path / "install-calls.txt"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "DARKPLACES_GAME_ROOT": str(game_root),
        "HAPAX_INSTALL_CALLS": str(install_calls),
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
    assert "quake assets changed (1)" in result.stdout
    assert "installing Screwm Quake assets" in result.stdout
    assert "restarting hapax-darkplaces-v4l2.service" in result.stdout
    assert install_calls.read_text(encoding="utf-8").splitlines() == [str(game_root)]
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user is-active --quiet hapax-darkplaces-v4l2.service" in calls
    assert "--user restart hapax-darkplaces-v4l2.service" in calls
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["quake_assets"] == ["assets/quake/maps/screwm.bsp"]
    assert "quake_assets" in record["avsdlc"]["runtime_media_witness_groups"]


def test_obs_audio_bind_unit_deploy_removes_stale_audio_l12_dropin(tmp_path: Path) -> None:
    unit_path = "systemd/units/hapax-obs-audio-bind.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "Description=OBS audio bind\n"
                "\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=%h/.cache/hapax/source-activation/worktree/scripts/hapax-obs-audio-bind\n"
            )
        },
    )
    home = tmp_path / "home"
    stale_dropin = (
        home
        / ".config"
        / "systemd"
        / "user"
        / "hapax-obs-audio-bind.service.d"
        / "95-codex-audio-l12-worktree.conf"
    )
    stale_dropin.parent.mkdir(parents=True, exist_ok=True)
    stale_dropin.write_text(
        "[Service]\nWorkingDirectory=/home/hapax/projects/hapax-council--codex-audio-l12\n",
        encoding="utf-8",
    )
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
    assert not stale_dropin.exists()
    assert "removing stale local drop-in" in result.stdout
    installed = home / ".config" / "systemd" / "user" / "hapax-obs-audio-bind.service"
    assert installed.exists()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user daemon-reload" in calls


def test_screwm_audio_reactivity_unit_deploy_removes_stale_target_dropin(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/hapax-screwm-audio-reactivity.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "Description=Screwm audio reactivity\n"
                "\n"
                "[Service]\n"
                "Environment=HAPAX_SCREWM_AUDIO_TARGET=hapax-broadcast-normalized\n"
                "ExecStart=%h/.cache/hapax/source-activation/worktree/scripts/"
                "screwm-audio-reactivity-source.py\n"
            )
        },
    )
    home = tmp_path / "home"
    stale_dropin = (
        home
        / ".config"
        / "systemd"
        / "user"
        / "hapax-screwm-audio-reactivity.service.d"
        / "override.conf"
    )
    stale_dropin.parent.mkdir(parents=True, exist_ok=True)
    stale_dropin.write_text(
        "[Service]\nEnvironment=HAPAX_SCREWM_AUDIO_TARGET=hapax-broadcast-normalized-capture\n",
        encoding="utf-8",
    )
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
    assert not stale_dropin.exists()
    assert not stale_dropin.parent.exists()
    assert "removing stale local drop-in" in result.stdout
    installed = home / ".config" / "systemd" / "user" / "hapax-screwm-audio-reactivity.service"
    assert installed.exists()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user daemon-reload" in calls


def test_audio_touching_units_restart_through_audio_safe_wrapper(tmp_path: Path) -> None:
    unit_path = "systemd/units/hapax-music-player.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "Description=Music player\n"
                "\n"
                "[Service]\n"
                "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
                "-m agents.local_music_player\n"
            )
        },
    )
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    audio_safe_bin, audio_safe_calls = _fake_audio_safe_restart(bin_dir, tmp_path, exit_code=1)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_AUDIO_SAFE_RESTART_BIN": str(audio_safe_bin),
        "HAPAX_AUDIO_SAFE_RESTART_CALLS": str(audio_safe_calls),
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
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user is-active --quiet hapax-music-player.service" in calls
    assert "--user restart hapax-music-player.service" not in calls
    assert audio_safe_calls.read_text(encoding="utf-8").splitlines() == [
        "hapax-music-player.service"
    ]
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["audio_safe_restart_units"] == ["hapax-music-player.service"]
    assert record["deploy_groups"]["systemd_units"] == [unit_path]


def test_audio_safe_wrapper_prefers_repo_script_over_stale_path(
    tmp_path: Path,
) -> None:
    unit_path = "systemd/units/hapax-music-player.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            unit_path: (
                "[Unit]\n"
                "Description=Music player\n"
                "\n"
                "[Service]\n"
                "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
                "-m agents.local_music_player\n"
            )
        },
    )
    repo_safe = repo / "scripts" / "hapax-audio-safe-restart"
    repo_safe.parent.mkdir(parents=True, exist_ok=True)
    repo_safe.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "$HAPAX_REPO_AUDIO_SAFE_CALLS"\nexit 0\n',
        encoding="utf-8",
    )
    repo_safe.chmod(0o755)
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl(tmp_path)
    stale_safe, stale_calls = _fake_audio_safe_restart(bin_dir, tmp_path, exit_code=99)
    stale_safe.chmod(0o755)
    repo_safe_calls = tmp_path / "repo-audio-safe-calls.txt"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_AUDIO_SAFE_RESTART_CALLS": str(stale_calls),
        "HAPAX_REPO_AUDIO_SAFE_CALLS": str(repo_safe_calls),
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
    assert repo_safe_calls.read_text(encoding="utf-8").splitlines() == [
        "hapax-music-player.service"
    ]
    assert not stale_calls.exists()


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


def test_hapax_script_deploy_restarts_active_units_that_reference_local_bin(
    tmp_path: Path,
) -> None:
    script_path = "scripts/hapax-audio-reconciler"
    unit_path = "systemd/units/hapax-audio-reconciler.service"
    repo, sha = _repo_with_linear_commit(
        tmp_path,
        {
            script_path: "#!/usr/bin/env bash\necho reconciler\n",
            unit_path: (
                "[Unit]\n"
                "Description=Reconciler\n"
                "\n"
                "[Service]\n"
                "ExecStart=%h/.local/bin/hapax-audio-reconciler\n"
            ),
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
    installed = home / ".local" / "bin" / "hapax-audio-reconciler"
    # Copy-from-SHA semantics (deploy-scripts-worktree-root-20260611): the
    # installed script is the release content, not a live symlink into a tree.
    assert installed.is_file() and not installed.is_symlink()
    assert installed.read_text() == (repo / script_path).read_text()
    assert installed.stat().st_mode & 0o111, "installed script must be executable"
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user restart hapax-audio-reconciler.service" in calls
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deploy_groups"]["hapax_scripts"] == [script_path]


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

    # HOME isolated so the real deploy's scripts/hapax-demo symlink lands under
    # tmp, not the operator's ~/.local/bin (fix-deploy-symlink-skew leak).
    home = tmp_path / "home"
    env = {
        **os.environ,
        "HOME": str(home),
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

    # HOME isolated so the real deploy's scripts/hapax-demo symlink lands under
    # tmp, not the operator's ~/.local/bin (fix-deploy-symlink-skew leak).
    home = tmp_path / "home"
    env = {
        **os.environ,
        "HOME": str(home),
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
    # HOME MUST be isolated: the deploy computes LOCAL_BIN=$HOME/.local/bin and
    # symlinks the fixture's scripts/hapax-demo into it. Without this override a
    # *real* deploy leaks ~/.local/bin/hapax-demo into the operator's PATH that
    # dangles the moment pytest cleans tmp_path (the fix-deploy-symlink-skew
    # leak — every other test here already isolates HOME for the same reason).
    home = tmp_path / "home"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"

    smoke_stub = repo / "scripts" / "hapax-post-merge-smoke"
    assert not smoke_stub.exists(), "fixture should not include smoke script"

    env = {
        **os.environ,
        "HOME": str(home),
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


def _music_player_unit_body() -> str:
    return (
        "[Unit]\n"
        "Description=Music player\n"
        "\n"
        "[Service]\n"
        "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
        "-m agents.local_music_player\n"
    )


def test_audio_safe_failure_defers_deploy_when_no_live_broadcast(tmp_path: Path) -> None:
    """A hard audio-safe-restart failure (rc>=2 — e.g. audio is intentionally
    down so its broadcast-clean verify can't pass) must NOT abort the whole
    deploy when there is no live broadcast on the line. The deploy DEFERS the
    audio restart (retried next cycle) and still completes (exit 0) so unrelated
    units — e.g. #3850's SDLC ``cpu.idle`` slice — still install.

    Regression for the reform deploy-decouple: previously the bare
    ``return "$safe_rc"`` propagated rc=2 under ``set -e`` and aborted every
    deploy for as long as audio stayed down.
    """
    unit_path = "systemd/units/hapax-music-player.service"
    repo, sha = _repo_with_linear_commit(tmp_path, {unit_path: _music_player_unit_body()})
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl_with_compositor_state(
        tmp_path, compositor_active=False
    )
    audio_safe_bin, audio_safe_calls = _fake_audio_safe_restart(bin_dir, tmp_path, exit_code=2)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_AUDIO_SAFE_RESTART_BIN": str(audio_safe_bin),
        "HAPAX_AUDIO_SAFE_RESTART_CALLS": str(audio_safe_calls),
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
    # the audio-safe restart was actually attempted (and failed, rc=2)
    assert audio_safe_calls.read_text(encoding="utf-8").splitlines() == [
        "hapax-music-player.service"
    ]
    # it probed for a live broadcast and, finding none, deferred rather than aborted
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user is-active --quiet studio-compositor.service" in calls
    assert "DEFERRING" in result.stderr
    # the deploy still ran to completion despite the deferred audio restart
    record = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["status"] == "completed"


def test_audio_safe_failure_aborts_deploy_during_live_broadcast(tmp_path: Path) -> None:
    """If a live broadcast IS on the line (``studio-compositor.service`` active),
    a hard audio-safe-restart failure must still ABORT the deploy (exit 2):
    breaking the audio chain mid-stream is more critical than deferring a unit
    install. This pins the broadcast-protecting half of the decouple.
    """
    unit_path = "systemd/units/hapax-music-player.service"
    repo, sha = _repo_with_linear_commit(tmp_path, {unit_path: _music_player_unit_body()})
    home = tmp_path / "home"
    bin_dir, systemctl_calls = _fake_systemctl_with_compositor_state(
        tmp_path, compositor_active=True
    )
    audio_safe_bin, audio_safe_calls = _fake_audio_safe_restart(bin_dir, tmp_path, exit_code=2)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "REPO": str(repo),
        "HAPAX_SYSTEMCTL_CALLS": str(systemctl_calls),
        "HAPAX_AUDIO_SAFE_RESTART_BIN": str(audio_safe_bin),
        "HAPAX_AUDIO_SAFE_RESTART_CALLS": str(audio_safe_calls),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2, (result.returncode, result.stderr)
    assert audio_safe_calls.read_text(encoding="utf-8").splitlines() == [
        "hapax-music-player.service"
    ]
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "--user is-active --quiet studio-compositor.service" in calls
    assert "LIVE" in result.stderr or "live broadcast" in result.stderr.lower()


# --- deploy-symlink-skew regressions (fix-deploy-symlink-skew-20260602) ---


def test_real_deploy_installs_symlinks_under_isolated_home(tmp_path: Path) -> None:
    """A real deploy MUST install ``scripts/hapax-*`` symlinks under the
    overridden ``$HOME/.local/bin`` — never the operator's real one. Pins the
    isolation contract whose violation leaked a dangling ``~/.local/bin/hapax-demo``
    pointing into a cleaned pytest tmpdir (the skew P0's recurring symptom).
    """
    repo, sha = _repo_with_merge_commit(tmp_path)
    home = tmp_path / "home"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        "HAPAX_DRIFT_NTFY": "0",
    }

    result = subprocess.run(
        [str(SCRIPT), sha], text=True, capture_output=True, check=False, env=env
    )

    assert result.returncode == 0, result.stderr
    leaked = home / ".local" / "bin" / "hapax-demo"
    assert leaked.is_file(), "demo script should install under the isolated home"
    # Copy-from-SHA semantics: a regular file with the release's content, not a
    # symlink into a mutable tree (deploy-scripts-worktree-root-20260611).
    assert not leaked.is_symlink()
    assert leaked.read_text() == (repo / "scripts" / "hapax-demo").read_text()
    # The deploy-end self-check must stay quiet: installed copies are not
    # symlinks, so the drift auditor (symlink-only) has nothing to flag.
    assert "drift" not in result.stderr.lower(), result.stderr


def test_since_invocation_form_is_accepted(tmp_path: Path) -> None:
    """The post-merge-deploy ``.service`` edge-trigger invokes the script as
    ``hapax-post-merge-deploy --since <since> <sha>`` to realize a multi-merge
    backlog in one cumulative deploy. Pin that the script's argument parser
    accepts that exact form and exits 0.

    Regression for fix-deploy-symlink-skew: a ``~/.local/bin`` symlink pointing
    at a STALE worktree (one predating ``--since`` support) made every
    ``.service`` deploy exit 2/INVALIDARGUMENT, silently stranding 9 merged
    commits. This fails loudly if the script ever loses ``--since``.
    """
    repo, sha = _repo_with_merge_commit(tmp_path)
    since = _git(repo, "rev-parse", f"{sha}^1")
    home = tmp_path / "home"
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "HOME": str(home),
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
    }

    result = subprocess.run(
        [str(SCRIPT), "--since", since, sha],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, (result.returncode, result.stderr)


def test_service_unit_since_contract_matches_script() -> None:
    """Static parity guard: if the ``.service`` ExecStart passes ``--since`` the
    script MUST have a ``--since`` handler. This is the precise contract whose
    violation — the wrapper passing a flag the (stale, symlinked) script didn't
    support — stranded the merged-but-undeployed commits.
    """
    unit = (REPO_ROOT / "systemd" / "units" / "hapax-post-merge-deploy.service").read_text(
        encoding="utf-8"
    )
    script_src = SCRIPT.read_text(encoding="utf-8")
    if "--since" in unit:
        assert '"--since"' in script_src, (
            "hapax-post-merge-deploy.service passes --since but the script has no "
            "--since handler — the deploy-symlink-skew arg-contract break."
        )


def _drift_env(tmp_path: Path, bin_dir: Path, **overrides: str) -> dict[str, str]:
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "REPO": str(REPO_ROOT),
        "HAPAX_LOCAL_BIN": str(bin_dir),
        "HAPAX_DRIFT_NTFY": "0",
        "HAPAX_DRIFT_STATE_DIR": str(tmp_path / "state"),
    }
    env.update(overrides)
    return env


def _link(bin_dir: Path, name: str, target: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / name).symlink_to(target)


def _check_drift(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), "--check-symlink-drift"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_check_symlink_drift_passes_when_canonical(tmp_path: Path) -> None:
    """No drift when every ``hapax-*`` symlink resolves under a canonical root."""
    root = tmp_path / "worktree"
    (root / "scripts").mkdir(parents=True)
    demo = root / "scripts" / "hapax-demo"
    demo.write_text("#!/bin/sh\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    _link(bin_dir, "hapax-demo", demo)

    result = _check_drift(_drift_env(tmp_path, bin_dir, HAPAX_DEPLOY_SYMLINK_ROOTS=str(root)))

    assert result.returncode == 0, result.stderr


def test_check_symlink_drift_flags_dangling(tmp_path: Path) -> None:
    """A ``hapax-*`` symlink whose target was removed (deleted worktree / cleaned
    test tmpdir — the skew P0's ``hapax-demo``) is reported as drift, exit 1.
    """
    bin_dir = tmp_path / "bin"
    _link(bin_dir, "hapax-demo", tmp_path / "gone" / "scripts" / "hapax-demo")

    result = _check_drift(_drift_env(tmp_path, bin_dir))

    assert result.returncode == 1, result.stdout
    assert "dangling" in result.stderr
    assert "hapax-demo" in result.stderr


def test_check_symlink_drift_flags_offtree(tmp_path: Path) -> None:
    """A ``hapax-*`` symlink resolving to a ``scripts/`` dir OUTSIDE the canonical
    roots (a stale lane worktree, or a live pytest tmpdir — the exact recurring
    leak) is drift even though the target currently exists.
    """
    foreign = tmp_path / "foreign" / "scripts"
    foreign.mkdir(parents=True)
    demo = foreign / "hapax-demo"
    demo.write_text("#!/bin/sh\n", encoding="utf-8")
    canonical = tmp_path / "worktree"
    (canonical / "scripts").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    _link(bin_dir, "hapax-demo", demo)

    result = _check_drift(_drift_env(tmp_path, bin_dir, HAPAX_DEPLOY_SYMLINK_ROOTS=str(canonical)))

    assert result.returncode == 1, result.stdout
    assert "off-tree" in result.stderr


def test_check_symlink_drift_ignores_non_script_install_symlinks(tmp_path: Path) -> None:
    """``hapax-hooks-doctor -> ~/.local/lib/hapax/hooks/hooks-doctor.sh`` is a
    manifest-installed hook, not a deploy-tree symlink — its target is not under
    ``*/scripts/*`` so it must NOT be flagged, or the assertion false-positives
    on a healthy system.
    """
    lib = tmp_path / "lib" / "hapax" / "hooks"
    lib.mkdir(parents=True)
    doctor = lib / "hooks-doctor.sh"
    doctor.write_text("#!/bin/sh\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    _link(bin_dir, "hapax-hooks-doctor", doctor)

    result = _check_drift(
        _drift_env(tmp_path, bin_dir, HAPAX_DEPLOY_SYMLINK_ROOTS=str(tmp_path / "wt"))
    )

    assert result.returncode == 0, result.stderr


# --- 2026-06-11 P0 regression: archive resurrection + conf parse-lint ---


def test_archive_confs_are_not_classified_as_deployable(tmp_path):
    """Bash case-globs match across slashes: config/pipewire/archive/** must be
    explicitly excluded or it deploys (the 09:34 P0: 25 archived confs
    resurrected, one syntax-invalid, audio stack start-limit dead)."""

    script = SCRIPT.read_text()
    assert "config/pipewire/archive/*" in script, "archive exclusion branch missing"
    # the exclusion must appear BEFORE the matching deploy branch
    excl = script.index("config/pipewire/archive/*")
    match = script.index("config/pipewire/*.conf)")
    assert excl < match, "exclusion must precede the deploy classification"


def test_pw_deploy_parse_lints_confs(tmp_path):
    script = SCRIPT.read_text()
    assert "spa-json-dump" in script, "conf parse-lint missing from PW deploy path"
    assert "REFUSED (spa-json parse error" in script
