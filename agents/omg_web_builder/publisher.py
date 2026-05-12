"""Phase 1.5 publisher — POSTs ``static/index.html`` to omg.lol (ytb-OMG2).

Reads the static HTML from disk, validates it is non-empty, and either
prints what would be sent (default ``--dry-run``) or posts through the
publication-bus omg.lol web publisher when ``--publish`` is passed explicitly.

The dry-run default is the safety invariant — running the publisher
with no flags **must not** mutate the live web page. ``--publish``
is the only way to perform the live API call.

Usage::

    # dry-run (safe default)
    uv run python -m agents.omg_web_builder.publisher

    # live publish (operator-explicit)
    uv run python -m agents.omg_web_builder.publisher --publish

    # custom HTML path
    uv run python -m agents.omg_web_builder.publisher --html-path /tmp/draft.html
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from agents.publication_bus.omg_web_publisher import OmgLolWebPublisher
from agents.publication_bus.publisher_kit import PublisherPayload
from shared.governance.omg_referent import OperatorNameLeak, safe_render

log = logging.getLogger(__name__)

DEFAULT_HTML_PATH = Path(__file__).resolve().parent / "static" / "index.html"
DEFAULT_ADDRESS = "hapax"


def read_html(path: Path) -> str:
    """Read the HTML file. Raise on missing or empty file."""
    if not path.exists():
        raise FileNotFoundError(f"HTML file not found: {path}")
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"HTML file is empty: {path}")
    return content


def render_dry_run_summary(content: str, *, address: str) -> str:
    """Return a human-readable summary of what would be POSTed."""
    lines = content.splitlines()
    head = "\n".join(lines[:5])
    tail = "\n".join(lines[-5:])
    return (
        f"DRY RUN — would POST to /address/{address}/web\n"
        f"  bytes={len(content)}, lines={len(lines)}\n"
        f"  publish=True, type=HTML\n"
        f"--- head (5 lines) ---\n{head}\n"
        f"--- tail (5 lines) ---\n{tail}\n"
        f"(re-run with --publish to perform the live POST)"
    )


def publish(
    *,
    html_path: Path = DEFAULT_HTML_PATH,
    address: str = DEFAULT_ADDRESS,
    dry_run: bool = True,
    client_factory=None,
) -> int:
    """Read HTML and either dry-run or live-publish.

    Returns 0 on success, 1 on failure. ``client_factory`` is injected
    by tests; production lets the default factory build a real
    ``OmgLolClient`` only when ``dry_run=False``.
    """
    try:
        content = read_html(html_path)
    except (FileNotFoundError, ValueError) as exc:
        log.error("publisher pre-flight failed: %s", exc)
        return 1

    if dry_run:
        sys.stdout.write(render_dry_run_summary(content, address=address))
        sys.stdout.write("\n")
        return 0

    client = (client_factory or _default_client_factory)()
    if not getattr(client, "enabled", True):
        log.error("omg.lol client disabled (no API key in pass store)")
        return 1

    # AUDIT-05: scan static HTML for legal-name leak before publishing
    # to /web. The web page is the broadest public surface in the OMG
    # cascade — fail-closed if HAPAX_OPERATOR_NAME guard matches.
    try:
        content = safe_render(content, segment_id=f"web-{address}")
    except OperatorNameLeak:
        log.error("omg-web: legal-name leak detected — DROPPING publish")
        return 1

    publisher = OmgLolWebPublisher(client=client)
    result = publisher.publish(
        PublisherPayload(target=address, text=content, metadata={"publish": True})
    )
    if not result.ok:
        log.error("omg web publication-bus publish failed: %s", result.detail)
        return 1
    log.info("omg web publish OK through publication bus for %s (bytes=%d)", address, len(content))
    return 0


def _default_client_factory():
    """Lazy-build an OmgLolClient. Heavy import isolated to live path."""
    from shared.omg_lol_client import OmgLolClient

    return OmgLolClient()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents.omg_web_builder.publisher",
        description="POST hapax.omg.lol web page (default: dry-run).",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="perform the live POST (default: dry-run only)",
    )
    parser.add_argument(
        "--html-path",
        type=Path,
        default=DEFAULT_HTML_PATH,
        help=f"path to HTML file (default: {DEFAULT_HTML_PATH})",
    )
    parser.add_argument(
        "--address",
        default=DEFAULT_ADDRESS,
        help=f"omg.lol address (default: {DEFAULT_ADDRESS})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv)
    return publish(
        html_path=args.html_path,
        address=args.address,
        dry_run=not args.publish,
    )


if __name__ == "__main__":
    sys.exit(main())
