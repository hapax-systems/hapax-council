"""Per-parameter constraint envelopes for the Reverie node graph.

Operator directive (2026-05-02T22:13Z, cumulative with
``feedback_no_presets_use_parametric_modulation`` + ``feedback_no_expert_system_rules``):

    "we should be relying on constrained algorithmic parametric modulation
    and combination and chaining of effects at the node graph level.
    Presets are dumb. Be smart about this."

This module is the spec for the parameter walk consumed by
:mod:`agents.parametric_modulation_heartbeat`. **It is not a preset
library** — each entry encodes a valid range + a smoothness budget +
joint constraints (aesthetic invariants), NOT a frozen snapshot of "good"
values. The walk samples within the range; the walk is the variance.

Architecture per ``CLAUDE.md § Reverie Vocabulary Integrity``: the per-node
``params_buffer`` lives at ``/dev/shm/hapax-imagination/uniforms.json`` and
the Rust pipeline writes ``base + delta`` per key. Envelopes here express
what ``base + delta`` may legally be — **not** what to set ``delta`` to.
The walker computes ``delta = target_within_envelope - base`` per tick.

Note on starting points: the (min, max, smoothness) numbers below are
informed by sampling the envelope of values that appear across
``presets/`` JSONs (so the playable range is realistic), but each
envelope entry is **explicitly authored**, not lifted from any one
preset. Per the operator directive, ``presets/`` is a starting-point
reference only, not a sample library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final


@dataclass(frozen=True)
class JointConstraint:
    """Two-parameter aesthetic invariant — neither pair may both peak.

    Encodes joint walk constraints that the parameter walker honors per
    tick. Example: ``intensity × degradation > 0.7`` would clip the
    pipeline to noise (operator-aesthetic invariant per the cc-task
    spec). Authored as a soft ceiling: when both parameters approach the
    threshold, the walker dampens whichever is moving faster.

    The constraint is symmetric and additive (joint mean), not
    multiplicative — easier to reason about in a Bayesian walker.
    """

    param_a_key: str
    """First parameter's ``{node_id}.{param_name}`` key."""

    param_b_key: str
    """Second parameter's ``{node_id}.{param_name}`` key."""

    joint_max: float
    """Maximum allowed value of ``(a + b) / 2``. When exceeded the
    walker clips both proportionally."""

    rationale: str
    """One-line aesthetic rationale (lands in journal logs on clip
    events for observability)."""


@dataclass(frozen=True)
class ParameterEnvelope:
    """Constraint envelope for one ``{node_id}.{param_name}`` slot.

    Per the cc-task spec acceptance criteria: each entry encodes
    ``(node_id, param_name, min, max, smoothness, joint_constraints)``.

    The walker treats ``smoothness`` as a per-tick step ceiling — the
    walk may not move ``|delta|`` more than ``smoothness`` per tick. For
    a 30s tick, ``smoothness=0.05`` means the parameter traverses its
    full range over ~10 minutes minimum. This is the smoothness invariant
    the regression test asserts — no stepwise jumps > envelope.smoothness.
    """

    node_id: str
    """Reverie node identifier (``noise``, ``rd``, ``color``, ``drift``,
    ``breath``, ``fb``, ``content``, ``post``)."""

    param_name: str
    """Parameter field within the node (matches WGSL Params struct
    field names per CLAUDE.md § Reverie Vocabulary Integrity)."""

    min_value: float
    """Inclusive lower bound for the parameter."""

    max_value: float
    """Inclusive upper bound for the parameter."""

    smoothness: float
    """Maximum |delta| per walker tick (smoothness invariant)."""

    joint_constraints: tuple[JointConstraint, ...] = field(default_factory=tuple)
    """Joint constraints involving this parameter (typically empty;
    populated for the small handful of aesthetic invariants — e.g.
    intensity × degradation)."""

    @property
    def key(self) -> str:
        """Canonical ``{node_id}.{param_name}`` key matching the
        uniforms.json schema written by ``agents.reverie._uniforms``."""

        return f"{self.node_id}.{self.param_name}"

    def clip(self, value: float) -> float:
        """Clamp ``value`` to ``[min_value, max_value]``."""

        return max(self.min_value, min(self.max_value, value))

    def clip_step(self, prev: float, target: float) -> float:
        """Limit per-tick delta to ``smoothness``, then clip to range."""

        delta = target - prev
        if abs(delta) > self.smoothness:
            delta = self.smoothness if delta > 0 else -self.smoothness
        return self.clip(prev + delta)


# ─── Joint constraints (aesthetic invariants per spec) ──────────────────────

# The directive's worked example: intensity × degradation must not both
# peak — would clip the pipeline to noise. Encoded as the joint mean
# ceiling; walker dampens proportionally on any tick that breaches.
INTENSITY_DEGRADATION_INVARIANT: Final = JointConstraint(
    param_a_key="content.intensity",
    param_b_key="post.sediment_strength",
    joint_max=0.55,
    rationale="content intensity × sediment_strength > 0.55 clips to visual noise",
)

# Feedback decay × feedback rotate — high decay (fast forgetting) AND
# high rotation amplitude together produces dizzying smear. Both peak at
# the upper end of their respective envelopes (decay ∈ [0.05, 0.45],
# rotate ∈ [-0.3, 0.3]). The constraint mean ceiling is set so the
# midpoints (decay=0.25, rotate=0.0) satisfy it but joint-peak does not.
FEEDBACK_DECAY_ROTATE_INVARIANT: Final = JointConstraint(
    param_a_key="fb.decay",
    param_b_key="fb.rotate",
    joint_max=0.30,
    rationale="feedback decay × rotate > 0.30 produces dizzying smear",
)

# Reaction-diffusion feed rate × kill rate — both peaking pushes the
# Gray-Scott pattern into pure noise (out of the structured-pattern
# basin of attraction).
RD_FEED_KILL_INVARIANT: Final = JointConstraint(
    param_a_key="rd.feed_rate",
    param_b_key="rd.kill_rate",
    joint_max=0.06,
    rationale="rd feed × kill > 0.06 leaves the Gray-Scott structured basin",
)


# ─── Envelopes (per-node, per-param) ────────────────────────────────────────
#
# The 8 active vocabulary nodes per ``presets/reverie_vocabulary.json``:
# noise, rd, color, drift, breath, fb, content, post.
#
# Smoothness budgets are tuned for a 30s walker tick:
#   - 0.02 → fully traverses min..max in ~12-15 mins (very slow drift)
#   - 0.05 → traverses in ~5-8 mins (slow drift, the common default)
#   - 0.10 → traverses in ~2-4 mins (medium drift, used for content/intensity-class params)
#   - 0.20 → traverses in ~1 min (fast drift; reserved for content.salience-style ephemera)
#
# These are deliberately CONSERVATIVE. Variance comes from the joint walk
# across many parameters, not from any one parameter sweeping fast.

_ENVELOPES: Final[tuple[ParameterEnvelope, ...]] = (
    # noise — generative substrate, slowest drift
    ParameterEnvelope("noise", "frequency_x", 0.5, 3.0, 0.05),
    ParameterEnvelope("noise", "frequency_y", 0.5, 3.0, 0.05),
    ParameterEnvelope("noise", "amplitude", 0.02, 0.25, 0.02),
    ParameterEnvelope("noise", "speed", 0.02, 0.20, 0.02),
    # rd — reaction-diffusion, joint-constrained (Gray-Scott invariant)
    ParameterEnvelope(
        "rd",
        "feed_rate",
        0.02,
        0.06,
        0.005,
        joint_constraints=(RD_FEED_KILL_INVARIANT,),
    ),
    ParameterEnvelope(
        "rd",
        "kill_rate",
        0.04,
        0.07,
        0.005,
        joint_constraints=(RD_FEED_KILL_INVARIANT,),
    ),
    ParameterEnvelope("rd", "speed", 0.5, 1.5, 0.05),
    # color — colorgrade, BitchX substrate-invariant clamps saturation
    # but the walker is free below the BitchX ceiling
    ParameterEnvelope("color", "brightness", 0.7, 1.3, 0.03),
    ParameterEnvelope("color", "saturation", 0.4, 1.2, 0.03),
    ParameterEnvelope("color", "contrast", 0.6, 1.2, 0.03),
    ParameterEnvelope("color", "hue_rotate", 0.0, 360.0, 6.0),
    # drift — spatial drift, low-amplitude default
    ParameterEnvelope("drift", "speed", 0.0, 0.4, 0.02),
    ParameterEnvelope("drift", "amplitude", 0.0, 0.3, 0.02),
    ParameterEnvelope("drift", "frequency", 0.4, 1.5, 0.05),
    ParameterEnvelope("drift", "coherence", 0.3, 0.9, 0.03),
    # breath — breathing modulation, very slow
    ParameterEnvelope("breath", "rate", 0.0, 0.3, 0.02),
    ParameterEnvelope("breath", "amplitude", 0.0, 0.4, 0.02),
    # fb — feedback, joint-constrained (decay × rotate invariant)
    ParameterEnvelope(
        "fb",
        "decay",
        0.05,
        0.45,
        0.04,
        joint_constraints=(FEEDBACK_DECAY_ROTATE_INVARIANT,),
    ),
    ParameterEnvelope("fb", "zoom", 0.92, 1.10, 0.01),
    ParameterEnvelope(
        "fb",
        "rotate",
        -0.3,
        0.3,
        0.02,
        joint_constraints=(FEEDBACK_DECAY_ROTATE_INVARIANT,),
    ),
    ParameterEnvelope("fb", "hue_shift", -30.0, 30.0, 2.0),
    # content — salience+intensity owned by imagination loop, sediment by post.
    # Joint-constrained (intensity × sediment invariant); walker writes
    # content.intensity *delta* but the imagination fragment owns the BASE,
    # so the constraint applies to the resulting absolute value.
    ParameterEnvelope(
        "content",
        "intensity",
        0.0,
        0.35,
        0.10,
        joint_constraints=(INTENSITY_DEGRADATION_INVARIANT,),
    ),
    # post — postprocess, sediment is joint-constrained
    ParameterEnvelope("post", "vignette_strength", 0.0, 0.25, 0.02),
    ParameterEnvelope(
        "post",
        "sediment_strength",
        0.0,
        0.05,
        0.02,
        joint_constraints=(INTENSITY_DEGRADATION_INVARIANT,),
    ),
)


def envelopes() -> tuple[ParameterEnvelope, ...]:
    """Return the canonical envelope set, frozen tuple.

    Used by :mod:`agents.parametric_modulation_heartbeat` to drive the
    constrained walk. Test fixtures monkeypatch this for deterministic
    behaviour.
    """

    return _ENVELOPES


def envelope_by_key(key: str) -> ParameterEnvelope | None:
    """Resolve an envelope by ``{node_id}.{param_name}`` key, or None."""

    for env in _ENVELOPES:
        if env.key == key:
            return env
    return None


def joint_constraints() -> tuple[JointConstraint, ...]:
    """Return the deduplicated joint constraints across all envelopes.

    Used for joint-constraint enforcement after the per-parameter walk
    step so the walker can dampen any pair that breaches the ceiling.
    """

    seen: set[tuple[str, str]] = set()
    out: list[JointConstraint] = []
    for env in _ENVELOPES:
        for jc in env.joint_constraints:
            sig = tuple(sorted((jc.param_a_key, jc.param_b_key)))
            if sig in seen:
                continue
            seen.add(sig)
            out.append(jc)
    return tuple(out)


__all__ = [
    "FEEDBACK_DECAY_ROTATE_INVARIANT",
    "INTENSITY_DEGRADATION_INVARIANT",
    "JointConstraint",
    "ParameterEnvelope",
    "RD_FEED_KILL_INVARIANT",
    "envelope_by_key",
    "envelopes",
    "joint_constraints",
]
