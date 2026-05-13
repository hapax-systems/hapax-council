"""Credits publisher — renders the Jinja template and posts the result
to omg.lol via :class:`OmgLolClient`.

Hash-dedup via state file: a SHA-256 of the rendered HTML is stored
after each successful publish. Subsequent calls skip the upstream
write if the content hash is unchanged — keeps the omg.lol paste
version history tidy and avoids burning API calls on no-op republishes.

v1 publishes through the publication bus to the pastebin slug `credits` at
`hapax.omg.lol/pastebin/credits`. A future PURL (ytb-OMG7) can alias
`/credits` → this paste URL without any publisher change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from agents.omg_credits_publisher.data import CreditsModel, build_credits_model
from agents.publication_bus.omg_pastebin_publisher import OmgLolPastebinPublisher
from agents.publication_bus.publisher_kit import PublisherPayload
from shared.governance.omg_referent import OperatorNameLeak, safe_render

log = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_STATE_FILE = Path.home() / ".cache" / "hapax" / "hapax-credits-publisher" / "state.json"
DEFAULT_ADDRESS = "hapax"
CREDITS_SLUG = "credits"


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_credits_html(model: CreditsModel) -> str:
    """Render the credits template against the given model."""
    env = _jinja_env()
    template = env.get_template("credits.html.j2")
    return template.render(model=model)


class OmgCreditsPublisher:
    """Publish the credits page when the rendered content changes.

    Parameters:
        library_root: path to ``assets/aesthetic-library/``
        state_file:   path to publisher state (JSON)
        client:       an :class:`OmgLolClient` — may be disabled
        address:      omg.lol address (default ``hapax``)
    """

    def __init__(
        self,
        library_root: Path,
        state_file: Path,
        client: Any,
        address: str = DEFAULT_ADDRESS,
    ) -> None:
        self.library_root = library_root
        self.state_file = state_file
        self.client = client
        self.address = address

    # ── state ────────────────────────────────────────────────────────

    def _read_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_state(self, state: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_name(f"{self.state_file.name}.tmp.{uuid.uuid4().hex}")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    # ── publish flow ─────────────────────────────────────────────────

    def publish(self, *, dry_run: bool = False) -> str:
        """Run one publish cycle. Returns one of:
        ``"published"``, ``"skipped"``, ``"dry-run"``,
        ``"empty-library"``, ``"client-disabled"``, ``"failed"``.
        """
        model = build_credits_model(self.library_root)
        if not model.assets:
            log.info("omg-credits: empty library — nothing to publish")
            return "empty-library"

        html = render_credits_html(model)
        content_sha = hashlib.sha256(html.encode("utf-8")).hexdigest()

        state = self._read_state()
        if state.get("last_content_sha256") == content_sha:
            log.info("omg-credits: unchanged since last publish (sha %s…)", content_sha[:8])
            return "skipped"

        if dry_run:
            log.info(
                "omg-credits: dry-run — %d assets, content sha %s…",
                len(model.assets),
                content_sha[:8],
            )
            return "dry-run"

        if not getattr(self.client, "enabled", False):
            log.warning("omg-credits: client disabled — skipping publish")
            return "client-disabled"

        # AUDIT-05: scan rendered credits HTML for legal-name leak
        # before publishing. Asset attribution metadata may contain
        # operator-name surface forms; this is the egress guard.
        try:
            html = safe_render(html, segment_id=CREDITS_SLUG)
        except OperatorNameLeak:
            log.warning("omg-credits: legal-name leak detected — DROPPING publish")
            return "legal-name-leak"

        result = OmgLolPastebinPublisher(client=self.client).publish(
            PublisherPayload(
                target=self.address,
                text=html,
                metadata={"title": CREDITS_SLUG, "listed": True},
            )
        )
        if not result.ok:
            log.warning("omg-credits: publication-bus publish failed: %s", result.detail)
            return "failed"

        state["last_content_sha256"] = content_sha
        state["last_publish_asset_count"] = len(model.assets)
        self._write_state(state)
        log.info("omg-credits: published %d assets, sha %s…", len(model.assets), content_sha[:8])
        return "published"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="single publish cycle (default)")
    mode.add_argument("--dry-run", action="store_true", help="render + hash; do not POST")
    p.add_argument("--address", default=DEFAULT_ADDRESS)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    # Lazy import so the module itself stays importable without the client.
    from shared.aesthetic_library.loader import ASSETS_ROOT_DEFAULT
    from shared.omg_lol_client import OmgLolClient

    publisher = OmgCreditsPublisher(
        library_root=ASSETS_ROOT_DEFAULT / "aesthetic-library",
        state_file=DEFAULT_STATE_FILE,
        client=OmgLolClient(address=args.address),
        address=args.address,
    )
    outcome = publisher.publish(dry_run=args.dry_run)
    print(outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
