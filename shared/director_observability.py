"""Director observability — Prometheus metrics per volitional-director epic §3.6.

Emit counters/histograms for each directorial intent + twitch move +
structural intent. All labels carry `condition_id` so the LRR Phase 10
per-condition slicing still applies. JSONL emission already happens in
`agents/studio_compositor/director_loop._emit_intent_artifacts` (Phase 1);
this module adds the Prometheus surface.

Consumers:
- Prometheus scrape on the compositor's existing exporter port
- Grafana dashboards — palette-coverage, grounding-signal distribution,
  director-latency percentiles
- RIFTS replay script reads the JSONL (not this module)

All emitters tolerate prometheus_client absence: if the import fails the
functions become no-ops. Never raise into the director's tick path.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from shared.director_intent import DirectorIntent

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _grounding_signal_whitelist() -> frozenset[str]:
    """Enumerate every dotted-path signal name reachable on PerceptualField.

    The director's grounding_provenance is LLM-emitted free text; if we
    forwarded it unbounded to a Prometheus label we would hit cardinality
    explosion. This walks the Pydantic schema once (cached) and returns
    the set of valid paths. Anything else is bucketed into "unrecognized".
    """
    from shared.perceptual_field import PerceptualField

    paths: set[str] = set()

    def _walk(model_cls: type[BaseModel], prefix: str) -> None:
        for field_name, field_info in model_cls.model_fields.items():
            dotted = f"{prefix}.{field_name}" if prefix else field_name
            paths.add(dotted)
            annotation = field_info.annotation
            try:
                if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                    _walk(annotation, dotted)
            except TypeError:
                continue

    _walk(PerceptualField, "")
    return frozenset(paths)


def canonicalize_grounding_signal(signal: str) -> str:
    """Return `signal` if it matches a known PerceptualField path, else "unrecognized"."""
    if not isinstance(signal, str):
        return "unrecognized"
    cleaned = signal.strip()
    if not cleaned:
        return "unrecognized"
    if cleaned in _grounding_signal_whitelist():
        return cleaned
    return "unrecognized"


def _synthetic_marker_family(marker: str) -> str:
    cleaned = marker.strip().lower()
    normalized = cleaned.replace("_", "-")
    if cleaned.startswith("inferred."):
        return "inferred"
    if cleaned.startswith("fallback."):
        return "fallback"
    if normalized.startswith("parser-error"):
        return "parser-error"
    if normalized.startswith("silence-hold"):
        return "silence-hold"
    return "other"


_METRICS_AVAILABLE = False

try:
    from prometheus_client import Counter, Gauge, Histogram

    # Phase C1 (homage-completion-plan §2): the compositor runs its own
    # CollectorRegistry at ``agents.studio_compositor.metrics.REGISTRY``
    # and the :9482 HTTP exporter scrapes THAT registry — not the
    # prometheus_client default. Without explicit registration the
    # hapax_homage_* metrics land on the default registry and never
    # appear on the scrape surface the §7.3 verification protocol
    # queries. This block imports the compositor REGISTRY when the
    # compositor package is available and falls back to ``None``
    # (prometheus_client's default) when it isn't — keeping the
    # ``shared.director_observability`` module importable outside the
    # compositor process (officium, tests, one-off scripts).
    try:
        from agents.studio_compositor.metrics import (
            REGISTRY as _COMPOSITOR_REGISTRY,
        )
    except Exception:
        _COMPOSITOR_REGISTRY = None

    # Apply the compositor's CollectorRegistry to EVERY metric defined in
    # this module. The HOMAGE block below introduced this kwargs pattern
    # in 2026-04-13 but the director-tier metrics above never adopted it
    # — every Counter / Histogram from ``hapax_director_intent_total``
    # through ``hapax_random_mode_transition_total`` was landing on
    # prometheus_client's default registry and so never reached the
    # ``:9482`` scrape surface or Grafana. Lifted into a shared dict and
    # applied to every metric in this module so the director observability
    # contract is uniform. Outside the compositor process (officium,
    # tests, one-off scripts) ``_COMPOSITOR_REGISTRY`` is ``None`` and the
    # dict is empty, leaving the metrics on the default registry — the
    # previous behaviour for non-compositor environments.
    _metric_kwargs: dict = (
        {"registry": _COMPOSITOR_REGISTRY} if _COMPOSITOR_REGISTRY is not None else {}
    )

    _director_intent_total = Counter(
        "hapax_director_intent_total",
        "Director intents emitted, labelled by condition + activity + stance.",
        ("condition_id", "activity", "stance"),
        **_metric_kwargs,
    )
    _grounding_signal_total = Counter(
        "hapax_director_grounding_signal_used_total",
        "Grounding-provenance signal references per intent.",
        ("condition_id", "signal_name"),
        **_metric_kwargs,
    )
    _compositional_impingement_total = Counter(
        "hapax_director_compositional_impingement_total",
        "Compositional impingements emitted, labelled by intent family.",
        ("condition_id", "intent_family"),
        **_metric_kwargs,
    )
    _twitch_move_total = Counter(
        "hapax_director_twitch_move_total",
        "Twitch-director moves emitted, labelled by intent family.",
        ("condition_id", "intent_family"),
        **_metric_kwargs,
    )
    _structural_intent_total = Counter(
        "hapax_director_structural_intent_total",
        "Structural-director intents emitted.",
        ("condition_id", "scene_mode", "preset_family_hint"),
        **_metric_kwargs,
    )
    _llm_latency_seconds = Histogram(
        "hapax_director_llm_latency_seconds",
        "Director LLM call latency in seconds.",
        ("condition_id", "director_tier"),
        buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 45.0, 60.0, 120.0),
        **_metric_kwargs,
    )
    _intent_parse_failure_total = Counter(
        "hapax_director_intent_parse_failure_total",
        "LLM response failed to parse as DirectorIntent — fell back to legacy path.",
        ("condition_id", "director_tier"),
        **_metric_kwargs,
    )
    _vacuum_prevented_total = Counter(
        "hapax_director_vacuum_prevented_total",
        (
            "Parser-error / silence fallbacks where the no-vacuum invariant "
            "(operator 2026-04-18) populated a silence-hold impingement."
        ),
        ("condition_id", "director_tier", "reason"),
        **_metric_kwargs,
    )
    _random_mode_pick_total = Counter(
        "hapax_random_mode_pick_total",
        "random_mode preset picks, labelled by selection path.",
        ("chosen_via",),
        **_metric_kwargs,
    )
    _random_mode_transition_total = Counter(
        "hapax_random_mode_transition_total",
        "random_mode chain-change transition picks, by capability name (Phase 7 of #166).",
        ("transition",),
        **_metric_kwargs,
    )
    # Director watchdog Phase 2 (§8 single-flight): counts ticks where the
    # director was about to call the LLM but the prior call had not yet
    # returned. Each increment is one tick the director silently skipped
    # (the existing micromove-fallback path now fires on the empty-string
    # return, so the broadcast still gets a compositional impingement).
    _director_tick_skipped_in_flight_total = Counter(
        "hapax_director_tick_skipped_in_flight_total",
        "Director ticks skipped because the prior LLM call was still in flight.",
        ("reason",),
        **_metric_kwargs,
    )
    # HOMAGE framework metrics — spec §6.
    # Registered against the compositor's CollectorRegistry via the shared
    # ``_metric_kwargs`` dict above, so the :9482 scrape surface exposes
    # them. ``_homage_metric_kwargs`` is kept as an alias so existing
    # references (e.g. test scaffolding that pokes the kwargs dict by
    # name) keep working — both names point at the same dict.
    _homage_metric_kwargs = _metric_kwargs
    _homage_package_active = Gauge(
        "hapax_homage_package_active",
        "1 if the named HOMAGE package is currently active, 0 otherwise.",
        ("package",),
        **_homage_metric_kwargs,
    )
    # Phase C1 (homage-completion-plan §2): labels extended from
    # ``(package, transition_name)`` to ``(package, ward, transition_name,
    # phase)`` so Grafana can slice the transition rate by the ward that
    # transitioned and the phase (entry/exit/modify) the choreographer
    # classified it as. Reckoning §3.9: the §7.3 verification protocol
    # needs the phase axis to assert ``rate(transition_total{phase="entry"}
    # [5m]) > 0.05`` per ward.
    _homage_transition_total = Counter(
        "hapax_homage_transition_total",
        ("HOMAGE transitions applied, labelled by package + ward + transition kind + phase."),
        ("package", "ward", "transition_name", "phase"),
        **_homage_metric_kwargs,
    )
    _homage_choreographer_rejection_total = Counter(
        "hapax_homage_choreographer_rejection_total",
        "Pending transitions the choreographer rejected, by reason.",
        ("reason",),
        **_homage_metric_kwargs,
    )
    _homage_choreographer_substrate_skip_total = Counter(
        "hapax_homage_choreographer_substrate_skip_total",
        "Pending transitions skipped by the choreographer because the "
        "named source is marked as HomageSubstrateSource (always-on).",
        ("source",),
        **_homage_metric_kwargs,
    )
    _homage_violation_total = Counter(
        "hapax_homage_violation_total",
        "Paste / anti-pattern violations detected at render time.",
        ("package", "kind"),
        **_homage_metric_kwargs,
    )
    _homage_signature_artefact_emitted_total = Counter(
        "hapax_homage_signature_artefact_emitted_total",
        "Signature artefacts emitted, labelled by package + form.",
        ("package", "form"),
        **_homage_metric_kwargs,
    )
    # HOMAGE Phase C1 metrics — spec §6 / homage-completion-plan §C1.
    # All six together provide the framework-spec observability surface:
    # transition rate, emphasis rate, per-ward render cadence, active
    # rotation mode, active package, substrate saturation target. The
    # §7.3 verification protocol reads all of these via the Prometheus
    # scrape at ``:9482``.
    _homage_emphasis_applied_total = Counter(
        "hapax_homage_emphasis_applied_total",
        (
            "Ward-properties emphasis writes driven by a narrative-tier "
            "intent_family, labelled by ward + intent_family."
        ),
        ("ward", "intent_family"),
        **_homage_metric_kwargs,
    )
    _homage_render_cadence_hz = Gauge(
        "hapax_homage_render_cadence_hz",
        "Current per-ward render rate (successful ticks per second).",
        ("ward",),
        **_homage_metric_kwargs,
    )
    _homage_rotation_mode = Gauge(
        "hapax_homage_rotation_mode",
        (
            "HOMAGE rotation mode — 1.0 for the active mode, 0.0 for "
            "every other labelled series (one-hot over "
            "sequential/random/weighted_by_salience/paused)."
        ),
        ("mode",),
        **_homage_metric_kwargs,
    )
    _homage_active_package = Gauge(
        "hapax_homage_active_package",
        (
            "1.0 for the HOMAGE package currently broadcast by the "
            "choreographer, 0.0 for every other labelled series."
        ),
        ("package",),
        **_homage_metric_kwargs,
    )
    _homage_substrate_saturation_target = Gauge(
        "hapax_homage_substrate_saturation_target",
        (
            "Substrate palette saturation target the choreographer is "
            "broadcasting to the substrate sources (0.0–1.0)."
        ),
        **_homage_metric_kwargs,
    )
    # HARDM communicative-anchoring metrics — task #160.
    _hardm_salience_bias = Gauge(
        "hapax_hardm_salience_bias",
        "HARDM weighted presence bias in [0, 1]. >0.7 → unskippable.",
    )
    _hardm_emphasis_state = Gauge(
        "hapax_hardm_emphasis_state",
        "HARDM emphasis state: 1 if speaking, 0 if quiescent.",
    )
    _hardm_operator_cue_total = Counter(
        "hapax_hardm_operator_cue_total",
        "Sidechat point-at-hardm cues issued, labelled by cell.",
        ("cell",),
    )

    # Audio-pathways Phase 3 (#134) — voice-embedding ducking gate metrics.
    # Spec docs/superpowers/specs/2026-04-18-audio-pathways-audit-design.md §3.2.
    _audio_ducking_triggered = Counter(
        "hapax_audio_ducking_triggered_total",
        (
            "VAD ducking decisions, labelled by reason: "
            "vad_and_embedding (high-confidence operator speech), "
            "vad_only_fallback (VAD fired but embedding match below "
            "high threshold), no_duck_phantom (VAD fired but embedding "
            "match below low threshold — phantom VAD detected)."
        ),
        ("reason",),
    )
    _audio_echo_cancel_active = Gauge(
        "hapax_audio_echo_cancel_active",
        "1 iff the WebRTC echo-cancel virtual source is the active capture.",
    )
    _audio_phantom_vad_detected = Counter(
        "hapax_audio_phantom_vad_detected_total",
        (
            "Count of VAD trigger events the embedding gate identified as "
            "phantom (likely YouTube crossfeed or other non-operator "
            "voice). >0 = the gate is doing its job."
        ),
    )
    _audio_source_active = Gauge(
        "hapax_audio_source_active",
        "1.0 for the audio source the daimonion currently consumes; 0 for others.",
        ("source_name",),
    )

    # FINDING-X (2026-04-21 wiring audit): UNGROUNDED audit counter.
    # Per the constitutional invariant cited in DirectorIntent docstring
    # ("the audit emits an UNGROUNDED warning for the operator to track
    # in research-mode logs"), every empty grounding_provenance — both
    # at the top-level intent and per compositional_impingement — must
    # be observable. Pre-fix: 428/430 (99.5%) of impingements emitted
    # empty grounding_provenance with zero warnings. This counter +
    # ``emit_ungrounded_audit`` close the silent-violation gap.
    _ungrounded_total = Counter(
        "hapax_director_ungrounded_total",
        (
            "Director intents or compositional impingements emitted with "
            "empty grounding_provenance. Closes silent-violation gap from "
            "the 2026-04-21 wiring audit (FINDING-X)."
        ),
        ("condition_id", "scope"),  # scope ∈ {"intent", "impingement"}
    )

    # FINDING-X Phase 1 (2026-04-21): post-parse synthesis hook records each
    # impingement whose empty grounding_provenance was replaced by a synthetic
    # "inferred.<stance>.<family>" marker so missing LLM provenance stays
    # visible without being stored as real evidence.
    # Separate from _ungrounded_total: that counter keeps measuring raw LLM
    # compliance pre-synthesis; this counter surfaces how often we had to
    # synthesize. A rising synth rate signals LLM-compliance drift.
    _ungrounded_synth_total = Counter(
        "hapax_director_ungrounded_synth_total",
        (
            "CompositionalImpingements whose grounding_provenance was empty "
            "from the LLM and had to be synthesized to preserve the "
            "constitutional invariant. A rising rate indicates LLM-compliance "
            "drift."
        ),
        ("intent_family",),
    )
    # R8 (2026-05-02 effect+cam orchestration audit, §6 R8 / §4 F4):
    # grounding-act gate on every impingement. LLM-emitted impingements
    # that arrive with empty real grounding_provenance AND no
    # synthetic_grounding_markers (i.e. NOT a deterministic-code fallback
    # path) are rejected LOUDLY at the gate — counter increments,
    # warn-level log fires, the impingement is dropped from the
    # downstream list. Operator framing (2026-05-02): "currently silent
    # dropping = the bug" — silent post-hoc synthesis (FINDING-X Phase 1)
    # let downstream consumers treat ungrounded narratives as if they
    # carried evidence. The R8 gate replaces synthesis with rejection
    # so the LLM-compliance failure has surface-level consequence.
    _ungrounded_rejection_total = Counter(
        "hapax_director_ungrounded_rejection_total",
        (
            "LLM-emitted CompositionalImpingements rejected by the R8 "
            "grounding-act gate because grounding_provenance was empty "
            "and no deterministic-code fallback marker was set. The "
            "rejected impingement is dropped from the downstream list."
        ),
        ("intent_family",),
    )
    _synthetic_grounding_placeholder_total = Counter(
        "hapax_director_synthetic_grounding_placeholder_total",
        (
            "Director grounding placeholders recorded outside real "
            "grounding_provenance, labelled by scope and marker family."
        ),
        ("scope", "marker_family"),
        **_metric_kwargs,
    )

    # Cc-task ``director-moves-grounding-trace-coverage`` (operator outcome 3
    # follow-up). The R8 grounding-act gate already drops LLM impingements
    # missing both real and synthetic markers, but the operator wants
    # per-move classification visible on the Prometheus surface so a
    # Grafana panel can answer "what fraction of camera.hero moves were
    # uniformly real-grounded today" without reading the JSONL by hand.
    #
    # ``move_type`` is the ``intent_family`` for compositional impingements
    # (e.g. ``camera.hero``, ``mood.tone_pivot``) plus the literal label
    # ``"intent"`` for the top-level DirectorIntent. ``grounding_class``
    # ∈ ``{"real", "synthetic", "missing"}``:
    #   - real    — at least one entry in ``grounding_provenance``.
    #   - synthetic — empty real grounding, but ``synthetic_grounding_markers``
    #                 carries a fallback / inferred marker (deterministic-code
    #                 fallback or post-parse synthesis).
    #   - missing — both empty (would be rejected by R8 in production; counted
    #               here for visibility into pre-R8 classification).
    _move_grounding_total = Counter(
        "hapax_director_move_grounding_total",
        (
            "Director moves classified by grounding-class. "
            "``move_type`` is the intent_family or 'intent' for the "
            "top-level DirectorIntent. ``grounding_class`` ∈ "
            "{real, synthetic, missing} per cc-task "
            "director-moves-grounding-trace-coverage."
        ),
        ("move_type", "grounding_class"),
        **_metric_kwargs,
    )

    _METRICS_AVAILABLE = True
except Exception:  # pragma: no cover — prometheus_client missing at install time
    log.info("prometheus_client unavailable — director observability metrics are no-ops")


def _classify_grounding(
    real: list[str] | None,
    synthetic: list[str] | None,
) -> str:
    """Classify a grounding pair as ``real``, ``synthetic``, or ``missing``.

    Cc-task ``director-moves-grounding-trace-coverage``: the operator
    wants every director move visible on the Prometheus surface, classified
    so a Grafana dashboard can compute the fallback ratio per move type
    without parsing the JSONL.

    A real entry takes precedence — if any non-empty string sits in
    ``grounding_provenance`` the move grounds in observable evidence,
    even if synthetic markers are also attached (split_grounding_provenance
    in shared.director_intent already migrates synthetic prefixes out of
    grounding_provenance, but the classification stays correct under any
    drift in that helper).
    """
    if real and any((entry or "").strip() for entry in real):
        return "real"
    if synthetic and any((entry or "").strip() for entry in synthetic):
        return "synthetic"
    return "missing"


def emit_move_grounding(intent: DirectorIntent) -> None:
    """Increment ``hapax_director_move_grounding_total`` per move in the intent.

    One increment for the top-level intent (``move_type="intent"``) and
    one increment per compositional impingement (``move_type=intent_family``).
    Each increment carries a ``grounding_class`` label of ``real``,
    ``synthetic``, or ``missing`` based on whether the move's
    grounding_provenance / synthetic_grounding_markers fields carry any
    real evidence. Fail-open — any exception inside the emit is logged at
    debug and swallowed so the director's tick path never breaks on
    metric-backend failure.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        top_class = _classify_grounding(
            intent.grounding_provenance,
            intent.synthetic_grounding_markers,
        )
        _move_grounding_total.labels(
            move_type="intent",
            grounding_class=top_class,
        ).inc()
        for imp in intent.compositional_impingements:
            cls = _classify_grounding(
                imp.grounding_provenance,
                imp.synthetic_grounding_markers,
            )
            _move_grounding_total.labels(
                move_type=imp.intent_family,
                grounding_class=cls,
            ).inc()
    except Exception:
        log.debug("emit_move_grounding failed", exc_info=True)


def emit_director_intent(intent: DirectorIntent, condition_id: str) -> None:
    """Record one narrative-director intent + real/synthetic grounding diagnostics."""
    if not _METRICS_AVAILABLE:
        return
    try:
        _director_intent_total.labels(
            condition_id=condition_id,
            activity=intent.activity,
            stance=str(intent.stance),
        ).inc()
        for signal in intent.grounding_provenance:
            _grounding_signal_total.labels(
                condition_id=condition_id,
                signal_name=canonicalize_grounding_signal(signal),
            ).inc()
        for marker in intent.synthetic_grounding_markers:
            _synthetic_grounding_placeholder_total.labels(
                scope="intent",
                marker_family=_synthetic_marker_family(marker),
            ).inc()
        for imp in intent.compositional_impingements:
            _compositional_impingement_total.labels(
                condition_id=condition_id, intent_family=imp.intent_family
            ).inc()
            for marker in imp.synthetic_grounding_markers:
                _synthetic_grounding_placeholder_total.labels(
                    scope="impingement",
                    marker_family=_synthetic_marker_family(marker),
                ).inc()
    except Exception:
        log.warning("emit_director_intent failed", exc_info=True)
    # Cc-task `director-moves-grounding-trace-coverage`: the per-move
    # grounding-class counter is the new surface that lets dashboards
    # compute fallback-ratio per move type. Called from the same emit
    # path as the legacy counters so the two stay in lock-step.
    emit_move_grounding(intent)


def emit_ungrounded_audit(intent: DirectorIntent, condition_id: str) -> None:
    """Audit + count missing-real-grounding emissions per FINDING-X.

    Walks the top-level intent and every compositional_impingement; for
    each empty real ``grounding_provenance`` field it increments the
    Prometheus counter labeled by scope and emits a warn-level log line.
    If synthetic markers are present, the warning says synthetic-only:
    that is visible diagnostic state, not audit success.

    Fail-open: any exception inside the audit is logged at debug and
    swallowed. The audit must never block emit.
    """
    try:
        if not intent.grounding_provenance:
            synthetic = list(intent.synthetic_grounding_markers)
            log.warning(
                "UNGROUNDED intent (condition=%s, activity=%s, stance=%s): "
                "top-level grounding_provenance empty%s",
                condition_id,
                intent.activity,
                intent.stance,
                f"; synthetic_only={synthetic}" if synthetic else "",
            )
            if _METRICS_AVAILABLE:
                _ungrounded_total.labels(condition_id=condition_id, scope="intent").inc()

        for imp in intent.compositional_impingements:
            if not imp.grounding_provenance:
                synthetic = list(imp.synthetic_grounding_markers)
                log.warning(
                    "UNGROUNDED impingement (condition=%s, family=%s, "
                    "salience=%.2f): per-impingement grounding_provenance empty%s",
                    condition_id,
                    imp.intent_family,
                    imp.salience,
                    f"; synthetic_only={synthetic}" if synthetic else "",
                )
                if _METRICS_AVAILABLE:
                    _ungrounded_total.labels(condition_id=condition_id, scope="impingement").inc()
    except Exception:
        log.debug("emit_ungrounded_audit failed", exc_info=True)


def emit_ungrounded_synth(intent_family: str) -> None:
    """Record one synthesized grounding-provenance entry per FINDING-X Phase 1.

    Called from the post-parse synthesis hook whenever an LLM-emitted
    CompositionalImpingement with empty grounding_provenance gets a
    synthetic "inferred.<stance>.<family>" marker. Fail-open: any
    exception is logged at debug and swallowed.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _ungrounded_synth_total.labels(intent_family=intent_family).inc()
    except Exception:
        log.debug("emit_ungrounded_synth failed", exc_info=True)


def emit_ungrounded_rejection(intent_family: str) -> None:
    """Record one R8 grounding-act-gate rejection (2026-05-02 effect+cam audit).

    Called when an LLM-emitted ``CompositionalImpingement`` arrives with
    empty real ``grounding_provenance`` AND no ``synthetic_grounding_markers``
    set by a deterministic-code fallback path. The gate drops the
    impingement from the downstream list and a warn-level log line fires
    next to this counter increment. Fail-open: any exception is logged at
    debug and swallowed.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _ungrounded_rejection_total.labels(intent_family=intent_family).inc()
    except Exception:
        log.debug("emit_ungrounded_rejection failed", exc_info=True)


def emit_twitch_move(intent_family: str, condition_id: str) -> None:
    if not _METRICS_AVAILABLE:
        return
    try:
        _twitch_move_total.labels(condition_id=condition_id, intent_family=intent_family).inc()
    except Exception:
        log.warning("emit_twitch_move failed", exc_info=True)


def emit_structural_intent(scene_mode: str, preset_family_hint: str, condition_id: str) -> None:
    if not _METRICS_AVAILABLE:
        return
    try:
        _structural_intent_total.labels(
            condition_id=condition_id,
            scene_mode=scene_mode,
            preset_family_hint=preset_family_hint,
        ).inc()
    except Exception:
        log.warning("emit_structural_intent failed", exc_info=True)


def observe_llm_latency(seconds: float, tier: str, condition_id: str) -> None:
    """tier ∈ {"narrative", "structural"}."""
    if not _METRICS_AVAILABLE:
        return
    try:
        _llm_latency_seconds.labels(condition_id=condition_id, director_tier=tier).observe(seconds)
    except Exception:
        log.warning("observe_llm_latency failed", exc_info=True)


def emit_parse_failure(tier: str, condition_id: str) -> None:
    if not _METRICS_AVAILABLE:
        return
    try:
        _intent_parse_failure_total.labels(condition_id=condition_id, director_tier=tier).inc()
    except Exception:
        log.warning("emit_parse_failure failed", exc_info=True)


def emit_director_tick_skipped_in_flight(reason: str = "lock_held") -> None:
    """Director watchdog Phase 2 (§8): increment when a tick is skipped
    because the prior LLM call hadn't returned. Default reason='lock_held'.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _director_tick_skipped_in_flight_total.labels(reason=reason).inc()
    except Exception:
        log.warning("emit_director_tick_skipped_in_flight failed", exc_info=True)


def emit_vacuum_prevented(reason: str, tier: str, condition_id: str) -> None:
    """Increment when a parser/silence fallback attaches a silence-hold
    impingement instead of emitting empty ``compositional_impingements``.

    Operator no-vacuum invariant (2026-04-18). Non-zero rate is expected
    (LLM occasionally returns malformed output); a sudden spike signals
    upstream parser or prompt regression.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _vacuum_prevented_total.labels(
            condition_id=condition_id, director_tier=tier, reason=reason
        ).inc()
    except Exception:
        log.warning("emit_vacuum_prevented failed", exc_info=True)


def emit_homage_package_active(package: str) -> None:
    """Record the active HOMAGE package. Sets 1 for ``package`` and
    0 for every previously-labelled series implicitly via Gauge."""
    if not _METRICS_AVAILABLE:
        return
    try:
        _homage_package_active.labels(package=package).set(1)
    except Exception:
        log.warning("emit_homage_package_active failed", exc_info=True)


def emit_homage_package_inactive(package: str) -> None:
    if not _METRICS_AVAILABLE:
        return
    try:
        _homage_package_active.labels(package=package).set(0)
    except Exception:
        log.warning("emit_homage_package_inactive failed", exc_info=True)


def emit_homage_transition(
    package: str,
    transition_name: str,
    *,
    ward: str = "",
    phase: str = "",
) -> None:
    """Increment the ``hapax_homage_transition_total`` counter.

    Phase C1 (homage-completion-plan §2) extended the counter's label set
    from ``(package, transition_name)`` to ``(package, ward,
    transition_name, phase)`` so Grafana can slice by the ward that
    transitioned and the phase (``entry``/``exit``/``modify``) the
    choreographer classified it as. ``ward`` and ``phase`` are
    keyword-only with empty-string defaults — legacy callers that only
    know the package + transition still emit a valid series (with
    empty labels) rather than raising.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _homage_transition_total.labels(
            package=package,
            ward=ward,
            transition_name=transition_name,
            phase=phase,
        ).inc()
    except Exception:
        log.warning("emit_homage_transition failed", exc_info=True)


def emit_homage_emphasis_applied(ward: str, intent_family: str) -> None:
    """Record a ward-properties emphasis write driven by an intent_family.

    Called from ``compositional_consumer._apply_emphasis`` (per
    narrative-tier ``ward_emphasis`` entry) and from ``dispatch_ward_*``
    handlers when a recruited ward.* capability lands. ``intent_family``
    is the originating routing family (e.g. ``structural.emphasis``,
    ``ward.highlight``); ``ward`` is the ward id that received the
    envelope. Non-zero rate on this counter is the direct proof that
    narrative-director emphasis is actually writing to the ward-properties
    surface — the §7.3 verification protocol's aliveness check.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _homage_emphasis_applied_total.labels(ward=ward, intent_family=intent_family).inc()
    except Exception:
        log.warning("emit_homage_emphasis_applied failed", exc_info=True)


def emit_homage_render_cadence(ward: str, hz: float) -> None:
    """Publish the current per-ward render rate on
    ``hapax_homage_render_cadence_hz``.

    Called from ``CairoSourceRunner._render_one_frame`` after every
    successful render tick. The value is the instantaneous rate computed
    as ``1.0 / period`` where ``period`` is the monotonic delta between
    consecutive successful renders — a ward that has never ticked (or is
    gated / degraded) stays at its last published value until the next
    successful render.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _homage_render_cadence_hz.labels(ward=ward).set(float(hz))
    except Exception:
        log.warning("emit_homage_render_cadence failed", exc_info=True)


def emit_homage_rotation_mode(mode: str) -> None:
    """One-hot publish the active HOMAGE rotation mode.

    The ``mode`` argument is one of ``sequential`` / ``random`` /
    ``weighted_by_salience`` / ``paused`` — matching the choreographer's
    ``_read_rotation_mode`` return type. The labelled series for the
    active mode is set to 1.0; every other registered series for the
    same metric is set to 0.0 so a Grafana ``max by (mode)`` returns
    exactly one row.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        for known in ("sequential", "random", "weighted_by_salience", "paused"):
            _homage_rotation_mode.labels(mode=known).set(1.0 if known == mode else 0.0)
    except Exception:
        log.warning("emit_homage_rotation_mode failed", exc_info=True)


def emit_homage_active_package(package: str) -> None:
    """One-hot publish the currently-active HOMAGE package.

    Separate from ``emit_homage_package_active`` (which uses a plain
    ``Gauge.set(1)`` pattern and relies on callers to zero prior
    packages). This emitter zeroes any previously-set label value
    automatically so the Grafana query ``max by (package)`` always
    returns exactly one row when at least one ``emit_homage_active_package``
    call has happened in the current process.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        # prometheus_client Gauge exposes ``_metrics`` as the dict of
        # labelled children. Walk it to zero any previously-set series
        # before setting the current one to 1.0. Access is a private
        # attribute but it's stable across the 0.x release series and
        # there is no public alternative that accomplishes the same
        # one-hot semantics without a module-level cache.
        try:
            existing = dict(getattr(_homage_active_package, "_metrics", {}))
        except Exception:
            existing = {}
        for label_tuple in existing:
            try:
                prior_pkg = label_tuple[0] if label_tuple else ""
            except Exception:
                continue
            if prior_pkg and prior_pkg != package:
                _homage_active_package.labels(package=prior_pkg).set(0.0)
        _homage_active_package.labels(package=package).set(1.0)
    except Exception:
        log.warning("emit_homage_active_package failed", exc_info=True)


def emit_homage_substrate_saturation_target(value: float) -> None:
    """Publish the substrate saturation target the choreographer is
    broadcasting to substrate sources.

    Values outside [0.0, 1.0] are clamped — spec §4 declares the
    saturation target as a normalised float; an out-of-band value
    represents a bug upstream but should not break the observability
    surface.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        clamped = max(0.0, min(1.0, float(value)))
        _homage_substrate_saturation_target.set(clamped)
    except Exception:
        log.warning("emit_homage_substrate_saturation_target failed", exc_info=True)


def emit_homage_choreographer_rejection(reason: str) -> None:
    if not _METRICS_AVAILABLE:
        return
    try:
        _homage_choreographer_rejection_total.labels(reason=reason).inc()
    except Exception:
        log.warning("emit_homage_choreographer_rejection failed", exc_info=True)


def emit_audio_ducking_decision(reason: str) -> None:
    """Record a ducking-trigger decision. Audio-pathways Phase 3 (#134).

    Reason taxonomy:
      - ``vad_and_embedding`` — VAD fired AND embedding match >= 0.75
        → duck fired with high confidence
      - ``vad_only_fallback`` — VAD fired AND 0.4 <= embedding_match < 0.75
        → duck fired, low confidence (operator may be speaking through
        room noise)
      - ``no_duck_phantom`` — VAD fired AND embedding_match < 0.4
        → duck NOT fired, phantom VAD detected (likely YouTube
        crossfeed or other non-operator voice)
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _audio_ducking_triggered.labels(reason=reason).inc()
        if reason == "no_duck_phantom":
            _audio_phantom_vad_detected.inc()
    except Exception:
        log.warning("emit_audio_ducking_decision failed", exc_info=True)


def emit_audio_echo_cancel_active(active: bool) -> None:
    """Set the echo-cancel-active gauge. Audio-pathways Phase 3 (#134)."""
    if not _METRICS_AVAILABLE:
        return
    try:
        _audio_echo_cancel_active.set(1.0 if active else 0.0)
    except Exception:
        log.warning("emit_audio_echo_cancel_active failed", exc_info=True)


def emit_audio_source_active(source_name: str) -> None:
    """Mark the named audio source active (1.0). Audio-pathways Phase 3 (#134).

    Other source-name labels keep their previously-set values; the
    Prometheus consumer takes the labelled-1.0 series as the current
    source. Use ``emit_audio_source_inactive(name)`` to zero a stale
    label when switching.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _audio_source_active.labels(source_name=source_name).set(1.0)
    except Exception:
        log.warning("emit_audio_source_active failed", exc_info=True)


def emit_audio_source_inactive(source_name: str) -> None:
    """Mark the named audio source inactive (0.0). Audio-pathways Phase 3 (#134)."""
    if not _METRICS_AVAILABLE:
        return
    try:
        _audio_source_active.labels(source_name=source_name).set(0.0)
    except Exception:
        log.warning("emit_audio_source_inactive failed", exc_info=True)


def emit_homage_choreographer_substrate_skip(source: str) -> None:
    """Record that a pending transition was skipped because the named
    source is always-on substrate (HomageSubstrateSource protocol).

    Non-zero rate on this counter indicates a design violation: something
    in the system is trying to schedule transitions for the substrate,
    which should never happen. Grafana panel sits next to
    ``hapax_homage_choreographer_rejection_total``.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _homage_choreographer_substrate_skip_total.labels(source=source).inc()
    except Exception:
        log.warning("emit_homage_choreographer_substrate_skip failed", exc_info=True)


def emit_homage_violation(package: str, kind: str) -> None:
    """Record a paste / anti-pattern violation. Kind is free-form but
    convention follows ``AntiPatternKind`` literal (emoji, anti-aliased,
    proportional-font, ...) plus render-time violations like
    ``paste-without-choreographed-transition``."""
    if not _METRICS_AVAILABLE:
        return
    try:
        _homage_violation_total.labels(package=package, kind=kind).inc()
    except Exception:
        log.warning("emit_homage_violation failed", exc_info=True)


def emit_homage_signature_artefact(package: str, form: str) -> None:
    if not _METRICS_AVAILABLE:
        return
    try:
        _homage_signature_artefact_emitted_total.labels(package=package, form=form).inc()
    except Exception:
        log.warning("emit_homage_signature_artefact failed", exc_info=True)


def emit_hardm_salience_bias(value: float) -> None:
    """Record the HARDM salience bias (task #160).

    Gauge in ``[0, 1]``. Called on every ``current_salience_bias()``
    evaluation in ``agents/studio_compositor/hardm_source.py``.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _hardm_salience_bias.set(float(value))
    except Exception:
        log.warning("emit_hardm_salience_bias failed", exc_info=True)


def emit_hardm_emphasis_state(speaking: bool) -> None:
    """Record the HARDM emphasis state (task #160). 1=speaking, 0=quiescent."""
    if not _METRICS_AVAILABLE:
        return
    try:
        _hardm_emphasis_state.set(1.0 if speaking else 0.0)
    except Exception:
        log.warning("emit_hardm_emphasis_state failed", exc_info=True)


def emit_hardm_operator_cue(cell: int) -> None:
    """Record a sidechat ``point-at-hardm <cell>`` cue (task #160)."""
    if not _METRICS_AVAILABLE:
        return
    try:
        _hardm_operator_cue_total.labels(cell=str(cell)).inc()
    except Exception:
        log.warning("emit_hardm_operator_cue failed", exc_info=True)


def emit_random_mode_pick(chosen_via: str) -> None:
    """Record a random_mode preset pick. ``chosen_via`` is one of
    ``family=<name>``, ``fallback=neutral-ambient``, ``uniform-fallback``.

    Lets Grafana distinguish director-recruited family picks from the
    neutral-fallback path (operator's "no shuffle feel" directive) so we
    can alert when fallback rate creeps toward shuffle behaviour.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _random_mode_pick_total.labels(chosen_via=chosen_via).inc()
    except Exception:
        log.warning("emit_random_mode_pick failed", exc_info=True)


def emit_transition_pick(transition_name: str) -> None:
    """Record a random_mode chain-change transition pick (Phase 7 of #166).

    ``transition_name`` is one of the ``transition.*`` capability names
    in ``transition_primitives.PRIMITIVES``. The Phase 9 entropy metric
    derives from this counter.
    """
    if not _METRICS_AVAILABLE:
        return
    try:
        _random_mode_transition_total.labels(transition=transition_name).inc()
    except Exception:
        log.warning("emit_transition_pick failed", exc_info=True)


__all__ = [
    "canonicalize_grounding_signal",
    "emit_director_intent",
    "emit_homage_active_package",
    "emit_homage_choreographer_rejection",
    "emit_homage_choreographer_substrate_skip",
    "emit_homage_emphasis_applied",
    "emit_homage_package_active",
    "emit_homage_package_inactive",
    "emit_homage_render_cadence",
    "emit_homage_rotation_mode",
    "emit_homage_signature_artefact",
    "emit_homage_substrate_saturation_target",
    "emit_homage_transition",
    "emit_homage_violation",
    "emit_move_grounding",
    "emit_parse_failure",
    "emit_random_mode_pick",
    "emit_transition_pick",
    "emit_ungrounded_audit",
    "emit_ungrounded_rejection",
    "emit_ungrounded_synth",
    "emit_vacuum_prevented",
    "emit_structural_intent",
    "emit_twitch_move",
    "observe_llm_latency",
]
