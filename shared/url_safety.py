"""Small URL/domain validation helpers for trusted-origin checks."""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse


def normalize_hostname(hostname: object) -> str:
    """Return a lower-case hostname without a trailing root dot."""
    return str(hostname or "").strip().rstrip(".").lower()


def host_matches_domain(
    hostname: object,
    domain: str,
    *,
    include_subdomains: bool = True,
) -> bool:
    """Return True when ``hostname`` is ``domain`` or a real subdomain.

    The subdomain case requires a dot boundary, so ``evil-example.com`` and
    ``example.com.evil.test`` do not match ``example.com``.
    """
    host = normalize_hostname(hostname)
    expected = normalize_hostname(domain)
    if not host or not expected:
        return False
    if host == expected:
        return True
    return include_subdomains and host.endswith(f".{expected}")


def url_matches_domain(
    url: object,
    domain: str,
    *,
    schemes: Iterable[str] | None = ("https",),
    include_subdomains: bool = True,
) -> bool:
    """Parse ``url`` and validate scheme plus hostname boundary."""
    text = str(url or "").strip()
    if not text:
        return False
    try:
        parsed = urlparse(text)
    except ValueError:
        return False
    if schemes is not None:
        allowed_schemes = {scheme.lower() for scheme in schemes}
        if parsed.scheme.lower() not in allowed_schemes:
            return False
    return host_matches_domain(parsed.hostname, domain, include_subdomains=include_subdomains)


def url_matches_any_domain(
    url: object,
    domains: Iterable[str],
    *,
    schemes: Iterable[str] | None = ("https",),
    include_subdomains: bool = True,
) -> bool:
    """Return True when ``url`` matches any allowed hostname boundary."""
    return any(
        url_matches_domain(
            url,
            domain,
            schemes=schemes,
            include_subdomains=include_subdomains,
        )
        for domain in domains
    )


__all__ = [
    "host_matches_domain",
    "normalize_hostname",
    "url_matches_any_domain",
    "url_matches_domain",
]
