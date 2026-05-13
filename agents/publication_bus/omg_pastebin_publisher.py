"""omg.lol pastebin Publisher subclass."""

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

OMG_PASTEBIN_SURFACE = "omg-lol-pastebin"

DEFAULT_OMG_PASTEBIN_ALLOWLIST: AllowlistGate = load_allowlist(
    OMG_PASTEBIN_SURFACE,
    permitted=["hapax", "legomena"],
)


class OmgLolPastebinPublisher(Publisher):
    """Publish an omg.lol paste through the publication bus.

    ``payload.target`` is the omg.lol address. The paste title/slug is
    carried in ``payload.metadata["title"]`` so the allowlist stays scoped to
    operator-owned addresses while still preserving the paste title at egress.
    """

    surface_name: ClassVar[str] = OMG_PASTEBIN_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_OMG_PASTEBIN_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(self, *, client: Any) -> None:
        self.client = client

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not getattr(self.client, "enabled", True):
            return PublisherResult(refused=True, detail="omg-lol client disabled")

        title_value = payload.metadata.get("title")
        title = str(title_value) if title_value is not None else None
        listed = bool(payload.metadata.get("listed", True))
        result = self.client.set_paste(
            payload.target,
            content=payload.text,
            title=title,
            listed=listed,
        )
        if result is None:
            log.warning("omg.lol pastebin publish returned None")
            return PublisherResult(error=True, detail="set_paste returned None")
        return PublisherResult(ok=True, detail=f"pastebin:{payload.target}:{title or ''}")


__all__ = [
    "DEFAULT_OMG_PASTEBIN_ALLOWLIST",
    "OMG_PASTEBIN_SURFACE",
    "OmgLolPastebinPublisher",
]
