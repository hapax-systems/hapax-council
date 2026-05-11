"""InteractiveLoreQueryWard — chat ``!lore`` REPL ward.

Reactive BitchX-grammar ward driven by chat ``!lore <query>`` commands.
Queries from operator-curated chat-authority-allowlisted authors are
routed to a lore backend (chronicle / axiom-precedent / programme-
history) and the resulting query+response pairs render IRC-style in a
scrolling log at the surface scrim depth.

Spec: ytb-LORE-EXT-future-wards (cc-task
``ward-interactive-lore-query-bitchx-repl``). Bridges outcome 5 chat
work + lore wards.

**Load-bearing constraints**:

1. Chat-authority allowlist gate. Per the
   ``interpersonal_transparency`` axiom, persistent state about non-
   operator persons requires explicit consent. The allowlist
   (operator-curated YAML at
   ``config/lore/chat-authority-allowlist.yaml`` or via the
   ``HAPAX_LORE_CHAT_AUTHORITY_ALLOWLIST`` env override) IS the
   consent record. Inclusion in the allowlist is the operator's
   explicit "this person may query lore" affirmation. Non-allowlisted
   queries are silently dropped.
2. Author redaction. The ward never renders raw author identifiers;
   the chat-state surface already carries an anonymized
   ``author_token`` (per-process HMAC, see
   ``agents/youtube_chat_reader/anonymize.py``). The ward derives a
   short visual handle (``viewer-{first-4}``) from that token —
   never the original ``channelId``.
3. Operator-referent policy. Outgoing renderable text routes
   operator references through the
   ``shared/operator_referent.OperatorReferentPicker`` if the
   backend response contains the
   :data:`OPERATOR_PLACEHOLDER` token; literal operator legal name
   never appears in the ward.
4. Cadence cap. The ward refreshes its intake at most every
   :data:`DEFAULT_REFRESH_INTERVAL_S` (2 Hz). High chat traffic
   cannot starve the renderer.

The ward inherits :class:`HomageTransitionalSource` for HOMAGE FSM
participation; ``render_content()`` paints the IRC-style log at the
active package's grammar (mIRC palette, PxPlus VGA font for
authentic-asset packages).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from agents.youtube_chat_reader.anonymize import AuthorAnonymizer
from shared.operator_referent import OperatorReferentPicker

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)


SOURCE_ID: str = "interactive_lore_query"
"""Stable cairo-source registration name."""

LORE_COMMAND_PREFIX: str = "!lore "
"""Chat command prefix the ward parses. Anything else is ignored."""

DEFAULT_RING_SIZE: int = 10
"""Number of (query, response) pairs visible in the IRC-style log."""

DEFAULT_REFRESH_INTERVAL_S: float = 0.5
"""Per cc-task: cadence ≤ 2 Hz even under high chat load."""

DEFAULT_RESPONSE_MAX_CHARS: int = 200
"""Truncation ceiling on backend responses. Long entries are clipped
with an ellipsis so a single chatty backend response cannot displace
multiple older entries from the visual log."""

DEFAULT_CHAT_STATE_PATH: Path = Path("/dev/shm/hapax-chat/recent.jsonl")
"""Epsilon's chat-state surface (``agents.youtube_chat_reader.reader``).
The ward polls this jsonl file each refresh tick, dedup'd via the
``last_processed_ts`` cursor."""

DEFAULT_ALLOWLIST_PATH: Path = Path("config/lore/chat-authority-allowlist.yaml")
"""Repo-relative allowlist fallback when the env override is unset."""

ALLOWLIST_ENV: str = "HAPAX_LORE_CHAT_AUTHORITY_ALLOWLIST"
"""Operator override for the allowlist path."""

OPERATOR_PLACEHOLDER: str = "{operator}"
"""Token a backend may emit when it wants the ward to substitute the
sticky operator referent. Same contract as the chat-response
moderation layer (``cpal/response_dispatch.py``)."""

_HANDLE_PREFIX_LEN: int = 4
"""How many leading hex chars from ``author_token`` to surface as the
visual handle. 4 = ~16 bits, plenty for in-session disambiguation
without revealing the full per-process token."""


@dataclass(frozen=True)
class LoreQueryEntry:
    """One query+response pair visible in the IRC-style log."""

    handle: str  # short anonymized visual identifier (e.g. "viewer-3a1f")
    query: str
    response: str
    ts: float  # original chat-message timestamp


LoreBackend = Callable[[str], str]
"""Backend signature: ``query -> response``. Implementations route to
chronicle, axiom-precedent, or programme-history; tests stub directly."""


def _default_backend(query: str) -> str:
    """Fallback backend: returns a static "no-op" response.

    Real backends (chronicle / axiom-precedent / programme-history)
    are wired by the runtime. This default exists so the ward is
    importable + renderable without a backend dependency.
    """
    return f"(no backend wired) — query was: {query[:80]}"


def _safe_handle(author_token: str) -> str:
    """Short visual handle from the per-process anonymized token.

    Returns ``"viewer-{first-N}"`` where ``N`` is
    :data:`_HANDLE_PREFIX_LEN`. The author_token is already
    HMAC-anonymized upstream; this further truncates the displayed
    fragment so even within-session correlation between the ward and
    other surfaces requires alignment to that prefix only.
    """
    if not author_token:
        return "viewer-anon"
    return f"viewer-{author_token[:_HANDLE_PREFIX_LEN]}"


class ChatAuthorityAllowlist:
    """Operator-curated list of YouTube channelIds permitted to issue ``!lore``.

    Per the ``interpersonal_transparency`` axiom, persistent state
    about non-operator persons requires explicit consent. Inclusion
    in this allowlist IS the consent record.

    The on-disk allowlist contains raw ``channelId`` strings (operator
    has authority to know which viewers are trusted). At load time
    each is hashed via the ward's :class:`AuthorAnonymizer` to the
    same per-process token format the chat-state surface emits, so
    membership checks are O(1) frozenset lookups against incoming
    impingement ``author_token`` values.
    """

    def __init__(
        self,
        *,
        anonymizer: AuthorAnonymizer,
        channel_ids: Iterable[str],
    ) -> None:
        self._anonymizer = anonymizer
        self._allowed_tokens: frozenset[str] = frozenset(
            anonymizer.token(channel_id) for channel_id in channel_ids if channel_id
        )

    def permits(self, author_token: str) -> bool:
        """Return ``True`` iff ``author_token`` is in the consented set."""
        return author_token in self._allowed_tokens

    @property
    def size(self) -> int:
        """How many channelIds the operator has consented for."""
        return len(self._allowed_tokens)


def load_allowlist_channel_ids(path: Path | None = None) -> list[str]:
    """Read the allowlist YAML and return raw channelId strings.

    Schema::

        allowed_channel_ids:
          - "UC..."
          - "UC..."

    Empty file or missing key → empty list. Operator self-issuance:
    the operator's own channelId can be added to permit
    operator-side ``!lore`` commands during stream operations.
    """
    candidate = (
        Path(os.environ[ALLOWLIST_ENV])
        if ALLOWLIST_ENV in os.environ
        else path or DEFAULT_ALLOWLIST_PATH
    )
    if not candidate.is_file():
        return []
    try:
        data = yaml.safe_load(candidate.read_text()) or {}
    except (yaml.YAMLError, OSError) as exc:
        log.warning("lore allowlist load failed (%s): %s", candidate, exc)
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("allowed_channel_ids") or []
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if isinstance(x, str) and x.strip()]


def _moderate_response(response: str, *, query_id: str | None) -> str:
    """Substitute :data:`OPERATOR_PLACEHOLDER` with a sticky referent.

    Sticky-per-query so the same query rendered later looks the same.
    Identical contract to the chat-response moderation layer
    (``cpal/response_dispatch.moderate_chat_text``); kept inline here
    rather than imported because the ward's render path is independent
    of the cpal package and we want the substitution to run even if
    the cpal package isn't loaded (e.g., a daemon running only the
    compositor without the daimonion).
    """
    seed = f"lore-query-{query_id}" if query_id else None
    referent = OperatorReferentPicker.pick(seed)
    return response.replace(OPERATOR_PLACEHOLDER, referent)


def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


class InteractiveLoreQueryWard(HomageTransitionalSource):
    """Chat-driven ``!lore`` REPL ward.

    Polls the chat-state ring at :data:`DEFAULT_REFRESH_INTERVAL_S`
    cadence, parses ``!lore <query>`` commands from allowlisted
    authors, routes the query through the wired backend, and appends
    a :class:`LoreQueryEntry` to the visual log. ``render_content``
    paints the most recent :data:`DEFAULT_RING_SIZE` entries IRC-style.
    """

    def __init__(
        self,
        *,
        allowlist: ChatAuthorityAllowlist | None = None,
        backend: LoreBackend = _default_backend,
        chat_state_path: Path = DEFAULT_CHAT_STATE_PATH,
        ring_size: int = DEFAULT_RING_SIZE,
        refresh_interval_s: float = DEFAULT_REFRESH_INTERVAL_S,
        response_max_chars: int = DEFAULT_RESPONSE_MAX_CHARS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(SOURCE_ID)
        if allowlist is None:
            anonymizer = AuthorAnonymizer()
            allowlist = ChatAuthorityAllowlist(
                anonymizer=anonymizer,
                channel_ids=load_allowlist_channel_ids(),
            )
        self._allowlist = allowlist
        self._backend = backend
        self._chat_state_path = chat_state_path
        self._ring: deque[LoreQueryEntry] = deque(maxlen=ring_size)
        self._last_processed_ts: float = 0.0
        self._refresh_interval_s = refresh_interval_s
        self._response_max_chars = response_max_chars
        self._clock = clock
        self._next_refresh_at: float = 0.0

    @property
    def ring(self) -> tuple[LoreQueryEntry, ...]:
        """Snapshot of the current visible log (most recent last)."""
        return tuple(self._ring)

    def _read_chat_state(self) -> list[dict[str, Any]]:
        """Read the chat-state ring jsonl. Best-effort; returns [] on failure."""
        try:
            raw = self._chat_state_path.read_text(encoding="utf-8")
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                out.append(entry)
        return out

    def ingest(self) -> int:
        """Pull new chat entries, run !lore commands, append to the ring.

        Returns the number of entries appended this call.
        """
        added = 0
        for entry in self._read_chat_state():
            ts = entry.get("ts")
            text = entry.get("text")
            author_token = entry.get("author_token")
            if not isinstance(ts, int | float) or not isinstance(text, str):
                continue
            if ts <= self._last_processed_ts:
                continue
            self._last_processed_ts = float(ts)

            if not text.startswith(LORE_COMMAND_PREFIX):
                continue
            if not isinstance(author_token, str) or not self._allowlist.permits(author_token):
                # Silently drop non-allowlisted queries — the cc-task spec
                # forbids spam-back-to-chat for unauthorized queries.
                continue

            query = text[len(LORE_COMMAND_PREFIX) :].strip()
            if not query:
                continue
            try:
                raw_response = self._backend(query)
            except Exception:  # noqa: BLE001 — backend failures must not crash render
                log.debug("lore backend failed for query=%r", query, exc_info=True)
                raw_response = "(backend error)"
            response = _moderate_response(
                _truncate(str(raw_response), limit=self._response_max_chars),
                query_id=f"{author_token[:_HANDLE_PREFIX_LEN]}-{ts}",
            )
            self._ring.append(
                LoreQueryEntry(
                    handle=_safe_handle(author_token),
                    query=_truncate(query, limit=self._response_max_chars),
                    response=response,
                    ts=float(ts),
                )
            )
            added += 1
        return added

    def _refresh_if_due(self) -> None:
        """Run ``ingest`` if the cadence interval has elapsed."""
        now = self._clock()
        if now < self._next_refresh_at:
            return
        try:
            self.ingest()
        except Exception:  # noqa: BLE001 — render path must not crash on intake
            log.debug("interactive_lore_query intake failed", exc_info=True)
        self._next_refresh_at = now + self._refresh_interval_s

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """Paint the IRC-style scrolling log of recent (query, response) pairs."""
        # Avoid re-import on hot path; the helpers live in text_render.
        from agents.studio_compositor.text_render import (
            TextStyle,
            measure_text,
            render_text,
        )

        self._refresh_if_due()

        pkg = get_active_package()
        if pkg is None:
            return  # No active package → nothing to paint with grammar.

        muted = pkg.resolve_colour("muted")
        accent_query = pkg.resolve_colour("accent_cyan")
        accent_response = pkg.resolve_colour("accent_green")
        content = pkg.resolve_colour("terminal_default")

        font = f"{pkg.typography.primary_font_family} 12"

        line_height = 16.0
        margin_x = 8.0
        margin_y = 8.0
        max_text_width = max(80, canvas_w - 2 * int(margin_x))

        # Render oldest at top → newest at bottom (IRC log conventions).
        # The ring already maintains insertion order with maxlen, so a
        # straight iteration paints in chronological order.
        y = margin_y
        for entry in self._ring:
            if y + 2 * line_height > canvas_h:
                break  # Out of vertical room — clip rather than overflow.

            handle_style = TextStyle(
                text=f"<{entry.handle}>",
                font_description=font,
                color_rgba=muted,
                max_width_px=max_text_width,
            )
            handle_w, _ = measure_text(cr, handle_style)
            render_text(cr, handle_style, x=margin_x, y=y)

            query_style = TextStyle(
                text=f" > {entry.query}",
                font_description=font,
                color_rgba=accent_query,
                max_width_px=max_text_width - int(handle_w),
            )
            render_text(cr, query_style, x=margin_x + handle_w, y=y)
            y += line_height

            response_style = TextStyle(
                text=f"   « {entry.response}",
                font_description=font,
                color_rgba=accent_response,
                max_width_px=max_text_width,
            )
            render_text(cr, response_style, x=margin_x, y=y)
            y += line_height

        # If the ring is empty, paint a muted idle line so the ward isn't
        # silently invisible — operator can confirm it's loaded.
        if not self._ring:
            idle_style = TextStyle(
                text="(awaiting !lore <query> from allowlisted chat author)",
                font_description=font,
                color_rgba=content,
                max_width_px=max_text_width,
            )
            render_text(cr, idle_style, x=margin_x, y=margin_y)


__all__ = [
    "ALLOWLIST_ENV",
    "ChatAuthorityAllowlist",
    "DEFAULT_ALLOWLIST_PATH",
    "DEFAULT_CHAT_STATE_PATH",
    "DEFAULT_REFRESH_INTERVAL_S",
    "DEFAULT_RESPONSE_MAX_CHARS",
    "DEFAULT_RING_SIZE",
    "InteractiveLoreQueryWard",
    "LORE_COMMAND_PREFIX",
    "LoreBackend",
    "LoreQueryEntry",
    "OPERATOR_PLACEHOLDER",
    "SOURCE_ID",
    "load_allowlist_channel_ids",
]
