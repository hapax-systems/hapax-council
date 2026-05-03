"""Bayesian-engine → impingement bus emitter.

Audit 3 fix #1: five Bayesian engines (PresenceEngine, MoodArousalEngine,
MoodValenceEngine, MoodCoherenceEngine, reverie_prediction_monitor) collapse
their posterior to a scalar at the file/JSON boundary instead of broadcasting
it as an impingement on the cognitive substrate. Each engine has the math;
each just needs an emitter that publishes when the posterior crosses an
entry/exit threshold or when a prediction misses observation.

Downstream effect (per audit): the cosine-similarity engine that drives
recruitment will see SIGNIFICANTLY more diverse impingement narratives,
breaking the current pattern where 12 narrative prefixes account for 94% of
the bus traffic. This converts dormant capabilities (88% of the catalog) into
recruitable ones.

Design constraints:

* Each impingement narrative MUST be synthesized from the engine's actual
  measured values. Frozen templates defeat the entire point of the fix —
  they would still collapse posterior to scalar at the cosine-similarity
  layer. The narrative is the load-bearing surface that varies.
* Strength is derived from posterior magnitude or |Δposterior| for
  transitions. Both are bounded to [0, 1].
* Type is ``ImpingementType.PATTERN_MATCH`` per audit recommendation —
  state-transition events are pattern matches against the engine's
  dwell-counter trajectory.
* No ``consent_required`` here — the impingement bus is internal cognitive
  substrate, not user-facing content.
* Failures are logged at debug level; the engines' tick loops MUST NOT
  crash on a bus write failure.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from shared.impingement import Impingement, ImpingementType

log = logging.getLogger(__name__)

DEFAULT_IMPINGEMENTS_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")


def emit_state_transition_impingement(
    *,
    source: str,
    claim_name: str,
    from_state: str,
    to_state: str,
    posterior: float,
    prev_posterior: float | None,
    active_signals: dict[str, object] | None = None,
    bus_path: Path = DEFAULT_IMPINGEMENTS_PATH,
    intent_family: str | None = None,
    now: float | None = None,
) -> bool:
    """Publish an impingement when a Bayesian engine's hysteresis state changes.

    Parameters
    ----------
    source:
        Provenance string written to ``Impingement.source`` (e.g.
        ``"presence_engine"``, ``"mood_arousal"``,
        ``"mood_valence"``, ``"mood_coherence"``).
    claim_name:
        Human-readable claim label embedded in the narrative. For example
        ``"operator-presence"`` or ``"mood-arousal-high"``.
    from_state, to_state:
        Hysteresis state names from the engine. Must differ; if equal we
        return False without writing.
    posterior:
        Engine's posterior at transition time; written into both
        ``Impingement.strength`` (clamped) and the narrative.
    prev_posterior:
        Engine's posterior at the previous tick; used to compute |Δposterior|
        for narrative diversity. ``None`` on first transition (acceptable —
        the narrative simply omits the delta clause).
    active_signals:
        Optional dict of currently-active signal observations for the
        narrative. Truncated to the first 5 entries so narratives stay
        readable. Pass ``None`` if the engine doesn't surface them
        cheaply.
    bus_path:
        JSONL bus file. Defaults to the canonical
        ``/dev/shm/hapax-dmn/impingements.jsonl``.
    intent_family:
        Optional ``intent_family`` for family-tagged routing. The
        recruitment pipeline will restrict its capability search to
        capabilities whose name starts with this prefix when set. Most
        Bayesian state transitions leave this ``None`` (global catalog).
    now:
        Override timestamp for testing; ``time.time()`` if unset.

    Returns
    -------
    bool
        True if the impingement was successfully appended, False on
        no-op (no transition) or write failure.
    """
    if from_state == to_state:
        return False

    timestamp = now if now is not None else time.time()
    delta_str = ""
    delta_strength: float | None = None
    if prev_posterior is not None:
        delta = posterior - prev_posterior
        delta_strength = abs(delta)
        delta_str = f", Δ{delta:+.2f}"

    # Synthesize a rich narrative from the actual measured values. This is
    # the WHOLE POINT of the fix — variance comes from the values, never
    # from a frozen template. The narrative includes the claim name, the
    # transition vector, the posterior, the optional delta, and an active-
    # signals fingerprint.
    signals_clause = ""
    if active_signals:
        # Stable order — sort by key so equal observations produce equal
        # narratives across calls (deterministic for tests).
        items = sorted(
            ((str(k), v) for k, v in active_signals.items() if v is not None),
            key=lambda kv: kv[0],
        )[:5]
        if items:
            sig_str = ", ".join(f"{k}={v}" for k, v in items)
            signals_clause = f"; signals: {sig_str}"

    narrative = (
        f"{claim_name} transitioned to {to_state} from {from_state} "
        f"(posterior={posterior:.2f}{delta_str}){signals_clause}"
    )

    # Strength: prefer Δposterior magnitude when available (transitions are
    # the load-bearing event), fall back to absolute posterior otherwise.
    # Clamp to [0, 1] to satisfy the Impingement schema.
    if delta_strength is not None:
        strength = max(0.0, min(1.0, delta_strength))
    else:
        strength = max(0.0, min(1.0, abs(posterior)))

    imp = Impingement(
        id=uuid.uuid4().hex[:12],
        timestamp=timestamp,
        source=source,
        type=ImpingementType.PATTERN_MATCH,
        strength=strength,
        content={
            "narrative": narrative,
            "claim": claim_name,
            "from_state": from_state,
            "to_state": to_state,
            "posterior": round(posterior, 4),
            "prev_posterior": round(prev_posterior, 4) if prev_posterior is not None else None,
            "delta_posterior": round(posterior - prev_posterior, 4)
            if prev_posterior is not None
            else None,
        },
        intent_family=intent_family,
    )
    return _append(imp, bus_path)


def emit_prediction_miss_impingement(
    *,
    prediction_name: str,
    expected: str,
    observed: float,
    alert: str,
    detail: str | None = None,
    bus_path: Path = DEFAULT_IMPINGEMENTS_PATH,
    now: float | None = None,
) -> bool:
    """Publish an impingement when a behavioral prediction misses observation.

    Used by ``agents.reverie_prediction_monitor`` to surface "I expected X
    but Y happened" signals on the cognitive substrate. The alert text and
    measured value drive narrative diversity; no two prediction misses
    produce the same narrative because each carries the engine's actual
    expected/observed pair.

    Parameters
    ----------
    prediction_name:
        Identifier for the prediction (e.g. ``"P1_thompson_convergence"``).
    expected:
        Engine's expected value/range as a human-readable string.
    observed:
        Actual observed value at evaluation time.
    alert:
        Human-readable alert message — the engine's own description of the
        mismatch, used to drive narrative variation.
    detail:
        Optional structured detail (often JSON-serialized). Truncated to
        200 chars to keep impingement payloads bounded.
    bus_path:
        JSONL bus file.
    now:
        Override timestamp for testing.

    Returns
    -------
    bool
        True on successful append, False on write failure.
    """
    timestamp = now if now is not None else time.time()
    detail_clipped = (detail or "")[:200]
    narrative = (
        f"prediction {prediction_name} missed: expected {expected} but observed "
        f"{observed:.3f} — {alert}"
    )
    # Strength: 1.0 always (every miss matters); the narrative carries the
    # diversity. The recruitment scorer multiplies by base_level / context
    # boost downstream so an artificially low strength here would just
    # flatten signal-to-noise.
    imp = Impingement(
        id=uuid.uuid4().hex[:12],
        timestamp=timestamp,
        source="reverie_prediction",
        type=ImpingementType.PATTERN_MATCH,
        strength=1.0,
        content={
            "narrative": narrative,
            "prediction": prediction_name,
            "expected": expected,
            "observed": round(float(observed), 4),
            "alert": alert,
            "detail": detail_clipped,
        },
    )
    return _append(imp, bus_path)


def _append(imp: Impingement, bus_path: Path) -> bool:
    """Atomically append a serialized impingement to the bus.

    Uses ``model_dump_json`` (not ``json.dumps(model_dump())``) so the
    serialization matches what every other producer in the workspace
    writes — the consumer's parser is tested against ``model_dump_json``
    output.
    """
    try:
        bus_path.parent.mkdir(parents=True, exist_ok=True)
        with bus_path.open("a", encoding="utf-8") as f:
            f.write(imp.model_dump_json() + "\n")
        return True
    except OSError:
        log.debug(
            "bayesian_impingement_emitter: failed to append impingement to %s",
            bus_path,
            exc_info=True,
        )
        return False


__all__ = [
    "DEFAULT_IMPINGEMENTS_PATH",
    "emit_state_transition_impingement",
    "emit_prediction_miss_impingement",
]
