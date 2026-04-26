"""XXIIVV-style webring beacon — Phase 1.

Per drop 5 §3 fresh-pattern: a single-operator-friendly webring whose
member-identity is the operator's ORCID iD (durable, citation-graph-
linked, agent-stable identifier) rather than a username (fragile,
silo-bound). This module emits the HTML beacon block that goes on
hapax.omg.lol's main web page.

Phase 1 (this module) ships the renderer — a pure function that
returns the ``<a rel="webring">`` beacon HTML given an ORCID iD and
optional webring metadata. Operator pastes the rendered block into
their omg.lol surface (or a future automated deploy flow consumes
it).

Phase 2 will add registration with an existing
single-operator-systems webring (or registering a new one with
operator's ORCID as anchor).
"""

from __future__ import annotations

from dataclasses import dataclass

ORCID_BASE = "https://orcid.org/"
WEBRING_REL = "webring"


@dataclass(frozen=True)
class WebringBeacon:
    """Rendered beacon block; carries the source identifiers for telemetry."""

    html: str
    orcid_id: str
    webring_url: str | None
    has_prev_next: bool


def _normalise_orcid(orcid_id: str) -> str:
    """Accept either bare ORCID (XXXX-XXXX-XXXX-XXXX) or full URL."""
    raw = orcid_id.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return ORCID_BASE + raw


def render_beacon(
    *,
    orcid_id: str,
    webring_url: str | None = None,
    prev_url: str | None = None,
    next_url: str | None = None,
) -> WebringBeacon:
    """Return the webring beacon HTML block.

    The beacon contains:
    - One ``<a rel="webring me">`` link to the operator's ORCID iD
      (primary identity beacon)
    - Optional webring-home link with ``rel="webring"``
    - Optional prev/next member links with ``rel="webring prev"`` /
      ``rel="webring next"`` (XXIIVV convention)

    The output is intentionally minimal HTML — no styling, no script —
    so it survives any host environment (omg.lol weblog, raw HTML page,
    static-site generator).
    """
    orcid_url = _normalise_orcid(orcid_id)
    parts: list[str] = ['<nav aria-label="webring" class="webring">']
    parts.append(
        f'  <a rel="webring me" href="{orcid_url}">'
        f'<span aria-hidden="true">[</span>orcid<span aria-hidden="true">]</span>'
        f" {orcid_id.strip()}</a>"
    )
    if webring_url:
        parts.append(f'  <a rel="webring" href="{webring_url}">webring</a>')
    has_prev_next = False
    if prev_url:
        parts.append(f'  <a rel="webring prev" href="{prev_url}">prev</a>')
        has_prev_next = True
    if next_url:
        parts.append(f'  <a rel="webring next" href="{next_url}">next</a>')
        has_prev_next = True
    parts.append("</nav>")

    html = "\n".join(parts)
    return WebringBeacon(
        html=html,
        orcid_id=orcid_id,
        webring_url=webring_url,
        has_prev_next=has_prev_next,
    )


__all__ = ["ORCID_BASE", "WEBRING_REL", "WebringBeacon", "render_beacon"]
