# Grounding-Provenance Invariant — Root-Cause Fix

**Status:** design, post-audit (alpha 12.1)
**Author:** alpha (2026-04-20)
**Scope:** `shared/director_intent.py`, `shared/director_observability.py`,
`agents/studio_compositor/director_loop.py`, `shared/perceptual_field.py`
**Audit artefact:** `docs/research/2026-04-20-wiring-audit-alpha.md` §4.9;
`docs/research/2026-04-20-audit-synthesis-final.md` §2 Pattern 1

## 1. The invariant verbatim

The constitutional invariant owning this finding is the `§4.9 Cross-family
invariants` checklist in `docs/research/2026-04-20-wiring-audit-alpha.md`
(lines 401-408):

> ### §4.9 Cross-family invariants
>
> - [ ] Every emitted `CompositionalImpingement` has a non-empty
>   `grounding_provenance` OR an UNGROUNDED audit warning logged
> - [ ] `hapax_director_intent_parse_failure_total` stays at 0 during
>   live operation
> - [ ] `hapax_director_vacuum_prevented_total` increments when the
>   director would have emitted nothing
> - [ ] Every `intent_family` string used in the codebase is a member
>   of the `IntentFamily` literal …

The invariant's upstream normative source is the schema docstring on
`shared/director_intent.py::CompositionalImpingement.grounding_provenance`
(lines 140-153), which records the intent as a soft-constrained field:

> PR #1046 made compositional intent mandatory and required
> `grounding_provenance` per impingement, but the field was only on the
> envelope. Now first-class per impingement so the LLM can comply …
> Empty list is allowed (the pipeline accepts it) but the audit emits
> an UNGROUNDED warning for the operator to track in research-mode logs.

The top-of-envelope `DirectorIntent.grounding_provenance` docstring at
`shared/director_intent.py:345-353` is equally explicit about the
intent:

> PerceptualField signal names this move grounds in. Examples:
> `'audio.contact_mic.desk_activity.drumming'`,
> `'visual.overhead_hand_zones.turntable'`,
> `'ir.ir_hand_zone.turntable'`, `'album.artist'`.

And the volitional-grounded-director spec (`docs/superpowers/specs/
2026-04-17-volitional-grounded-director-design.md` §11 "Grounding"
success criteria, line 445):

> 100% of `DirectorIntent`s carry ≥1 `grounding_provenance` signal
> drawn from `PerceptualField`.

**Intent (synthesis).** Every directorial move — both at the envelope
and at each `CompositionalImpingement` — must either cite a
`PerceptualField` signal key that made the move felt-necessary, OR, when
nothing can be cited, fail loud: a `log.warning("UNGROUNDED …")` line
PLUS a `hapax_ungrounded_intent_total{family=…, tier=…, reason=…}`
counter increment, so (a) every move remains auditable back to its
perceptual antecedent and (b) the rate of ungrounded moves is itself a
first-class observable. The "empty list is allowed" clause in the
docstring is scaffolding to let the LLM ramp; it is not a licence for
the emitter to silently bypass the grounding contract. The audit
finding establishes that the emitter is taking that licence.

## 2. Current state

Live slice from `~/hapax-state/stream-experiment/director-intent.jsonl`
(last 500 intents on 2026-04-20):

| axis | count |
|---|---|
| total intents (500 ticks) | 500 |
| LLM-sourced intents | 372 (74%) |
| silence-hold fallback intents | 128 (26%) |
| micromove fallback intents | 0 |
| intents with empty top-level `grounding_provenance` | 129 (26%) |
| total `CompositionalImpingement`s emitted | 1,114 |
| impingements with empty `grounding_provenance` | 1,109 (99%) |
| `UNGROUNDED` log lines emitted | 0 |
| `hapax_ungrounded_intent_total` series | does not exist |

The alpha audit's 451/454 (99.3%) figure reproduces against the live
file. The overwhelming share of empties is on the LLM path (not the
fallback paths). The silence-hold impingement constructed by
`_silence_hold_impingement` (`agents/studio_compositor/director_loop.py:
41-44`) also emits with no `grounding_provenance` because the silence
hold is by definition absent a grounding signal — but that is a tiny
fraction of the population.

### 2.1 Emission path trace

1. **Prompt construction** — `DirectorLoop._build_unified_prompt`
   (`agents/studio_compositor/director_loop.py:1925-2079`) serialises
   the `PerceptualField.model_dump_json(exclude_none=True)` block into
   the prompt, then instructs the LLM:

   > "**Mandatory grounding_provenance per impingement.** Every
   > compositional_impingement carries the perceptual-field key that
   > made it felt-necessary. … An impingement without grounding is a
   > guess; the pipeline accepts it but the audit will mark it
   > ungrounded." (`director_loop.py:2068-2075`)

   The prompt threatens an audit mark that does not exist.

2. **LLM call** — `_call_activity_llm` returns a JSON string; the
   completion is not validated for the grounding contract.

3. **Parse** — `_parse_intent_from_llm`
   (`director_loop.py:129-205`). When `"compositional_impingements"`
   appears in the object, `DirectorIntent.model_validate(obj)` runs
   (line 183). Pydantic enforces `min_length=1` on
   `compositional_impingements` (by the class field at
   `shared/director_intent.py:371-380`), but `grounding_provenance` is
   `default_factory=list` with no minimum length. Empty arrays pass.

4. **Envelope construction fallback** — when the LLM returns a legacy
   `{"activity", "react"}` shape, `_silence_hold_fallback_intent`
   (`director_loop.py:67-103`) builds a `DirectorIntent` with
   `compositional_impingements=[_silence_hold_impingement()]`; the
   silence-hold impingement itself has no `grounding_provenance`
   populated (`director_loop.py:41-61`). No UNGROUNDED warning is
   logged.

5. **Micromove fallback** — `_emit_micromove_fallback`
   (`director_loop.py:1258-1373`) constructs a seven-entry cycle of
   `CompositionalImpingement`s, each with NO `grounding_provenance`
   field populated (line 1336-1342). The envelope is constructed at
   line 1355 with `grounding_provenance=[]` explicitly. No warning
   logged.

6. **Observability** — `_emit_intent_artifacts`
   (`director_loop.py:323-379`) writes the intent to JSONL (line 334),
   to `hapax-director/narrative-state.json`, to Prometheus via
   `emit_director_intent` (line 341), and to
   `/dev/shm/hapax-dmn/impingements.jsonl` via
   `_emit_compositional_impingements` (lines 246-296). At no point is
   the empty-grounding condition detected, counted, or logged.

7. **Prometheus emission** — `emit_director_intent` in
   `shared/director_observability.py:267-287` iterates the envelope's
   `grounding_provenance` to increment
   `hapax_director_grounding_signal_used_total`. When the list is
   empty, the loop body is skipped; no `signal_name="empty"` or
   `signal_name="ungrounded"` entry is written. **This is the
   blind spot: the only metric that would reveal the 99% empty rate
   silently no-ops on empty.** The per-impingement
   `grounding_provenance` (the one the docstring says PR #1046 made
   first-class) is never observed anywhere.

### 2.2 Downstream consumption

- `shared/impingement_consumer.ImpingementConsumer` and
  `AffordancePipeline` treat the impingement as a semantic envelope —
  narrative + intent_family + dimensions drive the recruitment call.
  `grounding_provenance` is not read by the pipeline at all. The
  pipeline "accepts it" because it has nothing to reject on.
- `grounding_provenance_ticker.py` (the small legibility surface on the
  frame) reads the JSONL tail and renders the envelope's list. When
  that list is empty the ticker renders blank, hiding the problem from
  the operator.

## 3. Root-cause hypothesis

Three mutually reinforcing causes, evidenced by the trace in §2:

1. **Soft schema, strong prose.** The prompt tells the LLM the field is
   mandatory; the schema marks it optional (`default_factory=list`).
   When the LLM is overloaded, under latency pressure, or when the
   prompt block's density pushes `grounding_provenance` past the
   utility horizon, the model drops it. This is a normal LLM
   behaviour — the schema must carry the constraint, not the prose.

2. **The audit counter was never created.** The prompt tells the LLM
   that "the audit will mark it ungrounded" — implying an operator-
   visible counter or log exists. It does not. The only related
   observable is `hapax_director_grounding_signal_used_total`, which is
   a *success* counter with no paired failure counter. The invariant
   was codified in `wiring-audit-alpha.md` §4.9 (checklist item) but
   never materialised as a runtime observable. This is the archetype
   of the "observability blind spot" pattern that cascade's §7.1
   audit warned about.

3. **Fallback paths silently inherit empty provenance.** The
   `_silence_hold_impingement` and `_emit_micromove_fallback` paths
   both construct `CompositionalImpingement`s without `grounding_
   provenance`. For the silence-hold case there is arguably no
   grounding signal, but the invariant still requires an explicit
   UNGROUNDED log + counter increment — "silence hold" is a valid
   `reason` label for the ungrounded emission, and observers need to
   count it. The micromove cycle is *deterministic cycling under
   degraded LLM* and could in principle cite the cycle index as its
   grounding, but there is no convention for deterministic-path
   grounding and nothing logs the deviation.

The ontological frame: Hapax's spec §2 commitment #1 (grounding-
exhaustive axiom, `feedback_grounding_exhaustive.md`) says every LLM
move is either an act of grounding or outsourced by a grounding move.
When a move appears to be "not grounded", it is either (a) actually
grounded and the emitter failed to cite the signal, (b) legitimately
ungrounded — in which case it should be deterministic code, not LLM —
or (c) a bug. The current state collapses all three cases into silent
failure.

## 4. Fix design

Two independent components, shipped in the rollout order given in §6.

### 4.1 Fail-loud observability (the meta-fix)

Add to `shared/director_observability.py`:

```python
_ungrounded_intent_total = Counter(
    "hapax_ungrounded_intent_total",
    (
        "CompositionalImpingements emitted without grounding_provenance, "
        "labelled by intent_family + tier + reason. Non-zero rate is a "
        "spec §4.9 invariant violation."
    ),
    ("condition_id", "intent_family", "tier", "reason"),
)

def emit_ungrounded_impingement(
    *,
    intent_family: str,
    tier: str,
    reason: str,
    condition_id: str,
) -> None:
    """Increment hapax_ungrounded_intent_total + log.warning in one call.

    Paired emit-and-log pattern — every invariant violation gets BOTH a
    structured log line (for the operator reading journalctl) AND a
    Prometheus series (for the dashboard / alert). Never one without
    the other.

    `reason` ∈ {"llm_omitted", "silence_hold", "micromove_cycle",
    "parser_fallback", "degraded_tick", "legacy_path"}.
    """
    log.warning(
        "UNGROUNDED intent: family=%s tier=%s reason=%s condition_id=%s",
        intent_family, tier, reason, condition_id,
    )
    if not _METRICS_AVAILABLE:
        return
    try:
        _ungrounded_intent_total.labels(
            condition_id=condition_id,
            intent_family=intent_family,
            tier=tier,
            reason=reason,
        ).inc()
    except Exception:
        log.warning("emit_ungrounded_impingement failed", exc_info=True)
```

Extend `emit_director_intent` (line 267-287) to scan impingements:

```python
def emit_director_intent(intent: DirectorIntent, condition_id: str,
                        tier: str = "narrative") -> None:
    # ... existing body ...
    for imp in intent.compositional_impingements:
        _compositional_impingement_total.labels(...).inc()
        if not imp.grounding_provenance:
            emit_ungrounded_impingement(
                intent_family=imp.intent_family,
                tier=tier,
                reason="llm_omitted",  # caller overrides for fallback paths
                condition_id=condition_id,
            )
    if not intent.grounding_provenance and not any(
        imp.grounding_provenance for imp in intent.compositional_impingements
    ):
        emit_ungrounded_impingement(
            intent_family="__envelope__",
            tier=tier,
            reason="envelope_and_all_impingements_empty",
            condition_id=condition_id,
        )
```

The caller-overridable `reason` parameter is the key: the silence-hold
and micromove paths call `emit_ungrounded_impingement` with
`reason="silence_hold"` / `reason="micromove_cycle"` BEFORE they call
`_emit_intent_artifacts`, and the artifacts emitter skips its own
`reason="llm_omitted"` check when called from a known-deterministic
context (by a new `skip_grounding_check` kwarg defaulting to `False`).

This preserves the distinction between "LLM should have grounded and
didn't" (anomaly, investigate) and "deterministic fallback path by
design has no grounding" (expected, but still counted).

### 4.2 Populate `grounding_provenance` on every LLM emission

The LLM prompt already names the expectation (`director_loop.py:2068-
2075`). What's missing is (a) validator-level enforcement and (b) a
grounding-retrieval fallback when the LLM omits the field.

**Step 1 — schema enforcement at the Pydantic layer.** Add a model-
level validator on `DirectorIntent` that ensures EITHER
`grounding_provenance` is non-empty, OR at least one
`CompositionalImpingement.grounding_provenance` is non-empty, OR the
intent carries an explicit `ungrounded_reason: Literal["silence_hold",
"micromove_cycle", "parser_fallback", "degraded_tick"] | None = None`
field. Under `ungrounded_reason` set, the validator passes; otherwise
it raises. Parse-failure paths in `_parse_intent_from_llm` catch the
validation error, increment
`hapax_director_intent_parse_failure_total{reason="no_grounding"}`, and
construct a silence-hold with `ungrounded_reason="parser_fallback"`.

**Step 2 — synthesise provenance when the LLM omits it.** The director
already has `PerceptualField` in hand when it builds the prompt. When
the LLM's returned JSON has empty `grounding_provenance`, the parser
can derive a best-effort list from the `PerceptualField` snapshot it
just sent, using a small scoring heuristic (which signals changed
most in the last N ticks, which signals match the emitted
`intent_family` by a static routing table). This is a shallow fallback
— the LLM's explicit citation is still preferred — but it closes the
invariant gap during the window when LLM behaviour is still being
tuned.

Routing table (static, in `shared/director_intent.py` or a sibling
module):

```python
_FAMILY_TO_DEFAULT_SIGNALS: dict[IntentFamily, tuple[str, ...]] = {
    "camera.hero":        ("visual.overhead_hand_zones", "visual.detected_action",
                           "ir.ir_hand_zone"),
    "preset.bias":        ("audio.midi.beat_position", "audio.contact_mic.desk_energy",
                           "stimmung.operator_energy"),
    "overlay.emphasis":   ("chat.tier_counts", "visual.top_emotion",
                           "context.active_objectives"),
    "youtube.direction":  ("context.stream_mode", "chat.tier_counts"),
    "attention.winner":   ("visual.operator_confirmed", "audio.vad_speech_active"),
    "ward.highlight":     ("audio.contact_mic.desk_activity", "visual.overhead_hand_zones"),
    "ward.size":          ("stimmung.operator_stress",),
    # ... remainder of IntentFamily literal
}
```

The fallback populator runs AFTER LLM parse, BEFORE
`_emit_intent_artifacts`:

```python
def _populate_missing_grounding(
    intent: DirectorIntent,
    field: PerceptualField,
    tier: str,
    condition_id: str,
) -> DirectorIntent:
    """For each impingement with empty grounding_provenance, populate
    from the family → default-signals table, but only for signals that
    are ACTUALLY PRESENT (non-None / non-default) on `field`.

    When no default signal is present for a family, the impingement
    remains empty — the downstream UNGROUNDED counter will fire with
    reason="llm_omitted" and the operator sees the rate in the dashboard.
    """
    ...
```

**Step 3 — prompt hardening.** The LLM prompt is edited to include a
worked example showing the correct shape ("when you emit a
`preset.bias` impingement because the operator is drumming at 120 BPM,
the `grounding_provenance` for that impingement is
`['audio.midi.beat_position', 'audio.contact_mic.desk_activity']`").
Worked examples move prompt-level compliance rates dramatically
(cascade has measured this elsewhere; re-measure here).

### 4.3 Fail-loud on the fallback paths

`_silence_hold_impingement` (`director_loop.py:41-61`) gains a
`grounding_provenance=["__silence_hold__"]` sentinel OR remains empty
with a guaranteed paired call to `emit_ungrounded_impingement(reason=
"silence_hold")` from the fallback constructor.

`_emit_micromove_fallback` (`director_loop.py:1258-1373`) gains a
`grounding_provenance=[f"__micromove_cycle__:{idx}"]` sentinel on
every constructed impingement. The sentinel convention makes the
fallback path discoverable via `jq` on the JSONL file (operator can
filter `select(.compositional_impingements[].grounding_provenance[0] |
startswith("__"))` to separate deterministic-path emissions from LLM-
path emissions) without muddying the grounding dashboard.

## 5. Test design

Two tests pin the invariant against regression. Both live in
`tests/studio_compositor/test_grounding_provenance_invariant.py`.

### 5.1 Per-tick pin — every emitted `DirectorIntent` satisfies §4.9

```python
def test_every_director_intent_satisfies_grounding_invariant(caplog):
    """Regression pin for alpha 12.1: every DirectorIntent emission
    either carries grounding_provenance OR logs UNGROUNDED.

    This test would have caught the audit finding. We run 200 mocked
    ticks through the parser + emitter with the LLM stubbed to emit
    every known failure mode, and assert that each empty-grounding
    impingement is paired with a log.warning starting "UNGROUNDED"
    AND a hapax_ungrounded_intent_total increment.
    """
    # 200 ticks, each a different known LLM failure shape:
    #  - empty response
    #  - malformed JSON
    #  - legacy {activity, react}
    #  - full DirectorIntent with missing grounding_provenance
    #  - full DirectorIntent with empty impingement-level gp
    #  - full DirectorIntent with one non-empty + one empty impingement
    #  - full DirectorIntent with all impingements grounded (control)
    results = run_mock_tick_sequence(fixtures=LLM_FAILURE_SHAPES)

    # Invariant: |ungrounded_log_lines + ungrounded_counter_increments|
    #           == |empty-gp impingement/envelope emissions|
    assert results.ungrounded_log_lines == results.empty_gp_emissions
    counter_sum = sum_counter_series("hapax_ungrounded_intent_total")
    assert counter_sum == results.empty_gp_emissions

    # Anti-pattern: no "UNGROUNDED" warning may fire on a grounded intent.
    assert not any(
        "UNGROUNDED" in rec.message
        for rec, emission in zip(caplog.records, results.all_emissions)
        if emission.has_grounding
    )
```

### 5.2 Population pin — missing grounding is filled-in when possible

```python
def test_populate_missing_grounding_from_perceptual_field():
    """Verifies §4.2 Step 2: when the LLM emits a preset.bias
    impingement without grounding_provenance, and the PerceptualField
    snapshot contains a populated audio.midi.beat_position, the
    populator fills grounding_provenance=["audio.midi.beat_position"].
    """
    field = PerceptualField(
        audio=AudioField(midi=MidiField(beat_position=0.5, transport_state="PLAYING"))
    )
    intent = DirectorIntent(
        activity="vinyl",
        stance=Stance.NOMINAL,
        narrative_text="...",
        compositional_impingements=[
            CompositionalImpingement(
                narrative="bias toward beat-synced preset",
                intent_family="preset.bias",
                grounding_provenance=[],  # LLM omitted
            )
        ],
    )
    populated = _populate_missing_grounding(intent, field, tier="narrative",
                                            condition_id="test")
    assert populated.compositional_impingements[0].grounding_provenance == [
        "audio.midi.beat_position",
    ]
```

Both tests run in unit-test mode (no live compositor). The first is
the regression pin for 12.1; the second documents the fallback-fill
behaviour so a future refactor doesn't regress it.

## 6. Rollout plan

Three stages, each independent and independently verifiable. The order
is chosen so observability proves the gap before any behavioural
change lands — the operator sees the dashboard light up red, then goes
green as the emission fixes deploy.

### Stage A — observability only (0 behavioural change)

**Change:** land §4.1 (fail-loud counter + log pair) plus a Grafana
dashboard row scoped to `rate(hapax_ungrounded_intent_total[5m])`.

**Deploy:** `scripts/rebuild-service.sh studio-compositor` on main; the
service restarts, the counter begins emitting. Expected behaviour:
non-zero rate immediately (99% of emissions will light up the counter
with `reason="llm_omitted"` and various `intent_family` labels).

**Verification gate (must pass before Stage B ships):**
- `hapax_ungrounded_intent_total` scraped at `:9482` ≥ 0 (counter exists)
- `journalctl -u hapax-compositor.service | grep "UNGROUNDED intent"`
  returns non-empty within 10 minutes
- Grafana dashboard row renders with the expected ~99% rate

This stage alone closes the "silent invariant break" anti-pattern. The
invariant is now visibly broken but visibly broken — the gap is no
longer silent.

### Stage B — fallback-path grounding sentinels

**Change:** land §4.3 (silence-hold + micromove-cycle sentinel
`grounding_provenance` entries) plus the `ungrounded_reason` field on
`DirectorIntent` + matching `reason` labels on the counter.

**Deploy:** same rebuild; restart. Expected behaviour: the counter's
label distribution shifts — `reason="llm_omitted"` stays roughly where
it was (that's the real gap), but `reason="silence_hold"` and
`reason="micromove_cycle"` now carry the fallback-path fraction, and
the operator can separate the two in Grafana.

**Verification gate:**
- `rate(hapax_ungrounded_intent_total{reason="silence_hold"}[5m]) > 0`
- `rate(hapax_ungrounded_intent_total{reason="micromove_cycle"}[5m])`
  matches the micromove activation rate
- `rate(hapax_ungrounded_intent_total{reason="llm_omitted"}[5m])` drops
  by exactly the silence-hold/micromove share of emissions

### Stage C — populate-missing + validator enforcement

**Change:** land §4.2 (fallback populator + worked-example prompt edit
+ Pydantic validator). The validator enforces the invariant for every
NEW `DirectorIntent` construction; legacy code paths that cannot
satisfy it set `ungrounded_reason`.

**Deploy:** rebuild + restart, but gated behind a feature flag
`HAPAX_GROUNDING_INVARIANT_ENFORCED=1`. On first deploy, the flag is
OFF — the populator runs and its effects are visible on the counter
(`reason="llm_omitted"` rate drops as populator fills in), but the
validator is informational-only. After 24 hours of stable observation,
the flag flips ON and the validator becomes hard.

**Verification gate:**
- `rate(hapax_ungrounded_intent_total{reason="llm_omitted"}[5m])` <
  target (initial target: 20% of prior baseline; final target: < 1%)
- `hapax_director_intent_parse_failure_total{reason="no_grounding"}`
  stays below the rollback threshold (5 per 10 min, per epic §9)
- No secondary regressions — director tick p95 latency unchanged,
  impingement recruitment rate unchanged, stance distribution
  unchanged.

The three stages together transition the invariant from "silent,
broken, unobservable" → "loud, broken, observable" → "loud, fixable,
decreasing rate" → "loud, fixed, pinned by tests + validator".

## 7. Generalised pattern — observability-invariant codification

Finding 12.1 is an instance of a family. `docs/research/
2026-04-20-audit-synthesis-final.md` §2 Pattern 1 names the family
("observability blind spots enable silent invariant breaks") and
pairs it with cascade's §7.1 warning ("only 20+ prometheus
registrations in the codebase without being sure coverage was
complete"). The fix pattern generalises; the generalisation is itself
the deeper fix.

### 7.1 The convention

Every spec-mandated invariant MUST be codified with four artefacts,
shipped together. No invariant is considered "enforced" unless all
four exist and are linked to the spec line that creates the
obligation.

| Artefact | Purpose | Location |
|---|---|---|
| **Hit counter** | Proves the invariant's subject is actually running (non-zero rate = the emitter is alive) | `shared/*_observability.py`, one Counter per invariant |
| **Violation counter** | Rate of invariant violations, labelled by reason (non-zero rate = silent break) | Same file, sibling Counter |
| **Regression test** | Asserts that every known violation pathway pairs with a violation-counter increment and a `log.warning` line | `tests/**/test_*_invariant.py`, one per invariant |
| **Dashboard row** | Makes the violation-counter rate visible to the operator in the same Grafana folder as the related subsystem | `config/grafana/dashboards/*.json`, one panel per invariant |

The four together are indexed by a registry line in a new file
`docs/invariants/registry.yaml`:

```yaml
- id: grounding-provenance-per-impingement
  spec: docs/research/2026-04-20-wiring-audit-alpha.md#49-cross-family-invariants
  hit_counter: hapax_director_compositional_impingement_total
  violation_counter: hapax_ungrounded_intent_total
  test: tests/studio_compositor/test_grounding_provenance_invariant.py::test_every_director_intent_satisfies_grounding_invariant
  dashboard: config/grafana/dashboards/director-invariants.json#grounding-provenance-rate
  severity: T0
```

A one-shot audit script (`scripts/audit-invariant-coverage.sh`) walks
the registry and verifies that every entry's artefacts exist. CI runs
it; PRs that add a new invariant without the four-tuple fail.

### 7.2 Backfill priority

Audit cascade's §7.1 concerns and alpha's pattern-1 enumeration
identify candidate invariants that today lack the four-tuple. Priority
ordering for backfill (driven by "what's empirically broken" and
"what the operator currently can't see"):

1. **grounding-provenance-per-impingement** (this doc, 12.1)
2. **face-obscure-detector-alive** (cascade 5.2 / alpha §11 — no gauge
   flips on detector crash)
3. **ward-dispatch-cadence** (alpha 12.4 — ward.highlight firing 508
   times empirically with no rate metric)
4. **consent-safe-layout-swap-latency** (it-irreversible-broadcast T0
   — swap must complete in ≤5s, not timed)
5. **director-tick-liveness** (tick skipped → no counter of it)
6. **pi-fleet-heartbeat-coverage** (9.2 — pi4/pi5/hapax-ai silent, no
   alert)

Each entry gets a 1-day design + implementation slot; total backfill
is roughly 2 weeks. None blocks live broadcast (the 12.1 fix itself is
post-live per the synthesis doc §1 gate).

### 7.3 Meta-test

A test in `tests/governance/test_invariant_registry_integrity.py`
loads `docs/invariants/registry.yaml`, dereferences each artefact,
asserts existence + basic shape. This is the "test-the-tests" for the
invariant layer.

## 8. Open questions

1. **Where does the fallback populator's routing table live?** Two
   options: co-located with `IntentFamily` in `shared/director_intent.
   py` (tight coupling, atomic edits), or in a sibling
   `shared/grounding_defaults.py` (separable, but risks drift). The
   first is preferred; the Literal and the routing table evolve
   together.

2. **Is `reason="silence_hold"` a violation or a normal mode?** The
   invariant as written says EVERY impingement needs provenance OR an
   UNGROUNDED warning. The silence-hold path legitimately has no
   provenance. Counting it as a violation inflates the rate; not
   counting it requires a separate "deterministic-path" counter
   (`hapax_deterministic_impingement_total{path="silence_hold" |
   "micromove_cycle"}`) that the dashboard subtracts from the
   violation counter to get the "real" LLM-omit rate. Decision
   deferred to Stage B deploy — the rate data will clarify.

3. **Should the populator ever citation-invent?** If the LLM emits an
   impingement with `intent_family="preset.bias"` but the
   `PerceptualField` has no audio activity signals at all, the
   populator's fallback table returns nothing; the impingement stays
   empty; the counter fires. The operator sees "LLM asked for
   preset.bias with no perceptual grounds". Is this acceptable? The
   grounding-exhaustive axiom says no — the LLM should never have
   emitted that impingement. The populator refusing to invent a
   citation is the correct behaviour here; the rate of such refusals
   is itself a signal that the LLM's prompt or the PerceptualField's
   coverage needs work. Keep populator strictly non-inventing.
