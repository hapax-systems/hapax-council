"""Segment director action materializer.

The segment director already authors *declared directorial needs* — the
``source_affordance_kinds`` a beat wants on screen (``source_card``,
``ranked_list_visible``, ``media_locator`` …) and the typed
``beat_action_intents`` (``show_evidence``/``compare_referents``/``cite_source``).
Until now nothing turned those declarations into *surface actions*: the
runner refused every beat with ``no_layout_needs`` and authored assets were
narrated as ``[IMAGE] caption`` text instead of shown.

This module is the missing executor. For each declared need it builds an
:class:`~shared.impingement.Impingement` whose narrative encodes the need's
semantics plus the beat text, then asks the live recruitment Via
(``AffordancePipeline.select``) to *score* it against the affordance
catalogue. The recruited capability is whatever wins the scoring — there is
deliberately **no** ``if need == X: show_card`` lookup table. A need→move
table would re-introduce exactly the brittle dispatcher the unified
recruitment model is killing, so it is a hard architectural reject. The need
selects a *capability* only through cosine similarity + base-level + Thompson
sampling inside ``select`` — never through a branch on ``need_kind``.

Downstream, recruited compositional capabilities are dispatched through the
one live ``compositional_consumer.dispatch`` Via; the layout-posture side is
fed by the existing bounded normaliser so the runner stops refusing. Media
moves (image/youtube) pass an egress gate before broadcast.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from shared.impingement import Impingement, ImpingementType

log = logging.getLogger(__name__)

# Mirror the live consumer's dispatch gate (run_loops_aux: combined >= 0.3).
DEFAULT_RECRUIT_THRESHOLD = 0.3
DEFAULT_TOP_K = 10
# Salience-integration impingements from authored segment needs carry a fixed,
# moderate activation: the segment *declared* the need, so it is real, but it
# is prepared rather than urgent. Real urgency still comes from live ticks.
DEFAULT_NEED_STRENGTH = 0.7


class SelectionCandidateLike(Protocol):
    capability_name: str
    combined: float


SelectFn = Callable[..., Sequence[SelectionCandidateLike]]


@dataclass(frozen=True)
class DeclaredNeed:
    """One declared directorial need resolved from a segment beat.

    ``need_kind`` is the semantic declaration (a ``source_affordance_kind`` or
    an authored ``ActionIntentKind``); it is encoded into the recruitment
    narrative and is NEVER switched on to choose a capability.
    """

    need_kind: str
    beat_text: str = ""
    role: str | None = None
    evidence_refs: tuple[str, ...] = ()
    origin: str = "source_affordance_kind"
    object_ref: str | None = None
    media_kind: str | None = None  # "image" | "youtube" when asset-backed


@dataclass(frozen=True)
class MaterializedAction:
    """A surface action recruited for one declared need."""

    need_kind: str
    capability: str
    score: float
    narrative: str
    origin: str = "source_affordance_kind"
    evidence_refs: tuple[str, ...] = ()
    object_ref: str | None = None
    media_kind: str | None = None


@dataclass(frozen=True)
class MediaMove:
    """One gated media surface action (image blit / YT-on-OARB cue)."""

    object_ref: str
    media_kind: str
    outcome: str
    cued: bool


@dataclass(frozen=True)
class MaterializationReceipt:
    """What one beat materialised: recruited effects, media, layout pressure."""

    programme_id: str | None
    beat_index: int | None
    recruited: tuple[MaterializedAction, ...] = ()
    media: tuple[MediaMove, ...] = ()
    layout_intents: tuple[Any, ...] = ()
    reused: bool = False

    @property
    def rendered_object_refs(self) -> tuple[str, ...]:
        """Media object_refs that were permitted to render (for readback)."""

        return tuple(move.object_ref for move in self.media if move.cued)


# (object_ref, media_kind) -> gate decision / cued-bool.
DispatchFn = Callable[["MaterializedAction"], bool]
CueMediaFn = Callable[[str, str], bool]


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _youtube_id(url: str) -> str:
    """Extract a stable youtube identifier from a watch/short URL.

    Falls back to the raw URL when no id can be parsed, so the object_ref is
    always deterministic for readback comparison.
    """

    for marker in ("v=", "youtu.be/", "/embed/", "/shorts/"):
        if marker in url:
            tail = url.split(marker, 1)[1]
            for sep in ("&", "?", "/"):
                tail = tail.split(sep, 1)[0]
            if tail:
                return tail
    return url


def media_object_ref(media_kind: str, url: str) -> str:
    """Deterministic object_ref for an asset, used by the rendered-readback."""

    if media_kind == "youtube":
        return f"object:yt:{_youtube_id(url)}"
    basename = url.rstrip("/").rsplit("/", 1)[-1] or url
    return f"object:image:{basename}"


def beat_key(segment_doc: Mapping[str, Any]) -> tuple[str | None, int | None]:
    """Identity of the active beat: (programme_id, beat_index)."""

    programme_id = _str(segment_doc.get("programme_id"))
    raw_index = segment_doc.get("current_beat_index")
    beat_index = (
        raw_index if isinstance(raw_index, int) and not isinstance(raw_index, bool) else None
    )
    return (programme_id, beat_index)


def declared_needs_from_segment(
    segment_doc: Mapping[str, Any],
    *,
    assets: Sequence[Mapping[str, Any]] = (),
) -> tuple[DeclaredNeed, ...]:
    """Resolve a beat's declared needs from active-segment + playback assets.

    Three sources, in declaration order: ``source_affordance_kinds`` (the
    role's abstract directorial needs), authored ``current_beat_action_intents``
    (typed action kinds, excluding ``narrate``), and media ``assets``
    (image/youtube). Abstract needs are recruited parametrically; media needs
    carry ``media_kind`` and an ``object_ref`` for type-based rendering.
    """

    if not isinstance(segment_doc, Mapping) or not _str(segment_doc.get("programme_id")):
        return ()

    role = _str(segment_doc.get("role"))
    beat_text = (
        _str(segment_doc.get("narrative_beat")) or _str(segment_doc.get("current_beat_text")) or ""
    )
    source_refs = tuple(_str_list(segment_doc.get("source_refs")))

    needs: list[DeclaredNeed] = []
    seen: set[tuple[str, str]] = set()

    def _add(need: DeclaredNeed, dedupe_value: str) -> None:
        key = (need.origin, dedupe_value)
        if key in seen:
            return
        seen.add(key)
        needs.append(need)

    for kind in _str_list(segment_doc.get("source_affordance_kinds")):
        _add(
            DeclaredNeed(
                need_kind=kind,
                beat_text=beat_text,
                role=role,
                evidence_refs=source_refs,
                origin="source_affordance_kind",
            ),
            kind,
        )

    for declaration in segment_doc.get("current_beat_action_intents") or []:
        if not isinstance(declaration, Mapping):
            continue
        for intent in declaration.get("intents") or []:
            if not isinstance(intent, Mapping):
                continue
            kind = _str(intent.get("kind"))
            if not kind or kind == "narrate":
                continue
            evidence = tuple(_str_list(intent.get("evidence_refs"))) or source_refs
            _add(
                DeclaredNeed(
                    need_kind=kind,
                    beat_text=beat_text,
                    role=role,
                    evidence_refs=evidence,
                    origin="beat_action_intent",
                ),
                kind,
            )

    for asset in assets or []:
        if not isinstance(asset, Mapping):
            continue
        media_kind = _str(asset.get("kind"))
        if media_kind not in {"image", "youtube"}:
            continue
        url = _str(asset.get("url"))
        if not url:
            continue
        object_ref = media_object_ref(media_kind, url)
        _add(
            DeclaredNeed(
                need_kind=("show_image" if media_kind == "image" else "play_youtube_on_oarb"),
                beat_text=_str(asset.get("caption")) or beat_text,
                role=role,
                evidence_refs=source_refs,
                origin="asset",
                object_ref=object_ref,
                media_kind=media_kind,
            ),
            object_ref,
        )

    return tuple(needs)


def _layout_pressure_kind_for_need(need: DeclaredNeed) -> str | None:
    """Normalise a declared need into the bounded layout-pressure vocabulary.

    Reuses the runner's supported-kind set directly and the contract's
    ``_layout_need_for_action_intent`` for authored ``ActionIntentKind`` —
    there is no new need->layout table here. Effect/media needs and needs
    outside the bounded layout vocabulary return ``None`` (they are recruited
    or rendered, never postured).
    """

    from agents.studio_compositor.layout_tick_driver import (
        SUPPORTED_SEGMENT_LAYOUT_PRESSURE_KINDS,
    )

    if need.media_kind is not None:
        return None
    if need.need_kind in SUPPORTED_SEGMENT_LAYOUT_PRESSURE_KINDS:
        return need.need_kind
    try:
        from agents.hapax_daimonion.segment_layout_contract import (
            ActionIntentKind,
            _layout_need_for_action_intent,
        )

        action_kind = ActionIntentKind(need.need_kind)
    except ValueError:
        return None
    if action_kind is ActionIntentKind.NARRATE:
        return None
    layout_need, _effect, _posture = _layout_need_for_action_intent(action_kind)
    value = str(layout_need.value)
    return value if value in SUPPORTED_SEGMENT_LAYOUT_PRESSURE_KINDS else None


def derive_layout_pressure_intents(
    segment_doc: Mapping[str, Any],
    *,
    now: float,
) -> tuple[Any, ...]:
    """Derive bounded layout-pressure intents the runner can posture on.

    The materializer's answer to ``no_layout_needs``: when a beat declares
    needs but authored no ``current_beat_layout_intents``, normalise the
    declared needs into proposal ``needs`` and run them through the runner's
    own ``_proposal_needs_to_intents`` parser so the result is identical to a
    file-authored proposal. Returns control-side ``SegmentActionIntent``s.
    """

    from agents.studio_compositor import layout_tick_driver

    _programme_id, beat_index = beat_key(segment_doc)
    proposal_needs: list[dict[str, Any]] = []
    for need in declared_needs_from_segment(segment_doc):
        kind = _layout_pressure_kind_for_need(need)
        if kind is None:
            continue
        proposal_needs.append({"kind": kind, "evidence_refs": list(need.evidence_refs)})
    if not proposal_needs:
        return ()
    intents, _refusals = layout_tick_driver._proposal_needs_to_intents(
        {"needs": proposal_needs},
        root=dict(segment_doc),
        index=0,
        now=now,
        prepared_artifact_ref=None,
        current_beat_index=beat_index,
    )
    return tuple(intents)


def _default_is_compositional(name: str) -> bool:
    """Whether ``name`` is a director/compositional capability.

    Delegates to the canonical predicate in ``compositional_consumer`` so the
    materializer and the dispatcher agree on what counts as a director move.
    """

    from agents.studio_compositor.compositional_consumer import is_compositional_capability

    return is_compositional_capability(name)


def _default_dispatch(action: MaterializedAction) -> bool:
    """Dispatch a recruited compositional effect through the live Via."""

    from agents.studio_compositor.compositional_consumer import RecruitmentRecord, dispatch

    record = RecruitmentRecord(
        name=action.capability,
        score=min(1.0, max(0.0, action.score)),
        impingement_narrative=action.narrative,
        ttl_s=30.0,
        request_id=f"segment-director:{action.need_kind}",
    )
    try:
        return dispatch(record) != "unknown"
    except Exception:
        log.warning("segment materializer dispatch failed", exc_info=True)
        return False


def _default_media_gate(object_ref: str, media_kind: str) -> Any:
    from agents.studio_compositor.media_egress_gate import gate_media_egress

    return gate_media_egress(object_ref, media_kind=media_kind)


def _default_cue_media(object_ref: str, media_kind: str) -> bool:
    """Cue a gated YT ref to the single OARB media-slot owner."""

    if media_kind != "youtube":
        return False
    from agents.studio_compositor.oarb_media_slot import cue_media_to_oarb

    try:
        return cue_media_to_oarb(object_ref).cued
    except Exception:
        log.warning("segment materializer OARB cue failed", exc_info=True)
        return False


def _humanize(need_kind: str) -> str:
    return need_kind.replace("_", " ").replace(".", " ").strip()


def _narrative_for_need(need: DeclaredNeed) -> str:
    """Build the recruitment-steering narrative for a declared need.

    One generic template for every need: the need's own words carry the
    semantics that ``select`` scores against. There is no per-need phrasing
    table.
    """

    human = _humanize(need.need_kind)
    parts = [f"surface the {human} for this segment beat so the audience can follow and verify it"]
    if need.beat_text:
        parts.append(need.beat_text.strip())
    return ": ".join(parts)


class SegmentActionMaterializer:
    """Recruit a surface action for a declared directorial need via scoring."""

    def __init__(
        self,
        *,
        select: SelectFn,
        is_compositional: Callable[[str], bool] = _default_is_compositional,
        dispatch: DispatchFn = _default_dispatch,
        cue_media: CueMediaFn = _default_cue_media,
        media_gate: Callable[[str, str], Any] = _default_media_gate,
        threshold: float = DEFAULT_RECRUIT_THRESHOLD,
        top_k: int = DEFAULT_TOP_K,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._select = select
        self._is_compositional = is_compositional
        self._dispatch = dispatch
        self._cue_media = cue_media
        self._media_gate = media_gate
        self._threshold = threshold
        self._top_k = top_k
        self._clock = clock
        # Loop-runaway guard: a beat materialises exactly once. Re-perceiving
        # the same beat returns the cached receipt instead of re-recruiting /
        # re-dispatching (a re-perceived "show image" can't recruit another).
        self._last_key: tuple[str | None, int | None] | None = None
        self._last_receipt: MaterializationReceipt | None = None

    def materialize_beat(
        self,
        segment_doc: Mapping[str, Any],
        *,
        assets: Sequence[Mapping[str, Any]] = (),
        now: float | None = None,
    ) -> MaterializationReceipt:
        """Resolve, recruit, gate, and dispatch one beat's surface actions.

        Idempotent per (programme_id, beat_index): the first call recruits and
        dispatches; subsequent calls for the same beat return the cached
        receipt with ``reused=True`` and perform no side effects.
        """

        ts = self._clock() if now is None else now
        programme_id, beat_index = beat_key(segment_doc)
        key = (programme_id, beat_index)
        if programme_id is not None and key == self._last_key and self._last_receipt is not None:
            return replace(self._last_receipt, reused=True)

        recruited: list[MaterializedAction] = []
        media: list[MediaMove] = []
        for need in declared_needs_from_segment(segment_doc, assets=assets):
            if need.media_kind is not None and need.object_ref:
                media.append(self._materialize_media(need))
                continue
            action = self.recruit_for_need(need)
            if action is not None and self._dispatch(action):
                recruited.append(action)

        receipt = MaterializationReceipt(
            programme_id=programme_id,
            beat_index=beat_index,
            recruited=tuple(recruited),
            media=tuple(media),
            layout_intents=derive_layout_pressure_intents(segment_doc, now=ts),
        )
        if programme_id is not None:
            self._last_key = key
            self._last_receipt = receipt
        return receipt

    def _materialize_media(self, need: DeclaredNeed) -> MediaMove:
        """Gate a media need; cue YT to the OARB owner (image is ward-rendered)."""

        assert need.object_ref is not None and need.media_kind is not None
        decision = self._media_gate(need.object_ref, need.media_kind)
        cued = False
        if getattr(decision, "allowed", False) and decision.media_ref is not None:
            if need.media_kind == "youtube":
                cued = bool(self._cue_media(decision.media_ref, need.media_kind))
            else:
                # Image is blitted by the reveal ward (which gates at render);
                # a permitted decision means it may render — recorded for readback.
                cued = True
        return MediaMove(
            object_ref=need.object_ref,
            media_kind=need.media_kind,
            outcome=str(decision.outcome.value),
            cued=cued,
        )

    def impingement_for_need(self, need: DeclaredNeed) -> Impingement:
        """Build the recruitment impingement for a declared need."""

        narrative = _narrative_for_need(need)
        content: dict[str, Any] = {
            "narrative": narrative,
            "metric": need.need_kind,
            "evidence_refs": list(need.evidence_refs),
            "role_context": need.role or "",
        }
        if need.object_ref:
            content["object_ref"] = need.object_ref
        return Impingement(
            timestamp=self._clock(),
            source="segment_director.materializer",
            type=ImpingementType.SALIENCE_INTEGRATION,
            strength=DEFAULT_NEED_STRENGTH,
            content=content,
        )

    def recruit_for_need(
        self,
        need: DeclaredNeed,
        *,
        context: dict[str, Any] | None = None,
    ) -> MaterializedAction | None:
        """Recruit the best-scoring compositional capability for ``need``.

        Returns ``None`` when nothing scores above threshold — the need simply
        does not materialise this tick, rather than forcing a fallback move.
        """

        impingement = self.impingement_for_need(need)
        candidates = self._select(impingement, top_k=self._top_k, context=context)
        for candidate in candidates:
            name = getattr(candidate, "capability_name", None)
            if not isinstance(name, str) or not name:
                continue
            combined = float(getattr(candidate, "combined", 0.0))
            if combined < self._threshold:
                continue
            if not self._is_compositional(name):
                continue
            return MaterializedAction(
                need_kind=need.need_kind,
                capability=name,
                score=combined,
                narrative=impingement.content["narrative"],
                origin=need.origin,
                evidence_refs=need.evidence_refs,
                object_ref=need.object_ref,
                media_kind=need.media_kind,
            )
        return None


__all__ = [
    "DeclaredNeed",
    "MaterializationReceipt",
    "MaterializedAction",
    "MediaMove",
    "SegmentActionMaterializer",
    "beat_key",
    "declared_needs_from_segment",
    "derive_layout_pressure_intents",
    "media_object_ref",
]
