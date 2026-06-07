from __future__ import annotations

import runpy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module() -> dict:
    return runpy.run_path(str(REPO_ROOT / "scripts" / "quake_media_drift.py"), run_name="__test__")


def _write_state(game_data: Path) -> None:
    values = {
        "effect-drift-source.txt": "slotdrift",
        "effect-drift-real-source.txt": "1.0000",
        "effect-drift-active-ratio.txt": "0.8200",
        "effect-drift-active-slot-ratio.txt": "0.8000",
        "effect-drift-active-effect-ratio.txt": "0.7300",
        "effect-drift-fast-ratio.txt": "0.6800",
        "effect-drift-slow-ratio.txt": "0.3200",
        "effect-drift-kind-variance.txt": "0.7200",
        "effect-drift-max-delta.txt": "1.0000",
        "effect-drift-region-count.txt": "0.7500",
        "effect-drift-tonal.txt": "0.7000",
        "effect-drift-atmospheric.txt": "0.4000",
        "effect-drift-temporal.txt": "0.8000",
        "effect-drift-texture.txt": "0.9000",
        "effect-drift-edge.txt": "0.8000",
        "effect-drift-compositing.txt": "0.8500",
        "effect-drift-mode-tonal.txt": "0.5000",
        "effect-drift-mode-atmospheric.txt": "0.7000",
        "effect-drift-mode-temporal.txt": "0.6500",
        "effect-drift-mode-texture.txt": "0.9000",
        "effect-drift-mode-edge.txt": "0.8000",
        "effect-drift-mode-compositing.txt": "0.6000",
        "visual-chain-noise.txt": "0.7000",
        "visual-chain-drift.txt": "0.9500",
        "visual-chain-color.txt": "1.0000",
        "visual-chain-feedback.txt": "0.8500",
        "visual-chain-aperture.txt": "0.3000",
        "visual-chain-param-pressure.txt": "1.0000",
    }
    game_data.mkdir(parents=True, exist_ok=True)
    for filename, value in values.items():
        (game_data / filename).write_text(value + "\n", encoding="utf-8")


def test_media_drift_changes_receiver_texture_bytes(tmp_path: Path) -> None:
    module = _load_module()
    game_data = tmp_path / "data"
    _write_state(game_data)
    renderer = module["MediaDriftRenderer"](game_data=game_data)
    width = 64
    height = 32
    frame = bytearray(bytes((20, 40, 80, 255)) * (width * height))
    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            frame[idx] = (x * 3) % 256
            frame[idx + 1] = (y * 7) % 256
            frame[idx + 2] = ((x + y) * 5) % 256

    drifted = renderer.apply(
        bytes(frame), width=width, height=height, receiver="oarb-youtube", frame=1, now=1000.0
    )

    assert drifted != bytes(frame)
    assert len(drifted) == len(frame)
    assert drifted[3::4] == bytes([255]) * (width * height)


def test_media_drift_accumulates_receiver_history(tmp_path: Path) -> None:
    module = _load_module()
    game_data = tmp_path / "data"
    _write_state(game_data)
    renderer = module["MediaDriftRenderer"](game_data=game_data)
    width = 48
    height = 24
    frame = bytes((10, 40, 120, 255)) * (width * height)

    first = renderer.apply(
        frame, width=width, height=height, receiver="reverie:test", frame=1, now=4.0
    )
    second = renderer.apply(
        frame, width=width, height=height, receiver="reverie:test", frame=2, now=4.3
    )

    assert first != frame
    assert second != first


def test_reverie_receiver_tonemap_rejects_washed_out_particle_field(tmp_path: Path) -> None:
    module = _load_module()
    game_data = tmp_path / "data"
    _write_state(game_data)
    renderer = module["MediaDriftRenderer"](game_data=game_data)
    width = 48
    height = 24
    frame = bytearray(bytes((220, 232, 224, 255)) * (width * height))
    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            frame[idx] = 214 + ((x * 3 + y) % 22)
            frame[idx + 1] = 226 + ((x + y * 2) % 18)
            frame[idx + 2] = 214 + ((x * 5 + y * 7) % 26)

    drifted = renderer.apply(
        bytes(frame), width=width, height=height, receiver="reverie:w05", frame=1, now=10.0
    )

    source_rgb = [value for idx, value in enumerate(frame) if idx % 4 != 3]
    drifted_rgb = [value for idx, value in enumerate(drifted) if idx % 4 != 3]
    assert sum(drifted_rgb) / len(drifted_rgb) < sum(source_rgb) / len(source_rgb) * 0.80
    assert max(drifted_rgb) - min(drifted_rgb) > max(source_rgb) - min(source_rgb)


def test_media_drift_uses_lightweight_camera_tier(tmp_path: Path) -> None:
    module = _load_module()
    game_data = tmp_path / "data"
    _write_state(game_data)
    renderer = module["MediaDriftRenderer"](game_data=game_data)
    width = 48
    height = 24
    frame = bytes((10, 40, 120, 255)) * (width * height)

    first = renderer.apply(
        frame, width=width, height=height, receiver="camera:test", frame=1, now=4.0
    )
    second = renderer.apply(
        frame, width=width, height=height, receiver="camera:test", frame=2, now=4.3
    )

    assert first != frame
    assert second != frame
    assert "camera:test" not in renderer._history


def test_media_drift_treats_direct_ir_brio_slots_as_camera_receivers(tmp_path: Path) -> None:
    module = _load_module()
    game_data = tmp_path / "data"
    _write_state(game_data)
    renderer = module["MediaDriftRenderer"](game_data=game_data)
    width = 48
    height = 24
    frame = bytes((10, 40, 120, 255)) * (width * height)

    first = renderer.apply(
        frame, width=width, height=height, receiver="ir-brio-operator", frame=1, now=4.0
    )
    second = renderer.apply(
        frame, width=width, height=height, receiver="ir-brio-operator", frame=2, now=4.3
    )

    assert module["_receiver_is_camera"]("ir-brio-operator")
    assert module["_receiver_gain"]("ir-brio-operator") == module["_receiver_gain"]("camera:test")
    assert first != frame
    assert second != frame
    assert "ir-brio-operator" not in renderer._history


def test_media_drift_keeps_ir_ward_view_labels_on_ward_tier() -> None:
    module = _load_module()

    assert not module["_receiver_is_camera"]("brio-operator-ir-ward")
    assert module["_receiver_gain"]("brio-operator-ir-ward") == module["_receiver_gain"](
        "ward-atlas"
    )


def test_media_drift_uses_slotdrift_variance_scalars(tmp_path: Path) -> None:
    module = _load_module()
    game_data = tmp_path / "data"
    _write_state(game_data)
    renderer = module["MediaDriftRenderer"](game_data=game_data)
    width = 64
    height = 32
    frame = bytes((22, 48, 96, 255)) * (width * height)

    active = renderer.apply(
        frame, width=width, height=height, receiver="oarb-youtube", frame=5, now=30.0
    )

    for name in (
        "effect-drift-active-slot-ratio.txt",
        "effect-drift-active-effect-ratio.txt",
        "effect-drift-fast-ratio.txt",
        "effect-drift-slow-ratio.txt",
        "effect-drift-kind-variance.txt",
        "effect-drift-mode-texture.txt",
    ):
        (game_data / name).write_text("0.0000\n", encoding="utf-8")
    renderer = module["MediaDriftRenderer"](game_data=game_data)
    muted = renderer.apply(
        frame, width=width, height=height, receiver="oarb-youtube", frame=5, now=30.0
    )

    assert active != muted


def test_media_drift_disabled_is_identity(tmp_path: Path) -> None:
    module = _load_module()
    game_data = tmp_path / "data"
    _write_state(game_data)
    renderer = module["MediaDriftRenderer"](game_data=game_data, enabled=False)
    frame = bytes((1, 2, 3, 255)) * 16

    assert (
        renderer.apply(frame, width=4, height=4, receiver="ticker:test", frame=1, now=1.0) == frame
    )


def test_aces_tonemap_is_filmic_and_not_blown() -> None:
    import numpy as np

    module = _load_module()
    aces = module["_aces_tonemap"]
    # aces(0) == 0; input 255 (1.0) -> filmic shoulder ~0.80*255
    assert float(aces(np.array([0.0]))[0]) == 0.0
    mid = float(aces(np.array([255.0]))[0])
    assert 195.0 < mid < 215.0
    # 3x overdrive -> rolls off smoothly, NEVER flat-white-clips
    big = float(aces(np.array([255.0 * 3.0]))[0])
    assert big < 250.0
    # monotonic increasing (no inversion)
    xs = np.array([0.0, 64.0, 128.0, 255.0, 512.0, 1024.0])
    ys = aces(xs)
    assert bool(np.all(np.diff(ys) > 0))
    # bounded [0,255]
    assert float(ys.min()) >= 0.0 and float(ys.max()) <= 255.0


def test_media_drift_aces_constants_match_wgsl_and_python() -> None:
    """CPU/GPU parity guard: media_drift.wgsl aces_tonemap and quake_media_drift._aces_tonemap
    must carry the IDENTICAL Narkowicz ACES constants, or the GPU + CPU drift paths diverge."""
    import re

    wgsl = (REPO_ROOT / "agents" / "shaders" / "nodes" / "media_drift.wgsl").read_text()
    for const in ("2.51", "0.03", "2.43", "0.59", "0.14"):
        assert const in wgsl, f"wgsl aces_tonemap missing Narkowicz constant {const}"
    src = (REPO_ROOT / "scripts" / "quake_media_drift.py").read_text()
    m = re.search(r"a, b, c, d, e = ([\d., ]+)", src)
    assert m is not None, "python _aces_tonemap constants not found"
    vals = [float(x) for x in m.group(1).split(",")]
    assert vals == [2.51, 0.03, 2.43, 0.59, 0.14], f"CPU/GPU ACES constant divergence: {vals}"
