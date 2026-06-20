"""S-4 audio/route presence witness — dynamic-audio-env DA-7.

Publishes S-4 MIDI reachability plus the current mk5/S-4 analog insert
route state to the FX device witness at
``/dev/shm/hapax-audio/fx-device-witness.json``.

Called by the audio router's tick loop and by the voice-path dry-bypass
probe. Pure function: reads PipeWire state, writes JSON, no side effects.

The current mk5 topology does not require the S-4 USB audio interface for
public voice: the S-4 is an analog insert. The structural route is present
when the dry voice send reaches mk5 OUT AUX2/3, mk5 IN AUX2/3 feeds
``hapax-voice-wet``, and ``hapax-voice-wet`` feeds ``hapax-livestream-tap``.

This witness does not claim the S-4 wet return is audible. Public S-4
readiness additionally requires a fresh signal witness that sets
``s4_wet_return_signal=true``. Whenever that signal field is explicitly
written, ``s4_wet_return_signal_observed_at`` timestamps the verdict so
callers can reject stale wet-return evidence.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

FX_DEVICE_WITNESS_PATH = Path("/dev/shm/hapax-audio/fx-device-witness.json")
_S4_DEVICE_PATTERNS = ("Torso_Electronics_S-4", "Torso_Elektron", "usb-Torso")
_MK5_OUTPUT = "alsa_output.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-output-0"
_MK5_INPUT = "alsa_input.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-input-0"
_ANALOG_INSERT_LINKS = (
    ("hapax-loudnorm-playback:output_FL", "->", f"{_MK5_OUTPUT}:playback_AUX2"),
    ("hapax-loudnorm-playback:output_FR", "->", f"{_MK5_OUTPUT}:playback_AUX3"),
    ("hapax-voice-wet-capture:input_AUX2", "<-", f"{_MK5_INPUT}:capture_AUX2"),
    ("hapax-voice-wet-capture:input_AUX3", "<-", f"{_MK5_INPUT}:capture_AUX3"),
    ("hapax-voice-wet-playback:output_FL", "->", "hapax-livestream-tap:playback_FL"),
    ("hapax-voice-wet-playback:output_FR", "->", "hapax-livestream-tap:playback_FR"),
)


def is_s4_audio_present() -> bool:
    """Return True if the legacy S-4 USB audio device is reachable."""
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


def _pw_link_has_edge(text: str, source: str, direction: str, target: str) -> bool:
    current_port = ""
    wanted_prefix = f"|{direction} "
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if raw_line[:1] not in {" ", "\t"}:
            current_port = line
            continue
        if current_port == source and line.startswith(wanted_prefix):
            linked_port = line.removeprefix(wanted_prefix).strip()
            if linked_port == target:
                return True
    return False


def is_s4_analog_insert_route_present() -> bool:
    """Return True when the current mk5/S-4 structural route is linked."""
    try:
        result = subprocess.run(
            ["pw-link", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        log.debug("pw-link probe failed", exc_info=True)
        return False
    return all(
        _pw_link_has_edge(result.stdout, source, direction, target)
        for source, direction, target in _ANALOG_INSERT_LINKS
    )


def update_fx_device_witness(
    *,
    s4_audio: bool | None = None,
    s4_midi: bool | None = None,
    s4_analog_insert_route: bool | None = None,
    s4_wet_return_signal: bool | None = None,
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
    if s4_analog_insert_route is not None:
        existing["s4_analog_insert_route"] = s4_analog_insert_route
    if s4_wet_return_signal is not None:
        existing["s4_wet_return_signal"] = s4_wet_return_signal
        existing["s4_wet_return_signal_observed_at"] = now

    existing.setdefault("s4_audio", False)
    existing.setdefault("s4_midi", False)
    existing.setdefault("s4_analog_insert_route", False)
    existing.setdefault("s4_wet_return_signal", False)
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

    if s4_analog_insert_route:
        ref = "s4_analog_insert_route:mk5_links_present"
        if ref not in existing["evidence_refs"]:
            existing["evidence_refs"].append(ref)
    elif "s4_analog_insert_route:mk5_links_present" in existing.get("evidence_refs", []):
        existing["evidence_refs"].remove("s4_analog_insert_route:mk5_links_present")

    if s4_wet_return_signal:
        ref = "s4_wet_return_signal:runtime_probe"
        if ref not in existing["evidence_refs"]:
            existing["evidence_refs"].append(ref)
    elif "s4_wet_return_signal:runtime_probe" in existing.get("evidence_refs", []):
        existing["evidence_refs"].remove("s4_wet_return_signal:runtime_probe")

    FX_DEVICE_WITNESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = FX_DEVICE_WITNESS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    tmp.rename(FX_DEVICE_WITNESS_PATH)
    log.debug(
        "FX device witness updated: s4_midi=%s s4_analog_insert_route=%s s4_wet_return_signal=%s",
        existing.get("s4_midi"),
        existing.get("s4_analog_insert_route"),
        existing.get("s4_wet_return_signal"),
    )


def probe_and_publish() -> bool:
    """Probe S-4 route presence and publish to FX device witness.

    Returns True if the structural mk5/S-4 analog insert route is available.
    """
    from shared.s4_midi import find_s4_midi_output

    s4_audio = is_s4_audio_present()
    s4_analog_insert_route = is_s4_analog_insert_route_present()
    s4_midi_port = find_s4_midi_output()
    s4_midi = s4_midi_port is not None
    if s4_midi_port is not None:
        try:
            s4_midi_port.close()
        except Exception:
            pass

    update_fx_device_witness(
        s4_audio=s4_audio,
        s4_midi=s4_midi,
        s4_analog_insert_route=s4_analog_insert_route,
        s4_wet_return_signal=False,
    )
    return s4_analog_insert_route
