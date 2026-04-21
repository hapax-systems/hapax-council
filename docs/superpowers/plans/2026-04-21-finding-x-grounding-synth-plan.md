# FINDING-X Grounding-Provenance Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Close the constitutional-invariant gap where LLM-emitted `CompositionalImpingement`s can have empty `grounding_provenance`. After this ships, every impingement downstream of the parser carries non-empty provenance (real LLM-emitted, fallback-populated, or synthesized).

**Architecture:** Single synthesis hook in `director_loop._parse_intent_from_llm`, new Prometheus counter in `shared/director_observability.py`, invariant regression test. See spec: `docs/superpowers/specs/2026-04-21-finding-x-grounding-synth-design.md`.

**Tech Stack:** Python 3.12+, Pydantic, pytest, prometheus_client.

---

## File Structure

- Modify: `agents/studio_compositor/director_loop.py` — add `_ensure_impingement_grounded` helper + wire into `_parse_intent_from_llm`.
- Modify: `shared/director_observability.py` — add `_ungrounded_synth_total` counter; expose in `__all__`.
- Create: `tests/studio_compositor/test_grounding_provenance_synthesis.py`
- Modify: director prompt clause in `director_loop.py` (adjacent polish).

---

## Task 1: Prometheus counter

**Files:**

- Modify: `shared/director_observability.py`
- Test: `tests/shared/test_director_observability.py` (extend)

- [ ] **Step 1: Extend observability test with synth-counter assertion**

```python
def test_ungrounded_synth_counter_registered():
    from shared.director_observability import _ungrounded_synth_total
    assert _ungrounded_synth_total is not None
    # Exercise the counter
    _ungrounded_synth_total.labels(intent_family="camera.hero").inc()
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/shared/test_director_observability.py::test_ungrounded_synth_counter_registered -v
```

- [ ] **Step 3: Add counter in `director_observability.py`**

Add after the existing `_ungrounded_total` definition (around line 322):

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

Add to `__all__`:

```python
__all__ = [
    ...,
    "_ungrounded_synth_total",
]
```

- [ ] **Step 4: Run test, confirm PASS**

- [ ] **Step 5: Commit**

```bash
git add shared/director_observability.py tests/shared/test_director_observability.py
git commit -m "feat(observability): hapax_director_ungrounded_synth_total counter (FINDING-X)"
```

---

## Task 2: Synthesis hook

**Files:**

- Modify: `agents/studio_compositor/director_loop.py`
- Test: `tests/studio_compositor/test_grounding_provenance_synthesis.py`

- [ ] **Step 1: Write failing hook test**

```python
# tests/studio_compositor/test_grounding_provenance_synthesis.py
from shared.director_intent import (
    CompositionalImpingement,
    DirectorIntent,
    Stance,
)
from agents.studio_compositor.director_loop import (
    _ensure_impingement_grounded,
)

def test_populated_provenance_unchanged():
    imp = CompositionalImpingement(
        narrative="focus on vinyl", intent_family="camera.hero",
        grounding_provenance=["audio.midi.beat_position"],
    )
    result = _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    assert result.grounding_provenance == ["audio.midi.beat_position"]
    assert result is imp  # no-op copy avoided

def test_empty_provenance_synthesized():
    imp = CompositionalImpingement(
        narrative="noop", intent_family="preset.bias",
        grounding_provenance=[],
    )
    result = _ensure_impingement_grounded(imp, stance=Stance.SEEKING)
    assert result.grounding_provenance == ["inferred.seeking.preset.bias"]

def test_synth_counter_increments_on_empty():
    from shared.director_observability import _ungrounded_synth_total
    before = _ungrounded_synth_total.labels(
        intent_family="ward.highlight"
    )._value.get()
    imp = CompositionalImpingement(
        narrative="surface this", intent_family="ward.highlight",
        grounding_provenance=[],
    )
    _ensure_impingement_grounded(imp, stance=Stance.NOMINAL)
    after = _ungrounded_synth_total.labels(
        intent_family="ward.highlight"
    )._value.get()
    assert after - before == 1.0
```

- [ ] **Step 2: Run — expect ImportError on `_ensure_impingement_grounded`**

```bash
uv run pytest tests/studio_compositor/test_grounding_provenance_synthesis.py -v
```

- [ ] **Step 3: Implement hook in `director_loop.py`**

Add near the other `_impingement` helper functions (search for `_silence_hold_impingement`):

```python
def _ensure_impingement_grounded(
    imp: CompositionalImpingement,
    *,
    stance: Stance,
) -> CompositionalImpingement:
    """Constitutional invariant guard: every CompositionalImpingement carries
    non-empty grounding_provenance.

    LLM emissions sometimes omit the field despite the prompt's mandate.
    This hook synthesizes a deterministic "inferred.<stance>.<family>" marker
    so downstream wards see a grounded impingement, and increments a counter
    so LLM-compliance drift stays operator-visible.

    Fallback-path emitters (_silence_hold_impingement, _micromove_impingement,
    parser_non_dict) populate provenance eagerly, so the hook is a no-op on
    their output. Only LLM emissions trigger the synthesis branch.
    """
    if imp.grounding_provenance:
        return imp
    try:
        from shared.director_observability import _ungrounded_synth_total

        _ungrounded_synth_total.labels(intent_family=imp.intent_family).inc()
    except Exception:
        log.debug("synth counter increment failed", exc_info=True)
    synthetic = f"inferred.{stance.value.lower()}.{imp.intent_family}"
    return imp.model_copy(update={"grounding_provenance": [synthetic]})
```

- [ ] **Step 4: Run tests, confirm PASS**

- [ ] **Step 5: Commit**

```bash
git add agents/studio_compositor/director_loop.py tests/studio_compositor/test_grounding_provenance_synthesis.py
git commit -m "feat(director): grounding-provenance synthesis hook (FINDING-X Phase 1)"
```

---

## Task 3: Wire hook into `_parse_intent_from_llm`

**Files:**

- Modify: `agents/studio_compositor/director_loop.py`
- Test: extend `test_grounding_provenance_synthesis.py` with an integration case.

- [ ] **Step 1: Write failing integration test**

```python
def test_parse_intent_from_llm_synthesizes_empties(monkeypatch):
    """End-to-end: LLM returns a dict with empty provenance; after parse, the
    invariant holds."""
    from agents.studio_compositor.director_loop import _parse_intent_from_llm

    raw = {
        "stance": "nominal",
        "narrative_text": "steady",
        "grounding_provenance": [],
        "compositional_impingements": [
            {
                "narrative": "neutral ambient",
                "intent_family": "preset.bias",
                "grounding_provenance": [],
                "salience": 0.3,
            },
        ],
    }
    intent = _parse_intent_from_llm(raw, condition_id="test")
    assert intent is not None
    for imp in intent.compositional_impingements:
        assert imp.grounding_provenance, (
            f"impingement {imp.intent_family} has empty provenance after parse"
        )
```

- [ ] **Step 2: Run — expect empty provenance on the parsed output**

- [ ] **Step 3: Inject hook into `_parse_intent_from_llm`**

Locate the return statement at the end of `_parse_intent_from_llm` (search for `return DirectorIntent` or `return intent`). Insert immediately before the return:

```python
intent = intent.model_copy(
    update={
        "compositional_impingements": [
            _ensure_impingement_grounded(imp, stance=intent.stance)
            for imp in intent.compositional_impingements
        ],
    }
)
```

- [ ] **Step 4: Run integration test, confirm PASS**

- [ ] **Step 5: Verify existing tests still pass**

```bash
uv run pytest tests/studio_compositor/ tests/shared/ -q
```

- [ ] **Step 6: Commit**

```bash
git add agents/studio_compositor/director_loop.py tests/studio_compositor/test_grounding_provenance_synthesis.py
git commit -m "feat(director): wire grounding synthesis into _parse_intent_from_llm"
```

---

## Task 4: Prompt polish (adjacent)

**Files:**

- Modify: `agents/studio_compositor/director_loop.py` (prompt literal around line 2420)

- [ ] **Step 1: Locate the "Mandatory grounding_provenance per impingement" clause**

```bash
grep -n "Mandatory grounding_provenance per impingement" agents/studio_compositor/director_loop.py
```

- [ ] **Step 2: Append one line after that clause**

```python
"Missing a grounding_provenance entry does not fail the pipeline "
"but causes a synthetic marker to be inserted, which is less "
"specific than a real perceptual-field key. Prefer naming the key."
```

- [ ] **Step 3: Commit**

```bash
git add agents/studio_compositor/director_loop.py
git commit -m "docs(director): prompt note on synth-marker cost of empty provenance"
```

---

## Task 5: PR and post-merge verification

- [ ] **Step 1: Push + open PR**

```bash
git push -u origin feat/finding-x-grounding-synth
gh pr create --title "feat(director): FINDING-X — grounding-provenance synthesis hook" --body "$(cat <<'EOF'
## Summary

- Closes the FINDING-X constitutional-invariant violation. Every
  CompositionalImpingement downstream of `_parse_intent_from_llm` now
  carries non-empty `grounding_provenance` by construction.
- Adds `_ensure_impingement_grounded(imp, stance)` hook; LLM empties
  synthesize a deterministic `inferred.<stance>.<family>` marker.
- New Prometheus counter `hapax_director_ungrounded_synth_total{intent_family}`
  tracks how often we had to synthesize — operator-visible
  LLM-compliance drift signal, separate from the existing
  `hapax_director_ungrounded_total` which keeps measuring raw LLM empty rate.
- Prompt clause reinforces the incentive to name real perceptual-field keys.

Research: `docs/research/2026-04-21-finding-x-grounding-provenance-research.md`
Spec: `docs/superpowers/specs/2026-04-21-finding-x-grounding-synth-design.md`

## Test plan

- [x] `uv run pytest tests/studio_compositor/test_grounding_provenance_synthesis.py tests/shared/test_director_observability.py -v`
- [ ] Admin-merge through CI drift if pattern continues.
- [ ] Post-merge, tail `~/hapax-state/stream-experiment/director-intent.jsonl`
  — every impingement has non-empty `grounding_provenance`.
- [ ] Grafana: `hapax_director_ungrounded_total` and
  `hapax_director_ungrounded_synth_total` both visible (dashboard is a
  follow-up PR).
EOF
)"
```

- [ ] **Step 2: Post-merge verification**

```bash
# After service restart (rebuild-services timer picks up within 5 min):
tail -20 ~/hapax-state/stream-experiment/director-intent.jsonl | python3 -c "
import json, sys
total = empty = 0
for line in sys.stdin:
    try: o = json.loads(line)
    except: continue
    for imp in o.get('compositional_impingements', []):
        total += 1
        if not imp.get('grounding_provenance'):
            empty += 1
print(f'total={total} empty={empty}')"
# Expected: empty == 0.
```

---

## Sequencing Notes

Tasks are ordered by dependency: counter → hook → integration → prompt → PR.
Task 4 (prompt) is independent and could ship in its own tiny PR if desired.

## Acceptance Criteria

Mirrored from spec §9:

- Every `compositional_impingement` in `director-intent.jsonl` has non-empty
  `grounding_provenance` within 5 minutes of service restart.
- `hapax_director_ungrounded_synth_total` accounts for every synthesized
  case.
- No existing test breakage.
- `emit_ungrounded_audit` continues to warn-log empty LLM emissions
  pre-synthesis.
