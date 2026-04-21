# Preset variety Phase 9 — partial post-Phase-6 measurement

**Phase:** preset-variety-plan Phase 9 (task #166)
**Status:** PARTIAL — Phases 1-6 deployed; Phases 7+8 not yet shipped
**Tool:** `scripts/compare-preset-variety.py`

## What's deployed

| Phase | Status | What it does |
|---|---|---|
| 1 — Telemetry baseline | ✅ shipped pre-session | `measure-preset-variety-baseline.py` + 2026-04-20 baseline JSON |
| 2 — Narrative monoculture unblocked | ✅ shipped pre-session | director prompt no longer biases `calm-textural` |
| 3 — `recency_distance` scoring input | ✅ this session (PR #1157) | rolling window novelty term, 0.10 weight default |
| 4 — Thompson posterior decay | ✅ this session (PR #1158) | dormant capabilities recover variance, γ=0.999 default |
| 5 — Affordance catalog closure | ✅ this session (PR #1159) | `fx.family.neutral-ambient` registered + seeded |
| 6 — Perceptual distance impingement | ✅ this session (PR #1168) | `content.too-similar-recently` fires at cluster sim ≥0.85 + `novelty.shift` capability |
| 7 — Chain-level transition variety | ⬜ not shipped | new transition primitives + recruitment integration |
| 8 — Programme-owned palettes | ⬜ blocked on #164 | content-programming layer dependency |

## Comparator output (live data from 2026-04-21 21:26 UTC)

```
baseline:    2026-04-20T21:52:57Z
post-deploy: 2026-04-21T21:26:24Z

metric                                        baseline          post     delta   threshold   verdict
----------------------------------------------------------------------------------------------------
preset_family_entropy_bits                       0.000         0.000    +0.000        1.50      FAIL
colorgrade_halftone_ratio                           NA            NA         -       10.00   NO-DATA
recent_10_cosine_min_distance_mean                  NA            NA         -        0.40   NO-DATA

summary: 0 pass / 1 fail / 2 no-data of 3
```

## Read

- **NOT a win declaration.** Phases 1-6 deployed for ~30 min before this measurement; the plan asks for a 60-min post-deploy window.
- **Entropy still 0.0** — the live director-intent.jsonl recorded 0 `preset_family_hint` records during the post-deploy window. Two possible causes:
  - The structural director hasn't been emitting (TabbyAPI was unhealthy until 15:30 CDT — see this session's earlier diagnosis); the imagination loop only resumed shortly before measurement
  - The `preset_family_hint` field may not yet be populated by the structural director path
- **2 NO-DATA findings** — `colorgrade_halftone_ratio` and `recent_10_cosine_min_distance_mean` both depend on `~/hapax-state/affordance/recruitment-log.jsonl`, which doesn't exist on this box. The recruitment-log writer is not yet wired in any service; this is a pre-existing instrumentation gap that the baseline script itself flagged (`recruitment_log_present: false`).

## Surfaced gaps (for follow-up workstreams)

1. **Recruitment log writer missing.** Without `~/hapax-state/affordance/recruitment-log.jsonl`, two of three quantitative metrics can never produce a reading. A small writer hook in `AffordancePipeline._log_cascade` (or a separate persistent recorder) would unblock Phase 9 measurement entirely.
2. **`preset_family_hint` extraction.** The baseline script grabs family hints from `structural-intent.jsonl` records. Need to verify the structural director actually populates this field; if not, the histogram can never grow.
3. **Director-intent freshness.** Imagination loop staleness blocked recruitment for hours earlier today (TabbyAPI cache exhaustion). A health-check + auto-restart on `current.json` staleness >5 min would prevent recurrence.

## Operator follow-up (when Phase 7 lands and the livestream has been running 60 min)

```bash
# Take a fresh post-deploy snapshot
uv run scripts/measure-preset-variety-baseline.py \
    --output docs/research/preset-variety-postdeploy-$(date +%F).json

# Compare against baseline
uv run scripts/compare-preset-variety.py \
    docs/research/preset-variety-baseline-2026-04-20.json \
    docs/research/preset-variety-postdeploy-$(date +%F).json
```

The comparator exits non-zero on FAIL so it's CI/script-friendly. `--strict` treats NO-DATA as failure for stricter gating.
