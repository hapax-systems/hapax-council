"""omg.lol /now Publisher subclass."""

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

OMG_NOW_SURFACE = "omg-lol-now"

DEFAULT_OMG_NOW_ALLOWLIST: AllowlistGate = load_allowlist(
    OMG_NOW_SURFACE,
    permitted=["hapax"],
)


class OmgLolNowPublisher(Publisher):
    """Publish the operator /now page through the publication bus."""

    surface_name: ClassVar[str] = OMG_NOW_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_OMG_NOW_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, client: Any) -> None:
        self.client = client

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not getattr(self.client, "enabled", True):
            return PublisherResult(refused=True, detail="omg-lol client disabled")

        listed = bool(payload.metadata.get("listed", True))
        result = self.client.set_now(payload.target, content=payload.text, listed=listed)
        if result is None:
            log.warning("omg.lol now publish returned None")
            return PublisherResult(error=True, detail="set_now returned None")
        return PublisherResult(ok=True, detail=f"now:{payload.target}")


__all__ = [
    "DEFAULT_OMG_NOW_ALLOWLIST",
    "OMG_NOW_SURFACE",
    "OmgLolNowPublisher",
]
