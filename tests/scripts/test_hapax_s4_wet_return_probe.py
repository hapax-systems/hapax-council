from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-s4-wet-return-probe"


def load_module():
    loader = importlib.machinery.SourceFileLoader("hapax_s4_wet_return_probe", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def _capture(*, marker: bool, rms: float, peak: float) -> dict:
    return {
        "channels": {
            "0": {
                "marker_detected": marker,
                "rms_dbfs": rms,
                "peak_dbfs": peak,
            },
            "1": {
                "marker_detected": marker,
                "rms_dbfs": rms,
                "peak_dbfs": peak,
            },
        }
    }


def test_evaluate_probe_rejects_marker_crosstalk_below_wet_level() -> None:
    mod = load_module()
    wet_signal, reasons = mod.evaluate_probe(
        structural_route_present=True,
        captures={
            "dry_loudnorm_playback": _capture(marker=True, rms=-38.0, peak=-29.0),
            "wet_voice_playback": _capture(marker=True, rms=-90.0, peak=-78.0),
        },
        wet_min_rms_dbfs=-65.0,
        wet_min_peak_dbfs=-55.0,
    )

    assert wet_signal is False
    assert "wet_rms_below_threshold" in reasons
    assert "wet_peak_below_threshold" in reasons


def test_evaluate_probe_accepts_structural_route_dry_marker_and_usable_wet_signal() -> None:
    mod = load_module()
    wet_signal, reasons = mod.evaluate_probe(
        structural_route_present=True,
        captures={
            "dry_loudnorm_playback": _capture(marker=True, rms=-38.0, peak=-29.0),
            "wet_voice_playback": _capture(marker=True, rms=-42.0, peak=-30.0),
        },
        wet_min_rms_dbfs=-65.0,
        wet_min_peak_dbfs=-55.0,
    )

    assert wet_signal is True
    assert reasons == []


def test_evaluate_probe_requires_structural_route_and_dry_marker() -> None:
    mod = load_module()
    wet_signal, reasons = mod.evaluate_probe(
        structural_route_present=False,
        captures={
            "dry_loudnorm_playback": _capture(marker=False, rms=-120.0, peak=-120.0),
            "wet_voice_playback": _capture(marker=True, rms=-42.0, peak=-30.0),
        },
        wet_min_rms_dbfs=-65.0,
        wet_min_peak_dbfs=-55.0,
    )

    assert wet_signal is False
    assert "structural_route_missing" in reasons
    assert "dry_marker_missing" in reasons


def test_generate_tone_bytes_is_stereo_s16le() -> None:
    mod = load_module()
    raw = mod.generate_tone_bytes(
        rate=1000,
        tone_hz=100.0,
        tone_duration_s=0.1,
        lead_s=0.01,
        trail_s=0.02,
        amplitude=0.1,
    )

    assert len(raw) == int((0.01 + 0.1 + 0.02) * 1000) * 2 * 2


def test_build_capture_specs_includes_mk5_input_aux2_aux3() -> None:
    mod = load_module()
    args = mod.parse_args([])
    specs = {spec.name: spec for spec in mod.build_capture_specs(args)}

    spec = specs["mk5_input_aux2_aux3_raw"]
    assert args.mk5_input_target in spec.command
    assert spec.channels == 20
    assert spec.interesting_channels == (2, 3)


def test_channel_stats_reports_top_marker_channels() -> None:
    mod = load_module()
    rate = 1000
    frames = 250
    samples = np.zeros((frames, 4), dtype=np.int16)
    t = np.arange(frames, dtype=np.float64) / rate
    samples[:, 2] = (0.5 * np.sin(2.0 * np.pi * 100.0 * t) * 32767.0).astype(np.int16)

    stats = mod.channel_stats(
        samples.tobytes(),
        channels=4,
        interesting_channels=(2,),
        rate=rate,
        tone_hz=100.0,
        snr_threshold_db=12.0,
    )

    assert stats["channels"]["2"]["marker_detected"] is True
    assert stats["top_marker_channels"][0]["channel"] == 2
