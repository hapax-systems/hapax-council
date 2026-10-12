"""HTTP layer for the discourse sensor: one read-only GET per call.

Reach is a reported fact, never an exception: network errors and HTTP >= 400
come back as FetchResult(reached=False, ...) with the status kept.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

USER_AGENT = "hapax-discourse-sensing/1.0 (read-only public-endpoint polling)"


@dataclass(frozen=True)
class FetchResult:
    reached: bool
    http_status: int
    body: bytes
    final_url: str
    error: str | None


def fetch_url(
    url: str, timeout_s: float = 20.0, transport: httpx.BaseTransport | None = None
) -> FetchResult:
    """GET one public URL with a named User-Agent; reach failures never raise."""
    try:
        with httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_s,
            follow_redirects=True,
            transport=transport,
        ) as client:
            response = client.get(url)
    except Exception as exc:
        return FetchResult(
            reached=False,
            http_status=0,
            body=b"",
            final_url=url,
            error=f"{type(exc).__name__}: {exc}",
        )
    reached = response.status_code < 400
    return FetchResult(
        reached=reached,
        http_status=response.status_code,
        body=response.content,
        final_url=str(response.url),
        error=None if reached else f"HTTP {response.status_code}",
    )
