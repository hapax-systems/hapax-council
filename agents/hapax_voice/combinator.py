"""Combinator (withLatestFrom) — fuses an Event trigger with Behavior samples.

When the trigger fires, all Behaviors are sampled and a FusedContext is emitted.
The output Event fires at exactly the trigger's times, carrying current Behavior
values with their watermarks.

Consent threading (DD-22, L3): Computes the join of all input Behavior consent
labels and attaches it to the FusedContext. If all Behaviors are untracked (None),
the FusedContext consent_label is None. If any Behavior has a label, untracked
Behaviors are treated as bottom (public) for the join computation.
"""

from __future__ import annotations

from agents.hapax_voice.governance import FusedContext
from agents.hapax_voice.primitives import Behavior, Event
from shared.governance.consent_label import ConsentLabel


def with_latest_from(
    trigger: Event,
    behaviors: dict[str, Behavior],
) -> Event[FusedContext]:
    """When trigger fires, sample all behaviors and emit fused context.

    Args:
        trigger: The driving Event — output fires at its times.
        behaviors: Named Behaviors to sample on each trigger.

    Returns:
        A new Event that emits FusedContext on each trigger firing.
    """
    result: Event[FusedContext] = Event()

    def _on_trigger(timestamp: float, value: object) -> None:
        samples = {name: b.sample() for name, b in behaviors.items()}
        min_wm = min((s.watermark for s in samples.values()), default=timestamp)
        consent_label = _join_behavior_labels(behaviors)
        context = FusedContext(
            trigger_time=timestamp,
            trigger_value=value,
            samples=samples,
            min_watermark=min_wm,
            consent_label=consent_label,
        )
        result.emit(timestamp, context)

    trigger.subscribe(_on_trigger)
    return result


def _join_behavior_labels(behaviors: dict[str, Behavior]) -> ConsentLabel | None:
    """Join all Behavior consent labels. Returns None if all are untracked."""
    labels = [b.consent_label for b in behaviors.values() if b.consent_label is not None]
    if not labels:
        return None
    result = ConsentLabel.bottom()
    for label in labels:
        result = result.join(label)
    return result
