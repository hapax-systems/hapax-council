"""C2PA trust-list cache helpers for Article 50 provenance work."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

C2PA_CONFORMANCE_TRUST_LIST_URL = (
    "https://raw.githubusercontent.com/c2pa-org/conformance-public/refs/heads/main/"
    "trust-list/C2PA-TRUST-LIST.pem"
)
DEFAULT_REFRESH_SECONDS = 24 * 60 * 60


class TrustListRefreshStatus(StrEnum):
    """Refresh/cache state for C2PA trust anchors."""

    REFRESHED = "refreshed"
    CACHED_FALLBACK = "cached_fallback"
    BLOCKED_NO_TRUST_LIST = "blocked_no_trust_list"


class HttpResponse(Protocol):
    content: bytes

    def raise_for_status(self) -> None: ...


class HttpGetter(Protocol):
    def __call__(self, url: str, *, timeout: float) -> HttpResponse: ...


@dataclass(frozen=True)
class TrustListRefreshResult:
    """Outcome of refreshing the official C2PA trust anchors cache."""

    status: TrustListRefreshStatus
    cache_path: Path
    source_url: str
    anchor_count: int
    detail: str
    refreshed_at: str


def trust_list_cache_path(state_root: Path | None = None) -> Path:
    """Return the local PEM cache path for C2PA trust anchors."""

    root = state_root or Path(os.environ.get("HAPAX_STATE", str(Path.home() / "hapax-state")))
    return root / "art50" / "c2pa-trust" / "C2PA-TRUST-LIST.pem"


def refresh_trust_list(
    *,
    cache_path: Path | None = None,
    source_url: str = C2PA_CONFORMANCE_TRUST_LIST_URL,
    get: HttpGetter | None = None,
    timeout: float = 10.0,
    now: datetime | None = None,
) -> TrustListRefreshResult:
    """Refresh the official C2PA trust list, falling back to cached anchors.

    The production signing MVP does not mint trusted certificates. This cache
    gives validators a stable, locally inspectable trust-anchor path once
    certificate provisioning is in place.
    """

    path = cache_path or trust_list_cache_path()
    refreshed_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    try:
        getter = get or _requests_get
        response = getter(source_url, timeout=timeout)
        response.raise_for_status()
        content = response.content
        anchor_count = _anchor_count(content)
        if anchor_count == 0:
            raise ValueError("downloaded C2PA trust list contained no PEM certificates")
        _atomic_write_bytes(path, content)
        return TrustListRefreshResult(
            status=TrustListRefreshStatus.REFRESHED,
            cache_path=path,
            source_url=source_url,
            anchor_count=anchor_count,
            detail="C2PA trust anchors refreshed",
            refreshed_at=refreshed_at,
        )
    except Exception as exc:
        cached = load_trust_anchors_pem(path)
        if cached:
            return TrustListRefreshResult(
                status=TrustListRefreshStatus.CACHED_FALLBACK,
                cache_path=path,
                source_url=source_url,
                anchor_count=_anchor_count(cached.encode("utf-8")),
                detail=f"refresh failed; using cached C2PA trust anchors: {type(exc).__name__}",
                refreshed_at=refreshed_at,
            )
        return TrustListRefreshResult(
            status=TrustListRefreshStatus.BLOCKED_NO_TRUST_LIST,
            cache_path=path,
            source_url=source_url,
            anchor_count=0,
            detail=f"refresh failed and no cached C2PA trust anchors exist: {type(exc).__name__}",
            refreshed_at=refreshed_at,
        )


def load_trust_anchors_pem(cache_path: Path | None = None) -> str | None:
    """Load cached trust anchors, returning ``None`` when unavailable/empty."""

    path = cache_path or trust_list_cache_path()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if "-----BEGIN CERTIFICATE-----" not in content:
        return None
    return content


def _requests_get(url: str, *, timeout: float) -> HttpResponse:
    import requests

    return requests.get(url, timeout=timeout)


def _anchor_count(content: bytes) -> int:
    return content.count(b"-----BEGIN CERTIFICATE-----")


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        tmp_path = Path(tmp_name)
        if tmp_path.exists():
            tmp_path.unlink()
        raise


__all__ = [
    "C2PA_CONFORMANCE_TRUST_LIST_URL",
    "DEFAULT_REFRESH_SECONDS",
    "TrustListRefreshResult",
    "TrustListRefreshStatus",
    "load_trust_anchors_pem",
    "refresh_trust_list",
    "trust_list_cache_path",
]
