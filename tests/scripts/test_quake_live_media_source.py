from __future__ import annotations

import json
import os
import runpy
import subprocess
import time
from argparse import Namespace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module() -> dict:
    return runpy.run_path(
        str(REPO_ROOT / "scripts" / "quake-live-media-source.py"), run_name="__test__"
    )


def test_missing_camera_device_uses_explicit_offline_texture_fallback() -> None:
    module = _load_module()
    args = Namespace(
        source="camera",
        camera_role="c920-overhead",
        camera_device="/dev/definitely-missing-hapax-camera",
        camera_format="mjpeg",
        camera_size="1280x720",
        camera_fps=30,
        fps=15,
        width=1280,
        height=720,
        projection="flat",
        mask="none",
        mask_background="0c0b0d",
        camera_visibility_profile="auto",
        camera_reserved_for_ir=False,
        restart_delay=2.0,
        fallback_reason="",
    )

    command = module["_ffmpeg_command"](args, 1280, 720)
    command_text = " ".join(command)

    assert "-f lavfi" in command_text
    assert "C920 OVERHEAD OFFLINE" in command_text
    assert "WAITING FOR LIVE CAMERA" in command_text
    assert args.fallback_reason.startswith("camera_device_missing:")


def test_brio_rgb_reserved_for_ir_publishes_explicit_fresh_placeholder(tmp_path: Path) -> None:
    module = _load_module()
    device = tmp_path / "video0"
    device.write_bytes(b"")
    args = Namespace(
        source="camera",
        camera_role="brio-room",
        camera_device=str(device),
        camera_format="mjpeg",
        camera_size="1280x720",
        camera_fps=10,
        camera_reserved_for_ir=True,
        fps=5,
        width=1280,
        height=720,
        projection="flat",
        mask="none",
        mask_background="0c0b0d",
        camera_visibility_profile="auto",
        fallback_reason="",
    )

    command = module["_ffmpeg_command"](args, 1280, 720)
    command_text = " ".join(command)

    assert "-f lavfi" in command_text
    assert "BRIO ROOM RESERVED" in command_text
    assert "LOCAL RGB OFF; IR WARD OWNS BRIO" in command_text
    assert str(device) not in command_text
    assert args.fallback_reason == "camera_reserved_for_ir:same_physical_brio_ir_ward"


def test_media_sidecar_includes_shm_rgba_reader_aliases(tmp_path: Path) -> None:
    module = _load_module()
    meta = tmp_path / "quake-live-ir-brio-operator.raw.json"
    args = Namespace(
        source="camera",
        url="",
        camera_role="brio-operator-ir",
        camera_device="/dev/video-ir",
        width=340,
        height=340,
        source_frame_width=340,
        source_frame_height=340,
        fps=6,
        mask="none",
        mask_background="0c0b0d",
        projection="flat",
        camera_visibility_profile="brio-ir-low-light",
        gpu_drift=True,
        gpu_drift_raw_output=tmp_path / "quake-live-ir-brio-operator.raw.bgra",
        output=tmp_path / "quake-live-ir-brio-operator.bgra",
        gpu_projection_kind="",
        youtube_gpu_decode=False,
        youtube_gpu_decode_active=False,
        youtube_gpu_decode_runtime_disabled=False,
        drift="off",
        drift_intensity=1.0,
        drift_input_hash="abc",
        drift_output_hash="",
        drift_changed=False,
        fallback_reason="",
    )

    module["_write_meta"](meta, args, frames=42)
    payload = json.loads(meta.read_text(encoding="utf-8"))

    assert payload["w"] == 340
    assert payload["h"] == 340
    assert payload["stride"] == 1360
    assert payload["frame_id"] == 42
    assert payload["width"] == 340
    assert payload["height"] == 340
    assert payload["frames"] == 42
    assert payload["camera_visibility_profile"] == "brio-ir-low-light"
    assert payload["resolved_camera_visibility_profile"] == "brio-ir-low-light"


def test_frame_read_timeout_returns_none_for_silent_pipe() -> None:
    module = _load_module()
    read_fd, write_fd = os.pipe()
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as pipe:
            started = time.monotonic()
            assert module["_read_exact_with_timeout"](pipe, 4, 0.02) is None
            assert time.monotonic() - started < 1.0
    finally:
        os.close(write_fd)


def test_recovered_camera_loop_first_frame_refreshes_metadata() -> None:
    module = _load_module()

    assert module["_metadata_write_due"](frames=84, loop_frames=1, fps=6)
    assert not module["_metadata_write_due"](frames=84, loop_frames=2, fps=6)


def test_camera_timeout_after_success_schedules_visible_fallback(tmp_path: Path) -> None:
    module = _load_module()
    device = tmp_path / "video-ir"
    device.write_bytes(b"")
    args = Namespace(
        source="camera",
        camera_role="brio-synths-ir",
        camera_device=str(device),
        camera_format="gray",
        camera_size="340x340",
        camera_fps=10,
        fps=6,
        width=340,
        height=340,
        projection="flat",
        mask="none",
        mask_background="0c0b0d",
        camera_visibility_profile="brio-ir-low-light",
        camera_reserved_for_ir=False,
        camera_forced_fallback_reason="",
        restart_delay=2.0,
        fallback_reason="",
    )

    module["_mark_camera_loop_failure"](args, "camera_frame_timeout:8.0s", stop=False)
    command = module["_ffmpeg_command"](args, 340, 340)
    command_text = " ".join(command)

    assert args.fallback_reason == "camera_frame_timeout:8.0s"
    assert args.camera_forced_fallback_reason == ""
    assert "-f lavfi" in command_text
    assert "BRIO SYNTHS IR OFFLINE" in command_text
    assert "WAITING FOR LIVE CAMERA" in command_text
    assert str(device) not in command_text


def test_sphere_front_projection_uses_deterministic_oarb_sphere_fill() -> None:
    module = _load_module()
    args = Namespace(
        projection="sphere-front",
        width=2048,
        height=1024,
        sphere_front_aspect=16 / 9,
    )

    assert module["_decode_dimensions"](args) == (1820, 1024)


def test_sphere_front_projection_centers_and_unmirrors_media_on_model_seam() -> None:
    module = _load_module()
    columns = [
        bytes((10, 0, 0, 255)),
        bytes((20, 0, 0, 255)),
        bytes((30, 0, 0, 255)),
        bytes((40, 0, 0, 255)),
    ]
    data = b"".join(columns)

    projected = module["_compose_sphere_front"](
        data,
        frame_width=4,
        frame_height=1,
        out_width=8,
        out_height=1,
        background="000000",
    )
    out_columns = [projected[idx : idx + 4] for idx in range(0, len(projected), 4)]

    assert out_columns[0] == columns[2]
    assert out_columns[1] == columns[3]
    assert out_columns[6] == columns[0]
    assert out_columns[7] == columns[1]


def test_sphere_front_ffmpeg_filter_uses_hflip_before_bgra() -> None:
    module = _load_module()
    args = Namespace(
        source="test",
        fps=15,
        width=2048,
        height=1024,
        projection="sphere-front",
        mask="none",
        mask_background="0c0b0d",
        fallback_reason="",
    )

    command = module["_ffmpeg_command"](args, 1820, 1024)
    command_text = " ".join(command)

    assert "crop=1820:1024,hflip,format=bgra" in command_text
    assert "-threads 1" in command_text
    assert "-filter_threads 1" in command_text


def test_gpu_owned_sphere_front_projection_omits_cpu_hflip() -> None:
    module = _load_module()
    args = Namespace(
        source="test",
        fps=15,
        width=2048,
        height=1024,
        projection="sphere-front",
        mask="none",
        mask_background="0c0b0d",
        fallback_reason="",
        gpu_projection_kind="sphere-front",
    )

    command = module["_ffmpeg_command"](args, 1820, 1024)
    command_text = " ".join(command)

    assert "crop=1820:1024,format=bgra" in command_text
    assert "hflip" not in command_text


def test_youtube_gpu_decode_uses_cuda_scale_when_projection_is_gpu_owned() -> None:
    module = _load_module()
    module["_ffmpeg_command"].__globals__["_run_checked"] = lambda _args: (
        "https://media.invalid/1024.mp4\n"
    )
    args = Namespace(
        source="youtube",
        url="https://www.youtube.com/watch?v=abc123def45",
        configured_url="https://www.youtube.com/watch?v=abc123def45",
        url_file=None,
        youtube_fallback="canary",
        youtube_player_attr_files=(),
        youtube_gpu_decode=True,
        fps=3,
        width=2048,
        height=1024,
        projection="sphere-front",
        mask="none",
        mask_background="0c0b0d",
        fallback_reason="",
        gpu_projection_kind="sphere-front",
    )

    command = module["_ffmpeg_command"](args, 1820, 1024)
    command_text = " ".join(command)

    assert "-hwaccel cuda" in command_text
    assert "-hwaccel_output_format cuda" in command_text
    assert "scale_cuda=w=1820:h=1024:interp_algo=lanczos:format=yuv420p" in command_text
    assert "hwdownload,format=yuv420p,format=bgra" in command_text
    assert "hflip" not in command_text
    assert args.youtube_gpu_decode_active is True


def test_youtube_private_url_falls_back_to_canary_stream() -> None:
    module = _load_module()
    calls: list[list[str]] = []

    def fake_run_checked(args: list[str]) -> str:
        calls.append(args)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, args, output="", stderr="Private video")
        return "https://media.invalid/canary.mp4\n"

    module["_ffmpeg_command"].__globals__["_run_checked"] = fake_run_checked
    args = Namespace(
        source="youtube",
        url="https://www.youtube.com/watch?v=private12345",
        configured_url="https://www.youtube.com/watch?v=private12345",
        url_file=None,
        youtube_fallback="canary",
        youtube_player_attr_files=(),
        youtube_gpu_decode=False,
        youtube_gpu_decode_active=False,
        youtube_gpu_decode_runtime_disabled=False,
        fps=3,
        width=2048,
        height=1024,
        projection="sphere-front",
        sphere_front_aspect=16 / 9,
        mask="none",
        mask_background="0c0b0d",
        freshness_overlay="none",
        fallback_reason="",
        gpu_projection_kind="sphere-front",
    )

    command = module["_ffmpeg_command"](args, 1820, 1024)

    assert calls[0][-1] == "https://www.youtube.com/watch?v=private12345"
    assert calls[1][-1] == module["DEFAULT_YOUTUBE_URL"]
    assert "https://media.invalid/canary.mp4" in command
    assert args.resolved_url == module["DEFAULT_YOUTUBE_URL"]
    assert args.url_source == "fallback-canary"
    assert args.fallback_reason.startswith("youtube_url_resolve_failed:canary:")


def test_exact_size_camera_filter_skips_scale_and_pad(tmp_path: Path) -> None:
    module = _load_module()
    device = tmp_path / "video0"
    device.write_bytes(b"")
    args = Namespace(
        source="camera",
        camera_role="brio-room",
        camera_device=str(device),
        camera_format="mjpeg",
        camera_size="1920x1080",
        camera_fps=15,
        fps=10,
        width=1920,
        height=1080,
        projection="flat",
        mask="none",
        mask_background="0c0b0d",
        camera_visibility_profile="auto",
        fallback_reason="",
    )

    command = module["_ffmpeg_command"](args, 1920, 1080)
    command_text = " ".join(command)

    assert "scale=" not in command_text
    assert "pad=" not in command_text
    assert "format=bgra" in command_text


def test_low_light_brio_ir_roles_use_histeq_before_bgra(tmp_path: Path) -> None:
    module = _load_module()
    device = tmp_path / "video-ir"
    device.write_bytes(b"")

    for role in ("brio-room-ir", "brio-synths-ir"):
        args = Namespace(
            source="camera",
            camera_role=role,
            camera_device=str(device),
            camera_format="gray",
            camera_size="340x340",
            camera_fps=10,
            fps=6,
            width=340,
            height=340,
            projection="flat",
            mask="none",
            mask_background="0c0b0d",
            camera_visibility_profile="auto",
            fallback_reason="",
        )

        command = module["_ffmpeg_command"](args, 340, 340)
        vf = command[command.index("-vf") + 1]

        assert "scale=" not in vf
        assert "pad=" not in vf
        assert "histeq=strength=0.30:intensity=0.20:antibanding=weak" in vf
        assert vf.index("histeq=") < vf.index("format=bgra")
        assert args.resolved_camera_visibility_profile == "brio-ir-low-light"


def test_operator_ir_role_keeps_unmodified_visibility_profile(tmp_path: Path) -> None:
    module = _load_module()
    device = tmp_path / "video-ir"
    device.write_bytes(b"")
    args = Namespace(
        source="camera",
        camera_role="brio-operator-ir",
        camera_device=str(device),
        camera_format="gray",
        camera_size="340x340",
        camera_fps=10,
        fps=6,
        width=340,
        height=340,
        projection="flat",
        mask="none",
        mask_background="0c0b0d",
        camera_visibility_profile="auto",
        fallback_reason="",
    )

    command = module["_ffmpeg_command"](args, 340, 340)
    vf = command[command.index("-vf") + 1]

    assert "histeq=" not in vf
    assert vf == "fps=6,format=bgra"
    assert args.resolved_camera_visibility_profile == "none"


def test_brio_ir_env_files_declare_visibility_profiles() -> None:
    expected = {
        "brio-operator-ir.env": "HAPAX_QUAKE_CAMERA_VISIBILITY_PROFILE=none",
        "brio-room-ir.env": "HAPAX_QUAKE_CAMERA_VISIBILITY_PROFILE=brio-ir-low-light",
        "brio-synths-ir.env": "HAPAX_QUAKE_CAMERA_VISIBILITY_PROFILE=brio-ir-low-light",
    }
    for filename, line in expected.items():
        text = (REPO_ROOT / "config" / "quake-live-cameras" / filename).read_text()
        assert line in text


def test_brio_ir_camera_roles_default_to_greyscale_endpoints() -> None:
    module = _load_module()

    expected = {
        "brio-operator-ir": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index2",
        "brio-room-ir": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_43B0576A-video-index2",
        "brio-synths-ir": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_9726C031-video-index2",
    }
    for role, device in expected.items():
        args = module["parse_args"](["--source", "camera", "--camera-role", role])

        assert args.camera_device == device
        assert args.camera_format == "gray"
        assert args.camera_size == "340x340"
        assert args.camera_fps == 10
        assert args.camera_reserved_for_ir is False


def test_youtube_url_file_accepts_video_id(tmp_path: Path) -> None:
    module = _load_module()
    url_file = tmp_path / "youtube-video-id.txt"
    url_file.write_text("abc123def45\n", encoding="utf-8")
    args = Namespace(
        url="https://example.invalid/configured",
        configured_url="https://example.invalid/configured",
        url_file=url_file,
    )

    assert module["_resolve_youtube_page_url"](args) == (
        "https://www.youtube.com/watch?v=abc123def45"
    )
    assert args.url_source == f"file:{url_file}"


def test_youtube_url_file_accepts_watch_url(tmp_path: Path) -> None:
    module = _load_module()
    url_file = tmp_path / "youtube-url.txt"
    url_file.write_text("https://www.youtube.com/watch?v=xyz987xyz98\n", encoding="utf-8")
    args = Namespace(
        url="https://example.invalid/configured",
        configured_url="https://example.invalid/configured",
        url_file=url_file,
    )

    assert module["_resolve_youtube_page_url"](args) == (
        "https://www.youtube.com/watch?v=xyz987xyz98"
    )


def test_empty_youtube_url_file_falls_back_to_configured_url(tmp_path: Path) -> None:
    module = _load_module()
    url_file = tmp_path / "youtube-video-id.txt"
    url_file.write_text("\n", encoding="utf-8")
    args = Namespace(
        url="https://example.invalid/configured",
        configured_url="https://example.invalid/configured",
        url_file=url_file,
        youtube_fallback="canary",
    )

    assert module["_resolve_youtube_page_url"](args) == "https://example.invalid/configured"
    assert args.url_source == "configured"


def test_empty_youtube_url_file_prefers_existing_youtube_player_attribution(
    tmp_path: Path,
) -> None:
    module = _load_module()
    url_file = tmp_path / "youtube-video-id.txt"
    url_file.write_text("\n", encoding="utf-8")
    attr_file = tmp_path / "yt-attribution-0.txt"
    attr_file.write_text(
        "A title\nA channel\nhttps://www.youtube.com/watch?v=live1234567\n",
        encoding="utf-8",
    )
    args = Namespace(
        url="https://example.invalid/configured",
        configured_url="https://example.invalid/configured",
        url_file=url_file,
        youtube_fallback="canary",
        youtube_player_attr_files=(attr_file,),
    )

    assert module["_resolve_youtube_page_url"](args) == (
        "https://www.youtube.com/watch?v=live1234567"
    )
    assert args.url_source == f"youtube-player:{attr_file}"


def test_empty_youtube_url_file_can_force_offline_fallback(tmp_path: Path) -> None:
    module = _load_module()
    url_file = tmp_path / "youtube-video-id.txt"
    url_file.write_text("\n", encoding="utf-8")
    args = Namespace(
        url=module["DEFAULT_YOUTUBE_URL"],
        configured_url=module["DEFAULT_YOUTUBE_URL"],
        url_file=url_file,
        youtube_fallback="offline",
    )

    assert module["_resolve_youtube_page_url"](args) == ""
    assert args.url_source == "unbound"


def test_unbound_youtube_uses_explicit_offline_texture_fallback(tmp_path: Path) -> None:
    module = _load_module()
    url_file = tmp_path / "youtube-video-id.txt"
    url_file.write_text("\n", encoding="utf-8")
    args = Namespace(
        source="youtube",
        url=module["DEFAULT_YOUTUBE_URL"],
        configured_url=module["DEFAULT_YOUTUBE_URL"],
        url_file=url_file,
        youtube_fallback="offline",
        fps=15,
        width=2048,
        height=1024,
        mask_background="0c0b0d",
        restart_delay=2.0,
        fallback_reason="",
        projection="sphere-front",
    )

    command = module["_ffmpeg_command"](args, 1820, 1024)
    command_text = " ".join(command)

    assert "-f lavfi" in command_text
    assert "drawgrid" not in command_text
    assert "drawtext" not in command_text
    assert "r=1,format=bgra" in command_text
    assert "-t 10.0" in command_text
    assert args.fallback_reason == "youtube_source_unbound"


def test_freshness_overlay_changes_texture_bytes() -> None:
    module = _load_module()
    data = bytes((0, 0, 0, 255)) * (64 * 32)

    frame_a = module["_apply_freshness_overlay"](data, 64, 32, "seam-pulse", 1)
    frame_b = module["_apply_freshness_overlay"](data, 64, 32, "seam-pulse", 20)

    assert frame_a != data
    assert frame_b != frame_a


def test_metadata_records_oarb_sphere_fill(tmp_path: Path) -> None:
    module = _load_module()
    args = Namespace(
        source="youtube",
        url="https://example.invalid/video",
        configured_url="https://example.invalid/video",
        resolved_url="https://example.invalid/resolved",
        url_source="unit-test",
        url_file=tmp_path / "youtube-video-id.txt",
        camera_role="",
        camera_device="",
        fps=15,
        width=2048,
        height=1024,
        source_frame_width=1820,
        source_frame_height=1024,
        projection="sphere-front",
        mask="none",
        mask_background="0c0b0d",
        freshness_overlay="seam-pulse",
        gpu_projection_kind="",
        fallback_reason="",
    )
    meta = tmp_path / "meta.json"

    module["_write_meta"](meta, args, 7)
    payload = json.loads(meta.read_text(encoding="utf-8"))

    assert payload["width"] == 2048
    assert payload["height"] == 1024
    assert payload["source_frame_width"] == 1820
    assert payload["source_frame_height"] == 1024
    assert payload["projection_front_height_ratio"] == 1.0
    assert payload["url"] == "https://example.invalid/resolved"
    assert payload["configured_url"] == "https://example.invalid/video"
    assert payload["url_source"] == "unit-test"
    assert payload["freshness_overlay"] == "seam-pulse"
    assert payload["gpu_projection"] is False
    assert payload["gpu_projection_kind"] == ""


def test_gpu_drift_metadata_uses_raw_sidecar_and_final_output_owner(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "quake-live-yt.bgra"
    raw_output, raw_meta = module["_gpu_drift_paths"](output)
    args = Namespace(
        source="test",
        url="",
        configured_url="",
        camera_role="",
        camera_device="",
        output=output,
        meta=tmp_path / "quake-live-yt.json",
        fps=10,
        width=64,
        height=32,
        source_frame_width=64,
        source_frame_height=32,
        projection="flat",
        mask="none",
        mask_background="0c0b0d",
        freshness_overlay="none",
        drift="on",
        drift_receiver="media:test",
        drift_game_data=tmp_path / "data",
        drift_intensity=1.0,
        drift_input_hash="abc123",
        drift_output_hash="",
        drift_changed=False,
        fallback_reason="",
        gpu_drift=True,
        gpu_drift_raw_output=raw_output,
        gpu_projection_kind="",
    )

    module["_write_meta"](raw_meta, args, 3)
    payload = json.loads(raw_meta.read_text(encoding="utf-8"))

    assert raw_output == tmp_path / "quake-live-yt.raw.bgra"
    assert raw_meta == tmp_path / "quake-live-yt.raw.json"
    assert payload["gpu_drift"] is True
    assert payload["gpu_drift_raw_output"] == str(raw_output)
    assert payload["gpu_drift_final_output"] == str(output)
    assert payload["gpu_drift_output_owner"] == "screwm_media_drift"
    assert payload["drift_enabled"] is False
    assert payload["drift_input_hash"] == "abc123"
    assert payload["drift_output_hash"] == ""
    assert payload["gpu_projection"] is False


def test_gpu_projection_metadata_marks_screwm_media_drift_as_projection_owner(
    tmp_path: Path,
) -> None:
    module = _load_module()
    output = tmp_path / "quake-live-yt.bgra"
    raw_output, raw_meta = module["_gpu_drift_paths"](output)
    args = Namespace(
        source="youtube",
        url="",
        configured_url="",
        resolved_url="",
        url_source="unit-test",
        url_file=tmp_path / "youtube-video-id.txt",
        camera_role="",
        camera_device="",
        output=output,
        meta=tmp_path / "quake-live-yt.json",
        fps=3,
        width=2048,
        height=1024,
        source_frame_width=1820,
        source_frame_height=1024,
        projection="sphere-front",
        mask="none",
        mask_background="0c0b0d",
        freshness_overlay="none",
        drift="on",
        drift_receiver="oarb-youtube",
        drift_game_data=tmp_path / "data",
        drift_intensity=1.0,
        drift_input_hash="raw-hash",
        drift_output_hash="",
        drift_changed=False,
        fallback_reason="",
        gpu_drift=True,
        gpu_drift_raw_output=raw_output,
        gpu_projection_kind="sphere-front",
    )

    module["_write_meta"](raw_meta, args, 1)
    payload = json.loads(raw_meta.read_text(encoding="utf-8"))

    assert payload["width"] == 2048
    assert payload["height"] == 1024
    assert payload["source_frame_width"] == 1820
    assert payload["source_frame_height"] == 1024
    assert payload["gpu_projection"] is True
    assert payload["gpu_projection_kind"] == "sphere-front"
    assert payload["gpu_projection_output_owner"] == "screwm_media_drift"
    assert payload["gpu_drift_raw_output"] == str(raw_output)
