"""Registry of migrated CairoSource classes, keyed by class_name.

``SourceRegistry.construct_backend`` looks up cairo sources here by the
``params.class_name`` field from the Layout JSON so new sources can be
declared in config without editing a hardcoded dispatch table — drop a
module with a CairoSource subclass into the codebase, import it at the
bottom of this file, and it's declarable in any Layout.

The Phase 3b compositor-unification epic already migrated the four core
cairo sources into their ``*CairoSource`` classes (TokenPoleCairoSource,
AlbumOverlayCairoSource, SierpinskiCairoSource, OverlayZonesCairoSource).
This package re-exports three of them for the source-registry PR 1
default layout (OverlayZones is deliberately left out — it renders at
full canvas via DVD-bounce and isn't a natural-size PiP candidate; its
migration is a follow-up).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.studio_compositor.cairo_source import CairoSource

_CAIRO_SOURCE_CLASSES: dict[str, type[CairoSource]] = {}


def register(name: str, cls: type[CairoSource]) -> None:
    """Register a CairoSource subclass under ``name``.

    Idempotent on duplicate registration of the same class. Raises
    :class:`ValueError` if ``name`` is already bound to a different class —
    we fail loud rather than silently overwriting (silent-failure discipline).
    """
    existing = _CAIRO_SOURCE_CLASSES.get(name)
    if existing is None:
        _CAIRO_SOURCE_CLASSES[name] = cls
        return
    if existing is cls:
        return
    raise ValueError(
        f"cairo_sources: name {name!r} already bound to {existing.__name__}, not {cls.__name__}"
    )


def get_cairo_source_class(name: str) -> type[CairoSource]:
    """Return the CairoSource subclass registered under ``name``.

    Raises :class:`KeyError` with the unknown name if not registered.
    """
    try:
        return _CAIRO_SOURCE_CLASSES[name]
    except KeyError as e:
        raise KeyError(f"cairo source class not registered: {name}") from e


def list_classes() -> list[str]:
    """Return the sorted list of registered class names."""
    return sorted(_CAIRO_SOURCE_CLASSES.keys())


# --- Built-in registrations -------------------------------------------------
#
# Import the three migrated classes at module load time so they show up in
# ``list_classes()`` and ``get_cairo_source_class()`` without the caller
# having to import them. Each import is late (inside a function) only to
# break circular imports between cairo_source and cairo_sources — direct
# imports are fine here.


def _register_builtins() -> None:
    from agents.studio_compositor.album_overlay import AlbumOverlayCairoSource
    from agents.studio_compositor.captions_source import CaptionsCairoSource
    from agents.studio_compositor.cbip_signal_density import (
        CBIPSignalDensityCairoSource,
    )

    # HOMAGE follow-on #123 (2026-04-18) — ChatAmbientWard replaces the
    # static ChatKeywordLegendCairoSource with a dynamic, aggregate-only
    # BitchX-grammar chat surface. HOTFIX 2026-04-19: ChatKeywordLegendCairoSource
    # is still referenced by existing layout JSONs (default.json + garage-door
    # .json); re-register it under both names until the layouts catch up.
    from agents.studio_compositor.chat_ambient_ward import ChatAmbientWard
    from agents.studio_compositor.hothouse_sources import (
        ActivityVarietyLogCairoSource,
        ImpingementCascadeCairoSource,
        PressureGaugeCairoSource,
        RecruitmentCandidatePanelCairoSource,
        ThinkingIndicatorCairoSource,
        WhosHereCairoSource,
    )
    from agents.studio_compositor.legibility_sources import (
        ActivityHeaderCairoSource,
        ChatKeywordLegendCairoSource,
        GroundingProvenanceTickerCairoSource,
        StanceIndicatorCairoSource,
    )
    from agents.studio_compositor.research_marker_overlay import ResearchMarkerOverlay
    from agents.studio_compositor.sierpinski_renderer import SierpinskiCairoSource
    from agents.studio_compositor.stream_overlay import StreamOverlayCairoSource
    from agents.studio_compositor.token_pole import TokenPoleCairoSource

    register("TokenPoleCairoSource", TokenPoleCairoSource)
    register("AlbumOverlayCairoSource", AlbumOverlayCairoSource)
    register("CBIPSignalDensityCairoSource", CBIPSignalDensityCairoSource)
    register("SierpinskiCairoSource", SierpinskiCairoSource)
    # LRR Phase 9 §3.6 — scientific-register caption overlay. The
    # production default layout retired captions at GEM cutover; keep
    # the class registered for legacy rollback layouts and direct source
    # tests until those surfaces are explicitly removed.
    register("CaptionsCairoSource", CaptionsCairoSource)
    # Phase 4 legibility surfaces — volitional-director epic (PR #1017 §3.5).
    # Make the directorial intent visible to viewers on every frame.
    register("ActivityHeaderCairoSource", ActivityHeaderCairoSource)
    register("StanceIndicatorCairoSource", StanceIndicatorCairoSource)
    # HOMAGE follow-on #123 (2026-04-18) — ChatAmbientWard is the
    # dynamic, aggregate-only replacement. HOTFIX 2026-04-19: both
    # classes are registered until layout JSONs migrate to ChatAmbientWard.
    # Once the migration lands (separate PR), ChatKeywordLegendCairoSource
    # can be removed.
    register("ChatAmbientWard", ChatAmbientWard)
    register("ChatKeywordLegendCairoSource", ChatKeywordLegendCairoSource)
    register(
        "GroundingProvenanceTickerCairoSource",
        GroundingProvenanceTickerCairoSource,
    )
    # Post-epic layout fix: StreamOverlayCairoSource renders the
    # preset/viewers/chat-activity three-line status strip, anchored
    # to the bottom-right of whatever canvas it is drawn into. It
    # feeds the ``stream_overlay`` source in the default layout's
    # ``pip-lr`` quadrant — operator's "chat stats LR" default.
    register("StreamOverlayCairoSource", StreamOverlayCairoSource)
    # Phase 10 carry-over from Phase 2 item 4: expose the research
    # marker overlay in the class-name registry so it's declarable
    # from layout JSON. Actual layout surface + assignment is a
    # separate operator-owned decision (the overlay is a top-strip
    # banner so it needs a full-width surface, unlike the other PiP
    # cairo sources). Registering here unblocks ``ResearchMarkerOverlay``
    # layout declarations without forcing a default-layout change.
    register("ResearchMarkerOverlay", ResearchMarkerOverlay)
    # Epic 2 Phase C (2026-04-17) — hothouse pressure surfaces. Make the
    # director's presence and recruitment pressure unavoidable on every
    # frame. Operator directive: "evidence of ALL recruitment potential
    # and impingement pressure".
    register("ImpingementCascadeCairoSource", ImpingementCascadeCairoSource)
    register("RecruitmentCandidatePanelCairoSource", RecruitmentCandidatePanelCairoSource)
    register("ThinkingIndicatorCairoSource", ThinkingIndicatorCairoSource)
    register("PressureGaugeCairoSource", PressureGaugeCairoSource)
    register("ActivityVarietyLogCairoSource", ActivityVarietyLogCairoSource)
    # Epic 2 Phase D (2026-04-17) — operator-always-here audience framing.
    register("WhosHereCairoSource", WhosHereCairoSource)
    # HOMAGE follow-on #159 (2026-04-18) — vinyl-platter ward. Registered
    # but NOT added to the default layout; operator declares a vinyl-focus
    # layout (see config/compositor-layouts/examples/vinyl-focus.json)
    # when the platter ward should appear on the stream.
    from agents.studio_compositor.vinyl_platter import VinylPlatterCairoSource

    register("VinylPlatterCairoSource", VinylPlatterCairoSource)
    # GEM (Graffiti Emphasis Mural) — 15th HOMAGE ward, operator-directed
    # 2026-04-19 (b6ec4a723). Replaces captions in the lower-band
    # geometry. See docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md.
    from agents.studio_compositor.gem_source import GemCairoSource

    register("GemCairoSource", GemCairoSource)
    # ytb-LORE-MVP PR A (2026-04-24) — chronicle-ticker lore-surface ward.
    # Default OFF via HAPAX_LORE_CHRONICLE_TICKER_ENABLED; registered so
    # layout JSON can declare it independent of the flag.
    from agents.studio_compositor.chronicle_ticker import ChronicleTickerCairoSource

    register("ChronicleTickerCairoSource", ChronicleTickerCairoSource)
    # ytb-LORE-MVP PR B (2026-04-24) — programme-state lore-surface ward.
    # Default OFF via HAPAX_LORE_PROGRAMME_STATE_ENABLED.
    from agents.studio_compositor.programme_state_ward import ProgrammeStateCairoSource

    register("ProgrammeStateCairoSource", ProgrammeStateCairoSource)
    # ward-programme-history-e-panel (2026-05-04) — Enlightenment-GTK +
    # BitchX HOMAGE Ward hybrid epic. Multi-session arc surface using
    # the Moksha curly-chrome aesthetic from PR #1314
    # (ytb-AUTH-ENLIGHTENMENT-package). Default OFF via
    # HAPAX_LORE_PROGRAMME_HISTORY_ENABLED so the operator can flip it
    # after a visual sign-off without forcing default-layout changes.
    from agents.studio_compositor.programme_history_ward import (
        ProgrammeHistoryCairoSource,
    )

    register("ProgrammeHistoryCairoSource", ProgrammeHistoryCairoSource)
    # ward-precedent-ticker-bitchx (cc-task, 2026-05-04) — axiom precedent
    # history ward. BitchX-grammar header + most-recent N precedents by
    # ratification date. Default OFF via HAPAX_LORE_PRECEDENT_TICKER_ENABLED;
    # registered so layout JSON can declare it independent of the flag.
    from agents.studio_compositor.precedent_ticker_ward import (
        PrecedentTickerCairoSource,
    )

    register("PrecedentTickerCairoSource", PrecedentTickerCairoSource)
    # programme-banner-ward (PR #2366, 2026-05-03) — Cairo lower-third
    # surfacing the active programme's role + narrative_beat + residual
    # time. Per /tmp/wsjf-path-content-programming.md §3 G1: the planner
    # is emitting role + narrative_beat per programme but the livestream
    # had no surface naming the active programme. Registered here so it
    # can be declared from layout JSON; default-layout assignment is a
    # separate operator-owned decision (anchors bottom-left, would
    # collide with album cover on default layout).
    from agents.studio_compositor.programme_banner_ward import ProgrammeBannerWard

    register("ProgrammeBannerWard", ProgrammeBannerWard)
    # DURF (Display Under Reflective Frame) — 2026-04-24T23:10Z operator
    # directive. First full-frame HOMAGE ward. Text-only tmux-capture of
    # the 4-session Claude-Code coordination setup. Design:
    # docs/research/2026-04-24-durf-design.md.
    from agents.studio_compositor.durf_source import DURFCairoSource

    register("DURFCairoSource", DURFCairoSource)
    # ef7b-165 Phase 9 Part 2 (2026-04-24) — anti-personification egress
    # footer. Static text strip framing the channel as a research
    # instrument. Mounted in default.json; the source fails closed to an
    # empty render if Ring 2 validation rejects the text.
    from agents.studio_compositor.egress_footer_source import EgressFooterCairoSource

    register("EgressFooterCairoSource", EgressFooterCairoSource)
    from agents.studio_compositor.mobile_cairo_sources import (
        MobileActivityHeaderCairoSource,
        MobileCaptionsCairoSource,
        MobileImpingementCascadeCairoSource,
        MobileStanceIndicatorCairoSource,
        MobileTokenPoleCairoSource,
    )

    register("MobileActivityHeaderCairoSource", MobileActivityHeaderCairoSource)
    register("MobileStanceIndicatorCairoSource", MobileStanceIndicatorCairoSource)
    register("MobileImpingementCascadeCairoSource", MobileImpingementCascadeCairoSource)
    register("MobileTokenPoleCairoSource", MobileTokenPoleCairoSource)
    register("MobileCaptionsCairoSource", MobileCaptionsCairoSource)


_register_builtins()
