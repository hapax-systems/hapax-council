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

    _director_intent_total = Counter(
        "hapax_director_intent_total",
        "Director intents emitted, labelled by condition + activity + stance.",
        ("condition_id", "activity", "stance"),
    )
    _grounding_signal_total = Counter(
        "hapax_director_grounding_signal_used_total",
        "Grounding-provenance signal references per intent.",
        ("condition_id", "signal_name"),
    )
    _compositional_impingement_total = Counter(
        "hapax_director_compositional_impingement_total",
        "Compositional impingements emitted, labelled by intent family.",
        ("condition_id", "intent_family"),
    )
    _twitch_move_total = Counter(
        "hapax_director_twitch_move_total",
        "Twitch-director moves emitted, labelled by intent family.",
        ("condition_id", "intent_family"),
    )
    _structural_intent_total = Counter(
        "hapax_director_structural_intent_total",
        "Structural-director intents emitted.",
        ("condition_id", "scene_mode", "preset_family_hint"),
    )
    _llm_latency_seconds = Histogram(
        "hapax_director_llm_latency_seconds",
        "Director LLM call latency in seconds.",
        ("condition_id", "director_tier"),
        buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 45.0, 60.0, 120.0),
    )
    _intent_parse_failure_total = Counter(
        "hapax_director_intent_parse_failure_total",
        "LLM response failed to parse as DirectorIntent — fell back to legacy path.",
        ("condition_id", "director_tier"),
    )
    _vacuum_prevented_total = Counter(
        "hapax_director_vacuum_prevented_total",
        (
            "Parser-error / silence fallbacks where the no-vacuum invariant "
            "(operator 2026-04-18) populated a silence-hold impingement."
        ),
        ("condition_id", "director_tier", "reason"),
    )
    _random_mode_pick_total = Counter(
        "hapax_random_mode_pick_total",
        "random_mode preset picks, labelled by selection path.",
        ("chosen_via",),
    )
    # HOMAGE framework metrics — spec §6.
    # Registered against the compositor's CollectorRegistry (when the
    # compositor package is importable) so the :9482 scrape surface
    # actually exposes them. Passing a registry keyword-only argument
    # only when non-None keeps the metric registered against the
    # prometheus_client default registry in non-compositor environments
    # (officium, test sandboxes without the compositor package).
    _homage_metric_kwargs: dict = (
        {"registry": _COMPOSITOR_REGISTRY} if _COMPOSITOR_REGISTRY is not None else {}
    )
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

    _METRICS_AVAILABLE = True
except Exception:  # pragma: no cover — prometheus_client missing at install time
    log.info("prometheus_client unavailable — director observability metrics are no-ops")


def emit_director_intent(intent: DirectorIntent, condition_id: str) -> None:
    """Record one narrative-director intent + its grounding_provenance + impingements."""
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
        for imp in intent.compositional_impingements:
            _compositional_impingement_total.labels(
                condition_id=condition_id, intent_family=imp.intent_family
            ).inc()
    except Exception:
        log.warning("emit_director_intent failed", exc_info=True)


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
    "emit_parse_failure",
    "emit_random_mode_pick",
    "emit_vacuum_prevented",
    "emit_structural_intent",
    "emit_twitch_move",
    "observe_llm_latency",
]
