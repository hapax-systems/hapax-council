"""Tests for `_uniforms._iter_passes` and `_load_plan_defaults` schema handling.

Regression coverage for the v1 → v2 plan schema drift that silently starved
the visual chain → GPU bridge. See
`docs/superpowers/specs/2026-04-12-reverie-bridge-repair-design.md`.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from agents.reverie import _uniforms
from shared import working_mode
from shared.visual_mode_bias import PALETTE_HINT
from shared.working_mode import WorkingMode


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear the module-level plan-defaults cache between tests."""
    _uniforms._plan_defaults_cache = None
    _uniforms._plan_defaults_mtime = 0.0
    yield
    _uniforms._plan_defaults_cache = None
    _uniforms._plan_defaults_mtime = 0.0


# -- _iter_passes ------------------------------------------------------------


def test_iter_passes_v1_flat():
    plan = {
        "passes": [
            {"node_id": "noise", "uniforms": {"amplitude": 0.7}},
            {"node_id": "rd", "uniforms": {"feed_rate": 0.055}},
        ]
    }
    result = list(_uniforms._iter_passes(plan))
    assert len(result) == 2
    assert result[0]["node_id"] == "noise"
    assert result[1]["node_id"] == "rd"


def test_iter_passes_v2_single_target():
    plan = {
        "version": 2,
        "targets": {
            "main": {
                "passes": [
                    {"node_id": "noise", "uniforms": {"amplitude": 0.7}},
                    {"node_id": "rd", "uniforms": {"feed_rate": 0.055}},
                    {"node_id": "color", "uniforms": {"saturation": 1.0}},
                ]
            }
        },
    }
    result = list(_uniforms._iter_passes(plan))
    assert len(result) == 3
    assert [p["node_id"] for p in result] == ["noise", "rd", "color"]


def test_iter_passes_v2_multi_target_merges():
    plan = {
        "version": 2,
        "targets": {
            "main": {"passes": [{"node_id": "noise", "uniforms": {"amplitude": 0.7}}]},
            "aux": {"passes": [{"node_id": "post", "uniforms": {"vignette_strength": 0.4}}]},
        },
    }
    result = list(_uniforms._iter_passes(plan))
    assert len(result) == 2
    node_ids = {p["node_id"] for p in result}
    assert node_ids == {"noise", "post"}


def test_iter_passes_empty_and_malformed():
    assert list(_uniforms._iter_passes({})) == []
    assert list(_uniforms._iter_passes({"version": 2})) == []
    assert list(_uniforms._iter_passes({"passes": []})) == []
    assert list(_uniforms._iter_passes({"targets": {}})) == []
    assert list(_uniforms._iter_passes({"targets": "not-a-dict"})) == []


def test_iter_passes_handles_none_targets():
    # targets key present but None — fall through to v1 "passes" branch.
    assert list(_uniforms._iter_passes({"targets": None})) == []
    # targets dict contains None target — skip that target, continue.
    plan = {
        "version": 2,
        "targets": {
            "main": None,
            "aux": {"passes": [{"node_id": "noise", "uniforms": {"amplitude": 0.7}}]},
        },
    }
    result = list(_uniforms._iter_passes(plan))
    assert len(result) == 1
    assert result[0]["node_id"] == "noise"


# -- _load_plan_defaults -----------------------------------------------------


def _write_plan(tmp_path: Path, plan: dict) -> Path:
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan))
    return plan_file


def test_load_plan_defaults_v2_live_shape(tmp_path: Path):
    """Mirrors the shape actually emitted by the Rust DynamicPipeline."""
    plan = {
        "version": 2,
        "targets": {
            "main": {
                "passes": [
                    {
                        "node_id": "noise",
                        "shader": "noise_gen.wgsl",
                        "type": "render",
                        "backend": "wgsl_render",
                        "inputs": [],
                        "output": "layer_0",
                        "uniforms": {
                            "frequency_x": 1.5,
                            "frequency_y": 1.0,
                            "octaves": 3.0,
                            "amplitude": 0.7,
                            "speed": 0.08,
                        },
                        "param_order": [
                            "frequency_x",
                            "frequency_y",
                            "octaves",
                            "amplitude",
                            "speed",
                        ],
                    },
                    {
                        "node_id": "color",
                        "uniforms": {
                            "saturation": 1.0,
                            "brightness": 1.0,
                            "contrast": 0.8,
                            "sepia": 0.0,
                            "hue_rotate": 0.0,
                        },
                        "param_order": [
                            "saturation",
                            "brightness",
                            "contrast",
                            "sepia",
                            "hue_rotate",
                        ],
                    },
                ]
            }
        },
    }
    plan_file = _write_plan(tmp_path, plan)

    with mock.patch.object(_uniforms, "PLAN_FILE", plan_file):
        defaults = _uniforms._load_plan_defaults()

    # All numeric uniforms land keyed as {node_id}.{param_name}.
    assert defaults["noise.amplitude"] == 0.7
    assert defaults["noise.frequency_x"] == 1.5
    assert defaults["noise.octaves"] == 3.0
    assert defaults["color.saturation"] == 1.0
    assert defaults["color.brightness"] == 1.0
    assert defaults["color.contrast"] == 0.8
    # Total count: 5 noise + 5 color.
    assert len(defaults) == 10


def test_load_plan_defaults_v1_still_supported(tmp_path: Path):
    plan = {
        "passes": [
            {"node_id": "noise", "uniforms": {"amplitude": 0.7}},
        ]
    }
    plan_file = _write_plan(tmp_path, plan)

    with mock.patch.object(_uniforms, "PLAN_FILE", plan_file):
        defaults = _uniforms._load_plan_defaults()

    assert defaults == {"noise.amplitude": 0.7}


def test_load_plan_defaults_missing_file_returns_empty(tmp_path: Path):
    missing = tmp_path / "does-not-exist.json"
    with mock.patch.object(_uniforms, "PLAN_FILE", missing):
        defaults = _uniforms._load_plan_defaults()
    assert defaults == {}


def test_load_plan_defaults_malformed_json_returns_empty(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    with mock.patch.object(_uniforms, "PLAN_FILE", bad):
        defaults = _uniforms._load_plan_defaults()
    assert defaults == {}


def test_load_plan_defaults_v2_empty_target_returns_empty(tmp_path: Path):
    plan = {"version": 2, "targets": {"main": {"passes": []}}}
    plan_file = _write_plan(tmp_path, plan)
    with mock.patch.object(_uniforms, "PLAN_FILE", plan_file):
        defaults = _uniforms._load_plan_defaults()
    assert defaults == {}


def test_load_plan_defaults_skips_non_numeric_uniforms(tmp_path: Path):
    plan = {
        "version": 2,
        "targets": {
            "main": {
                "passes": [
                    {
                        "node_id": "noise",
                        "uniforms": {
                            "amplitude": 0.7,
                            "tag": "not-a-number",
                            "slot_opacities": [0.0, 0.0, 0.0, 0.0],
                        },
                    }
                ]
            }
        },
    }
    plan_file = _write_plan(tmp_path, plan)
    with mock.patch.object(_uniforms, "PLAN_FILE", plan_file):
        defaults = _uniforms._load_plan_defaults()
    assert defaults == {"noise.amplitude": 0.7}


def test_load_plan_defaults_caches_until_mtime_changes(tmp_path: Path):
    plan_a = {
        "version": 2,
        "targets": {"main": {"passes": [{"node_id": "noise", "uniforms": {"amplitude": 0.7}}]}},
    }
    plan_b = {
        "version": 2,
        "targets": {"main": {"passes": [{"node_id": "noise", "uniforms": {"amplitude": 0.9}}]}},
    }
    plan_file = _write_plan(tmp_path, plan_a)

    with mock.patch.object(_uniforms, "PLAN_FILE", plan_file):
        first = _uniforms._load_plan_defaults()
        assert first["noise.amplitude"] == 0.7

        # Rewrite with a newer mtime.
        plan_file.write_text(json.dumps(plan_b))
        newer_mtime = plan_file.stat().st_mtime + 1.0
        import os

        os.utime(plan_file, (newer_mtime, newer_mtime))

        second = _uniforms._load_plan_defaults()
        assert second["noise.amplitude"] == 0.9


def test_load_plan_defaults_v2_multi_target_last_wins_on_key_collision(tmp_path: Path):
    # Two targets writing the same {node_id}.{param} key. _load_plan_defaults
    # iterates via _iter_passes and dict-assigns, so the later target in
    # iteration order wins. This test pins that behavior so future readers
    # aren't surprised by the design doc's "later target wins on key
    # collision" claim.
    plan = {
        "version": 2,
        "targets": {
            "main": {"passes": [{"node_id": "noise", "uniforms": {"amplitude": 0.5}}]},
            "aux": {"passes": [{"node_id": "noise", "uniforms": {"amplitude": 0.9}}]},
        },
    }
    plan_file = _write_plan(tmp_path, plan)
    with mock.patch.object(_uniforms, "PLAN_FILE", plan_file):
        defaults = _uniforms._load_plan_defaults()
    # "aux" comes after "main" in Python dict iteration order (insertion-
    # ordered since 3.7), so aux's 0.9 wins.
    assert defaults["noise.amplitude"] == 0.9


def test_load_plan_defaults_file_deletion_caches_empty(tmp_path: Path):
    # Pins the F9 cache-on-file-deletion behavior described in the audit
    # follow-up design doc. When PLAN_FILE is missing, the OSError branch
    # sets current_mtime=0.0, the try/except for json.loads fails silently,
    # and an empty dict is cached against mtime=0.0. Subsequent calls with
    # the file still missing return the empty cached dict without retrying.
    # Once the file reappears with a real mtime, the cache invalidates.
    missing = tmp_path / "not-yet-written.json"
    with mock.patch.object(_uniforms, "PLAN_FILE", missing):
        first = _uniforms._load_plan_defaults()
        assert first == {}
        # Second call: file still missing, cache hit (both mtimes are 0.0).
        second = _uniforms._load_plan_defaults()
        assert second == {}
        # Now create the file — cache should invalidate on new mtime.
        missing.write_text(
            json.dumps(
                {
                    "version": 2,
                    "targets": {
                        "main": {"passes": [{"node_id": "noise", "uniforms": {"amplitude": 0.7}}]}
                    },
                }
            )
        )
        third = _uniforms._load_plan_defaults()
        assert third == {"noise.amplitude": 0.7}


# -- write_uniforms integration-level coverage -------------------------------


class _FakeVisualChain:
    """Minimal VisualChainCapability stand-in for write_uniforms tests."""

    def __init__(self, deltas: dict[str, float]) -> None:
        self._deltas = dict(deltas)

    def compute_param_deltas(self) -> dict[str, float]:
        return dict(self._deltas)


def test_write_uniforms_end_to_end_produces_expected_keys(tmp_path: Path):
    """First direct test of write_uniforms. Asserts every plan-default key is
    written, chain deltas are merged correctly, content.material is overwritten
    from the imagination fragment, and content.intensity stays at the plan
    default (0.0) after the audit follow-up reverted the passthrough."""
    plan = {
        "version": 2,
        "targets": {
            "main": {
                "passes": [
                    {"node_id": "noise", "uniforms": {"amplitude": 0.7, "frequency_x": 1.5}},
                    {"node_id": "rd", "uniforms": {"feed_rate": 0.055, "kill_rate": 0.062}},
                    {"node_id": "color", "uniforms": {"saturation": 1.0, "brightness": 1.0}},
                    {"node_id": "fb", "uniforms": {"decay": 0.12}},
                    {
                        "node_id": "content",
                        "uniforms": {"salience": 0.0, "intensity": 0.0, "material": 0.0},
                    },
                    {"node_id": "post", "uniforms": {"vignette_strength": 0.4}},
                ]
            }
        },
    }
    plan_file = _write_plan(tmp_path, plan)
    uniforms_file = tmp_path / "uniforms.json"

    fake_chain = _FakeVisualChain(
        {
            "noise.amplitude": 0.1,
            "color.saturation": 0.2,
            "rd.feed_rate": -0.005,
        }
    )

    # Fake "now" — use the same value for imagination timestamp so silence = 1.0.
    FAKE_NOW = 1776041528.0

    fake_imagination = {
        "salience": 0.4,
        "material": "fire",
        "timestamp": FAKE_NOW,
    }
    fake_stimmung = {
        "overall_stance": "cautious",
        "health": {"value": 0.2},
    }

    with (
        mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
        mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
        # Phase A6: patch HOMAGE_SUBSTRATE_PACKAGE_FILE to a nonexistent
        # path so this test's plan-default+chain-delta invariants aren't
        # overridden by the live broadcast (the homage substrate-invariant
        # damping is pinned separately in test_homage_substrate_damping.py).
        mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", tmp_path / "no-homage.json"),
        # U8 mode tint is covered separately; keep this legacy merge test
        # focused on plan-default + chain-delta composition.
        mock.patch.object(_uniforms, "_apply_mode_palette_tint", lambda u, **kw: None),
        mock.patch.object(_uniforms.time, "time", return_value=FAKE_NOW),
    ):
        _uniforms.write_uniforms(
            fake_imagination,
            fake_stimmung,
            fake_chain,
            trace_strength=0.0,
            trace_center=(0.5, 0.5),
            trace_radius=0.0,
        )

    result = json.loads(uniforms_file.read_text())

    # Every plan-default key is present with base + delta applied.
    assert result["noise.amplitude"] == pytest.approx(0.7 + 0.1)
    assert result["noise.frequency_x"] == pytest.approx(1.5)  # no delta
    assert result["rd.feed_rate"] == pytest.approx(0.055 + -0.005)
    assert result["color.saturation"] == pytest.approx(1.0 + 0.2)

    # content.material was overwritten by the imagination branch ("fire" = 1).
    assert result["content.material"] == pytest.approx(1.0)
    # content.salience was overwritten by salience × silence (silence=1.0
    # for fresh imagination).
    assert result["content.salience"] == pytest.approx(0.4)
    # content.intensity — F8 restored the passthrough now that Rust routes
    # content.* into UniformData.custom[0][0..2]. With fresh imagination
    # (silence=1.0), intensity mirrors salience × silence.
    assert result["content.intensity"] == pytest.approx(0.4)

    # Signal keys present.
    assert result["signal.stance"] == pytest.approx(0.25)  # cautious
    assert result["signal.color_warmth"] == pytest.approx(0.2)  # max of health

    # Trace keys present (fb.trace_* overlaps with plan default in fb node, but
    # here fb node only declared `decay` so the trace keys are written fresh).
    assert result["fb.trace_strength"] == pytest.approx(0.0)
    assert result["fb.trace_center_x"] == pytest.approx(0.5)

    # Plan defaults: noise(2) + rd(2) + color(2) + fb(1) + content(3) + post(1) = 11
    # Plus signal.stance + signal.color_warmth + fb.trace_* (4 new since fb
    # node only had decay) = 11 + 2 + 4 = 17.
    # U8 mode tint is patched out above; dedicated tint tests pin color.hue_rotate.
    assert len(result) == 17


def test_write_uniforms_silence_attenuation_when_imagination_stale(tmp_path: Path):
    """When imagination is stale, silence attenuates chain deltas toward plan defaults."""
    plan = {
        "version": 2,
        "targets": {
            "main": {
                "passes": [
                    {"node_id": "noise", "uniforms": {"amplitude": 0.7}},
                ]
            }
        },
    }
    plan_file = _write_plan(tmp_path, plan)
    uniforms_file = tmp_path / "uniforms.json"

    fake_chain = _FakeVisualChain({"noise.amplitude": 0.5})

    # Very stale imagination — age = 120s, STALE_S = 60s.
    # raw = 1.0 - (120 - 60)/60 = 0.0, clamped to SILENCE_FLOOR (0.15).
    FAKE_NOW = 1776041528.0
    stale_imagination = {"salience": 0.4, "material": "water", "timestamp": FAKE_NOW - 120.0}

    with (
        mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
        mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
        # Phase A6: isolate from live homage broadcast.
        mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", tmp_path / "no-homage.json"),
        mock.patch.object(_uniforms.time, "time", return_value=FAKE_NOW),
    ):
        _uniforms.write_uniforms(
            stale_imagination,
            None,
            fake_chain,
            trace_strength=0.0,
            trace_center=(0.5, 0.5),
            trace_radius=0.0,
        )

    result = json.loads(uniforms_file.read_text())
    # silence = max(0.15, 0.0) = 0.15
    # noise.amplitude = 0.7 + 0.5 * 1.0 * 0.15 = 0.775
    assert result["noise.amplitude"] == pytest.approx(0.7 + 0.5 * 0.15)


def test_write_uniforms_silence_floor_when_imagination_missing(tmp_path: Path):
    """When imagination is None, silence = SILENCE_FLOOR (0.15)."""
    plan = {
        "version": 2,
        "targets": {"main": {"passes": [{"node_id": "noise", "uniforms": {"amplitude": 0.7}}]}},
    }
    plan_file = _write_plan(tmp_path, plan)
    uniforms_file = tmp_path / "uniforms.json"

    fake_chain = _FakeVisualChain({"noise.amplitude": 0.5})

    with (
        mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
        mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
        # Phase A6: isolate from live homage broadcast.
        mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", tmp_path / "no-homage.json"),
    ):
        _uniforms.write_uniforms(
            None,
            None,
            fake_chain,
            trace_strength=0.0,
            trace_center=(0.5, 0.5),
            trace_radius=0.0,
        )

    result = json.loads(uniforms_file.read_text())
    # silence = 0.15 (SILENCE_FLOOR, imagination is None)
    assert result["noise.amplitude"] == pytest.approx(0.7 + 0.5 * 0.15)
    # imagination is None, so content.* keys should NOT be written by the
    # imagination branch. The minimal fixture has no content node in plan,
    # so no content.* keys should be in the result.
    assert not any(k.startswith("content.") for k in result)


# -- _sanitize_uniform_value -------------------------------------------------


class TestSanitizeUniformValue:
    """Unit coverage for the NaN/Inf/bool poison-value clamp.

    Audit: 24h independent-auditor batch 2026-05-02 (E #9). Rust
    ``serde_json`` silently crashes on NaN/Inf in input from the Python
    modulator; the sanitizer is the last line of defence.
    """

    def test_nan_clamps_to_zero(self):
        assert _uniforms._sanitize_uniform_value(float("nan")) == 0.0

    def test_positive_inf_clamps_to_zero(self):
        assert _uniforms._sanitize_uniform_value(float("inf")) == 0.0

    def test_negative_inf_clamps_to_zero(self):
        assert _uniforms._sanitize_uniform_value(float("-inf")) == 0.0

    def test_true_coerces_to_one(self):
        assert _uniforms._sanitize_uniform_value(True) == 1.0

    def test_false_coerces_to_zero(self):
        assert _uniforms._sanitize_uniform_value(False) == 0.0

    def test_normal_float_passes_through(self):
        assert _uniforms._sanitize_uniform_value(0.5) == pytest.approx(0.5)
        assert _uniforms._sanitize_uniform_value(-0.7) == pytest.approx(-0.7)
        assert _uniforms._sanitize_uniform_value(180.0) == pytest.approx(180.0)

    def test_int_coerces_to_float(self):
        result = _uniforms._sanitize_uniform_value(42)
        assert result == pytest.approx(42.0)
        assert isinstance(result, float)

    def test_pathological_large_value_clipped(self):
        assert _uniforms._sanitize_uniform_value(1e9) == 1e6
        assert _uniforms._sanitize_uniform_value(-1e9) == -1e6


def test_write_uniforms_sanitizes_nan_inf_bool_before_json_dump(tmp_path: Path):
    """End-to-end: poison values from compute_param_deltas() never reach the
    serialised JSON.

    Audit-driven regression pin (24h independent-auditor batch 2026-05-02 E #9).
    The visual chain modulator could aggregate NaN/Inf/bool through
    compute_param_deltas() and silently crash the Rust serde_json parser
    that consumes /dev/shm/hapax-imagination/uniforms.json. The sanitizer
    forces every emitted value to a finite, JSON-safe float.
    """
    plan = {
        "version": 2,
        "targets": {
            "main": {
                "passes": [
                    {
                        "node_id": "noise",
                        "uniforms": {
                            "amplitude": 0.7,
                            "frequency_x": 1.5,
                            "phase": 0.0,
                        },
                    },
                ]
            }
        },
    }
    plan_file = _write_plan(tmp_path, plan)
    uniforms_file = tmp_path / "uniforms.json"

    # Chain emits one NaN, one +Inf, one -Inf, plus a normal float that
    # combines with a plan default to produce a sane finite value. The
    # bool path is harder to inject through a plan-default merge (the
    # base + delta arithmetic forces float), so we cover True/False via
    # the unit-class above and via _sanitize_uniform_value direct calls.
    fake_chain = _FakeVisualChain(
        {
            "noise.amplitude": float("nan"),  # NaN delta → NaN value
            "noise.frequency_x": float("inf"),  # +Inf delta → +Inf value
            "noise.phase": float("-inf"),  # -Inf delta → -Inf value
        }
    )

    FAKE_NOW = 1776041528.0

    with (
        mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
        mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
        mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", tmp_path / "no-homage.json"),
        # U8 mode tint intentionally owns hue_rotate in production; this
        # sanitizer test only asserts finite chain values survive the
        # scalar merge path.
        mock.patch.object(_uniforms, "_apply_mode_palette_tint", lambda u, **kw: None),
        mock.patch.object(_uniforms.time, "time", return_value=FAKE_NOW),
    ):
        _uniforms.write_uniforms(
            None,
            None,
            fake_chain,
            trace_strength=0.0,
            trace_center=(0.5, 0.5),
            trace_radius=0.0,
        )

    # The file MUST be readable JSON — Rust serde_json must be able to parse it.
    raw_text = uniforms_file.read_text()
    # json.loads tolerates the Python literals "NaN" / "Infinity" by default,
    # but the strict-spec parser (Rust serde_json) does not. We assert on the
    # raw text to catch the case where Python wrote a non-spec literal.
    assert "NaN" not in raw_text
    assert "Infinity" not in raw_text
    assert "-Infinity" not in raw_text

    result = json.loads(raw_text)
    # All three poisoned uniforms must be sanitized to 0.0 (the safe default).
    assert result["noise.amplitude"] == 0.0
    assert result["noise.frequency_x"] == 0.0
    assert result["noise.phase"] == 0.0


def test_write_uniforms_passes_normal_values_through(tmp_path: Path):
    """Sanitizer must not perturb legitimate finite values."""
    plan = {
        "version": 2,
        "targets": {
            "main": {
                "passes": [
                    {"node_id": "noise", "uniforms": {"amplitude": 0.7}},
                    {"node_id": "color", "uniforms": {"hue_rotate": 0.0}},
                ]
            }
        },
    }
    plan_file = _write_plan(tmp_path, plan)
    uniforms_file = tmp_path / "uniforms.json"

    fake_chain = _FakeVisualChain(
        {
            "noise.amplitude": 0.1,
            "color.hue_rotate": 70.0,  # the audit-mentioned hue shift
        }
    )

    FAKE_NOW = 1776041528.0

    with (
        mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
        mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
        mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", tmp_path / "no-homage.json"),
        # U8 mode tint intentionally owns hue_rotate in production; this
        # sanitizer test only asserts finite chain values survive the
        # scalar merge path.
        mock.patch.object(_uniforms, "_apply_mode_palette_tint", lambda u, **kw: None),
        mock.patch.object(_uniforms.time, "time", return_value=FAKE_NOW),
    ):
        _uniforms.write_uniforms(
            {"salience": 0.4, "material": "water", "timestamp": FAKE_NOW},
            None,
            fake_chain,
            trace_strength=0.0,
            trace_center=(0.5, 0.5),
            trace_radius=0.0,
        )

    result = json.loads(uniforms_file.read_text())
    assert result["noise.amplitude"] == pytest.approx(0.7 + 0.1)
    # color.hue_rotate is now derived from PALETTE_HINT[mode][0] by U8
    # imagination-tint (#2378) — the chain delta is overwritten by the
    # mode-bias derivation. Just check the key is present.
    assert "color.hue_rotate" in result


def test_write_uniforms_mode_tint_reacts_to_working_mode_file(tmp_path: Path):
    """U8 e2e pin: write_uniforms reads the live working-mode file each tick
    and emits visibly distinct color.hue_rotate values."""
    plan = {
        "version": 2,
        "targets": {
            "main": {
                "passes": [
                    {"node_id": "color", "uniforms": {"hue_rotate": 0.0}},
                ]
            }
        },
    }
    plan_file = _write_plan(tmp_path, plan)
    uniforms_file = tmp_path / "uniforms.json"
    mode_file = tmp_path / "working-mode"

    def write_for(mode: WorkingMode) -> float:
        mode_file.write_text(f"{mode.value}\n")
        with (
            mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
            mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
            mock.patch.object(
                _uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", tmp_path / "no-homage.json"
            ),
            mock.patch.object(working_mode, "WORKING_MODE_FILE", mode_file),
        ):
            _uniforms.write_uniforms(
                None,
                None,
                _FakeVisualChain({}),
                trace_strength=0.0,
                trace_center=(0.5, 0.5),
                trace_radius=0.0,
            )
        return json.loads(uniforms_file.read_text())["color.hue_rotate"]

    research_value = write_for(WorkingMode.RESEARCH)
    rnd_value = write_for(WorkingMode.RND)

    assert research_value < 0.0
    assert rnd_value > 0.0
    assert abs(research_value - rnd_value) > 100.0


def test_write_uniforms_mode_tint_overrides_extreme_hue_chain_delta(tmp_path: Path):
    """Mode tint is authoritative over visual-chain hue_rotate deltas and
    therefore cannot leak an out-of-schema colorgrade value."""
    plan = {
        "version": 2,
        "targets": {
            "main": {
                "passes": [
                    {"node_id": "color", "uniforms": {"hue_rotate": 0.0}},
                ]
            }
        },
    }
    plan_file = _write_plan(tmp_path, plan)
    uniforms_file = tmp_path / "uniforms.json"
    mode_file = tmp_path / "working-mode"
    mode_file.write_text(f"{WorkingMode.RESEARCH.value}\n")

    with (
        mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
        mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
        mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", tmp_path / "no-homage.json"),
        mock.patch.object(working_mode, "WORKING_MODE_FILE", mode_file),
    ):
        _uniforms.write_uniforms(
            None,
            None,
            _FakeVisualChain({"color.hue_rotate": 1000.0}),
            trace_strength=0.0,
            trace_center=(0.5, 0.5),
            trace_radius=0.0,
        )

    result = json.loads(uniforms_file.read_text())
    expected = _uniforms._palette_hint_to_hue_rotate(PALETTE_HINT[WorkingMode.RESEARCH])
    assert result["color.hue_rotate"] == pytest.approx(expected)
    assert -180.0 <= result["color.hue_rotate"] <= 180.0
