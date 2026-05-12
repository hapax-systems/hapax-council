"""One-shot email-forwarding setup for hapax@omg.lol."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from agents.publication_bus.omg_email_publisher import OmgLolEmailPublisher
from agents.publication_bus.publisher_kit import PublisherPayload

log = logging.getLogger(__name__)

DEFAULT_ADDRESS = "hapax"


def configure_email_forwarding(
    *,
    client: Any,
    address: str = DEFAULT_ADDRESS,
    forwards_to: str,
) -> str:
    """Set the email-forward destination for ``<address>@omg.lol``.

    Returns one of ``"configured"``, ``"unchanged"``,
    ``"client-disabled"``, ``"failed"``.

    Idempotent: reads the current destination first and skips the
    ``set_email`` call if it already matches.
    """
    if not getattr(client, "enabled", False):
        log.warning("omg-email: client disabled — skipping configuration")
        return "client-disabled"

    current = client.get_email(address)
    if current:
        current_dest = (
            current.get("response", {}).get("destination") or current.get("destination") or ""
        )
        if current_dest == forwards_to:
            log.info("omg-email: already configured to %s", forwards_to)
            return "unchanged"

    result = OmgLolEmailPublisher(client=client).publish(
        PublisherPayload(target=address, text=forwards_to)
    )
    if not result.ok:
        log.warning("omg-email: publication-bus publish failed: %s", result.detail)
        return "failed"

    log.info("omg-email: configured %s → %s", address, forwards_to)
    return "configured"


def show_current_destination(*, client: Any, address: str = DEFAULT_ADDRESS) -> str:
    """Return the current forwarding destination, or an empty string
    when unknown / client disabled."""
    if not getattr(client, "enabled", False):
        return ""
    resp = client.get_email(address)
    if not resp:
        return ""
    return resp.get("response", {}).get("destination") or resp.get("destination") or ""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub_set = sub.add_parser("set", help="configure forwarding destination")
    sub_set.add_argument("forwards_to")
    sub_set.add_argument("--address", default=DEFAULT_ADDRESS)

    sub_show = sub.add_parser("show", help="show the current forwarding destination")
    sub_show.add_argument("--address", default=DEFAULT_ADDRESS)

    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    from shared.omg_lol_client import OmgLolClient

    client = OmgLolClient(address=args.address)

    if args.cmd == "set":
        outcome = configure_email_forwarding(
            client=client,
            address=args.address,
            forwards_to=args.forwards_to,
        )
        print(outcome)
        return 0 if outcome in ("configured", "unchanged") else 1

    if args.cmd == "show":
        dest = show_current_destination(client=client, address=args.address)
        if dest:
            print(dest)
        else:
            print("(no forwarding configured or client disabled)")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
