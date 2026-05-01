#!/usr/bin/env python3
"""Citable nexus build CLI — render the static site to a target directory.

Usage:

    scripts/build_citable_nexus.py --out /tmp/hapax-research-build
    scripts/build_citable_nexus.py --out /tmp/hapax-research-build --format json

The default output is a directory tree of HTML files (``index.html``,
``cite/index.html``, ``refuse/index.html``, ``surfaces/index.html``).
The ``--format json`` mode emits a single ``site.json`` keyed by URL
path → rendered HTML — useful when piping into the eventual
``ryanklee/hapax-research`` deploy step (GitHub Pages or omg.lol).

The renderer is in :mod:`agents.citable_nexus.renderer`; this script
is the operator-facing thin shell.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from agents.citable_nexus.renderer import render_site

log = logging.getLogger(__name__)


def _path_for(url_path: str, out_dir: Path) -> Path:
    """Map a URL path to a filesystem path under ``out_dir``.

    ``/`` → ``out_dir/index.html``
    ``/cite`` → ``out_dir/cite/index.html``
    """
    if url_path == "/":
        return out_dir / "index.html"
    return out_dir / url_path.lstrip("/") / "index.html"


def write_html_tree(out_dir: Path) -> int:
    """Render the site and write each page to its filesystem path.

    Returns the number of pages written. Caller is responsible for
    creating ``out_dir`` ahead of the call.
    """
    site = render_site()
    written = 0
    for url_path, html in site.pages.items():
        target = _path_for(url_path, out_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        log.info("wrote %s (%d chars)", target, len(html))
        written += 1
    return written


def write_json_dump(out_path: Path) -> int:
    """Render the site and write a single JSON file keyed by URL path."""
    site = render_site()
    payload = {
        "schema_version": 1,
        "pages": site.pages,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    log.info("wrote %s (%d pages)", out_path, len(site.pages))
    return len(site.pages)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="build_citable_nexus",
        description="Render the citable-nexus static site to disk.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="output directory (html-tree mode) or output file path (json mode)",
    )
    parser.add_argument(
        "--format",
        choices=("html-tree", "json"),
        default="html-tree",
        help="output format (default: html-tree of <out>/index.html etc.)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _parse_args(argv)

    if args.format == "html-tree":
        args.out.mkdir(parents=True, exist_ok=True)
        n = write_html_tree(args.out)
        log.info("html-tree build complete: %d pages under %s", n, args.out)
    else:
        n = write_json_dump(args.out)
        log.info("json build complete: %d pages in %s", n, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
