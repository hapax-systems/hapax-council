"""Parametric modulation heartbeat — constrained parameter walker.

Operator directive (2026-05-02T22:13Z, ``feedback_no_presets_use_parametric_modulation``):

    "we should be relying on constrained algorithmic parametric modulation
    and combination and chaining of effects at the node graph level.
    Presets are dumb. Be smart about this."

This agent supersedes :mod:`agents.preset_bias_heartbeat` (PR #2239).
The preset-bias unit uniform-samples 27 frozen preset families when LLM
recruitment stalls — that is the wrong unit of variance. Per the directive
+ the cc-task at ``parametric-modulation-heartbeat.md``, variance must
emerge from the **generative substrate**: the per-node ``params_buffer``
documented in CLAUDE.md § Reverie Vocabulary Integrity.

**What this agent does (per cc-task spec acceptance criteria):**

1. Walks the per-node parameter space (``{node_id}.{param_name}``) within
   :func:`shared.parameter_envelopes.envelopes` constraints. Walk uses a
   low-frequency oscillator (LFO) per parameter + perturbation noise — no
   random jumps. Smoothness invariant: ``|delta| ≤ envelope.smoothness``
   per tick.
2. Honors joint constraints (e.g. ``content.intensity × post.sediment_strength``
   must not both peak — would clip pipeline to noise).
3. Writes deltas to the existing ``/dev/shm/hapax-imagination/uniforms.json``
   bridge that ``agents.reverie._uniforms.write_uniforms`` reads. This is
   the **same surface** the visual chain writes to — heartbeat composes
   with chain-driven modulation, never replaces it.
4. On envelope **boundary crossings** (parameter approaching min/max),
   emits a transition primitive (``transition.fade.smooth`` /
   ``transition.cut.hard`` / etc.) via ``recent-recruitment.json`` with
   ``kind: "transition_primitive"``. **NOT** ``kind: "preset.bias"``.
5. On affordance shifts (read from imagination_loop's recruited
   affordances stream), the walker shifts which envelopes it actively
   modulates — leveraging the existing AffordancePipeline output, not a
   hardcoded list.

**What this agent explicitly does NOT do:**

- Sample from ``presets/`` directory or preset_family_selector
  (``test_no_preset_family_in_module`` + ``test_no_preset_path_imports`` enforce this).
- Pick a frozen snapshot of "good" values.
- Modify the GPU uniform buffer schema (the 9 dimensions stay).
- Modify imagination_loop, affordance pipeline, or DMN tick — those are
  already correct (parameter-driven, recruited).

**Composition with PR #2239:** the preset-bias heartbeat module is
**not deleted in this PR** (revert-safety per cc-task constraints). Both
units may run alongside during transition; operator disables the preset
unit post-merge by stopping ``hapax-preset-bias-heartbeat.service``.

Spec: ``docs/superpowers/specs/2026-05-02-parametric-modulation-heartbeat.md``.
"""

from __future__ import annotations

from agents.parametric_modulation_heartbeat.heartbeat import (
    DEFAULT_LFO_PERIOD_S,
    DEFAULT_PERTURBATION,
    DEFAULT_TICK_S,
    HEARTBEAT_SOURCE,
    RECRUITMENT_FILE,
    UNIFORMS_FILE,
    BoundaryEvent,
    ParameterWalker,
    emit_transition_primitive,
    run_forever,
    tick_once,
    write_uniform_overrides,
)

__all__ = [
    "BoundaryEvent",
    "DEFAULT_LFO_PERIOD_S",
    "DEFAULT_PERTURBATION",
    "DEFAULT_TICK_S",
    "HEARTBEAT_SOURCE",
    "ParameterWalker",
    "RECRUITMENT_FILE",
    "UNIFORMS_FILE",
    "emit_transition_primitive",
    "run_forever",
    "tick_once",
    "write_uniform_overrides",
]
