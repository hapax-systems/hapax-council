from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "screwm-gpu-drift-cutover-preflight.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("screwm_gpu_drift_cutover_preflight", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_live_texture_parser_matches_launcher_and_autoexec_slots() -> None:
    module = _load_module()
    launcher_slots = module.parse_live_texture_slots(
        (REPO_ROOT / "scripts" / "darkplaces-v4l2-xvfb.sh").read_text(encoding="utf-8")
    )
    autoexec_slots = module.parse_live_texture_slots(
        (REPO_ROOT / "assets" / "quake" / "config" / "autoexec.cfg").read_text(encoding="utf-8")
    )

    launcher_signature = [
        (slot.slot_number, slot.texture_name, slot.final_output, slot.width, slot.height)
        for slot in launcher_slots
    ]
    autoexec_signature = [
        (slot.slot_number, slot.texture_name, slot.final_output, slot.width, slot.height)
        for slot in autoexec_slots
    ]
    assert launcher_signature == autoexec_signature
    assert len(launcher_signature) == 14
    assert launcher_signature[0] == (
        1,
        "progs/aoa_sphere.mdl_0",
        "/dev/shm/hapax-compositor/quake-live-yt.bgra",
        2048,
        1024,
    )
    assert launcher_signature[12] == (
        13,
        "speech_wave",
        "/dev/shm/hapax-compositor/quake-live-speech-wave.bgra",
        512,
        128,
    )
    assert launcher_signature[-1] == (
        14,
        "progs/aoa.mdl_0",
        "/dev/shm/hapax-compositor/quake-live-aoa-atlas.bgra",
        2048,
        2048,
    )


def test_manifest_derives_supported_gpu_drift_candidates() -> None:
    module = _load_module()
    manifest = module.build_manifest(REPO_ROOT)
    candidates = {entry["slot"]: entry for entry in manifest["candidates"]}

    assert manifest["version"] == "screwm-gpu-drift-cutover-preflight-v1"
    assert manifest["source"] == "scripts/darkplaces-v4l2-xvfb.sh"
    assert manifest["runtime_actions_performed"] is False
    assert len(candidates) == 13
    assert "speech-wave" not in candidates
    assert any(warning["slot"] == "speech-wave" for warning in manifest["warnings"])

    yt = candidates["yt"]
    assert yt["slot_spec"] == "yt:2048x1024:1.6:sphere-front:1820x1024:0c0b0d"
    assert yt["mount_id"] == "aoa-media-sphere"
    assert yt["producer_class"] == "live-media-youtube"
    assert yt["service"] == "hapax-quake-live-youtube.service"
    assert yt["producer_env_flag"] == "HAPAX_QUAKE_GPU_DRIFT"
    assert yt["raw_output"] == "/dev/shm/hapax-compositor/quake-live-yt.raw.bgra"
    assert yt["raw_sidecar"] == "/dev/shm/hapax-compositor/quake-live-yt.raw.json"
    assert yt["final_sidecar"] == "/dev/shm/hapax-compositor/quake-live-yt.json"

    camera = candidates["cam-brio-operator"]
    assert camera["service"] == "hapax-quake-live-camera@brio-operator.service"
    assert camera["producer_class"] == "live-media-camera"
    assert camera["slot_spec"] == "cam-brio-operator:1280x720"

    ticker = candidates["ticker-grounding"]
    assert ticker["service"] == "hapax-quake-live-ticker@grounding.service"
    assert ticker["producer_env_flag"] == "HAPAX_QUAKE_TICKER_GPU_DRIFT"

    ward = candidates["ward-atlas"]
    assert ward["service"] == "hapax-quake-live-ward-atlas.service"
    assert ward["slot_spec"] == "ward-atlas:2048x2304"

    reverie = candidates["reverie"]
    assert reverie["mount_id"] == "reverie-field"
    assert reverie["service"] == "hapax-quake-live-reverie.service"
    assert reverie["producer_env_flag"] == "HAPAX_QUAKE_REVERIE_GPU_DRIFT"
    assert reverie["slot_spec"] == "reverie:960x540"

    aoa = candidates["aoa-atlas"]
    assert aoa["mount_id"] == "aoa-fractal-face-atlas"
    assert aoa["producer_class"] == "live-aoa-face-atlas"
    assert aoa["service"] == "hapax-quake-live-aoa-atlas.service"
    assert aoa["producer_env_flag"] == "HAPAX_QUAKE_AOA_ATLAS_GPU_DRIFT"
    assert aoa["texture_name"] == "progs/aoa.mdl_0"
    assert aoa["slot_spec"] == "aoa-atlas:2048x2048:2.25"
    assert aoa["raw_output"] == "/dev/shm/hapax-compositor/quake-live-aoa-atlas.raw.bgra"
    assert aoa["final_sidecar"] == "/dev/shm/hapax-compositor/quake-live-aoa-atlas.json"

    assert "speech-wave" not in manifest["drift_slots_env"]
    assert "aoa-atlas:2048x2048:2.25" in manifest["drift_slots_env"]
    assert manifest["drift_slots_env"].split(",")[0] == (
        "yt:2048x1024:1.6:sphere-front:1820x1024:0c0b0d"
    )


def test_manifest_slot_filter_is_deterministic_and_warns_on_missing_slot() -> None:
    module = _load_module()
    manifest = module.build_manifest(REPO_ROOT, slots={"ward-atlas", "reverie", "missing"})

    assert [entry["slot"] for entry in manifest["candidates"]] == ["ward-atlas", "reverie"]
    assert manifest["drift_slots_env"] == "ward-atlas:2048x2304,reverie:960x540"
    assert {"slot": "missing", "reason": "requested_slot_not_declared"} in manifest["warnings"]


def test_manifest_matches_media_drift_service_slot_env() -> None:
    module = _load_module()
    manifest = module.build_manifest(REPO_ROOT)
    service = (REPO_ROOT / "systemd" / "units" / "hapax-screwm-media-drift.service").read_text(
        encoding="utf-8"
    )
    match = re.search(r"^Environment=HAPAX_SCREWM_DRIFT_SLOTS=(.+)$", service, re.MULTILINE)

    assert match is not None
    assert manifest["drift_slots_env"] == match.group(1)
