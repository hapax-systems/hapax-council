"""CLI entry point for the studio compositor."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from .compositor import StudioCompositor
from .config import _default_config, load_config

log = logging.getLogger(__name__)


# systemd sd_notify integration — see camera epic Phase 1 design doc.
# Bound lazily to avoid import errors when systemd is not available.
_sd_notifier: Any = None


def _get_notifier() -> Any:
    """Lazy-load sdnotify.SystemdNotifier; None if unavailable."""
    global _sd_notifier
    if _sd_notifier is None:
        try:
            import sdnotify

            _sd_notifier = sdnotify.SystemdNotifier()
        except ImportError:
            _sd_notifier = False  # cache the negative
    return _sd_notifier if _sd_notifier else None


def sd_notify_ready() -> None:
    """Signal systemd Type=notify that the service is ready to accept work."""
    n = _get_notifier()
    if n is not None:
        n.notify("READY=1")


def sd_notify_watchdog() -> None:
    """Feed the systemd watchdog. Called on a GLib timer."""
    n = _get_notifier()
    if n is not None:
        n.notify("WATCHDOG=1")


def sd_notify_status(msg: str) -> None:
    """Set a short status string visible in `systemctl status`."""
    n = _get_notifier()
    if n is not None:
        n.notify(f"STATUS={msg}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Studio Compositor -- tiled camera output")
    parser.add_argument("--config", type=Path, help="Config YAML path")
    parser.add_argument(
        "--default-config", action="store_true", help="Print default config and exit"
    )
    parser.add_argument("--no-overlay", action="store_true", help="Disable overlay rendering")
    parser.add_argument("--record-dir", type=str, help="Override recording output directory")
    parser.add_argument("--no-record", action="store_true", help="Disable per-camera recording")
    parser.add_argument("--no-hls", action="store_true", help="Disable HLS output")
    parser.add_argument(
        "--layout",
        type=Path,
        default=None,
        help=(
            "Override compositor layout JSON. Defaults to "
            "HAPAX_COMPOSITOR_LAYOUT_PATH, then the repo baseline."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from agents._log_setup import configure_logging

    configure_logging(agent="studio-compositor", level="DEBUG" if args.verbose else None)

    if args.default_config:
        cfg = _default_config()
        print(yaml.dump(json.loads(cfg.model_dump_json()), default_flow_style=False))
        sys.exit(0)

    cfg = load_config(path=args.config)
    if args.no_overlay:
        cfg.overlay_enabled = False
    if args.no_record:
        cfg.recording.enabled = False
    if args.record_dir:
        cfg.recording.output_dir = args.record_dir
    if args.no_hls:
        cfg.hls.enabled = False

    log.info(
        "Config: %d cameras, output=%s, %dx%d@%dfps, overlay=%s, recording=%s, hls=%s",
        len(cfg.cameras),
        cfg.output_device,
        cfg.output_width,
        cfg.output_height,
        cfg.framerate,
        cfg.overlay_enabled,
        cfg.recording.enabled,
        cfg.hls.enabled,
    )

    layout_path = args.layout
    if layout_path is None and os.environ.get("HAPAX_COMPOSITOR_LAYOUT_PATH"):
        layout_path = Path(os.environ["HAPAX_COMPOSITOR_LAYOUT_PATH"])

    compositor = StudioCompositor(cfg, layout_path=layout_path)
    compositor.start()


if __name__ == "__main__":
    main()
