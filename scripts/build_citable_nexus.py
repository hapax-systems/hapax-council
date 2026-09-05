#!/usr/bin/env python3
"""Citable nexus build CLI — render the static site to a target directory.

Supply --canonical-url (or HAPAX_CITABLE_NEXUS_CANONICAL_URL); no domain
is assumed. --cleared-inputs lists optional reviewed source paths, one per line.
With no allowlist, the build includes only committed home copy and site chrome.
The HTML tree includes a generated CNAME and 404.html. JSON mode contains the
same pages, CNAME and optional RSS feed without writing a second tree.

The renderer is in :mod:`agents.citable_nexus.renderer`; this script
is the operator-facing thin shell.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from agents.citable_nexus.renderer import normalize_canonical_url, render_site

log = logging.getLogger(__name__)


def _path_for(url_path: str, out_dir: Path) -> Path:
    """Map a URL path to a filesystem path under ``out_dir``.

    ``/`` → ``out_dir/index.html``
    ``/cite`` → ``out_dir/cite/index.html``
    """
    if url_path == "/404.html":
        return out_dir / "404.html"
    if url_path == "/":
        return out_dir / "index.html"
    return out_dir / url_path.lstrip("/") / "index.html"


def write_html_tree(out_dir: Path, canonical_url: str, cleared_inputs: Path | None = None) -> int:
    """Render the site and write each page to its filesystem path.

    Returns the number of pages written. Inputs are validated before writing.
    """
    site = render_site(canonical_url, cleared_inputs=cleared_inputs)
    # Remove only known generated routes that this build no longer includes.
    # Reusing an output directory must not retain a formerly cleared document.
    for old_path in (
        "/manifesto",
        "/refusal-brief",
        "/deposits",
        "/citation-graph",
        "/refuse",
        "/surfaces",
    ):
        if old_path not in site.pages:
            _path_for(old_path, out_dir).unlink(missing_ok=True)
    written = 0
    for url_path, html in site.pages.items():
        target = _path_for(url_path, out_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        log.info("wrote %s (%d chars)", target, len(html))
        written += 1
    (out_dir / "CNAME").write_text(_cname(canonical_url), encoding="utf-8")
    feed_path = out_dir / "rss.xml"
    if site.feed is not None:
        feed_path.write_text(site.feed, encoding="utf-8")
    else:
        feed_path.unlink(missing_ok=True)
    return written


def write_json_dump(out_path: Path, canonical_url: str, cleared_inputs: Path | None = None) -> int:
    """Render the site and write a single JSON file keyed by URL path."""
    site = render_site(canonical_url, cleared_inputs=cleared_inputs)
    payload = {
        "schema_version": 1,
        "pages": site.pages,
        "cname": _cname(canonical_url).strip(),
    }
    if site.feed is not None:
        payload["feed"] = site.feed
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    log.info("wrote %s (%d pages)", out_path, len(site.pages))
    return len(site.pages)


def _cname(canonical_url: str) -> str:
    template = Path(__file__).resolve().parents[1] / "docs/citable-nexus/CNAME.template"
    host = urlsplit(normalize_canonical_url(canonical_url)).hostname
    return template.read_text(encoding="utf-8").format(canonical_host=host)


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
    parser.add_argument(
        "--canonical-url",
        default=os.environ.get("HAPAX_CITABLE_NEXUS_CANONICAL_URL"),
        help="canonical HTTP(S) address; overrides HAPAX_CITABLE_NEXUS_CANONICAL_URL",
    )
    parser.add_argument(
        "--cleared-inputs",
        type=Path,
        help="allowlist of reviewed input paths, one per line (default: none)",
    )
    args = parser.parse_args(argv)
    if not args.canonical_url or not args.canonical_url.strip():
        parser.error("--canonical-url is required (or set HAPAX_CITABLE_NEXUS_CANONICAL_URL)")
    try:
        args.canonical_url = normalize_canonical_url(args.canonical_url)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _parse_args(argv)

    try:
        if args.format == "html-tree":
            n = write_html_tree(args.out, args.canonical_url, args.cleared_inputs)
            log.info("html-tree build complete: %d pages under %s", n, args.out)
        else:
            n = write_json_dump(args.out, args.canonical_url, args.cleared_inputs)
            log.info("json build complete: %d pages in %s", n, args.out)
    except (ValueError, OSError) as exc:
        log.error("Build refused: %s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
