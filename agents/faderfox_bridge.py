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


def _wpctl(args: list[str], node_name: str) -> None:
    nid = resolve_node_id(node_name)
    if nid is None:
        log.debug("node %s not present — skipping", node_name)
        return
    try:
        subprocess.run(["wpctl", *args[:1], str(nid), *args[1:]], timeout=5, check=False)
    except Exception:
        log.debug("wpctl %s on %s failed", args, node_name, exc_info=True)
        _id_cache.pop(node_name, None)


def set_volume(node_name: str, vol: float) -> None:
    _wpctl(["set-volume", f"{max(0.0, vol):.3f}"], node_name)


def set_mute(node_name: str, mute: bool) -> None:
    _wpctl(["set-mute", "1" if mute else "0"], node_name)


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
        try:
            for msg in inport:
                if learn:
                    log.info("MIDI %s", msg)
                    continue
                if msg.type != "control_change":
                    continue
                key = (msg.channel, msg.control)
                fader = faders.get(key)
                if fader is not None:
                    scale = float(fader.get("scale", 1.0))
                    vol = (msg.value / 127.0) * scale
                    set_volume(fader["target"], vol)
                    log.debug("fader %s -> %s vol=%.3f", fader.get("label"), fader["target"], vol)
                    continue
                button = buttons.get(key)
                if button is not None:
                    if msg.value >= 64:
                        new_mute = not bool(button.get("_muted"))
                        set_mute(button["target"], new_mute)
                        button["_muted"] = new_mute
                        log.info(
                            "button %s -> %s mute=%s",
                            button.get("label"),
                            button["target"],
                            new_mute,
                        )
                    continue
                log.info(
                    "unmapped CC ch=%d cc=%d val=%d (add to controls YAML)",
                    msg.channel + 1,
                    msg.control,
                    msg.value,
                )
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
