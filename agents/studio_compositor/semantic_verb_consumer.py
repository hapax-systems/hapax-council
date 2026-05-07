"""Semantic-verb consumer (cc-task u5-verb-prometheus-counter-and-consumer Phase 1).

Per ``/tmp/wsjf-path-director-moves.md`` §4 item 3 + §3 G8: U5 substrate
(11-verb vocabulary in ``shared/director_semantic_verbs.py``) shipped via
PR #2326 — vocabulary registered, no-orphan invariant pinned. But the
director was talking to itself: no consumer mapped verbs into chain
mutations.

This Phase 1 consumer wires each of the 11 canonical verbs into one of
two dispatch paths:

  ENVELOPE   — write to a parametric-heartbeat envelope nudge file. The
               heartbeat envelope reader (downstream daemon) interprets
               the nudge as a temporal/intensity delta over its own
               cadence. Used for verbs whose hint touches motion /
               cadence / intensity (ascend, linger, accelerate, dwell,
               warm, cool).
  TRANSITION — write to a transition-primitive bias file. The
               recruitment consumer reads this on its next tick and
               biases its primitive selection (verb ``rupture`` biases
               ``cut.hard`` etc.). Used for verbs whose hint touches
               structure / discontinuity (gather, disperse, rupture,
               align, drift).

Per memory ``feedback_no_presets_use_parametric_modulation``: verbs bias
parametric modulation (envelope nudge OR transition-bias delta) — they
NEVER force a preset swap. The substrate's ``hint["force_preset_swap"]``
is intentionally NOT consumed here; Phase 2 may surface it as a separate
"hard rupture" path.

Per memory ``feedback_no_expert_system_rules``: verb→consumer routing is
the declarative ``VERB_CONSUMER_ROUTES`` table — no branching logic in
the dispatcher.

Output paths (atomic-rename JSONL writes; downstream consumers tail):
- ``/dev/shm/hapax-compositor/semantic-verb-envelope-nudges.jsonl``
- ``/dev/shm/hapax-compositor/semantic-verb-transition-bias.jsonl``

Prometheus counter ``hapax_semantic_verb_consumed_total{verb, outcome}``:
- ``outcome=dispatched``: verb routed + write succeeded
- ``outcome=ignored``: verb not in vocabulary OR write failed (consumer
  is fail-open; metrics flag the broken state path independent of the
  metrics pipeline)
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Final, Literal

from prometheus_client import Counter

from shared.director_semantic_verbs import (
    SEMANTIC_VERB_ACTIONS,
    SEMANTIC_VERBS,
    VerbAction,
)

log = logging.getLogger(__name__)

ConsumerRoute = Literal["envelope", "transition"]
"""The two dispatch paths a verb routes to."""

ConsumerOutcome = Literal["dispatched", "ignored"]
"""Counter outcome label."""

#: Default JSONL output for envelope-nudge verbs. Heartbeat-envelope
#: daemon reads this on its tick and applies the verb's hint as a
#: temporal/intensity delta.
DEFAULT_ENVELOPE_PATH: Final[Path] = Path(
    "/dev/shm/hapax-compositor/semantic-verb-envelope-nudges.jsonl"
)

#: Default JSONL output for transition-bias verbs. Recruitment consumer
#: reads this on its tick and biases primitive selection.
DEFAULT_TRANSITION_BIAS_PATH: Final[Path] = Path(
    "/dev/shm/hapax-compositor/semantic-verb-transition-bias.jsonl"
)

#: Declarative routing table: verb → consumer path.
#:
#: Rationale per axis:
#: - temporal verbs (ascend, linger, accelerate) → envelope (cadence/intensity)
#: - phenomenological/dwell → envelope (extends present-moment duration)
#: - chromatic (warm, cool) → envelope (palette bias is a slow delta)
#: - phenomenological/rupture → transition (forces a primitive choice)
#: - spatial (gather, disperse) → transition (collapse vs spread is a primitive)
#: - structural (align, drift) → transition (snap vs loose is a primitive)
VERB_CONSUMER_ROUTES: dict[str, ConsumerRoute] = {
    "ascend": "envelope",
    "linger": "envelope",
    "accelerate": "envelope",
    "gather": "transition",
    "disperse": "transition",
    "dwell": "envelope",
    "rupture": "transition",
    "warm": "envelope",
    "cool": "envelope",
    "align": "transition",
    "drift": "transition",
}

# Prometheus counter — increments per consume() attempt, labelled by
# verb + outcome. Pinned label values: outcome ∈ {dispatched, ignored}.
hapax_semantic_verb_consumed_total: Counter = Counter(
    "hapax_semantic_verb_consumed_total",
    "Number of semantic-verb consumption attempts, by verb and outcome",
    labelnames=("verb", "outcome"),
)


def _atomic_append_jsonl(path: Path, payload: dict[str, object]) -> None:
    """Append a JSON line, atomic-rename-reconstruct.

    JSONL doesn't have a partial-write concern at line granularity — a
    single ``write()`` of one line + newline is atomic up to the OS page
    size. We use append-mode with O_APPEND for single-record writes; the
    "atomic rename" is unnecessary at the line scale.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, sort_keys=True) + "\n"
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o644,
    )
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


class SemanticVerbConsumer:
    """Dispatches semantic verbs into envelope-nudge or transition-bias writes.

    Stateless across calls; each ``consume(verb)`` is independent. The
    consumer does NOT maintain a session — the downstream envelope /
    recruitment consumers own their own state.

    Usage:
        consumer = SemanticVerbConsumer()
        outcome = consumer.consume("rupture")  # -> ConsumerOutcome
    """

    def __init__(
        self,
        *,
        envelope_path: Path = DEFAULT_ENVELOPE_PATH,
        transition_bias_path: Path = DEFAULT_TRANSITION_BIAS_PATH,
        clock: object = None,
    ) -> None:
        self._envelope_path = envelope_path
        self._transition_bias_path = transition_bias_path
        self._clock = clock if clock is not None else time.time

    @property
    def envelope_path(self) -> Path:
        return self._envelope_path

    @property
    def transition_bias_path(self) -> Path:
        return self._transition_bias_path

    def consume(self, verb: str) -> ConsumerOutcome:
        """Dispatch ``verb`` and return the outcome label.

        Returns ``"dispatched"`` if the verb is in the vocabulary and the
        write succeeded; ``"ignored"`` otherwise. Counter is incremented
        in both branches.
        """
        # Unknown verb — increment ignored counter without write attempt.
        if verb not in VERB_CONSUMER_ROUTES:
            hapax_semantic_verb_consumed_total.labels(verb=verb, outcome="ignored").inc()
            return "ignored"

        action = SEMANTIC_VERB_ACTIONS[verb]
        route = VERB_CONSUMER_ROUTES[verb]

        target_path = self._envelope_path if route == "envelope" else self._transition_bias_path
        payload = self._build_payload(verb, action, route)

        try:
            _atomic_append_jsonl(target_path, payload)
        except OSError:
            log.warning(
                "semantic verb %r write to %s failed; counter outcome=ignored",
                verb,
                target_path,
                exc_info=True,
            )
            hapax_semantic_verb_consumed_total.labels(verb=verb, outcome="ignored").inc()
            return "ignored"

        hapax_semantic_verb_consumed_total.labels(verb=verb, outcome="dispatched").inc()
        return "dispatched"

    def _build_payload(
        self,
        verb: str,
        action: VerbAction,
        route: ConsumerRoute,
    ) -> dict[str, object]:
        """Build the JSONL record. Includes verb + axis + hint + dispatched_at."""
        return {
            "verb": verb,
            "axis": action.axis,
            "route": route,
            "hint": dict(action.hint),
            "dispatched_at": float(self._clock()),
        }


def all_verbs() -> tuple[str, ...]:
    """Return the canonical 11-verb vocabulary (delegates to substrate)."""
    return SEMANTIC_VERBS


def route_for(verb: str) -> ConsumerRoute | None:
    """Look up the consumer route for ``verb``; None if unknown."""
    return VERB_CONSUMER_ROUTES.get(verb)


def verbs_for_route(route: ConsumerRoute) -> tuple[str, ...]:
    """Return verbs routed to ``route``, sorted."""
    return tuple(sorted(v for v, r in VERB_CONSUMER_ROUTES.items() if r == route))


__all__ = [
    "ConsumerOutcome",
    "ConsumerRoute",
    "DEFAULT_ENVELOPE_PATH",
    "DEFAULT_TRANSITION_BIAS_PATH",
    "SemanticVerbConsumer",
    "VERB_CONSUMER_ROUTES",
    "all_verbs",
    "hapax_semantic_verb_consumed_total",
    "route_for",
    "verbs_for_route",
]
