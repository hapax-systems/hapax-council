# preset.bias similarity-recruit trace — 2026-05-02

cc-task: `preset-bias-similarity-recruit-trace` (P2 / WSJF 8.5, gamma)

## Symptom

Per `/tmp/effect-cam-orchestration-audit-2026-05-02.md` §R7 and the
operator's `recent-recruitment.json` audit: the studio_compositor director
emits `compositional_impingements[i].narrative = "Set the preset family to
calm-textural"` every tick, but **zero `preset.bias` family entries appear
in `recent-recruitment.json`**. The architectural intent is that director
narrative → embed → cosine-similarity vs Qdrant `affordances` collection
→ recruit `fx.family.*`. The loop was broken end-to-end in production.

## Trace finding (root cause)

The `AffordancePipeline.select()` machinery already writes a structured
dispatch trace (one record per call) to
`~/hapax-state/affordance/dispatch-trace.jsonl`. Tail of the live trace
file showed the smoking gun:

```
intent_family distribution (last 2000 traces):
   162 narrative.autonomous_speech
   101 overlay.emphasis
    42 preset.bias                      ← present, attempted
    38 ward.highlight
    32 camera.hero
    ...

preset.bias dropouts (last 10000 traces):
   188 total preset.bias attempts
   176 dropout_at: monetization_filter_empty
    12 dropout_at: retrieve_family_empty
     0 winners
```

So 94% of `preset.bias` impingements drop at the **monetization gate**.
Live Qdrant inspection of the `affordances` collection confirmed the
mechanism:

```
fx.family.audio-reactive   monetization_risk=None  public_capable=None  content_risk=None
fx.family.warm-minimal     monetization_risk=None  public_capable=None  content_risk=None
fx.family.calm-textural    monetization_risk=None  public_capable=None  content_risk=None
fx.family.glitch-dense     monetization_risk=None  public_capable=None  content_risk=None
fx.family.neutral-ambient  monetization_risk=None  public_capable=None  content_risk=None
```

The catalog source (`shared/compositional_affordances.py`) declares all
five `fx.family.*` capabilities with `monetization_risk='none'` +
`public_capable=True` + `content_risk='tier_0_owned'`. The seeder
(`shared/affordance_pipeline.AffordancePipeline.index_capability`) writes
those exact fields into the Qdrant payload.

But the live Qdrant rows had `None` for all three. **The Qdrant collection
is older than those fields.** The fix path that was supposed to keep them
in sync (`scripts/seed-compositional-affordances.py`) had not been re-run
since the governance fields were added to `OperationalProperties`.

`MonetizationRiskGate.assess()` (`shared/governance/monetization_safety.py`)
correctly fails closed on missing fields:

1. `_coerce_risk(None)` → `"unknown"`
2. `_public_or_monetizable(payload, surface=None)` checks
   `payload.get("public_capable")` → `None` (falls through),
   `surface in _BROADCAST_SURFACES` → False (no surface arg from pipeline),
   `medium = "visual"` is in `_PUBLIC_MEDIA = {"visual", "auditory",
   "speech", "textual"}` → returns `True`
3. unknown-risk + public_or_monetizable → blocked with reason
   `"missing; public/monetizable surfaces fail closed"`

So the gate's "fail closed on stale Qdrant" branch (documented at
`monetization_safety.py:269-271`) was firing every time. The catalog
source was right; the gate was right; the indexed payloads were stale
sentinels of pre-governance-fields state.

## Fix shipped

Ran `uv run scripts/seed-compositional-affordances.py` — the existing
idempotent batch reseeder. Live verification post-reseed:

```
$ uv run scripts/verify-affordance-seed-health.py --prefix fx.family.
status: healthy
checked: 5 payloads
all required governance fields populated; no drift detected
```

Specific payload fields after reseed:

```
fx.family.audio-reactive   monetization_risk='none'  public_capable=True  content_risk='tier_0_owned'
fx.family.warm-minimal     monetization_risk='none'  public_capable=True  content_risk='tier_0_owned'
...
```

## Regression prevention shipped (this PR)

- **`tests/test_preset_bias_monetization_gate.py`** — 5-test pin matrix:
  - Catalog contract: `fx.family.*` records exist (≥4), declare
    non-medium/non-high `monetization_risk`, declare `public_capable=True`.
  - Gate behavior: every `fx.family.*` candidate built from the catalog
    with the post-seed payload shape passes `MonetizationRiskGate.assess()`.
  - Negative pin: the stale-Qdrant payload shape (missing
    `monetization_risk` + `public_capable`, `medium='visual'`) MUST remain
    blocked. The fix is the seeder, not relaxing the gate.
- **`scripts/verify-affordance-seed-health.py`** — operator-runnable drift
  detector. Reports per-capability missing-fields list. Exits non-zero on
  drift. Cheap; runs in <1s; can be added to a sweep timer if desired.

## Phase 1 (separate cc-task; not shipped here)

- Auto-reseed at compositor startup with a content-hash check. The cost
  is one Qdrant scroll + a content hash compare; 113 of 115 catalog
  entries are already cached on disk (`~/.cache/hapax/embed-cache.json`),
  so the embedding round-trip is paid for. Wire `reseed_if_drifted()`
  into `studio_compositor.start_director()` so every restart self-heals.
- Promote `verify-affordance-seed-health.py` into the
  `agents/health_monitor/checks/` family so the council surface alerts
  on drift rather than waiting for the operator to notice.
- Make the gate's `_public_or_monetizable()` log a warning identifying
  the capability_name when it fails closed on missing fields — turns
  silent dispatch dropouts into self-documenting failures.

## Refs

- `shared/affordance_pipeline.py` — pipeline + dispatch trace
- `shared/governance/monetization_safety.py` — `MonetizationRiskGate`
- `shared/compositional_affordances.py` — catalog source of truth
- `scripts/seed-compositional-affordances.py` — reseeder (operational fix)
- `scripts/audit-preset-affordances.py` — adjacent audit (Phase 5 of
  preset-variety plan; covers FAMILY_PRESETS / disk gaps)
- CLAUDE.md `## Unified Semantic Recruitment` — pipeline architecture
- Trace data: `~/hapax-state/affordance/dispatch-trace.jsonl`
