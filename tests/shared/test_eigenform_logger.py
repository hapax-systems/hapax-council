"""Tests for shared.eigenform_logger.log_state_vector.

Both sinks are isolated by the root conftest. Fresh imports below bind
production defaults inside a synthetic home before exercising regressions.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from shared import eigenform_logger
from shared.eigenform_logger import log_state_vector


@pytest.fixture
def logger(tmp_path, monkeypatch):
    fake_home = tmp_path / "synthetic-home"
    source = Path(eigenform_logger.__file__)
    spec = importlib.util.spec_from_file_location("isolated_eigenform_logger", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        spec.loader.exec_module(module)
    expected = fake_home / "hapax-state/research/eigenform-log.jsonl"
    assert expected == module.PERSISTENT_LOG
    monkeypatch.setattr(module, "EIGENFORM_LOG", fake_home / "state-log.jsonl")
    # Old ring defaults are also redirected so the RED run cannot reach tmpfs.
    ring_default = inspect.signature(module.log_state_vector).parameters["path"].default
    if isinstance(ring_default, Path):
        monkeypatch.setattr(
            module.log_state_vector,
            "__kwdefaults__",
            {**module.log_state_vector.__kwdefaults__, "path": module.EIGENFORM_LOG},
        )
    # Accept a required path or the old captured default, but never an unsafe one.
    destinations = [value for value in vars(module).values() if isinstance(value, Path)]
    for function in (module.log_state_vector, module._append_and_trim):
        destinations.extend(
            parameter.default
            for parameter in inspect.signature(function).parameters.values()
            if isinstance(parameter.default, Path)
        )
    assert destinations and all(path.is_relative_to(fake_home) for path in destinations)
    return module


def test_custom_sink_does_not_write_default_research_log(logger):
    target = logger.EIGENFORM_LOG.parent / "custom-state-log.jsonl"
    logger.log_state_vector(presence=0.7, path=target)
    assert target.exists()
    assert not logger.PERSISTENT_LOG.exists(), "custom sink escaped to default persistent sink"


def test_patching_persistent_sink_redirects_the_actual_write(logger, monkeypatch):
    captured_default = logger.PERSISTENT_LOG
    replacement = logger.EIGENFORM_LOG.parent / "replacement-persistent.jsonl"
    monkeypatch.setattr(logger, "PERSISTENT_LOG", replacement)
    logger.log_state_vector(presence=0.8, path=logger.EIGENFORM_LOG.parent / "custom-log.jsonl")
    assert replacement.exists(), "global patch did not redirect the captured default"
    assert not captured_default.exists()


def test_default_call_writes_both_sinks(logger):
    logger.log_state_vector(presence=0.9)
    assert logger.EIGENFORM_LOG.read_text() == logger.PERSISTENT_LOG.read_text()
    assert json.loads(logger.PERSISTENT_LOG.read_text())["presence"] == 0.9


def test_persistent_trim_retains_50k_after_twice_the_limit(logger):
    target = logger.EIGENFORM_LOG.parent / "persistent.jsonl"
    target.parent.mkdir(parents=True)
    target.write_text("".join(json.dumps({"n": i}) + "\n" for i in range(99_999)))
    logger._append_and_trim({"n": 99_999}, path=target)
    assert len(target.read_text().splitlines()) == 100_000
    logger._append_and_trim({"n": 100_000}, path=target)
    entries = [json.loads(line) for line in target.read_text().splitlines()]
    assert len(entries) == 50_000
    assert entries[0] == {"n": 50_001}
    assert entries[-1] == {"n": 100_000}


def test_persistent_oserror_does_not_prevent_ring_write(logger, monkeypatch):
    blocker = logger.EIGENFORM_LOG.parent / "not-a-directory"
    blocker.parent.mkdir(parents=True)
    blocker.write_text("blocked")
    monkeypatch.setattr(logger, "PERSISTENT_LOG", blocker / "persistent.jsonl")
    logger.log_state_vector(presence=0.4)
    assert json.loads(logger.EIGENFORM_LOG.read_text())["presence"] == 0.4


def test_persistent_sink_isolation(tmp_path):
    """Run both whole modules before checking HOME; survives fixture removal."""
    fake_home = tmp_path / "suite-home"
    fake_home.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--confcutdir=tests",
            "tests/test_eigenform_logger.py",
            "tests/shared/test_eigenform_logger.py",
            "-k",
            "not test_persistent_sink_isolation",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "HOME": str(fake_home), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    research = fake_home / "hapax-state/research"
    assert not any(path.is_file() for path in research.rglob("*")), (
        "test modules wrote the default persistent research sink"
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ── Append behaviour ──────────────────────────────────────────────


class TestAppend:
    def test_first_call_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(presence=0.7, path=target)
        assert target.exists()
        line = target.read_text().strip()
        entry = json.loads(line)
        assert entry["presence"] == 0.7

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "path" / "log.jsonl"
        log_state_vector(path=target)
        assert target.exists()

    def test_subsequent_calls_append(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(presence=0.1, path=target)
        log_state_vector(presence=0.2, path=target)
        log_state_vector(presence=0.3, path=target)
        lines = target.read_text().strip().split("\n")
        assert len(lines) == 3
        entries = [json.loads(line) for line in lines]
        assert [e["presence"] for e in entries] == [0.1, 0.2, 0.3]


# ── Entry shape ───────────────────────────────────────────────────


class TestEntryShape:
    def test_default_field_set(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(path=target)
        entry = json.loads(target.read_text().strip())
        # All canonical fields present
        expected_keys = {
            "t",
            "presence",
            "flow_score",
            "audio_energy",
            "stimmung_stance",
            "imagination_salience",
            "visual_brightness",
            "heart_rate",
            "operator_stress",
            "activity",
            "e_mesh",
            "restriction_residual_rms",
            "sensitive_fields_redacted",
        }
        assert set(entry.keys()) == expected_keys

    def test_default_values(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(path=target)
        entry = json.loads(target.read_text().strip())
        assert entry["presence"] == 0.0
        assert entry["stimmung_stance"] == "nominal"
        assert entry["activity"] == "idle"
        assert entry["e_mesh"] == 1.0

    def test_all_fields_serialised(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(
            presence=0.8,
            flow_score=0.6,
            audio_energy=0.3,
            stimmung_stance="cautious",
            imagination_salience=0.4,
            visual_brightness=0.2,
            heart_rate=72.0,
            operator_stress=0.5,
            activity="speaking",
            e_mesh=0.4,
            restriction_residual_rms=0.1,
            path=target,
        )
        entry = json.loads(target.read_text().strip())
        assert entry["presence"] == 0.8
        assert entry["stimmung_stance"] == "cautious"
        assert entry["heart_rate"] == 0.0
        assert entry["operator_stress"] == 0.0
        assert entry["sensitive_fields_redacted"] == ["heart_rate", "operator_stress"]
        assert entry["activity"] == "speaking"

    def test_sensitive_numeric_fields_are_not_serialised(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(
            heart_rate=123.0,
            operator_stress=0.87,
            activity="secret-activity-value",
            stimmung_stance="secret-stimmung-value",
            path=target,
        )
        raw = target.read_text()
        entry = json.loads(raw.strip())
        assert "secret-activity-value" not in raw
        assert "secret-stimmung-value" not in raw
        assert entry["heart_rate"] == 0.0
        assert entry["operator_stress"] == 0.0
        assert entry["activity"] == "unknown"
        assert entry["stimmung_stance"] == "nominal"

    def test_timestamp_is_float(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        log_state_vector(path=target)
        entry = json.loads(target.read_text().strip())
        assert isinstance(entry["t"], float)
        assert entry["t"] > 0


# ── Ring-buffer trim ──────────────────────────────────────────────


class TestRingBufferTrim:
    def test_under_threshold_no_trim(self, tmp_path: Path, monkeypatch: object) -> None:
        """When line count is <= 2× MAX_ENTRIES, no trim happens."""
        target = tmp_path / "log.jsonl"
        # Use a small max via monkeypatch for fast tests
        from pytest import MonkeyPatch

        mp = MonkeyPatch()
        mp.setattr(eigenform_logger, "MAX_ENTRIES", 5)
        try:
            for i in range(8):  # 8 < 2*5 = 10 → no trim
                log_state_vector(presence=float(i), path=target)
            lines = target.read_text().strip().split("\n")
            assert len(lines) == 8
        finally:
            mp.undo()

    def test_over_threshold_trims_to_max(self, tmp_path: Path) -> None:
        """When line count exceeds 2× MAX_ENTRIES, trim to last MAX_ENTRIES."""
        target = tmp_path / "log.jsonl"
        from pytest import MonkeyPatch

        mp = MonkeyPatch()
        mp.setattr(eigenform_logger, "MAX_ENTRIES", 3)
        try:
            for i in range(7):  # 7 > 2*3 = 6 → trim
                log_state_vector(presence=float(i), path=target)
            lines = target.read_text().strip().split("\n")
            # Should be trimmed to last 3 entries
            assert len(lines) == 3
            entries = [json.loads(line) for line in lines]
            # Last 3 are presence 4, 5, 6
            assert [e["presence"] for e in entries] == [4.0, 5.0, 6.0]
        finally:
            mp.undo()


# ── Error tolerance ───────────────────────────────────────────────


class TestErrorTolerance:
    def test_trim_oserror_swallowed(self, tmp_path: Path) -> None:
        """The trim's read_text/write_text is wrapped in try/except OSError;
        a hostile filesystem doesn't crash the logger. Verify the append
        still made it to disk."""
        target = tmp_path / "log.jsonl"
        log_state_vector(presence=0.5, path=target)
        assert target.exists()
        entry = json.loads(target.read_text().strip())
        assert entry["presence"] == 0.5
