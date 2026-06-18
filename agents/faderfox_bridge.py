"""Faderfox MX12 -> PipeWire manual-trim bridge.

A REDUNDANT manual control surface over the broadcast mix. Reads MX12 MIDI CC
and applies a per-channel MANUAL TRIM (PipeWire node volume via wpctl) that
MULTIPLIES with the automation gains (ducker / loudnorm filter-chain controls):
the faders ride on top of automation, they never replace it.

Fail-safe by construction: if this daemon dies, node volumes simply hold their
last value and the automation layer keeps governing the mix. There is no path
by which a dead bridge silences or unmutes the broadcast on its own.

The CC->target mapping is config-driven
(config/equipment/faderfox-mx12-controls.yaml). Faderfox CC assignments are
device-config-specific, so run with ``--learn`` to print incoming MIDI and
capture the real map; the daemon also logs unmapped CCs at INFO.

Run: ``uv run python -m agents.faderfox_bridge [--learn] [--config PATH]``
Service: ``systemd/units/hapax-faderfox-bridge.service``.
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

try:
    import mido

    _MIDO_AVAILABLE = True
except ImportError:  # pragma: no cover - environment without mido
    mido: Any = None  # type: ignore[no-redef]
    _MIDO_AVAILABLE = False

log = logging.getLogger("faderfox_bridge")

DEFAULT_CONFIG = (
    Path(__file__).resolve().parent.parent / "config" / "equipment" / "faderfox-mx12-controls.yaml"
)
# ALSA/mido port name fragments for the MX12.
PORT_PATTERNS = ("MX12", "Faderfox")
RECONNECT_S = 3.0
# Two CC steps is ~1.6% of the fader throw: enough to avoid sticky pickup,
# small enough that the hand must visibly meet the live value before takeover.
PICKUP_TOLERANCE_CC = 2

# node.name -> PipeWire object id cache (invalidated on a failed wpctl call).
_id_cache: dict[str, int] = {}


def find_input() -> Any | None:
    """Open the MX12 MIDI input by name match, or None if absent."""
    if not _MIDO_AVAILABLE:
        return None
    try:
        names = mido.get_input_names()
    except Exception:
        log.debug("mido.get_input_names() failed", exc_info=True)
        return None
    for pattern in PORT_PATTERNS:
        for name in names:
            if pattern.lower() in name.lower():
                try:
                    return mido.open_input(name)
                except Exception:
                    log.warning("MX12 input %r open failed", name, exc_info=True)
                    return None
    return None


def resolve_node_id(node_name: str) -> int | None:
    """Resolve a PipeWire node.name to its object id (cached)."""
    if node_name in _id_cache:
        return _id_cache[node_name]
    try:
        out = subprocess.run(
            ["pw-cli", "ls", "Node"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        log.debug("pw-cli ls Node failed", exc_info=True)
        return None
    cur_id: int | None = None
    needle = f'node.name = "{node_name}"'
    for line in out.splitlines():
        m = re.match(r"\s*id (\d+),", line)
        if m:
            cur_id = int(m.group(1))
        elif needle in line and cur_id is not None:
            _id_cache[node_name] = cur_id
            return cur_id
    return None


TICK_S = 0.02  # coalescing tick — fader sweeps apply at ~50Hz max, latest value wins


def _handle_button(button: dict, value: int) -> None:
    if value < 64:
        return
    current_mute = get_mute(button["target"])
    if current_mute is None:
        log.warning(
            "button %s -> %s skipped; mute state unavailable",
            button.get("label"),
            button["target"],
        )
        return
    new_mute = not current_mute
    set_mute(button["target"], new_mute)
    button["_muted"] = new_mute
    log.info("button %s -> %s mute=%s", button.get("label"), button["target"], new_mute)


def _wpctl(args: list[str], node_name: str) -> subprocess.CompletedProcess[str] | None:
    nid = resolve_node_id(node_name)
    if nid is None:
        log.debug("node %s not present — skipping", node_name)
        return None
    try:
        proc = subprocess.run(
            ["wpctl", *args[:1], str(nid), *args[1:]],
            timeout=5,
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            _id_cache.pop(node_name, None)
            log.debug(
                "wpctl %s on %s failed: %s",
                args,
                node_name,
                (proc.stderr or proc.stdout).strip(),
            )
            return None
        return proc
    except Exception:
        log.debug("wpctl %s on %s failed", args, node_name, exc_info=True)
        _id_cache.pop(node_name, None)
        return None


def set_volume(node_name: str, vol: float) -> None:
    _wpctl(["set-volume", f"{max(0.0, vol):.3f}"], node_name)


def set_mute(node_name: str, mute: bool) -> None:
    _wpctl(["set-mute", "1" if mute else "0"], node_name)


def get_mute(node_name: str) -> bool | None:
    proc = _wpctl(["get-volume"], node_name)
    if proc is None:
        return None
    text = f"{proc.stdout}\n{proc.stderr}".lower()
    return "muted" in text


def _parse_wpctl_volume(text: str) -> float | None:
    match = re.search(r"\bVolume:\s*([0-9]+(?:\.[0-9]+)?)", text)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def get_volume(node_name: str) -> float | None:
    proc = _wpctl(["get-volume"], node_name)
    if proc is None:
        return None
    return _parse_wpctl_volume(f"{proc.stdout}\n{proc.stderr}")


def _cc_to_volume(fader: dict, value: int) -> float:
    scale = float(fader.get("scale", 1.0))
    return (value / 127.0) * scale


def _volume_to_cc(fader: dict, volume: float) -> int:
    scale = max(float(fader.get("scale", 1.0)), 0.001)
    normalized = max(0.0, min(volume / scale, 1.0))
    return round(normalized * 127)


def resync_faders(faders: dict[tuple[int, int], dict]) -> None:
    """Seed pickup targets from current PipeWire volume without writing volume.

    The MX12 sends absolute CC values. After a bridge restart, the physical
    fader position can be stale relative to PipeWire; pickup mode ignores
    fader moves until the hardware meets or crosses the current live value.
    """
    for fader in faders.values():
        volume = get_volume(fader["target"])
        if volume is None:
            fader.pop("_pickup_target", None)
            fader.pop("_pickup_last_value", None)
            log.warning(
                "fader %s -> %s resync skipped; volume state unavailable; "
                "verify configured target node and non-mutating wpctl get-volume readback",
                fader.get("label"),
                fader["target"],
            )
            continue
        fader["_pickup_target"] = _volume_to_cc(fader, volume)
        fader["_pickup_last_value"] = None
        log.info(
            "fader %s -> %s pickup target=%s from volume=%.3f",
            fader.get("label"),
            fader["target"],
            fader["_pickup_target"],
            volume,
        )


def _pickup_ready(fader: dict, value: int) -> bool:
    target = fader.get("_pickup_target")
    if target is None:
        return True
    last_value = fader.get("_pickup_last_value")
    within_tolerance = abs(value - int(target)) <= PICKUP_TOLERANCE_CC
    crossed_target = last_value is not None and (
        int(last_value) <= int(target) <= value or int(last_value) >= int(target) >= value
    )
    if within_tolerance or crossed_target:
        fader.pop("_pickup_target", None)
        fader.pop("_pickup_last_value", None)
        return True
    fader["_pickup_last_value"] = value
    log.debug(
        "fader %s -> %s pickup pending: value=%s target=%s",
        fader.get("label"),
        fader["target"],
        value,
        target,
    )
    return False


def _handle_fader(fader: dict, value: int) -> bool:
    if not _pickup_ready(fader, value):
        return False
    _apply_fader(fader, value)
    return True


def _apply_fader(fader: dict, value: int) -> None:
    vol = _cc_to_volume(fader, value)
    set_volume(fader["target"], vol)
    log.debug("fader %s -> %s vol=%.3f", fader.get("label"), fader["target"], vol)


def _coalesced_fader_value(fader: dict, values: list[int]) -> int | None:
    if not values:
        return None
    if fader.get("_pickup_target") is None:
        return values[-1]
    for value in values:
        if _pickup_ready(fader, value):
            return values[-1]
    return None


def _handle_fader_batch(fader: dict, values: list[int]) -> bool:
    value = _coalesced_fader_value(fader, values)
    if value is None:
        return False
    _apply_fader(fader, value)
    return True


def load_map(path: str | Path) -> tuple[dict, dict]:
    """Load fader + button maps keyed by (0-indexed channel, cc)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    faders: dict[tuple[int, int], dict] = {}
    buttons: dict[tuple[int, int], dict] = {}
    for f in data.get("faders", []) or []:
        faders[(int(f.get("channel", 1)) - 1, int(f["cc"]))] = f
    for b in data.get("buttons", []) or []:
        buttons[(int(b.get("channel", 1)) - 1, int(b["cc"]))] = b
    return faders, buttons


def run(config_path: str | Path, *, learn: bool = False) -> None:
    faders: dict[tuple[int, int], dict] = {}
    buttons: dict[tuple[int, int], dict] = {}
    if not learn:
        faders, buttons = load_map(config_path)
        log.info("loaded %d fader(s), %d button(s) from %s", len(faders), len(buttons), config_path)
    else:
        log.info("LEARN mode — printing incoming MIDI; no volume changes applied")

    while True:
        inport = find_input()
        if inport is None:
            log.warning("Faderfox MX12 not found; retrying in %.0fs", RECONNECT_S)
            time.sleep(RECONNECT_S)
            continue
        log.info("MX12 connected: %s", getattr(inport, "name", "?"))
        if not learn:
            resync_faders(faders)
        try:
            while True:
                # Drain-and-coalesce: a fader sweep emits dozens of CCs; applying
                # each serially (one wpctl subprocess per event) lags seconds
                # behind the hand. Keep only the LATEST value per fader and apply
                # once per tick. Buttons are discrete presses — never coalesced.
                fader_events: dict[tuple[int, int], list[int]] = {}
                button_events: list[tuple[tuple[int, int], int]] = []
                for msg in inport.iter_pending():
                    if learn:
                        log.info("MIDI %s", msg)
                        continue
                    if msg.type != "control_change":
                        continue
                    key = (msg.channel, msg.control)
                    if key in faders:
                        fader_events.setdefault(key, []).append(msg.value)
                    elif key in buttons:
                        button_events.append((key, msg.value))
                if not fader_events and not button_events:
                    time.sleep(TICK_S)
                    continue
                for key, values in fader_events.items():
                    fader = faders[key]
                    _handle_fader_batch(fader, values)
                for key, value in button_events:
                    msg_value = value
                    _handle_button(buttons[key], msg_value)
                time.sleep(TICK_S)
        except Exception:
            log.warning("MX12 read loop error; reconnecting", exc_info=True)
        finally:
            try:
                inport.close()
            except Exception:
                pass
        time.sleep(RECONNECT_S)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    ap = argparse.ArgumentParser(description="Faderfox MX12 -> PipeWire manual-trim bridge")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--learn", action="store_true", help="print incoming MIDI, apply nothing")
    args = ap.parse_args()
    if not _MIDO_AVAILABLE:
        log.error("mido not available — install python-rtmidi/mido in the council venv")
        return 1
    run(args.config, learn=args.learn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
