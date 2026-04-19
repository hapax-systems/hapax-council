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
    _homage_package_active = Gauge(
        "hapax_homage_package_active",
        "1 if the named HOMAGE package is currently active, 0 otherwise.",
        ("package",),
    )
    _homage_transition_total = Counter(
        "hapax_homage_transition_total",
        "HOMAGE transitions applied, labelled by package + transition kind.",
        ("package", "transition_name"),
    )
    _homage_choreographer_rejection_total = Counter(
        "hapax_homage_choreographer_rejection_total",
        "Pending transitions the choreographer rejected, by reason.",
        ("reason",),
    )
    _homage_choreographer_substrate_skip_total = Counter(
        "hapax_homage_choreographer_substrate_skip_total",
        "Pending transitions skipped by the choreographer because the "
        "named source is marked as HomageSubstrateSource (always-on).",
        ("source",),
    )
    _homage_violation_total = Counter(
        "hapax_homage_violation_total",
        "Paste / anti-pattern violations detected at render time.",
        ("package", "kind"),
    )
    _homage_signature_artefact_emitted_total = Counter(
        "hapax_homage_signature_artefact_emitted_total",
        "Signature artefacts emitted, labelled by package + form.",
        ("package", "form"),
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


def emit_homage_transition(package: str, transition_name: str) -> None:
    if not _METRICS_AVAILABLE:
        return
    try:
        _homage_transition_total.labels(package=package, transition_name=transition_name).inc()
    except Exception:
        log.warning("emit_homage_transition failed", exc_info=True)


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
    "emit_homage_choreographer_rejection",
    "emit_homage_choreographer_substrate_skip",
    "emit_homage_package_active",
    "emit_homage_package_inactive",
    "emit_homage_signature_artefact",
    "emit_homage_transition",
    "emit_homage_violation",
    "emit_parse_failure",
    "emit_random_mode_pick",
    "emit_vacuum_prevented",
    "emit_structural_intent",
    "emit_twitch_move",
    "observe_llm_latency",
]
