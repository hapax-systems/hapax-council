"""Recompose continuity: every recompose pass is an ITERATIVE revision, not a cold start.

The coherence-low refine path already carried the prior draft; the disconfirmation,
narrative, and actionability recompose paths used to compose FRESH from
``seed + feedback`` — discarding the prior (often coherence-refined) draft and regressing
its quality. They now route through ``_build_refine_seed`` like the refine path, so the
prior draft + the gate's feedback are both carried. Self-contained per council test
conventions.
"""

from __future__ import annotations

from agents.hapax_daimonion.daily_segment_prep import _build_refine_seed


def test_refine_seed_carries_prior_draft_for_iterative_recompose() -> None:
    script = ["beat one — the blank attribution field", "beat two — the legal void"]
    seed = "== RECRUITED SOURCES ==\nsrc:0 the attribution log"
    feedback = "argumentative_specificity is weak; ground the claim in the source"
    out = _build_refine_seed(seed, script, feedback)
    # The prior draft is carried — recompose is a revision, never a cold start.
    assert "beat one — the blank attribution field" in out
    assert "beat two — the legal void" in out
    assert "PRIOR DRAFT" in out
    assert seed in out
    assert feedback in out


def test_refine_seed_framing_is_gate_neutral() -> None:
    # The refine seed is now shared by the disconfirmation / narrative / actionability
    # recompose paths too, so its framing must not name a single gate.
    out = _build_refine_seed("seed", ["a beat"], "some feedback")
    assert "coherence council" not in out
    assert "council" in out  # still framed as a council-judged revision
