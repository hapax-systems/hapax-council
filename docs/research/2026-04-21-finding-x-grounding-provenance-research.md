# FINDING-X — Grounding-Provenance Constitutional Violation Research

**Author:** delta
**Date:** 2026-04-21
**Status:** research complete — spec + plan follow
**References:**

- Origin: `docs/research/2026-04-20-wiring-audit-findings.md` §FINDING-X (lines 821–842)
- Observability fix landed: `agents/studio_compositor/director_loop.py:449-460` +
  `shared/director_observability.py:349-384` (`emit_ungrounded_audit`)
- Memory: `feedback_grounding_exhaustive` — architectural axiom "every move is
  grounded or outsourced-by-grounding"

## 1. Executive Summary

The observability half of FINDING-X has shipped: every `DirectorIntent` emitted by
the compositor is now checked via `emit_ungrounded_audit`, which warn-logs and
increments `hapax_director_ungrounded_total{scope="intent|impingement"}` on each
empty `grounding_provenance`. Journalctl confirms 337 UNGROUNDED warnings in the
last 6 hours — the silent-violation is no longer silent.

The constitutional half is still open. Live measurement against
`~/hapax-state/stream-experiment/director-intent.jsonl` (recent 200 entries):

| metric | pre-fix (2026-04-19) | post-obs-fix (2026-04-21) |
|---|---|---|
| impingements sampled | 430 | 299 |
| empty `grounding_provenance` | 428 (99.5 %) | 163 (54.5 %) |
| populated | 2 (0.5 %) | 136 (45.5 %) |
| UNGROUNDED warnings logged | 0 | 337 (≥1 per empty) |

Populated entries are overwhelmingly deterministic-fallback strings
(`fallback.micromove.*`, `fallback.parser_*`, `fallback.parser_legacy_shape`).
These are legitimate — per the `feedback_grounding_exhaustive` memory the ground
is the fallback type, and `_silence_hold_impingement` / `_micromove_impingement`
populate them. LLM-authored impingements remain the empty-provenance majority.

The axiom "every impingement is grounded" is therefore still violated at runtime
by LLM emissions roughly half the time. The observability layer quantifies the
violation; it does not prevent it.

## 2. Source Classification

Every `CompositionalImpingement` emission in `agents/studio_compositor/` and
`shared/director_intent.py` falls into one of three classes.

### 2.1 Fallback-path emissions (deterministic code)

- `_silence_hold_impingement(reason)` — `shared/director_intent.py:48-58`
  populates `grounding_provenance=[f"fallback.{reason}"]`.
- `_micromove_impingement` — `director_loop.py:~1595` populates
  `grounding_provenance=[f"fallback.micromove.{reason}"]`.
- `parser_non_dict` / `parser_legacy_shape` fallbacks in
  `director_loop._parse_intent_from_llm` populate
  `grounding_provenance=[f"fallback.parser_{reason}"]`.

All three are compliant. The "ground" is the deterministic-code reason, which
matches the memory's "ground IS the fallback type" principle. No work needed
here.

### 2.2 LLM-authored emissions

Produced by `director_loop._run_director_llm_call` → `pydantic-ai` structured
output. The prompt (lines 2420–2426 of `director_loop.py`) explicitly instructs
the LLM:

> **Mandatory grounding_provenance per impingement.** Every
> compositional_impingement carries the perceptual-field key that made it
> felt-necessary. …

Empirically the LLM ignores this ~54 % of the time. The schema
(`shared/director_intent.py:140-150`) has `default_factory=list`, so an empty
list is a valid Pydantic model and passes validation.

### 2.3 Test-only emissions

`tests/shared/test_director_intent.py` constructs impingements with empty
provenance to test validator edge cases. Out of scope for production fix —
these are deliberate.

## 3. Observability State (already shipped)

| surface | path / name | status |
|---|---|---|
| warn-log | `studio-compositor` journald | live (337 hits / 6 h) |
| Prometheus counter | `hapax_director_ungrounded_total{condition_id,scope}` | registered in `director_observability.py:311-322` |
| audit hook call | `director_loop.py:449-460` | wired after every decision |
| grounding-provenance ticker ward | `GroundingProvenanceTickerCairoSource` | renders last INTENT's provenance; FINDING-V retirement confirms this ward works as-is (tails `director-intent.jsonl`) |

Grafana dashboard for `hapax_director_ungrounded_total` does not exist. It is
the cheapest visibility win remaining.

## 4. Options for the Constitutional Fix

### Option A — Pydantic schema enforcement (strict, breaks compat)

Change `CompositionalImpingement.grounding_provenance` from
`default_factory=list` to `Field(min_length=1)`. LLM emissions with empty
provenance would fail Pydantic validation at parse time, and pydantic-ai's
output-validator retry would kick in automatically.

**Pros:** eliminates empty provenance at the type system boundary. No runtime
branch needed.

**Cons:**

- Every existing test that constructs impingements without provenance must
  be updated (`tests/shared/test_director_intent.py` has many cases).
- Pydantic-ai's retry budget adds latency on LLM non-compliance turns.
- If the LLM is structurally incapable of emitting provenance for certain
  move types (unlikely but possible), this would cause retry storms.
- The `default_factory=list` was chosen deliberately (spec §3.4 of the
  volitional-grounded-director design doc says "Empty list is allowed (the
  pipeline accepts ungrounded fallback) but warrants inspection"). Changing
  it reverses that design decision.

### Option B — Post-parse synthesis (liberal, always compliant)

Introduce a post-parse hook `_ensure_impingement_grounded(impingement, context)`
in `director_loop._parse_intent_from_llm`. For any impingement with empty
`grounding_provenance`, synthesize a provenance from available context:

```python
def _ensure_impingement_grounded(
    imp: CompositionalImpingement, *, stance: Stance, narrative: str
) -> CompositionalImpingement:
    if imp.grounding_provenance:
        return imp
    # The ground IS the fallback type (per feedback_grounding_exhaustive).
    # Synthesize a deterministic marker so the invariant holds and downstream
    # wards can render something other than "(ungrounded)".
    synth = f"inferred.{stance.value.lower()}.{imp.intent_family}"
    _ungrounded_synth_total.labels(intent_family=imp.intent_family).inc()
    return imp.model_copy(update={"grounding_provenance": [synth]})
```

**Pros:**

- 100 % of impingements carry non-empty provenance downstream.
- Deterministic-fallback semantics (same pattern as `_silence_hold_impingement`).
- New counter (`hapax_director_ungrounded_synth_total`) separates "LLM
  compliant" from "we had to synthesize" — more actionable than the existing
  UNGROUNDED counter which mixes categories.
- No test breakage: existing tests that construct with empty provenance are
  upstream of the parse path; only `_parse_intent_from_llm` runs the hook.

**Cons:**

- Synthesized provenance strings are not grounded in actual perception, so
  `GroundingProvenanceTickerCairoSource` will show synthetic strings in the
  synthesized cases. This is visible but acceptable — better than `* (ungrounded)`.
- Hides the LLM-compliance problem from the surface, so if the LLM
  regresses to 99 % empty we won't see it in the live stream. The
  Prometheus counter catches it, but an operator looking at the ward would
  see stable synthetic strings.

### Option C — Prompt strengthening + retry (incremental, polish)

Tighten the director prompt's grounding section (add an example, add a
"without a grounding key your impingement will be rejected" line), plus add a
pydantic-ai output validator that retries once if any impingement has empty
provenance. On second failure, fall back to Option B synthesis.

**Pros:**

- Addresses the LLM-compliance root cause first.
- Still lands at a 100 % invariant via synthesis.

**Cons:**

- Adds LLM call latency (retry path) in the worst case.
- Prompt changes have unpredictable downstream effects on director behavior;
  regression risk in other intent fields.

## 5. Recommended Approach

**Option B as the primary fix** + prompt-strengthening from Option C as a
smaller adjacent improvement.

Rationale:

- Option B guarantees the constitutional invariant without LLM-call
  latency impact.
- Synthesizing from `(stance, intent_family)` preserves the "ground IS the
  fallback type" principle — the synthetic provenance IS the deterministic
  reason the impingement was emitted even though the LLM didn't articulate it.
- The new `hapax_director_ungrounded_synth_total` counter preserves the
  visibility that Option A would lose (Pydantic validation failures are
  harder to track in aggregate).
- Option A's test-breakage cost is high; most existing tests construct
  empty-provenance impingements for validator edge-case coverage.
- Prompt strengthening (Option C increment) is low-risk and compounds the
  Option B fix — fewer synthesized cases over time.

## 6. Proposed Scope

Ship in three phases:

- **Phase 1 (small):** Post-parse synthesis hook in
  `_parse_intent_from_llm`, new `hapax_director_ungrounded_synth_total`
  counter, test for hook behavior. Shipped as one PR.
- **Phase 2 (small, independent):** Grafana panel for
  `hapax_director_ungrounded_total` + `hapax_director_ungrounded_synth_total`
  rates. One PR against `systemd/grafana-dashboards/`.
- **Phase 3 (polish):** Director prompt strengthening — one-line addition in
  `director_loop.py` and a new test asserting the prompt contains the
  required clause. One PR.

Phase 1 closes the constitutional axiom violation. Phases 2 and 3 are polish.

## 7. Out of Scope

- Perceptual-field signal catalog. Any work to make the LLM able to name more
  signals (by expanding perceptual_field to include previously-unexposed
  signals) is a separate concern. FINDING-X is specifically about the
  invariant, not the grounding vocabulary.
- HARDM / legibility surface redesign. The grounding-provenance ticker ward
  already works; any redesign is independent of this research.
- Revising the constitutional axiom itself. The memory
  `feedback_grounding_exhaustive` is explicit that the axiom is correct as
  stated. We converge the implementation to match, not the other way round.

## 8. Acceptance Criteria

- `hapax_director_ungrounded_total{scope="impingement"}` should decay toward
  zero over time (the raw LLM-compliance rate).
- `hapax_director_ungrounded_synth_total` should account for 100 % of
  previously-unobserved empty-provenance cases (every synth is one less
  ungrounded empty).
- INTENT JSONL inspection: every `compositional_impingement` has non-empty
  `grounding_provenance` within 5 minutes of service restart.
- No test breakage (tests that construct empty-provenance impingements
  remain valid — the hook only runs in the LLM parse path).
