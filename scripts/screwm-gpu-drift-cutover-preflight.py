#!/usr/bin/env python3
"""Build a source-only GPU media-drift cutover manifest.

The manifest is derived from committed DarkPlaces live-texture declarations and
producer contracts. It does not inspect /dev/shm, set environment variables, or
restart services.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SHM_PREFIX = "/dev/shm/hapax-compositor/"
VERSION = "screwm-gpu-drift-cutover-preflight-v1"
LIVE_TEXTURE_RE = re.compile(
    r"(?:^|\s)\+?hapax_live_texture(?P<slot>\d*)_"
    r"(?P<key>enable|name|path|width|height)\s+(?P<value>\S+)"
)


@dataclass(frozen=True)
class LiveTextureSlot:
    slot_number: int
    enabled: bool
    texture_name: str
    final_output: str
    width: int
    height: int


@dataclass(frozen=True)
class ProducerSupport:
    producer_class: str
    service: str
    producer_env_flag: str


def _slot_number(raw: str) -> int:
    return int(raw) if raw else 1


def parse_live_texture_slots(text: str) -> list[LiveTextureSlot]:
    fields: dict[int, dict[str, str]] = {}
    for match in LIVE_TEXTURE_RE.finditer(text):
        slot = _slot_number(match.group("slot"))
        fields.setdefault(slot, {})[match.group("key")] = match.group("value")

    out: list[LiveTextureSlot] = []
    for slot, values in sorted(fields.items()):
        if values.get("enable", "1") != "1":
            continue
        if not {"name", "path", "width", "height"} <= values.keys():
            continue
        out.append(
            LiveTextureSlot(
                slot_number=slot,
                enabled=True,
                texture_name=values["name"],
                final_output=values["path"],
                width=int(values["width"]),
                height=int(values["height"]),
            )
        )
    return out


def slot_name_from_output(output: str) -> str:
    name = Path(output).name
    if not name.startswith("quake-live-") or not name.endswith(".bgra"):
        raise ValueError(f"unsupported live texture output path: {output}")
    return name.removeprefix("quake-live-").removesuffix(".bgra")


def raw_output_for(final_output: str) -> str:
    return str(Path(final_output).with_suffix(".raw.bgra"))


def raw_sidecar_for(raw_output: str) -> str:
    return str(Path(raw_output).with_suffix(".json"))


def final_sidecar_for(final_output: str) -> str:
    return str(Path(final_output).with_suffix(".json"))


def _source_aspect(mount: dict[str, Any] | None) -> float:
    if not mount:
        return 16.0 / 9.0
    source_aspect = mount.get("source_aspect")
    if (
        isinstance(source_aspect, list)
        and len(source_aspect) == 2
        and float(source_aspect[1] or 0) > 0
    ):
        return float(source_aspect[0]) / float(source_aspect[1])
    return 16.0 / 9.0


def sphere_front_raw_dimensions(
    width: int, height: int, mount: dict[str, Any] | None
) -> tuple[int, int]:
    ratio = 1.0
    if mount:
        try:
            ratio = float(mount.get("projection_front_height_ratio", 1.0))
        except (TypeError, ValueError):
            ratio = 1.0
    front_height = int(height * max(0.0, min(1.0, ratio)))
    media_aspect = _source_aspect(mount)
    frame_width = min(width, int(round(front_height * media_aspect)))
    frame_height = min(front_height, int(round(frame_width / media_aspect)))
    return frame_width - (frame_width % 2), frame_height


def drift_slot_spec(
    slot_name: str, live_slot: LiveTextureSlot, mount: dict[str, Any] | None
) -> str:
    projection = str(mount.get("projection", "")) if mount else ""
    intensity = 1.0
    if mount and "gpu_drift_intensity" in mount:
        try:
            intensity = float(mount["gpu_drift_intensity"])
        except (TypeError, ValueError):
            intensity = 1.0
    if slot_name == "yt" and projection == "sphere-front":
        raw_w, raw_h = sphere_front_raw_dimensions(live_slot.width, live_slot.height, mount)
        intensity_segment = f":{intensity:g}" if intensity != 1.0 else ""
        return (
            f"{slot_name}:{live_slot.width}x{live_slot.height}{intensity_segment}"
            f":sphere-front:{raw_w}x{raw_h}:0c0b0d"
        )
    spec = f"{slot_name}:{live_slot.width}x{live_slot.height}"
    if intensity != 1.0:
        spec = f"{spec}:{intensity:g}"
    return spec


def _load_mounts(repo_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    payload = json.loads((repo_root / "config" / "screwm-quake-media-mounts.json").read_text())
    by_output: dict[str, dict[str, Any]] = {}
    by_texture: dict[str, dict[str, Any]] = {}
    for mount in payload.get("mounts", []):
        if not isinstance(mount, dict):
            continue
        output = str(mount.get("producer_output", ""))
        texture = str(mount.get("texture", ""))
        if output:
            by_output[output] = mount
        if texture:
            by_texture[texture] = mount
    return by_output, by_texture


def producer_support_for(slot_name: str) -> ProducerSupport | None:
    if slot_name == "yt":
        return ProducerSupport(
            producer_class="live-media-youtube",
            service="hapax-quake-live-youtube.service",
            producer_env_flag="HAPAX_QUAKE_GPU_DRIFT",
        )
    if slot_name.startswith("cam-"):
        camera_id = slot_name.removeprefix("cam-")
        return ProducerSupport(
            producer_class="live-media-camera",
            service=f"hapax-quake-live-camera@{camera_id}.service",
            producer_env_flag="HAPAX_QUAKE_GPU_DRIFT",
        )
    if slot_name.startswith("ticker-"):
        ticker_id = slot_name.removeprefix("ticker-")
        return ProducerSupport(
            producer_class="live-ticker",
            service=f"hapax-quake-live-ticker@{ticker_id}.service",
            producer_env_flag="HAPAX_QUAKE_TICKER_GPU_DRIFT",
        )
    if slot_name == "ward-atlas":
        return ProducerSupport(
            producer_class="live-compositor-ward-atlas",
            service="hapax-quake-live-ward-atlas.service",
            producer_env_flag="HAPAX_QUAKE_WARD_ATLAS_GPU_DRIFT",
        )
    if slot_name == "reverie":
        return ProducerSupport(
            producer_class="live-reverie-substrate",
            service="hapax-quake-live-reverie.service",
            producer_env_flag="HAPAX_QUAKE_REVERIE_GPU_DRIFT",
        )
    if slot_name == "aoa-atlas":
        return ProducerSupport(
            producer_class="live-aoa-face-atlas",
            service="hapax-quake-live-aoa-atlas.service",
            producer_env_flag="HAPAX_QUAKE_AOA_ATLAS_GPU_DRIFT",
        )
    return None


def build_manifest(repo_root: Path = REPO_ROOT, slots: set[str] | None = None) -> dict[str, Any]:
    launcher = repo_root / "scripts" / "darkplaces-v4l2-xvfb.sh"
    texture_slots = parse_live_texture_slots(launcher.read_text())
    mounts_by_output, mounts_by_texture = _load_mounts(repo_root)

    candidates: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    requested = set(slots or set())
    seen_requested: set[str] = set()

    for live_slot in texture_slots:
        if not live_slot.final_output.startswith(SHM_PREFIX):
            continue
        if not live_slot.final_output.endswith(".bgra"):
            continue

        slot_name = slot_name_from_output(live_slot.final_output)
        if requested and slot_name not in requested:
            continue
        seen_requested.add(slot_name)

        support = producer_support_for(slot_name)
        mount = mounts_by_output.get(live_slot.final_output) or mounts_by_texture.get(
            live_slot.texture_name
        )
        if support is None:
            warnings.append(
                {
                    "slot": slot_name,
                    "texture_slot": live_slot.slot_number,
                    "texture_name": live_slot.texture_name,
                    "final_output": live_slot.final_output,
                    "reason": "producer_does_not_support_gpu_drift",
                }
            )
            continue

        raw_output = raw_output_for(live_slot.final_output)
        slot_spec = drift_slot_spec(slot_name, live_slot, mount)
        entry = {
            "slot": slot_name,
            "slot_spec": slot_spec,
            "texture_slot": live_slot.slot_number,
            "texture_name": live_slot.texture_name,
            "width": live_slot.width,
            "height": live_slot.height,
            "final_output": live_slot.final_output,
            "raw_output": raw_output,
            "raw_sidecar": raw_sidecar_for(raw_output),
            "final_sidecar": final_sidecar_for(live_slot.final_output),
            "producer_class": support.producer_class,
            "service": support.service,
            "producer_env_flag": support.producer_env_flag,
            "mount_id": str(mount.get("id", "")) if mount else "",
            "producer_kind": str(mount.get("producer_kind", "")) if mount else "",
            "projection": str(mount.get("projection", "")) if mount else "",
        }
        candidates.append(entry)

    for missing in sorted(requested - seen_requested):
        warnings.append({"slot": missing, "reason": "requested_slot_not_declared"})

    return {
        "version": VERSION,
        "source": str(launcher.relative_to(repo_root)),
        "drift_slots_env": ",".join(entry["slot_spec"] for entry in candidates),
        "producer_env_value": "1",
        "candidates": candidates,
        "warnings": warnings,
        "runtime_actions_performed": False,
    }


def _parse_slots(values: list[str]) -> set[str]:
    slots: set[str] = set()
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                slots.add(part)
    return slots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--slot",
        action="append",
        default=[],
        help="Limit output to a slot name; may be repeated or comma-separated.",
    )
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args()

    manifest = build_manifest(args.repo_root.resolve(), slots=_parse_slots(args.slot))
    if args.compact:
        print(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
