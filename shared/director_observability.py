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
    from prometheus_client import Counter, Histogram

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
    _random_mode_pick_total = Counter(
        "hapax_random_mode_pick_total",
        "random_mode preset picks, labelled by selection path.",
        ("chosen_via",),
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
    "emit_parse_failure",
    "emit_random_mode_pick",
    "emit_structural_intent",
    "emit_twitch_move",
    "observe_llm_latency",
]
