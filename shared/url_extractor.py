"""URL extractor + classifier — Phase 1 of YouTube broadcast bundle (#144).

Pure-string utility for the chat-monitor URL extraction stage. No HTTP
requests at extract time (a separate enrichment pass can resolve t.co
shortlinks etc.). Classification is a pure-string heuristic on
hostname + path.

Per `docs/superpowers/specs/2026-04-18-youtube-broadcast-bundle-design.md`
§2.3 + plan Phase 1 T1.2.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from shared.attribution import AttributionKind

# Match URLs with http(s)://, optionally surrounded by markdown brackets.
# Captures the URL itself; trailing punctuation that's not URL-legal is
# trimmed in post-processing.
_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"'`\[\](){}]+",
    re.I,
)
# Trailing characters that are typically punctuation (commas, periods,
# parens) not part of the URL — strip them off the right edge.
_TRAILING_PUNCT = ".,;:!?)]}>'\"`"

# Hostname → AttributionKind mapping. Matches if the hostname contains
# any token (case-insensitive substring); first match wins. Order matters
# for prefix-matching domains (e.g. doi.org before generic .org).
_HOST_HEURISTICS: list[tuple[tuple[str, ...], AttributionKind]] = [
    (("doi.org", "dx.doi.org"), "doi"),
    (("github.com", "gist.github.com"), "github"),
    (("twitter.com", "x.com", "nitter."), "tweet"),
    (("youtube.com", "youtu.be"), "youtube"),
    (("wikipedia.org", "wikimedia.org"), "wikipedia"),
    (
        (
            "bandcamp.com",
            "soundcloud.com",
            "spotify.com",
            "music.apple.com",
            "discogs.com",
        ),
        "album-ref",
    ),
    (
        (
            "nature.com",
            "arxiv.org",
            "sciencedirect.com",
            "ncbi.nlm.nih.gov",
            "pubmed",
            "scholar.google.",
        ),
        "citation",
    ),
]


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from ``text``. Returns unique URLs in first-seen
    order with trailing punctuation stripped.

    Does NOT resolve shortlinks (t.co, bit.ly etc.) — that's a separate
    enrichment step. Does NOT decode HTML entities — chat producers
    should pre-decode.
    """
    seen: set[str] = set()
    result: list[str] = []
    for match in _URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(_TRAILING_PUNCT)
        # Re-check after strip — a bare "https://" with all-punctuation
        # tail collapses to empty.
        if not url or len(url) < len("https://x"):
            continue
        if url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result


def classify_url(url: str) -> AttributionKind:
    """Pure-string heuristic on hostname + path. Returns the
    AttributionKind for ``url``.

    Falls back to "other" when no rule matches. Never raises — invalid
    URLs (no scheme, garbage) classify as "other".
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return "other"
    host = (parsed.hostname or "").lower()
    if not host:
        return "other"
    for tokens, kind in _HOST_HEURISTICS:
        for token in tokens:
            if token in host:
                return kind
    return "other"


__all__ = ["classify_url", "extract_urls"]
