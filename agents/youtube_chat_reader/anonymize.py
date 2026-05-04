"""Per-session author anonymization for live-chat impingements.

The ``interpersonal_transparency`` axiom forbids persistent state about
non-operator persons without an active consent contract. YouTube chat
authors arrive with a stable ``channelId`` that would otherwise allow
cross-session correlation. We hash with a per-process key so:

* Within a single daemon run, the same author maps to the same token —
  consumers can see "this author has sent 3 messages in this session"
  for cluster detection and rate-of-question reasoning.
* Across daemon restarts (== across livestream sessions in practice),
  the salt regenerates so identity does not persist. No
  consent → no cross-session memory.

The token is intentionally short (12 hex chars, 48 bits) — enough for
in-session dedup but small enough that brute-force matching against a
known set of YouTube channelIds is computationally trivial. That is a
feature, not a bug: the data on disk genuinely cannot identify anyone
without already-known prior knowledge of who is in the room.
"""

from __future__ import annotations

import hmac
import secrets
from hashlib import sha256

__all__ = ["AuthorAnonymizer"]


class AuthorAnonymizer:
    """HMAC author IDs with a per-process key.

    The key is generated at construction time from
    ``secrets.token_bytes(32)`` — never persisted, never logged. A new
    daemon process gets a new key, breaking cross-session linkage.
    """

    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)

    def token(self, author_id: str | None) -> str:
        """Return a 12-hex-char anonymous token for an author id.

        Empty / None inputs map to ``"anon"`` so consumers can still
        differentiate "system message" from "real chat author whose id
        we redacted". The token is HMAC-SHA256 truncated, not raw
        SHA256 — without the key there is no offline attack against
        the YouTube channelId space.
        """
        if not author_id:
            return "anon"
        digest = hmac.new(self._key, author_id.encode("utf-8"), sha256).hexdigest()
        return digest[:12]
