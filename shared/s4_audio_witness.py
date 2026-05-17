"""S-4 USB audio presence witness — dynamic-audio-env DA-7.

Checks whether the Torso S-4 USB audio device is enumerated in PipeWire
and publishes the result to the FX device witness at
``/dev/shm/hapax-audio/fx-device-witness.json``.

Called by the audio router's tick loop and by the voice-path dry-bypass
probe. Pure function: reads PipeWire state, writes JSON, no side effects.

The S-4 audio path is considered available when:
1. A PipeWire sink matching the S-4 USB device name exists
2. The ``hapax-tts-s4-send`` loopback node is active (not suspended with
   no downstream)

When either condition fails, ``s4_audio`` is False and the voice path
router falls through to the dry bypass (voice-fx chain).
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

FX_DEVICE_WITNESS_PATH = Path("/dev/shm/hapax-audio/fx-device-witness.json")
_S4_DEVICE_PATTERNS = ("Torso_Electronics_S-4", "Torso_Elektron", "usb-Torso")


def is_s4_audio_present() -> bool:
    """Return True if the S-4 USB audio device is reachable in PipeWire."""
    try:
        result = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        for pattern in _S4_DEVICE_PATTERNS:
            if pattern in result.stdout:
                return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        log.debug("pactl probe failed", exc_info=True)
    return False


def update_fx_device_witness(
    *,
    s4_audio: bool | None = None,
    s4_midi: bool | None = None,
    evil_pet_midi: bool = False,
    evil_pet_sd_pack: bool = False,
    evil_pet_firmware_verified: bool = False,
    l12_route: bool = False,
) -> None:
    """Atomically update the FX device witness JSON.

    Merges provided fields into the existing witness (if any) so
    multiple callers can independently update their own fields without
    clobbering each other.
    """
    existing: dict = {}
    try:
        if FX_DEVICE_WITNESS_PATH.exists():
            existing = json.loads(FX_DEVICE_WITNESS_PATH.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
    except (json.JSONDecodeError, OSError):
        existing = {}

    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()

    if s4_audio is not None:
        existing["s4_audio"] = s4_audio
    if s4_midi is not None:
        existing["s4_midi"] = s4_midi

    existing.setdefault("s4_audio", False)
    existing.setdefault("s4_midi", False)
    existing["evil_pet_midi"] = evil_pet_midi or existing.get("evil_pet_midi", False)
    existing["evil_pet_sd_pack"] = evil_pet_sd_pack or existing.get("evil_pet_sd_pack", False)
    existing["evil_pet_firmware_verified"] = evil_pet_firmware_verified or existing.get(
        "evil_pet_firmware_verified", False
    )
    existing["l12_route"] = l12_route or existing.get("l12_route", False)
    existing["observed_at"] = now
    existing["max_age_s"] = 300.0
    existing.setdefault("evidence_refs", [])

    if s4_audio:
        ref = "s4_audio:usb_enumerated"
        if ref not in existing["evidence_refs"]:
            existing["evidence_refs"].append(ref)
    elif "s4_audio:usb_enumerated" in existing.get("evidence_refs", []):
        existing["evidence_refs"].remove("s4_audio:usb_enumerated")

    FX_DEVICE_WITNESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = FX_DEVICE_WITNESS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    tmp.rename(FX_DEVICE_WITNESS_PATH)
    log.debug("FX device witness updated: s4_audio=%s", existing.get("s4_audio"))


def probe_and_publish() -> bool:
    """Probe S-4 audio presence and publish to FX device witness.

    Returns True if S-4 audio is available.
    """
    from shared.s4_midi import find_s4_midi_output

    s4_audio = is_s4_audio_present()
    s4_midi_port = find_s4_midi_output()
    s4_midi = s4_midi_port is not None
    if s4_midi_port is not None:
        try:
            s4_midi_port.close()
        except Exception:
            pass

    update_fx_device_witness(s4_audio=s4_audio, s4_midi=s4_midi)
    return s4_audio
