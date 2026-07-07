"""Single-writer codex-OAuth refresher — the auth-axis substrate.

One daemon owns the rotating ``refresh_token``; every codex session consumes the
``access_token`` READ-ONLY via the ``CODEX_ACCESS_TOKEN`` env var (codex enters its
``not_refreshable_auth`` state). Because no consumer holds or exercises a
refresh_token, no two consumers can race a rotation — cross-rig AND intra-rig
dissolve by construction. The access_token IS the ChatGPT subscription bearer
(not an API key), so this keeps the entitlement and introduces zero api-cost.

This module is the SUBSTRATE (slice 1): the token decode/load/expire/publish
contract. The live REFRESH (codex's stale-token path / the OAuth endpoint) is an
injected callable — the deployed daemon provides it (needs the appendix
refresh_token); unit tests mock it. Slice 2 wires the launchers to inject
CODEX_ACCESS_TOKEN; the hermeticity fixture (operator, appendix) is the go/no-go.

Verified design-of-record: non-boutique-codex-auth-and-lane-liveness-design-2026-07-03.md.
NEVER print or log the access_token itself — use :func:`token_fingerprint`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_AUTH_JSON = Path.home() / ".codex" / "auth.json"
DEFAULT_PUBLISH_DIR = Path.home() / ".cache" / "hapax" / "codex-oauth"
DEFAULT_PUBLISHED_ACCESS_TOKEN = DEFAULT_PUBLISH_DIR / "access_token"
DEFAULT_REFRESH_MARGIN_S = 300.0  # refresh this many seconds before expiry (5 min)

__all__ = [
    "DEFAULT_AUTH_JSON",
    "DEFAULT_PUBLISH_DIR",
    "DEFAULT_PUBLISHED_ACCESS_TOKEN",
    "DEFAULT_REFRESH_MARGIN_S",
    "AccessToken",
    "RefreshFn",
    "decode_access_token_exp",
    "load_access_token",
    "load_published_access_token",
    "needs_refresh",
    "publish_access_token",
    "refresh_and_publish",
    "token_fingerprint",
]

RefreshFn = Callable[[Path], str]
"""A refresh callable: given the auth.json path (the daemon is the sole writer),
read the refresh_token, perform the OAuth refresh (codex's stale-token path or the
OAuth endpoint), rewrite auth.json with the new tokens, and return the new
access_token. The daemon owns this; tests inject a mock."""


@dataclass(frozen=True)
class AccessToken:
    """The published access_token + its decoded JWT expiry (epoch seconds, or 0.0 if unparseable)."""

    raw: str
    exp: float  # epoch seconds (the JWT `exp` claim); 0.0 if unparseable


def decode_access_token_exp(token: str) -> float:
    """Return the JWT ``exp`` claim (epoch seconds), or 0.0 if unparseable."""
    parts = token.split(".")
    if len(parts) < 2:
        return 0.0
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)  # base64url pad to a multiple of 4
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return 0.0
    exp = claims.get("exp") if isinstance(claims, dict) else None
    return float(exp) if isinstance(exp, (int, float)) else 0.0


def load_access_token(auth_json: Path = DEFAULT_AUTH_JSON) -> AccessToken | None:
    """Read the access_token from codex ``auth.json`` (structure only).

    Returns None if the file is missing/corrupt or carries no access_token.
    NEVER log the returned token — use :func:`token_fingerprint`.
    """
    try:
        data = json.loads(auth_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    token = (data.get("tokens") or {}).get("access_token")
    if not isinstance(token, str) or not token:
        return None
    return AccessToken(raw=token, exp=decode_access_token_exp(token))


def load_published_access_token(
    publish_dir: Path = DEFAULT_PUBLISH_DIR,
    *,
    token_file: Path | None = None,
) -> AccessToken | None:
    """Read the single-writer published access token, if present.

    This is the consumer-side path for Codex launchers. It deliberately ignores
    ``auth.json`` and therefore never reads or exercises the refresh token.
    """

    path = token_file.expanduser() if token_file is not None else publish_dir / "access_token"
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None
        if info.st_uid != os.getuid():
            return None
        if stat.S_IMODE(info.st_mode) & 0o077:
            return None
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            token = handle.read().strip()
    except OSError:
        return None
    finally:
        if fd >= 0:
            os.close(fd)
    if not token:
        return None
    return AccessToken(raw=token, exp=decode_access_token_exp(token))


def needs_refresh(
    token: AccessToken | None,
    *,
    margin_s: float = DEFAULT_REFRESH_MARGIN_S,
    now: float | None = None,
) -> bool:
    """True if the access_token is missing, unparseable, or expires within ``margin_s``."""
    if token is None or token.exp <= 0.0:
        return True
    now = time.time() if now is None else now
    return token.exp - now <= margin_s


def publish_access_token(token: str, publish_dir: Path = DEFAULT_PUBLISH_DIR) -> Path:
    """Publish the access_token atomically (0600, tempfile + os.replace in the same dir).

    Same-dir tempfile so ``os.replace`` is atomic on the same filesystem; 0600 so
    only the owner can read the published token. The temp file is unlinked on any
    failure (a torn write never leaves a partial published token).
    """
    publish_dir.mkdir(parents=True, exist_ok=True)
    target = publish_dir / "access_token"
    fd, tmp_name = tempfile.mkstemp(prefix=".access_token.", dir=str(publish_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            # Preserve the original publish failure; stale temp cleanup is best-effort.
            pass
        raise
    return target


def refresh_and_publish(
    auth_json: Path,
    refresh: RefreshFn,
    *,
    publish_dir: Path = DEFAULT_PUBLISH_DIR,
) -> AccessToken:
    """Run one refresh cycle: ``refresh`` (the injected sole-writer) + publish.

    The daemon calls this on its cadence. The injected ``refresh`` performs the
    OAuth rotation (it owns auth.json) and returns the new access_token; this
    function publishes it atomically + returns the decoded :class:`AccessToken`.
    Raises ``ValueError`` if ``refresh`` returns no token.
    """
    token = refresh(auth_json)
    if not isinstance(token, str) or not token:
        raise ValueError("refresh returned no access_token")
    publish_access_token(token, publish_dir)
    return AccessToken(raw=token, exp=decode_access_token_exp(token))


def token_fingerprint(token: str) -> str:
    """A short stable fingerprint for logging (sha256[:12]) — NEVER the token itself."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
