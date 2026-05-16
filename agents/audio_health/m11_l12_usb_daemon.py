"""M11 L-12 USB capture continuity daemon.

Audio health monitor suite §3.12. Monitors the Zoom L-12 USB audio
interface at 30s cadence:

- Device PRESENT / ABSENT detection via ALSA card enumeration
- Sample-rate drift detection (expected 48000 Hz)
- ALSA xrun counter tracking
- P0 ntfy on >30s ABSENT during livestream

**Observability only** — never triggers USB recovery. The existing
``xhci-death-watchdog`` and ``usb-bandwidth-preflight`` units own recovery.

Run via ``systemd/units/hapax-audio-health-l12-usb.service``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from agents.audio_health.service_loop import interruptible_sleep

log = logging.getLogger(__name__)

DEFAULT_PROBE_INTERVAL_S: float = 30.0
DEFAULT_EXPECTED_SAMPLE_RATE: int = 48000
DEFAULT_ABSENT_THRESHOLD_S: float = 30.0  # >30s absent → P0 ntfy
DEFAULT_SNAPSHOT_PATH: Path = Path("/dev/shm/hapax-audio-health/l12-usb.json")
DEFAULT_TEXTFILE_DIR: Path = Path("/var/lib/node_exporter/textfile_collector")
DEFAULT_TEXTFILE_BASENAME: str = "hapax_audio_health_l12_usb.prom"
DEFAULT_LIVESTREAM_FLAG: Path = Path("/dev/shm/hapax-broadcast/livestream-active")

# L-12 identification
L12_USB_ID_PATTERNS: list[str] = ["Zoom", "L-12", "ZOOM_L-12"]
L12_ALSA_CARD_PATTERN: re.Pattern[str] = re.compile(
    r"^\s*(\d+)\s+\[.*?(?:Zoom|L-12|ZOOM)", re.IGNORECASE
)


@dataclass
class L12State:
    """L-12 tracking state."""

    present: bool = False
    sample_rate: int = 0
    alsa_xruns: int = 0
    last_xruns: int = 0
    xrun_delta: int = 0
    absent_since: float | None = None
    absent_alert_count: int = 0
    sample_rate_drift_count: int = 0


@dataclass
class M11DaemonConfig:
    """Top-level config — env-overridable."""

    probe_interval_s: float = DEFAULT_PROBE_INTERVAL_S
    expected_sample_rate: int = DEFAULT_EXPECTED_SAMPLE_RATE
    absent_threshold_s: float = DEFAULT_ABSENT_THRESHOLD_S
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH
    livestream_flag: Path = DEFAULT_LIVESTREAM_FLAG
    enable_ntfy: bool = True

    @classmethod
    def from_env(cls) -> M11DaemonConfig:
        """Build from env vars."""

        def _fenv(key: str, default: float) -> float:
            raw = os.environ.get(f"HAPAX_AUDIO_HEALTH_L12_USB_{key}")
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        return cls(
            probe_interval_s=_fenv("PROBE_INTERVAL_S", DEFAULT_PROBE_INTERVAL_S),
            absent_threshold_s=_fenv("ABSENT_THRESHOLD_S", DEFAULT_ABSENT_THRESHOLD_S),
        )


def detect_l12_card() -> int | None:
    """Find the L-12's ALSA card number.

    Returns the card number or None if the device is not present.
    """
    try:
        result = subprocess.run(
            ["cat", "/proc/asound/cards"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.split("\n"):
            match = L12_ALSA_CARD_PATTERN.search(line)
            if match:
                return int(match.group(1))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_alsa_sample_rate(card: int) -> int | None:
    """Read the current sample rate from ALSA proc for the given card."""
    proc_path = Path(f"/proc/asound/card{card}/pcm0c/sub0/hw_params")
    try:
        if proc_path.exists():
            content = proc_path.read_text()
            for line in content.split("\n"):
                if line.strip().startswith("rate:"):
                    rate_str = line.split(":", 1)[1].strip()
                    return int(rate_str.split()[0])
    except Exception:
        log.debug("Failed to read sample rate for card %d", card, exc_info=True)
    return None


def get_alsa_xruns(card: int) -> int:
    """Read xrun count from ALSA proc for the given card."""
    proc_path = Path(f"/proc/asound/card{card}/pcm0c/sub0/status")
    try:
        if proc_path.exists():
            content = proc_path.read_text()
            for line in content.split("\n"):
                if "xrun" in line.lower():
                    match = re.search(r"(\d+)", line)
                    if match:
                        return int(match.group(1))
    except Exception:
        log.debug("Failed to read xruns for card %d", card, exc_info=True)
    return 0


def is_livestream_active(flag_path: Path) -> bool:
    """Check if the livestream is active."""
    try:
        return flag_path.exists()
    except Exception:
        return False


def _emit_textfile(state: L12State) -> None:
    """Write Prometheus textfile-collector gauge file."""
    lines = [
        "# HELP hapax_audio_health_l12_usb_present L-12 USB device present (1/0)",
        "# TYPE hapax_audio_health_l12_usb_present gauge",
        f"hapax_audio_health_l12_usb_present {1.0 if state.present else 0.0}",
        "# HELP hapax_audio_health_l12_usb_sample_rate Current sample rate (0 if absent)",
        "# TYPE hapax_audio_health_l12_usb_sample_rate gauge",
        f"hapax_audio_health_l12_usb_sample_rate {state.sample_rate}",
        "# HELP hapax_audio_health_l12_usb_xrun_delta ALSA xrun delta since last probe",
        "# TYPE hapax_audio_health_l12_usb_xrun_delta gauge",
        f"hapax_audio_health_l12_usb_xrun_delta {state.xrun_delta}",
        "# HELP hapax_audio_health_l12_usb_absent_alert_count Absent during livestream events",
        "# TYPE hapax_audio_health_l12_usb_absent_alert_count counter",
        f"hapax_audio_health_l12_usb_absent_alert_count {state.absent_alert_count}",
        "# HELP hapax_audio_health_l12_usb_sample_rate_drift_count Sample rate drift events",
        "# TYPE hapax_audio_health_l12_usb_sample_rate_drift_count counter",
        f"hapax_audio_health_l12_usb_sample_rate_drift_count {state.sample_rate_drift_count}",
    ]
    try:
        textfile = DEFAULT_TEXTFILE_DIR / DEFAULT_TEXTFILE_BASENAME
        tmp = textfile.with_suffix(".tmp")
        textfile.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(textfile)
    except Exception:
        log.debug("textfile write failed", exc_info=True)


def _emit_snapshot(state: L12State, *, now: float, path: Path) -> None:
    """Write atomic SHM snapshot."""
    payload = {
        "monitor": "l12-usb",
        "timestamp": now,
        "present": state.present,
        "sample_rate": state.sample_rate,
        "xrun_delta": state.xrun_delta,
        "absent_alert_count": state.absent_alert_count,
        "sample_rate_drift_count": state.sample_rate_drift_count,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        log.debug("snapshot write failed", exc_info=True)


def _send_ntfy(msg: str, priority: str = "high") -> None:
    """Send desktop notification."""
    try:
        urgency = "critical" if priority == "high" else "normal"
        subprocess.run(
            ["notify-send", f"--urgency={urgency}", "--app-name=LLM Stack",
             "Audio: L-12 USB", msg],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        log.debug("notify-send failed", exc_info=True)


def run_daemon(config: M11DaemonConfig | None = None) -> None:
    """Main daemon loop."""
    cfg = config or M11DaemonConfig.from_env()

    try:
        import systemd.daemon  # type: ignore[import-untyped]

        systemd.daemon.notify("READY=1")
    except ImportError:
        pass

    shutdown = False

    def _sigterm(signum: int, frame: object) -> None:
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    state = L12State()

    log.info("M11 L-12 USB daemon started (interval=%.0fs)", cfg.probe_interval_s)

    while not shutdown:
        now = time.time()

        card = detect_l12_card()

        if card is not None:
            state.present = True
            state.absent_since = None

            # Sample rate check
            rate = get_alsa_sample_rate(card)
            if rate is not None:
                if state.sample_rate != 0 and rate != cfg.expected_sample_rate:
                    state.sample_rate_drift_count += 1
                    log.warning(
                        "L-12 sample rate drift: %d (expected %d)", rate, cfg.expected_sample_rate
                    )
                    if cfg.enable_ntfy:
                        _send_ntfy(
                            f"L-12 sample rate drift: {rate} Hz (expected {cfg.expected_sample_rate})",
                            "default",
                        )
                state.sample_rate = rate

            # Xrun tracking
            xruns = get_alsa_xruns(card)
            state.xrun_delta = max(0, xruns - state.last_xruns)
            state.last_xruns = xruns

        else:
            state.present = False
            state.sample_rate = 0
            state.xrun_delta = 0

            if state.absent_since is None:
                state.absent_since = now
            elif (now - state.absent_since) >= cfg.absent_threshold_s and is_livestream_active(
                cfg.livestream_flag
            ):
                state.absent_alert_count += 1
                log.error("L-12 USB ABSENT during livestream for >%.0fs", now - state.absent_since)
                if cfg.enable_ntfy:
                    _send_ntfy(
                        f"P0: L-12 USB ABSENT during livestream ({now - state.absent_since:.0f}s)",
                        "urgent",
                    )
                state.absent_since = now  # reset for next sustained absence

        _emit_textfile(state)
        _emit_snapshot(state, now=now, path=cfg.snapshot_path)

        try:
            import systemd.daemon  # type: ignore[import-untyped]

            systemd.daemon.notify("WATCHDOG=1")
        except ImportError:
            pass

        elapsed = time.time() - now
        sleep_time = max(1.0, cfg.probe_interval_s - elapsed)
        interruptible_sleep(sleep_time, lambda: shutdown)

    log.info("M11 L-12 USB daemon shutting down")


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    enabled = os.environ.get("HAPAX_AUDIO_HEALTH_L12_USB_ENABLED", "1")
    if enabled.strip().lower() in ("0", "false", "no", "off"):
        log.info("M11 daemon disabled")
        sys.exit(0)

    run_daemon()


if __name__ == "__main__":
    main()
