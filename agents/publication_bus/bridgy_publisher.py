"""Bridgy Publish webmention publisher (V5 publication-bus PUB-P3).

Per V5 weave drop 5 §3 mechanic #4: Bridgy is the only daemon-tractable
bridge from omg.lol (which is not natively ActivityPub) to Mastodon
+ Bluesky + GitHub. Each new omg.lol weblog entry can fan out via a
webmention POST to ``https://brid.gy/publish/webmention``; Bridgy
crawls the source URL and forwards the entry to the operator's
authorized downstream accounts.

Bootstrap (one-time, operator-side, NOT in this code):
  - Operator OAuths each downstream account at https://brid.gy/dashboard
  - Operator's omg.lol weblog entries carry h-entry microformats +
    webmention <link> headers (default for omg.lol weblog entries)

Once bootstrapped, this publisher's POST is sufficient — no API key
or per-request credentials needed at publish time. Bridgy validates
the source URL against the operator's authorized accounts at
crawl time.

The publisher subclasses ``Publisher`` from
``agents.publication_bus.publisher_kit.base`` (V5 keystone). Three
load-bearing invariants apply:

1. Allowlist gate — only ``hapax.omg.lol/*`` source URLs permitted
   (operator-curated to prevent fanout of unauthorized content)
2. Legal-name-leak guard — webmention payload is the entry URL, not
   text; the URL itself doesn't contain legal name. Default
   ``requires_legal_name = False``.
3. Counter — Prometheus per-result outcome
"""

from __future__ import annotations

import logging
from typing import ClassVar

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)
from agents.publication_bus.publisher_kit.base import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)

log = logging.getLogger(__name__)

BRIDGY_PUBLISH_ENDPOINT: str = "https://brid.gy/publish/webmention"
"""Webmention publish endpoint. Bridgy crawls the source URL and
forwards to the operator's authorized downstream accounts."""

BRIDGY_REQUEST_TIMEOUT_S: float = 30.0
"""Timeout for the Bridgy POST. Bridgy's crawl + forward can take
several seconds per fanout target; 30s comfortable upper bound."""


# Default allowlist: hapax.omg.lol weblog entries. Operator-curated;
# additions require explicit registry update + operator review.
BRIDGY_POSSE_TARGETS: list[str] = ["mastodon", "bluesky"]
"""Default POSSE syndication targets. Each becomes a Bridgy Publish
target URL: ``https://brid.gy/publish/{target}``."""

DEFAULT_BRIDGY_ALLOWLIST: AllowlistGate = load_allowlist(
    "bridgy-webmention-publish",
    permitted=[
        "https://hapax.omg.lol/weblog",
        "https://hapax.omg.lol/now",
        "https://hapax.omg.lol/statuslog",
        "https://brid.gy/publish/mastodon",
        "https://brid.gy/publish/bluesky",
    ],
)


class BridgyPublisher(Publisher):
    """Webmention POST to Bridgy for fanout to Mastodon / Bluesky / GitHub.

    Subclass of the V5 publication-bus :class:`Publisher` ABC. Each
    publish-event POSTs the operator's omg.lol entry URL to Bridgy;
    Bridgy then crawls the URL and forwards the content to the
    operator's authorized downstream accounts.

    The :class:`PublisherPayload` shape:

    - ``payload.target`` — the target downstream service URL
      (e.g., ``https://hapax.omg.lol/weblog`` for the source root,
      or a Bridgy-specific syndication target). Must be in the
      allowlist.
    - ``payload.text`` — the source URL (the operator's omg.lol
      entry that Bridgy should crawl). Bridgy reads the
      microformats from this URL.

    The webmention POST body shape (per
    https://www.w3.org/TR/webmention/):

        source=<source-url>&target=<bridgy-target>
    """

    surface_name: ClassVar[str] = "bridgy-webmention-publish"
    allowlist: ClassVar[AllowlistGate] = DEFAULT_BRIDGY_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(
        self,
        *,
        endpoint: str = BRIDGY_PUBLISH_ENDPOINT,
        timeout_s: float = BRIDGY_REQUEST_TIMEOUT_S,
    ) -> None:
        self.endpoint = endpoint
        self.timeout_s = timeout_s

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        """POST a webmention to Bridgy.

        Returns a :class:`PublisherResult` with ``ok=True`` on 200/201/
        202 (Bridgy returns 201 Created on accepted webmentions, 202
        Accepted on async-queued, 200 OK on already-published);
        ``error=True`` on transport failure; ``refused=True`` on 4xx
        rejection (which Bridgy uses for unauthorized source URLs).
        """
        if requests is None:
            return PublisherResult(
                error=True,
                detail="requests library not available",
            )

        try:
            response = requests.post(
                self.endpoint,
                data={
                    "source": payload.text,  # operator's omg.lol entry URL
                    "target": payload.target,  # Bridgy target
                },
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            log.warning("bridgy webmention POST raised: %s", exc)
            return PublisherResult(error=True, detail=f"transport failure: {exc}")

        status = response.status_code
        if status in (200, 201, 202):
            return PublisherResult(ok=True, detail=f"bridgy {status}")
        if 400 <= status < 500:
            log.warning("bridgy webmention rejected (status=%d): %s", status, response.text[:200])
            return PublisherResult(refused=True, detail=f"bridgy {status}")
        log.warning("bridgy webmention server error (status=%d)", status)
        return PublisherResult(error=True, detail=f"bridgy {status}")


__all__ = [
    "BRIDGY_POSSE_TARGETS",
    "BRIDGY_PUBLISH_ENDPOINT",
    "BRIDGY_REQUEST_TIMEOUT_S",
    "DEFAULT_BRIDGY_ALLOWLIST",
    "BridgyPublisher",
]
