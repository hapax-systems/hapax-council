"""Compose YouTube + cross-surface metadata from current Hapax state.

The composer is a pure function: given a scope and the input state at a
moment, it returns a ``ComposedMetadata`` describing every output surface.
Caching lives in ``state_readers``; the composer itself is stateless.

Three scopes:
    * ``vod_boundary`` — full description + chapter markers for an
      outgoing VOD; new title for the next live broadcast.
    * ``live_update`` — short description + title refresh while live.
    * ``cross_surface`` — Bluesky / Discord / Mastodon variants, usually
      triggered by a high-salience chronicle event.

LLM use is opt-in: if resident Command-R is reachable, the narrative
prose for title + description goes through the local grounded model with
a scientific-register prompt. If the call fails, the composer falls back to the
deterministic prose assembled from ``framing``. The structured outputs
(tags, chapters, char-limited variants) are always deterministic.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from agents.metadata_composer import chapters as _chapters
from agents.metadata_composer import framing, redaction, state_readers
from agents.metadata_composer.chapters import ChapterMarker
from shared.resident_command_r import call_resident_command_r

log = logging.getLogger(__name__)

Scope = Literal["vod_boundary", "live_update", "cross_surface"]


# ── per-surface character ceilings (YouTube + cross-surface 2026) ─────────
TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 5000
TAGS_TOTAL_LIMIT = 500
SHORTS_CAPTION_LIMIT = 100
BLUESKY_LIMIT = 300
DISCORD_TITLE_LIMIT = 256
DISCORD_DESCRIPTION_LIMIT = 4096
MASTODON_LIMIT = 500


class ComposedMetadata(BaseModel):
    """Output surface for one composer call.

    All fields are populated for every scope; per-scope relevance varies
    (e.g. ``description_chapters`` is None during ``live_update``). The
    ``grounding_provenance`` field is for audit — which input sources
    actually contributed to this composition.
    """

    title: str = Field(..., max_length=TITLE_LIMIT)
    description: str = Field(..., max_length=DESCRIPTION_LIMIT)
    description_chapters: list[ChapterMarker] | None = None
    tags: list[str] = Field(default_factory=list)
    shorts_caption: str = Field("", max_length=SHORTS_CAPTION_LIMIT)
    bluesky_post: str = Field("", max_length=BLUESKY_LIMIT)
    discord_embed_title: str = Field("", max_length=DISCORD_TITLE_LIMIT)
    discord_embed_description: str = Field("", max_length=DISCORD_DESCRIPTION_LIMIT)
    mastodon_post: str = Field("", max_length=MASTODON_LIMIT)
    pinned_comment: str = ""
    grounding_provenance: dict[str, Any] = Field(default_factory=dict)


def compose_metadata(
    scope: Scope,
    *,
    broadcast_id: str | None = None,
    vod_time_range: tuple[float, float] | None = None,
    triggering_event: dict | None = None,
    llm_call: Any | None = None,
) -> ComposedMetadata:
    """Compose metadata for the given scope.

    ``broadcast_id`` and ``vod_time_range`` are required for
    ``vod_boundary``; ``triggering_event`` is required for
    ``cross_surface``. ``live_update`` only needs ``broadcast_id`` (used
    in pinned-comment context but not load-bearing).

    ``llm_call`` is a test-injection hook. Production callers leave it
    None and the composer dispatches to ``_call_llm_resident_command_r``; tests can
    pass a stub returning the deterministic prose they expect.

    The composer picks one operator referent per call via
    ``shared.operator_referent.OperatorReferentPicker`` (per directive
    `su-non-formal-referent-001`) and threads it through the LLM prompt
    so all metadata surfaces for one VOD stay internally consistent. The
    picker import is soft — if the module is not yet present (pre-PR
    #1277 merge), referent-aware prompt-clauses are simply omitted.
    """
    state = state_readers.snapshot()
    referent = _pick_referent(scope, broadcast_id, triggering_event)
    grounding: dict[str, Any] = {
        "working_mode": state.working_mode,
        "programme_role": state.programme.role.value if state.programme else None,
        "stimmung_tone": state.stimmung_tone,
        "director_activity": state.director_activity,
        "scope": scope,
        "operator_referent": referent,
    }

    if scope == "vod_boundary":
        if vod_time_range is None:
            raise ValueError("vod_boundary scope requires vod_time_range=(start, end)")
        return _compose_vod_boundary(state, vod_time_range, grounding, llm_call, referent)

    if scope == "live_update":
        return _compose_live_update(state, grounding, llm_call, referent)

    if scope == "cross_surface":
        if triggering_event is None:
            raise ValueError("cross_surface scope requires triggering_event")
        return _compose_cross_surface(state, triggering_event, grounding, llm_call, referent)

    raise ValueError(f"unknown scope: {scope!r}")


def _pick_referent(
    scope: Scope, broadcast_id: str | None, triggering_event: dict | None
) -> str | None:
    """Pick one operator referent for this composition.

    Sticky-per-VOD seeding: a given ``broadcast_id`` always resolves to
    the same referent so all metadata for one VOD reads with one voice.
    Cross-surface posts seed on the triggering event to keep federated
    posts about one moment internally consistent. Returns None if the
    picker module is unavailable so the composer ships standalone.
    """
    try:
        from shared.operator_referent import OperatorReferentPicker  # noqa: PLC0415
    except ImportError:
        return None

    if broadcast_id:
        return OperatorReferentPicker.pick_for_vod_segment(broadcast_id)
    if triggering_event is not None:
        ev_id = triggering_event.get("id") or str(triggering_event.get("ts", ""))
        return OperatorReferentPicker.pick(f"cross-surface-{ev_id}")
    return OperatorReferentPicker.pick()


# ── per-scope composition ──────────────────────────────────────────────────


def _compose_vod_boundary(
    state: state_readers.StateSnapshot,
    vod_time_range: tuple[float, float],
    grounding: dict[str, Any],
    llm_call: Any,
    referent: str | None,
) -> ComposedMetadata:
    start, end = vod_time_range
    chapter_list = _chapters.extract_chapters(
        state_readers.read_chronicle(since=start, until=end),
        vod_start_s=start,
    )
    grounding["chapter_count"] = len(chapter_list)

    title_seed = framing.compose_title_seed(state)
    description_seed = framing.compose_description_seed(state, scope="vod_boundary")
    title = _maybe_llm_polish(
        title_seed, scope="vod_boundary", llm_call=llm_call, referent=referent
    )
    title = framing.enforce_register(title, fallback=title_seed)[:TITLE_LIMIT]
    description_body = _maybe_llm_polish(
        description_seed,
        scope="vod_boundary",
        llm_call=llm_call,
        kind="description",
        referent=referent,
    )
    description_body = framing.enforce_register(description_body, fallback=description_seed)
    description_body = redaction.redact_capabilities(description_body, state.programme)

    description = _format_description_with_chapters(description_body, chapter_list)[
        :DESCRIPTION_LIMIT
    ]

    tags = framing.compose_tags(state)
    shorts = framing.compose_shorts_caption(state)
    bluesky = framing.compose_bluesky_post(state, scope="vod_boundary")
    disco_title, disco_desc = framing.compose_discord_embed(state, scope="vod_boundary")
    masto = framing.compose_mastodon_post(state, scope="vod_boundary")
    pinned = framing.compose_pinned_comment(state, chapter_list)

    return ComposedMetadata(
        title=title,
        description=description,
        description_chapters=chapter_list,
        tags=_truncate_tags(tags),
        shorts_caption=shorts[:SHORTS_CAPTION_LIMIT],
        bluesky_post=bluesky[:BLUESKY_LIMIT],
        discord_embed_title=disco_title[:DISCORD_TITLE_LIMIT],
        discord_embed_description=disco_desc[:DISCORD_DESCRIPTION_LIMIT],
        mastodon_post=masto[:MASTODON_LIMIT],
        pinned_comment=pinned,
        grounding_provenance=grounding,
    )


def _compose_live_update(
    state: state_readers.StateSnapshot,
    grounding: dict[str, Any],
    llm_call: Any,
    referent: str | None,
) -> ComposedMetadata:
    title_seed = framing.compose_title_seed(state)
    description_seed = framing.compose_description_seed(state, scope="live_update")
    title = _maybe_llm_polish(title_seed, scope="live_update", llm_call=llm_call, referent=referent)
    title = framing.enforce_register(title, fallback=title_seed)[:TITLE_LIMIT]
    description_body = _maybe_llm_polish(
        description_seed,
        scope="live_update",
        llm_call=llm_call,
        kind="description",
        referent=referent,
    )
    description_body = framing.enforce_register(description_body, fallback=description_seed)
    description_body = redaction.redact_capabilities(description_body, state.programme)

    return ComposedMetadata(
        title=title,
        description=description_body[:DESCRIPTION_LIMIT],
        description_chapters=None,
        tags=_truncate_tags(framing.compose_tags(state)),
        shorts_caption=framing.compose_shorts_caption(state)[:SHORTS_CAPTION_LIMIT],
        bluesky_post=framing.compose_bluesky_post(state, scope="live_update")[:BLUESKY_LIMIT],
        discord_embed_title=framing.compose_discord_embed(state, scope="live_update")[0][
            :DISCORD_TITLE_LIMIT
        ],
        discord_embed_description=framing.compose_discord_embed(state, scope="live_update")[1][
            :DISCORD_DESCRIPTION_LIMIT
        ],
        mastodon_post=framing.compose_mastodon_post(state, scope="live_update")[:MASTODON_LIMIT],
        pinned_comment="",
        grounding_provenance=grounding,
    )


def _compose_cross_surface(
    state: state_readers.StateSnapshot,
    triggering_event: dict,
    grounding: dict[str, Any],
    llm_call: Any,
    referent: str | None,
) -> ComposedMetadata:
    grounding["triggering_event_kind"] = triggering_event.get("event_type")
    grounding["triggering_event_salience"] = triggering_event.get("payload", {}).get("salience")

    title_seed = framing.compose_title_seed(state)
    description_seed = framing.compose_event_description(state, triggering_event)
    description_body = framing.enforce_register(description_seed, fallback=description_seed)
    description_body = redaction.redact_capabilities(description_body, state.programme)

    bluesky = framing.compose_bluesky_post(
        state, scope="cross_surface", triggering_event=triggering_event
    )
    disco_title, disco_desc = framing.compose_discord_embed(
        state, scope="cross_surface", triggering_event=triggering_event
    )
    masto = framing.compose_mastodon_post(
        state, scope="cross_surface", triggering_event=triggering_event
    )

    return ComposedMetadata(
        title=title_seed[:TITLE_LIMIT],
        description=description_body[:DESCRIPTION_LIMIT],
        description_chapters=None,
        tags=_truncate_tags(framing.compose_tags(state)),
        shorts_caption=framing.compose_shorts_caption(state)[:SHORTS_CAPTION_LIMIT],
        bluesky_post=bluesky[:BLUESKY_LIMIT],
        discord_embed_title=disco_title[:DISCORD_TITLE_LIMIT],
        discord_embed_description=disco_desc[:DISCORD_DESCRIPTION_LIMIT],
        mastodon_post=masto[:MASTODON_LIMIT],
        pinned_comment="",
        grounding_provenance=grounding,
    )


# ── helpers ────────────────────────────────────────────────────────────────


def _format_description_with_chapters(body: str, chapter_list: list[ChapterMarker]) -> str:
    if not chapter_list:
        return body
    lines = [_format_chapter_line(c) for c in chapter_list]
    return "\n".join(lines) + "\n\n" + body


def _format_chapter_line(c: ChapterMarker) -> str:
    h, rem = divmod(int(c.timestamp_s), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d} {c.label}"
    return f"{m:02d}:{s:02d} {c.label}"


def _truncate_tags(tags: list[str]) -> list[str]:
    """Keep tags whose total comma-separated length stays within YouTube's 500-char cap."""
    out: list[str] = []
    total = 0
    for tag in tags:
        candidate = total + len(tag) + (1 if out else 0)
        if candidate > TAGS_TOTAL_LIMIT:
            break
        out.append(tag)
        total = candidate
    return out


def _maybe_llm_polish(
    seed: str,
    *,
    scope: Scope,
    llm_call: Any,
    kind: str = "title",
    referent: str | None = None,
) -> str:
    """Return the LLM-polished string or the seed on any failure."""
    if llm_call is None:
        llm_call = _call_llm_resident_command_r
    try:
        polished = llm_call(seed=seed, scope=scope, kind=kind, referent=referent)
        if polished and isinstance(polished, str):
            return polished.strip()
    except Exception as exc:
        log.warning("llm polish failed for %s/%s: %s", scope, kind, exc)
    return seed


def _call_llm_resident_command_r(
    *, seed: str, scope: Scope, kind: str, referent: str | None = None
) -> str | None:
    """Best-effort LLM polish via resident Command-R.

    Returns None on failure so callers fall back to the deterministic seed.
    """
    prompt = framing.build_llm_prompt(seed=seed, scope=scope, kind=kind, referent=referent)
    try:
        return call_resident_command_r(
            prompt,
            max_tokens=512,
            temperature=0.5,
        )
    except Exception as exc:
        log.info("resident Command-R metadata polish failed: %s", exc)
        return None
