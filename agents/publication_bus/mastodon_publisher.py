"""Mastodon Publisher subclass for public-event and artifact fanout."""

from __future__ import annotations

import json
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

MASTODON_SURFACE = "mastodon-post"

DEFAULT_MASTODON_ALLOWLIST: AllowlistGate = load_allowlist(
    MASTODON_SURFACE,
    permitted=["hapax"],
)


class MastodonPublisher(Publisher):
    """Publish a single Mastodon status through the publication bus."""

    surface_name: ClassVar[str] = MASTODON_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_MASTODON_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(
        self,
        *,
        instance_url: str | None,
        access_token: str | None,
        client_factory=None,
    ) -> None:
        self.instance_url = (instance_url or "").rstrip("/")
        self.access_token = access_token or ""
        self._client_factory = client_factory or _default_client_factory
        self._client = None

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not (self.instance_url and self.access_token):
            return PublisherResult(refused=True, detail="missing Mastodon credentials")

        try:
            raw_result = self._ensure_client().status_post(payload.text)
        except Exception:  # noqa: BLE001
            log.warning("Mastodon status_post raised", exc_info=True)
            return PublisherResult(error=True, detail="status_post_error")

        return PublisherResult(ok=True, detail=_receipt_detail(raw_result))

    def _ensure_client(self):
        if self._client is None:
            self._client = self._client_factory(self.instance_url, self.access_token)
        return self._client


def _receipt_detail(raw_result: Any) -> str:
    return json.dumps(
        {
            "uri": _extract_status_uri(raw_result),
            "public_url": _extract_status_public_url(raw_result),
        },
        sort_keys=True,
    )


def _extract_status_uri(raw_result: Any) -> str | None:
    if isinstance(raw_result, dict):
        uri = raw_result.get("uri")
    else:
        uri = getattr(raw_result, "uri", None)
    return uri if isinstance(uri, str) and uri else None


def _extract_status_public_url(raw_result: Any) -> str | None:
    if isinstance(raw_result, dict):
        url = raw_result.get("url")
    else:
        url = getattr(raw_result, "url", None)
    return url if isinstance(url, str) and url else None


def _default_client_factory(instance_url: str, access_token: str):
    from mastodon import Mastodon

    return Mastodon(access_token=access_token, api_base_url=instance_url)


__all__ = [
    "DEFAULT_MASTODON_ALLOWLIST",
    "MASTODON_SURFACE",
    "MastodonPublisher",
]
