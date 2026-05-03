"""Tests for cc-task audio-audit-B-startup-stage-check.

Pin the YAML schema + the dry-run path. Hardware-mode (--execute) is
operator-gated; not exercised at CI time.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audio-stage-check.sh"
CONFIG = REPO_ROOT / "config" / "audio-stage-expected-levels.yaml"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-audio-stage-check.service"


class TestConfigYAMLSchema:
    def test_config_exists(self) -> None:
        assert CONFIG.is_file()

    def test_config_parses(self) -> None:
        with CONFIG.open() as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "stages" in data
        assert isinstance(data["stages"], list)

    def test_config_has_at_least_4_stages(self) -> None:
        with CONFIG.open() as f:
            data = yaml.safe_load(f)
        assert len(data["stages"]) >= 4, (
            "cc-task B specifies 4 monitor stages: music-loudnorm, music-duck, "
            "usb-line-driver, obs-broadcast-remap. Configure all 4."
        )

    def test_each_stage_has_required_fields(self) -> None:
        required = {"monitor", "expected_dbfs", "tolerance_db", "description"}
        with CONFIG.open() as f:
            data = yaml.safe_load(f)
        for stage in data["stages"]:
            missing = required - set(stage.keys())
            assert not missing, (
                f"stage {stage.get('monitor', '<unnamed>')} missing required fields: {missing}"
            )

    def test_expected_dbfs_is_negative_or_zero(self) -> None:
        """RMS dBFS is always ≤ 0; positive expected_dbfs is a config bug."""
        with CONFIG.open() as f:
            data = yaml.safe_load(f)
        for stage in data["stages"]:
            assert stage["expected_dbfs"] <= 0, (
                f"stage {stage['monitor']} expected_dbfs={stage['expected_dbfs']} "
                f"> 0; RMS dBFS is always ≤ 0"
            )

    def test_tolerance_is_positive(self) -> None:
        with CONFIG.open() as f:
            data = yaml.safe_load(f)
        for stage in data["stages"]:
            assert stage["tolerance_db"] > 0

    def test_4_canonical_stages_present(self) -> None:
        """Pin the 4 specific monitor names cited in the cc-task body."""
        with CONFIG.open() as f:
            data = yaml.safe_load(f)
        names = {s["monitor"] for s in data["stages"]}
        for canonical in (
            "hapax-music-loudnorm.monitor",
            "hapax-music-duck.monitor",
            "hapax-usb-line-driver.monitor",
            "hapax-obs-broadcast-remap.monitor",
        ):
            assert canonical in names, (
                f"canonical stage {canonical!r} (cc-task acceptance) absent from config"
            )


class TestScriptShape:
    def test_script_exists_and_executable(self) -> None:
        assert SCRIPT.is_file()
        assert SCRIPT.stat().st_mode & stat.S_IXUSR

    def test_bash_syntax_clean(self) -> None:
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_help_exits_zero(self) -> None:
        result = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0
        assert result.stdout.strip()


class TestSystemdUnit:
    def test_unit_exists(self) -> None:
        assert SERVICE.is_file()

    def test_unit_orders_after_pipewire(self) -> None:
        content = SERVICE.read_text()
        assert "pipewire.service" in content
        assert "Type=oneshot" in content


class TestDryRunPath:
    def test_dry_run_writes_jsonl_with_skip_status(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "check.jsonl"
        textfile_dir = tmp_path / "metrics"
        env = {**os.environ, "HAPAX_AUDIO_STAGE_CONFIG": str(CONFIG)}
        result = subprocess.run(
            [
                str(SCRIPT),
                "--dry-run",
                "--jsonl-path",
                str(jsonl),
                "--textfile-dir",
                str(textfile_dir),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        assert result.returncode == 0
        assert jsonl.exists(), "dry-run must write at least one JSONL record per stage"
        lines = jsonl.read_text().strip().splitlines()
        assert len(lines) >= 4, (
            f"dry-run should write one JSONL line per stage (≥4); got {len(lines)}"
        )
        for line in lines:
            record = json.loads(line)
            assert record["mode"] == "dry-run"
            assert record["status"] == "dry-run"
            assert record["measured_dbfs"] is None or record["measured_dbfs"] == "null"
            assert record["diverged"] is False

    def test_dry_run_emits_textfile_gauges(self, tmp_path: Path) -> None:
        jsonl = tmp_path / "check.jsonl"
        textfile_dir = tmp_path / "metrics"
        env = {**os.environ, "HAPAX_AUDIO_STAGE_CONFIG": str(CONFIG)}
        subprocess.run(
            [
                str(SCRIPT),
                "--dry-run",
                "--jsonl-path",
                str(jsonl),
                "--textfile-dir",
                str(textfile_dir),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        textfile = textfile_dir / "hapax_audio_stage_check.prom"
        assert textfile.exists()
        content = textfile.read_text()
        assert "hapax_audio_stage_divergent_total 0" in content
        assert "hapax_audio_stage_checked_total" in content


class TestMissingConfig:
    def test_missing_config_exits_three(self, tmp_path: Path) -> None:
        env = {**os.environ}
        result = subprocess.run(
            [
                str(SCRIPT),
                "--config",
                str(tmp_path / "nope.yaml"),
                "--dry-run",
                "--jsonl-path",
                str(tmp_path / "j.jsonl"),
                "--textfile-dir",
                str(tmp_path / "m"),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        assert result.returncode == 3


@pytest.mark.parametrize(
    "stage",
    [
        "hapax-music-loudnorm.monitor",
        "hapax-music-duck.monitor",
        "hapax-usb-line-driver.monitor",
        "hapax-obs-broadcast-remap.monitor",
    ],
)
def test_dry_run_jsonl_contains_each_canonical_stage(tmp_path: Path, stage: str) -> None:
    jsonl = tmp_path / "check.jsonl"
    env = {**os.environ, "HAPAX_AUDIO_STAGE_CONFIG": str(CONFIG)}
    subprocess.run(
        [
            str(SCRIPT),
            "--dry-run",
            "--jsonl-path",
            str(jsonl),
            "--textfile-dir",
            str(tmp_path / "m"),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )
    content = jsonl.read_text()
    assert stage in content, f"dry-run JSONL did not include canonical stage {stage!r}"
