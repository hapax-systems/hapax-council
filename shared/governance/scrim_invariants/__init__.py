"""Scrim invariants — three-bound governance metrics for OQ-02.

Per `docs/research/2026-04-20-nebulous-scrim-three-bound-invariants-triage.md`
this package houses the oracles for the three hard bounds on every Nebulous
Scrim effect and chain:

  - **anti_recognition** (B1): face-recognition distance against operator's
    enrolled embedding > identifiability threshold.
  - **scrim_translucency** (B2): scene-legibility metric > minimum threshold;
    audience must always perceive a studio with inhabitants/objects/content.
  - **anti_visualizer** (B3): visualizer-register score < threshold; audio
    modulates but does not iconographically illustrate.

Operator GO received 2026-04-20 — modules ship as live oracles. Runtime
trackers wire via the same degraded-signal pattern as
``agents/studio_compositor/budget_signal.py``. Enforcement actions
(coupling-gain dampening, scrim-density forcing, fail-loud sentinels) are
gated by per-bound HAPAX_SCRIM_INVARIANT_* env vars defaulting to
observe-only so a false-positive metric never breaks the broadcast.
"""
