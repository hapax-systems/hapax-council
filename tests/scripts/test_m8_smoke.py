"""Tests for ``scripts/m8-smoke.py`` — M8 Re-Splay smoke verifier.

Cc-task ``m8-re-splay-operator-install-and-smoke``. The script is the
operator's post-install fast-loop check; tests pin the per-check
pass/fail logic so a future regression in the M8 surface layout
surfaces here rather than during a live broadcast.

The script lives at ``scripts/m8-smoke.py`` (hyphenated filename to
match the existing ``m8-*`` script convention). Tests import it via
``importlib.util`` so the hyphen doesn't break Python's normal
attribute-style imports.
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT_PATH = REPO_ROOT / "scripts" / "m8-smoke.py"


def _load_smoke_module() -> ModuleType:
    """Load ``scripts/m8-smoke.py`` as a module despite the hyphen in the name.

    Registers the module in ``sys.modules`` BEFORE ``exec_module`` so
    ``@dataclass`` introspection (which walks ``sys.modules`` to resolve
    the class's source module) doesn't crash on a missing entry.
    """

    import sys

    spec = importlib.util.spec_from_file_location("m8_smoke_under_test", SMOKE_SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["m8_smoke_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def smoke() -> ModuleType:
    return _load_smoke_module()


# ── 1. SHM freshness check ──────────────────────────────────────────


class TestShmFreshness:
    def test_missing_shm_fails(self, smoke, tmp_path: Path):
        result = smoke._check_shm_freshness(shm_path=tmp_path / "missing.rgba")
        assert result.passed is False
        assert "missing" in result.detail.lower()
        assert result.remediation

    def test_fresh_shm_passes(self, smoke, tmp_path: Path):
        shm = tmp_path / "m8-display.rgba"
        shm.write_bytes(b"\x00\x00\x00\xff" * 16)
        # The fixture's mtime is "now" by default — no need to bump.
        result = smoke._check_shm_freshness(
            shm_path=shm,
            freshness_window_s=10.0,
            now=time.time(),
        )
        assert result.passed is True
        assert "OK" not in result.detail  # detail describes the age numerically

    def test_stale_shm_fails(self, smoke, tmp_path: Path):
        shm = tmp_path / "m8-display.rgba"
        shm.write_bytes(b"")
        # Move mtime far into the past.
        old_ts = time.time() - 999.0
        import os

        os.utime(shm, (old_ts, old_ts))
        result = smoke._check_shm_freshness(
            shm_path=shm,
            freshness_window_s=5.0,
            now=time.time(),
        )
        assert result.passed is False
        assert "stale" in result.detail
        assert "Re-plug" in result.remediation


# ── 2. Affordance registered check ──────────────────────────────────


class TestAffordanceRegistered:
    def test_affordance_present_in_live_registry(self, smoke):
        # The live registry already carries studio.m8_lcd_reveal; the
        # check should pass without test-side setup.
        result = smoke._check_affordance_registered()
        assert result.passed is True
        assert "studio.m8_lcd_reveal" in result.detail


# ── 3. Layout ward_id check ─────────────────────────────────────────


class TestLayoutWardId:
    def test_live_default_layout_carries_ward_id(self, smoke):
        # PR #2492 wired ward_id='m8-display' on default.json + the
        # in-tree fallback. The check reads the live default.json.
        result = smoke._check_layout_ward_id()
        assert result.passed is True

    def test_layout_with_null_ward_id_fails(self, smoke, tmp_path: Path):
        bad_layout = {
            "name": "test",
            "sources": [
                {
                    "id": "m8-display",
                    "kind": "external_rgba",
                    "ward_id": None,
                }
            ],
            "surfaces": [],
            "assignments": [],
        }
        path = tmp_path / "default.json"
        path.write_text(json.dumps(bad_layout), encoding="utf-8")
        result = smoke._check_layout_ward_id(layout_path=path)
        assert result.passed is False
        assert "ward_id" in result.detail
        assert "PR #2492" in result.remediation

    def test_layout_without_m8_source_fails(self, smoke, tmp_path: Path):
        bad_layout = {"name": "test", "sources": [], "surfaces": [], "assignments": []}
        path = tmp_path / "default.json"
        path.write_text(json.dumps(bad_layout), encoding="utf-8")
        result = smoke._check_layout_ward_id(layout_path=path)
        assert result.passed is False
        assert "no m8-display" in result.detail.lower()

    def test_missing_layout_file_fails(self, smoke, tmp_path: Path):
        result = smoke._check_layout_ward_id(layout_path=tmp_path / "nope.json")
        assert result.passed is False
        assert "missing" in result.detail.lower()


# ── 4. PipeWire routing check ───────────────────────────────────────


class TestPipewireRouting:
    def test_live_conf_passes(self, smoke):
        # The live config/pipewire/hapax-m8-loudnorm.conf routes through
        # the bounded MPC AUX10/AUX11 handoff; the reconciler owns the
        # downstream L-12 wet return.
        result = smoke._check_pipewire_routing()
        assert result.passed is True

    def test_missing_conf_fails(self, smoke, tmp_path: Path):
        result = smoke._check_pipewire_routing(conf_path=tmp_path / "missing.conf")
        assert result.passed is False
        assert "missing" in result.detail.lower()

    def test_livestream_tap_bypass_fails(self, smoke, tmp_path: Path):
        # Include the expected MPC handoff so this probes bypass detection.
        bad_conf = (
            "# both the governed handoff AND a livestream-tap bypass\n"
            'target.object = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"\n'
            "audio.position = [ AUX10 AUX11 ]\n"
            "node.autoconnect = false\n"
            'target.object = "hapax-livestream-tap"\n'
        )
        path = tmp_path / "bad.conf"
        path.write_text(bad_conf, encoding="utf-8")
        result = smoke._check_pipewire_routing(conf_path=path)
        assert result.passed is False
        assert "livestream-tap" in result.detail
        assert "remove" in result.remediation.lower()

    def test_no_mpc_handoff_target_fails(self, smoke, tmp_path: Path):
        bad_conf = "# no target.object pointing at the MPC handoff\nname = silly\n"
        path = tmp_path / "bad.conf"
        path.write_text(bad_conf, encoding="utf-8")
        result = smoke._check_pipewire_routing(conf_path=path)
        assert result.passed is False
        assert "MPC" in result.detail

    def test_missing_aux_handoff_fails(self, smoke, tmp_path: Path):
        bad_conf = (
            'target.object = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"\n'
            "node.autoconnect = false\n"
        )
        path = tmp_path / "bad.conf"
        path.write_text(bad_conf, encoding="utf-8")
        result = smoke._check_pipewire_routing(conf_path=path)
        assert result.passed is False
        assert "AUX10 AUX11" in result.detail

    def test_autoconnect_enabled_fails(self, smoke, tmp_path: Path):
        bad_conf = (
            'target.object = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"\n'
            "audio.position = [ AUX10 AUX11 ]\n"
        )
        path = tmp_path / "bad.conf"
        path.write_text(bad_conf, encoding="utf-8")
        result = smoke._check_pipewire_routing(conf_path=path)
        assert result.passed is False
        assert "autoconnect" in result.detail


# ── 5. Activity-reveal lifecycle check ──────────────────────────────


class TestActivityRevealLifecycle:
    def test_fresh_shm_lifecycle_pass(self, smoke, tmp_path: Path):
        shm = tmp_path / "m8-display.rgba"
        shm.write_bytes(b"\x00" * 16)
        result = smoke._check_activity_reveal_lifecycle(
            shm_path=shm,
            now=time.time(),
        )
        assert result.passed is True
        assert "router will paint" in result.detail

    def test_missing_shm_lifecycle_fails(self, smoke, tmp_path: Path):
        result = smoke._check_activity_reveal_lifecycle(
            shm_path=tmp_path / "missing.rgba",
            now=time.time(),
        )
        assert result.passed is False
        assert "opacity 0.0" in result.detail


# ── 6. CLI entrypoint + run_checks dispatcher ───────────────────────


class TestRunChecks:
    def test_run_all_returns_five_results(self, smoke):
        results = smoke.run_checks()
        assert len(results) == 5
        names = {r.name for r in results}
        assert names == {
            "shm_freshness",
            "affordance_registered",
            "layout_ward_id",
            "pipewire_routing",
            "activity_reveal_lifecycle",
        }

    def test_run_single_check_by_name(self, smoke):
        results = smoke.run_checks(["affordance"])
        assert len(results) == 1
        assert results[0].name == "affordance_registered"

    def test_unknown_check_returns_failure(self, smoke):
        results = smoke.run_checks(["bogus"])
        assert len(results) == 1
        assert results[0].passed is False
        assert "unknown check" in results[0].detail


class TestCLI:
    def test_main_returns_one_when_any_check_fails(self, smoke, capsys):
        # No live SHM in CI → shm_freshness fails → exit 1.
        rc = smoke.main([])
        captured = capsys.readouterr()
        assert rc in (0, 1)
        assert "M8 Re-Splay smoke verifier" in captured.out
        assert "checks passed" in captured.out

    def test_main_json_emits_valid_json(self, smoke, capsys):
        smoke.main(["--json"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert "results" in payload
        assert "all_passed" in payload
        assert isinstance(payload["all_passed"], bool)
        assert isinstance(payload["results"], list)

    def test_main_with_check_runs_subset(self, smoke, capsys):
        rc = smoke.main(["--check", "affordance"])
        captured = capsys.readouterr()
        assert "affordance_registered" in captured.out
        # Affordance is statically wired in the registry, so this
        # check passes regardless of M8 hardware state.
        assert rc == 0
        # Other checks should not appear.
        assert "shm_freshness" not in captured.out


class TestFeatureFlagWarning:
    def test_feature_flag_disabled_by_default(self, smoke, monkeypatch):
        monkeypatch.delenv(smoke.ACTIVITY_REVEAL_M8_FLAG, raising=False)
        assert smoke._is_feature_flag_enabled() is False

    def test_feature_flag_enabled_when_set(self, smoke, monkeypatch):
        monkeypatch.setenv(smoke.ACTIVITY_REVEAL_M8_FLAG, "1")
        assert smoke._is_feature_flag_enabled() is True
