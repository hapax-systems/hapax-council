"""Entry point for hapax-daimonion daemon."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from pathlib import Path

# Re-export for backward compatibility — tests patch these at __main__ level
from agents.hapax_daimonion.audio_input import AudioInputStream  # noqa: F401
from agents.hapax_daimonion.chime_player import ChimePlayer  # noqa: F401
from agents.hapax_daimonion.config import load_config
from agents.hapax_daimonion.context_gate import ContextGate  # noqa: F401
from agents.hapax_daimonion.daemon import VoiceDaemon
from agents.hapax_daimonion.event_log import EventLog  # noqa: F401
from agents.hapax_daimonion.frame_gate import FrameGate  # noqa: F401
from agents.hapax_daimonion.governor import PipelineGovernor  # noqa: F401
from agents.hapax_daimonion.hotkey import HotkeyServer  # noqa: F401
from agents.hapax_daimonion.notification_queue import NotificationQueue  # noqa: F401
from agents.hapax_daimonion.ntfy_listener import subscribe_ntfy  # noqa: F401
from agents.hapax_daimonion.persona import format_notification  # noqa: F401
from agents.hapax_daimonion.presence import PresenceDetector  # noqa: F401
from agents.hapax_daimonion.session import SessionManager  # noqa: F401
from agents.hapax_daimonion.session_events import screen_flash as _screen_flash  # noqa: F401
from agents.hapax_daimonion.tts import TTSManager  # noqa: F401
from agents.hapax_daimonion.workspace_monitor import WorkspaceMonitor  # noqa: F401

__all__ = ["VoiceDaemon", "main"]

log = logging.getLogger("hapax_daimonion")

_PID_FILE = (
    Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hapax-daimonion.pid"
)
_FAST_EXIT_AFTER_SHUTDOWN_ENV = "HAPAX_DAIMONION_FAST_EXIT_AFTER_SHUTDOWN"
_FALSEY_ENV_VALUES = {"0", "false", "no", "off"}


def _enforce_single_instance() -> None:
    """Kill any stale hapax-daimonion process and write our PID file."""
    if _PID_FILE.exists():
        try:
            old_pid = int(_PID_FILE.read_text().strip())
            cmdline = Path(f"/proc/{old_pid}/cmdline").read_text()
            if "hapax_daimonion" in cmdline or "hapax.voice" in cmdline:
                log.warning("Killing stale hapax-daimonion process (PID %d)", old_pid)
                os.kill(old_pid, signal.SIGTERM)
                import time as _time

                _time.sleep(1)
                try:
                    os.kill(old_pid, 0)
                    os.kill(old_pid, signal.SIGKILL)
                    log.warning("Force-killed stale PID %d", old_pid)
                except ProcessLookupError:
                    pass
        except (ValueError, FileNotFoundError, ProcessLookupError, PermissionError):
            pass

    _PID_FILE.write_text(str(os.getpid()))


def _cleanup_pid_file() -> None:
    """Remove PID file on clean exit."""
    try:
        if _PID_FILE.exists() and _PID_FILE.read_text().strip() == str(os.getpid()):
            _PID_FILE.unlink()
    except Exception:
        pass


def _fast_exit_after_shutdown_enabled() -> bool:
    value = os.environ.get(_FAST_EXIT_AFTER_SHUTDOWN_ENV, "1")
    return value.strip().lower() not in _FALSEY_ENV_VALUES


def _exit_after_clean_shutdown() -> None:
    if not _fast_exit_after_shutdown_enabled():
        return

    # The daemon owns cleanup in VoiceDaemon.run(). After that returns, native
    # ML/audio worker pools can still crash in CPython finalizers during restart.
    logging.shutdown()
    os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hapax Daimonion daemon")
    parser.add_argument("--config", type=str, help="Path to config YAML")
    parser.add_argument("--check", action="store_true", help="Verify config and exit")
    args = parser.parse_args()

    from agents._log_setup import configure_logging

    configure_logging(agent="hapax-daimonion")

    cfg = load_config(Path(args.config) if args.config else None)
    if args.check:
        print(cfg.model_dump_json(indent=2))
        return

    _enforce_single_instance()

    # Clean up orphan temp wav files from prior unclean shutdown
    from agents._tmp_wav import cleanup_all_wavs

    cleanup_all_wavs()
    import glob as _glob

    for stale_wav in _glob.glob("/tmp/tmp*.wav"):
        try:
            Path(stale_wav).unlink()
            log.info("Cleaned legacy orphan temp file: %s", stale_wav)
        except OSError:
            pass

    # Runtime optimizations
    import gc

    import uvloop

    uvloop.install()
    gc.set_threshold(50_000, 30, 10)

    # Queue #225: Prometheus /metrics server on :9483 for CPAL loop telemetry.
    # Port choice: compositor owns 9482; daimonion gets 9483. Fails closed so
    # a port conflict or missing prometheus_client doesn't block the daemon.
    try:
        from prometheus_client import start_http_server

        metrics_port = int(os.environ.get("HAPAX_DAIMONION_METRICS_PORT", "9483"))
        start_http_server(metrics_port)
        log.info("Prometheus /metrics server listening on :%d", metrics_port)
    except (ImportError, OSError) as exc:
        log.warning("Prometheus /metrics server not started: %s", exc)

    daemon = VoiceDaemon(cfg=cfg)
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, daemon.stop)
    loop.add_signal_handler(signal.SIGHUP, daemon.workspace_monitor.reload_context)
    run_completed = False
    try:
        loop.run_until_complete(daemon.run())
        run_completed = True
    finally:
        _cleanup_pid_file()
        loop.close()
        if run_completed:
            _exit_after_clean_shutdown()


if __name__ == "__main__":
    main()
