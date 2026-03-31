"""CLI entry point for the studio compositor."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

from .compositor import StudioCompositor
from .config import _default_config, load_config

log = logging.getLogger(__name__)


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

    compositor = StudioCompositor(cfg)
    compositor.start()


if __name__ == "__main__":
    main()
