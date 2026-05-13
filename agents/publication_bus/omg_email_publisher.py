"""omg.lol email-forwarding Publisher subclass."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)

log = logging.getLogger(__name__)

OMG_EMAIL_SURFACE = "omg-lol-email-forward"

DEFAULT_OMG_EMAIL_ALLOWLIST: AllowlistGate = load_allowlist(
    OMG_EMAIL_SURFACE,
    permitted=["hapax", "legomena"],
)


class OmgLolEmailPublisher(Publisher):
    """Configure omg.lol email forwarding through the publication bus."""

    surface_name: ClassVar[str] = OMG_EMAIL_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_OMG_EMAIL_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, client: Any) -> None:
        self.client = client

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not getattr(self.client, "enabled", True):
            return PublisherResult(refused=True, detail="omg-lol client disabled")

        result = self.client.set_email(payload.target, forwards_to=payload.text)
        if result is None:
            log.warning("omg.lol email forward returned None")
            return PublisherResult(error=True, detail="set_email returned None")
        return PublisherResult(ok=True, detail=f"email:{payload.target}")


__all__ = [
    "DEFAULT_OMG_EMAIL_ALLOWLIST",
    "OMG_EMAIL_SURFACE",
    "OmgLolEmailPublisher",
]
