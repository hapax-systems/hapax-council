"""PURL registrar — one-shot + CLI for ad-hoc PURL management."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from agents.publication_bus.omg_purl_publisher import OmgLolPurlPublisher
from agents.publication_bus.publisher_kit import PublisherPayload

log = logging.getLogger(__name__)


class PurlSpec(BaseModel):
    """A single PURL registration intent — slug + target URL."""

    slug: str
    target: str
    description: str = ""


def build_initial_purls() -> list[PurlSpec]:
    """The canonical seed set per ytb-OMG7.

    Returned fresh each call so tests can override targets without
    mutating a module-level constant. ``claim5`` is a placeholder —
    operator updates when the first live claim lands.
    """
    return [
        PurlSpec(
            slug="stream",
            target="https://www.youtube.com/@LegomenaLive",
            description="Primary livestream channel.",
        ),
        PurlSpec(
            slug="geal",
            target="https://github.com/ryanklee/hapax-council/blob/main/docs/superpowers/specs/2026-04-23-geal-spec.md",
            description="GEAL (Gruvbox Emissive Animation Language) spec.",
        ),
        PurlSpec(
            slug="vocab",
            target="https://hapax.omg.lol/#vocabulary",
            description="Vocabulary anchor on the operator profile page.",
        ),
        PurlSpec(
            slug="axioms",
            target="https://hapax.omg.lol/#governance",
            description="Governance / axioms anchor on the profile page.",
        ),
        PurlSpec(
            slug="research",
            target="https://hapax.omg.lol/#research",
            description="Research anchor on the profile page.",
        ),
        PurlSpec(
            slug="claim5",
            target="https://hapax.omg.lol/#research",
            description="Placeholder → current research claim. Operator updates on first live claim.",
        ),
        PurlSpec(
            slug="now",
            target="https://hapax.omg.lol/now",
            description="Vanity short → /now page.",
        ),
        PurlSpec(
            slug="mail",
            target="mailto:hapax@omg.lol",
            description="Operator contact mail.",
        ),
        PurlSpec(
            slug="credits",
            target="https://hapax.omg.lol/pastebin/credits",
            description="Aesthetic-library credits page (ytb-OMG-CREDITS).",
        ),
    ]


INITIAL_PURLS: list[PurlSpec] = build_initial_purls()


try:
    from prometheus_client import Counter

    _PURL_REG_TOTAL = Counter(
        "hapax_broadcast_omg_purl_registrations_total",
        "PURL registration attempts by outcome.",
        ["outcome"],
    )

    def _record_reg(outcome: str) -> None:
        _PURL_REG_TOTAL.labels(outcome=outcome).inc()
except ImportError:

    def _record_reg(outcome: str) -> None:
        log.debug("prometheus_client unavailable; metric dropped (%s)", outcome)


class PurlRegistrar:
    """Wraps an :class:`OmgLolClient` to register / inspect PURLs idempotently.

    Parameters:
        client:  an OmgLolClient (may be disabled)
        address: the omg.lol address (default ``hapax``)
    """

    def __init__(self, client: Any, address: str = "hapax") -> None:
        self.client = client
        self.address = address

    def _existing(self) -> dict[str, str]:
        """Return current {slug: target} from the API, empty on failure."""
        resp = self.client.list_purls(self.address)
        if not resp:
            return {}
        # omg.lol returns {"response": {"purls": [{"name":..., "url":...}, ...]}}
        # Defensive: shape varies by endpoint; keep the unwrap tolerant.
        purls = resp.get("response", {}).get("purls") or resp.get("purls") or []
        out: dict[str, str] = {}
        for p in purls:
            name = p.get("name") or p.get("slug")
            url = p.get("url") or p.get("target")
            if name and url:
                out[name] = url
        return out

    def register(self, spec: PurlSpec, *, force: bool = False) -> str:
        """Register one PURL. Returns one of:
        ``"created"``, ``"unchanged"``, ``"drift-skipped"``,
        ``"drift-overwritten"``, ``"failed"``, ``"disabled"``.
        """
        if not getattr(self.client, "enabled", False):
            _record_reg("disabled")
            return "disabled"

        existing = self._existing()
        current = existing.get(spec.slug)
        if current == spec.target:
            _record_reg("unchanged")
            return "unchanged"
        if current is not None and not force:
            log.warning(
                "omg-purl: %s already points to %s (want %s); use --force to overwrite",
                spec.slug,
                current,
                spec.target,
            )
            _record_reg("drift-skipped")
            return "drift-skipped"

        result = OmgLolPurlPublisher(client=self.client).publish(
            PublisherPayload(
                target=self.address,
                text=spec.target,
                metadata={"name": spec.slug},
            )
        )
        if not result.ok:
            _record_reg("failed")
            return "failed"
        outcome = "drift-overwritten" if current is not None else "created"
        _record_reg(outcome)
        log.info("omg-purl: %s → %s (%s)", spec.slug, spec.target, outcome)
        return outcome

    def seed(
        self, specs: Iterable[PurlSpec] | None = None, *, force: bool = False
    ) -> dict[str, str]:
        """Register every spec in `specs` (or the canonical seed set).
        Returns {slug: outcome}."""
        specs = specs or build_initial_purls()
        outcomes: dict[str, str] = {}
        for spec in specs:
            outcomes[spec.slug] = self.register(spec, force=force)
        return outcomes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub_seed = sub.add_parser("seed", help="register the canonical initial PURL set")
    sub_seed.add_argument("--force", action="store_true", help="overwrite drifted targets")
    sub_seed.add_argument("--address", default="hapax")

    sub_add = sub.add_parser("add", help="register a single PURL")
    sub_add.add_argument("slug")
    sub_add.add_argument("target")
    sub_add.add_argument("--force", action="store_true")
    sub_add.add_argument("--address", default="hapax")

    sub_list = sub.add_parser("list", help="print current PURLs")
    sub_list.add_argument("--address", default="hapax")

    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    from shared.omg_lol_client import OmgLolClient

    client = OmgLolClient(address=args.address)
    reg = PurlRegistrar(client, address=args.address)

    if args.cmd == "seed":
        outcomes = reg.seed(force=args.force)
        for slug, outcome in outcomes.items():
            print(f"{slug}: {outcome}")
        # Non-zero exit if any slug failed.
        if any(o == "failed" for o in outcomes.values()):
            return 1
        return 0

    if args.cmd == "add":
        outcome = reg.register(
            PurlSpec(slug=args.slug, target=args.target),
            force=args.force,
        )
        print(f"{args.slug}: {outcome}")
        return 0 if outcome != "failed" else 1

    if args.cmd == "list":
        existing = reg._existing()
        if not existing:
            print("(no PURLs or client disabled)")
            return 0
        for slug, target in sorted(existing.items()):
            print(f"{slug}\t{target}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
