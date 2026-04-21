---
date: 2026-04-21
author: delta
status: draft
related:
  - docs/research/2026-04-21-finding-x-grounding-provenance-research.md
  - docs/research/2026-04-20-wiring-audit-findings.md
  - shared/director_intent.py
  - shared/director_observability.py
  - agents/studio_compositor/director_loop.py
scope: constitutional-invariant enforcement for grounding_provenance
---

# FINDING-X Grounding-Provenance Synthesis — Design

## 1. Goal

Close the FINDING-X constitutional-invariant gap. After this change:

- Every `CompositionalImpingement` downstream of `director_loop._parse_intent_from_llm`
  has non-empty `grounding_provenance`, guaranteed by construction.
- The existing observability surface (`hapax_director_ungrounded_total`)
  continues to measure raw LLM compliance.
- A new observability surface (`hapax_director_ungrounded_synth_total`)
  measures how often we had to synthesize — operator-visible signal for
  LLM-compliance drift.

## 2. Approach: post-parse synthesis

Per the research doc §5, Option B. A single post-parse hook in
`_parse_intent_from_llm` scans every impingement on the parsed
`DirectorIntent`. For any impingement with empty `grounding_provenance`, the
hook synthesizes a deterministic marker string and swaps the field.

Synthesis rule:

```
"inferred.<stance>.<intent_family>"
```

Rationale:

- Matches the existing fallback-provenance grammar (`fallback.*`).
- Names both the system state (`stance`) and the move's structural class
  (`intent_family`), so the synthetic key carries real context.
- Distinguishable from fallback and from real perceptual-field keys via the
  `inferred.` prefix.
- Deterministic: same (stance, family) pair always yields the same marker, so
  downstream wards that dedupe on provenance strings behave predictably.

## 3. Scope

**In scope:**

- New helper `_ensure_impingement_grounded(imp, *, stance) -> CompositionalImpingement`.
- Invocation site in `director_loop._parse_intent_from_llm` after the parsed
  `DirectorIntent` is constructed, before return.
- New Prometheus counter `hapax_director_ungrounded_synth_total{intent_family}`.
- Tests: hook behavior + counter increment + no-op on already-populated.
- Light prompt reinforcement in the director prompt's grounding section.

**Out of scope:**

- Changes to the `CompositionalImpingement` Pydantic schema.
- Changes to `emit_ungrounded_audit` (keep firing on LLM empties so we keep
  the compliance-rate measurement separate from the synth rate).
- Grafana dashboard — separate follow-up PR.
- Any change to fallback-path emitters (they already populate correctly).

## 4. Type contracts

The hook is a pure function:

```python
def _ensure_impingement_grounded(
    imp: CompositionalImpingement,
    *,
    stance: Stance,
) -> CompositionalImpingement:
    """Ensure `imp.grounding_provenance` is non-empty.

    If the LLM emitted a provenance, returns the impingement unchanged.
    If empty, returns a copy with a synthetic "inferred.{stance}.{family}"
    provenance entry and increments the synth counter.
    """
```

Call site (in `_parse_intent_from_llm`, after Pydantic parses the LLM output):

```python
intent = DirectorIntent(**parsed)
intent = intent.model_copy(
    update={
        "compositional_impingements": [
            _ensure_impingement_grounded(imp, stance=intent.stance)
            for imp in intent.compositional_impingements
        ],
    }
)
return intent
```

## 5. Observability

Prometheus counter in `shared/director_observability.py`:

```python
_ungrounded_synth_total = Counter(
    "hapax_director_ungrounded_synth_total",
    (
        "CompositionalImpingements whose grounding_provenance was empty from "
        "the LLM and had to be synthesized to preserve the constitutional "
        "invariant. A rising rate indicates LLM-compliance drift. Separate "
        "from hapax_director_ungrounded_total, which continues to count "
        "raw LLM empties pre-synthesis."
    ),
    labelnames=("intent_family",),
)
```

Exposed via the existing director-observability registry. No new scrape
target.

## 6. Behavioral changes

| consumer | pre-fix | post-fix |
|---|---|---|
| `GroundingProvenanceTickerCairoSource` | renders `* (ungrounded)` when INTENT JSONL row has empty provenance | renders `inferred.<stance>.<family>` string; synthetic but non-empty |
| `hapax_director_ungrounded_total{scope="impingement"}` | rate matches raw LLM empty rate (~54 %) | unchanged — this counter measures LLM compliance, fires BEFORE synthesis in `emit_ungrounded_audit` |
| `hapax_director_ungrounded_synth_total{intent_family}` | n/a (new) | rate matches post-synthesis empties, ~54 % at deploy, should decay with prompt improvements |
| `director-intent.jsonl` rows | empty `grounding_provenance` lists | populated with synth markers for previously-empty cases |

## 7. Invariant

After this change, the following assertion holds for every INTENT JSONL row
written by `director_loop` after 60 s of service uptime:

```python
assert all(imp.grounding_provenance for imp in row.compositional_impingements)
```

This is the axiom `feedback_grounding_exhaustive` demands. The assertion
should be added as a regression test in `tests/studio_compositor/` that runs
the director loop over sample LLM outputs and asserts the invariant.

## 8. Prompt adjustment (adjacent polish)

One-line addition to the director prompt, after the existing
"Mandatory grounding_provenance per impingement" clause:

> Missing a grounding_provenance entry does not fail the pipeline but causes
> a synthetic marker to be inserted, which is less specific than a real
> perceptual-field key. Prefer naming the key.

Low-risk, reinforces the compliance incentive without introducing parse-path
strictness.

## 9. Acceptance Criteria

Mirrored from the research doc §8:

- Every `compositional_impingement` in `director-intent.jsonl` has non-empty
  `grounding_provenance` within 5 minutes of service restart.
- `hapax_director_ungrounded_synth_total` accounts for every synthesized
  case (no unaccounted-for empty in JSONL).
- No existing test breakage — the synthesis hook only runs in the LLM-parse
  path; tests that construct `CompositionalImpingement` with empty provenance
  at model-construction time continue to pass.
- `emit_ungrounded_audit` continues to warn-log empty LLM emissions
  pre-synthesis.

## 10. Risks

- **Synth-string flooding the ticker ward.** If LLM compliance never
  improves, the ward becomes dominated by `inferred.*` strings that carry
  less signal than real provenance. Mitigation: the synth counter gives
  operator-visible pressure to strengthen the prompt (Phase 3 work).
- **Intent-family cardinality explosion in Prometheus.** The counter has
  one label (`intent_family`). Cardinality is bounded by the 18-item
  `INTENT_FAMILY_LITERAL` enum. Safe.
- **Post-parse ordering**: the hook must run AFTER the Pydantic parse but
  BEFORE `emit_ungrounded_audit` is called, otherwise audit counters would
  zero out. Call-order is enforced in `_parse_intent_from_llm` and asserted
  in the new test.

## 11. Follow-ups

- Grafana panel for the two counters (separate PR under
  `systemd/grafana-dashboards/`).
- Prompt polish (separate PR in `director_loop.py`).
- If LLM compliance improves to >95 %, consider making the synth a WARN-log
  (currently DEBUG) so the remaining tail is actionable.
