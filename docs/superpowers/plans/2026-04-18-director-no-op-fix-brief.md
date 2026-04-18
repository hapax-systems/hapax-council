# Director "Do Nothing" Invariant Fix — PR Brief

**Status:** 🟢 READY TO SHIP (no further spec needed)
**Last updated:** 2026-04-18
**Source:** [`docs/superpowers/research/2026-04-18-cvs-research-dossier.md`](../research/2026-04-18-cvs-research-dossier.md) §2 (#158) + `/tmp/cvs-research-158.md`
**Priority:** 🚨 HIGHEST — live invariant violation 25.03% of director ticks

---

## 1. Why Brief, Not Spec

This is a **fix PR**, not a new feature. The operator's invariant is already partially codified in `_emit_micromove_fallback` (2026-04-18). Three of four vacuum paths are plugged. This brief is the checklist to close the fourth, tighten the schema, remove the contradictory prompt language, and pin behavior with a regression test.

---

## 2. The Four Vacuum Paths

| # | Path | Status |
|---|---|---|
| 1 | LLM returns empty | ✅ plugged by `_emit_micromove_fallback` |
| 2 | Narrative repeats prior | ✅ plugged by `_emit_micromove_fallback` |
| 3 | Silence-or-empty reasoning | ✅ plugged by `_emit_micromove_fallback` |
| 4 | **Parser-error fallback in `_parse_intent_from_llm`** | ❌ **OPEN — the 25% leak** |

The parser-error path constructs `DirectorIntent` with `compositional_impingements=[]` without going through `_emit_micromove_fallback`. This is the live bug.

---

## 3. The Endorsing Docstring

`shared/director_intent.py:173`:

> *"Zero impingements means the director chose to reinforce the prior state."*

This **directly contradicts** operator directive. Must be changed.

---

## 4. The Contradictory Prompt

`agents/studio_compositor/director_loop.py:638` (`ACTIVITY_CAPABILITIES`):

> *"silence is a legal option"* ... *"EVEN IN SILENCE: emit at least one compositional_impingement"*

Non-deterministic compliance. Remove the "silence is legal" framing.

---

## 5. PR Changeset

### Change 1: Close parser-error vacuum path

**File:** `agents/studio_compositor/director_loop.py` (in `_parse_intent_from_llm`)

Replace parser-error construction `DirectorIntent(compositional_impingements=[], ...)` with a call to `_emit_micromove_fallback(reason="parser_error")`. The micromove fallback already guarantees at least one impingement.

### Change 2: Tighten schema

**File:** `shared/director_intent.py`

```python
compositional_impingements: list[CompositionalImpingement] = Field(
    ...,
    min_length=1,
    description=(
        "One or more impingements the director commits to emit this tick. "
        "Every tick MUST produce at least one. There is no justifiable "
        "context where zero impingements is acceptable (operator invariant "
        "2026-04-18). If the LLM returned empty, the micromove fallback "
        "must populate this field before construction."
    ),
)
```

Remove the old "reinforce the prior state" language. Pydantic validation now catches any zero-length attempt at construction time.

### Change 3: Remove contradictory prompt framing

**File:** `agents/studio_compositor/director_loop.py:638` (`ACTIVITY_CAPABILITIES`)

Delete "silence is a legal option" clause. Replace with:

> *"Every tick must produce at least one compositional_impingement. Even at the lowest activity level, emit a micromove (stance hold, minimal preset parameter nudge, ward brightness tick) rather than nothing."*

### Change 4: Historical-replay regression test

**New file:** `tests/studio_compositor/test_director_no_noop_invariant.py`

Two complementary tests:
- **Fixture-based:** 10-minute canned livestream recording, cadence forced to 10 s. Run director. Assert zero empty-impingement ticks.
- **Historical replay:** trailing 2000 `director-intent.jsonl` records. Fails today (25.03% no-op); after Change 1 + 2, should pass.

Fixture location: `tests/fixtures/director/10min-canned-livestream.jsonl` — capture fresh from live hapax-state if not yet present.

### Change 5: Observability

**File:** `shared/director_observability.py`

Add metric `hapax_director_vacuum_prevented_total{reason}` — counter incremented by `_emit_micromove_fallback` with reason-label (`parser_error`, `llm_empty`, `narrative_repeat`, `silence`). Lets Grafana trend vacuum frequency vs. time.

---

## 6. Test Expectations

- Pre-PR: historical replay fails on 184/735 lines (25.03%).
- Post-PR: historical replay passes on a fresh run of 2000 live ticks.
- Pre-PR: schema accepts `DirectorIntent(compositional_impingements=[])`.
- Post-PR: same construction raises `ValidationError`.
- Pre-PR: prompt tells LLM "silence is legal".
- Post-PR: prompt tells LLM "every tick emits at least one".

---

## 7. Rollback

Feature flag `HAPAX_DIRECTOR_STRICT_INVARIANT` default ON. Setting to OFF reverts Change 2 schema validation to `min_length=0` (Changes 1/3/4 have no flag — they're always-on because they're correctness fixes, not behavior changes).

---

## 8. Dependencies

None internal. **Pairs naturally with #150** (vision integration) — one root cause of director punting is that rich perception signals aren't reaching it, so when asked to act it has nothing to act on. #150's Phase 1 (scene → preset-family bias) provides more raw action candidates, reducing pressure on the fallback.

---

## 9. Acceptance

- [ ] All 4 changes above merged in a single PR
- [ ] Regression test green locally + in CI
- [ ] Historical replay passes on 2000-record window post-deploy
- [ ] Grafana panel confirms `hapax_director_vacuum_prevented_total` is non-zero (fallback fires when needed) and stays stable
- [ ] Operator verifies on livestream: no visible "pulse goes quiet" moments for 30-minute observation window

---

## 10. Related

- **Dossier §2 #158** (source)
- **Task #91** iterative director sim runs (this invariant was what the iterations were closing toward; the live 25% leak is what was slipping through)
- **Task #150** vision integration (reduces pressure on fallback by feeding director richer signals)
- **Task #148** reactivity sync gap — orthogonal; different invariant layer
