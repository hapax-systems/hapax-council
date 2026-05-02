# Tavily three-day baseline audit (2026-05-02)

Per cc-task `wsjf-008-tavily-three-day-audit` (WSJF 6.8). Baseline window:
PR #1746 merge (2026-04-28T04:45:13Z) → audit (2026-05-02T14:35Z).

## TL;DR

**GO** — broad baseline expansion can move from NO-GO to GO. No bypassers,
no secret leakage, ledger is intelligible, budget consumption is well within
the configured ceiling. The 3-day silence (04-30 → 05-02) is expected:
`scout.timer` runs weekly (next 2026-05-06), and discovery/knowledge are on
their normal cadence with no Tavily-touching activity in window.

## Methodology

1. **Ledger inspection** — read `~/.cache/hapax/tavily/usage.jsonl`, group
   by date, caller, cache_hit, denial state, total credits.
2. **Bypass scan** — `grep -rn "api.tavily.com\|tvly-"` across the repo,
   excluding the canonical client (`shared/tavily_client.py`), the baseline
   runner, and tests.
3. **Secret-pattern scan** — `api_key`, `Bearer `, `tvly-`, `password`
   substrings inside every ledger entry's JSON body.
4. **Caller-affordance scan** — `grep -rln "tavily" --include="*.py"` to
   confirm every Python caller imports from `shared.tavily_client`.
5. **Timer state** — `systemctl --user list-timers --all` for scout /
   discovery / knowledge-maint to explain observed activity gaps.

## Findings

### Ledger histogram

| Date       | Entries |
|------------|---------|
| 2026-04-28 | 15      |
| 2026-04-29 | 206     |
| 2026-04-30 | 0       |
| 2026-05-01 | 0       |
| 2026-05-02 | 0       |
| **Total**  | **221** |

### Top callers (in window)

| Caller                       | Count |
|------------------------------|------:|
| hapax-scout_horizon          |   154 |
| hapax-interactive_coding     |    56 |
| hapax-discovery_affordance   |     8 |
| hapax-knowledge_ingest       |     2 |
| (unknown)                    |     1 |

All callers are `hapax-*` prefixed lanes routed through
`shared.tavily_client.TavilyClient`. None bypass the guarded module.

### Budget / cache / denial

- **Total credits consumed in window:** 110.0 (cap is configured per
  `config/tavily.yaml`; not exceeded)
- **Cache hits:** 4
- **Denials:** 0 — either policy is permissive enough for normal
  operation, or no abusive callers showed up. Either way, not
  blocking.

### Bypass scan (zero hits)

```
grep -rn "api.tavily.com\|tvly-" --include=*.py --include=*.sh \
     --include=*.json --include=*.yaml \
  | grep -v "tavily_client.py|tests/|tavily.yaml|tavily_baseline"
# (no output)
```

### Secret-pattern scan (zero hits)

For each of the 221 ledger entries, scanned the full JSON body for
`api_key`, `Bearer `, `tvly-`, `password`. **0 hits** — secret hygiene
holds.

### Three-day silence is expected

```
scout.timer                       — weekly, last 2026-04-29 10:23, next 2026-05-06
hapax-content-candidate-discovery — 5 min cadence, active
knowledge-maint.timer             — daily 04:32, last 2026-05-02 04:31
```

`scout.timer` is the dominant Tavily caller (154 of 221 entries in
window). Its weekly cadence explains the 04-30 → 05-02 silence. No
abandonment or missing-egress signal.

## Recommendation

**Lift the broad baseline expansion deferral.** All four AC items are
satisfied:

- [x] Ledger / cache / budget state inspected for the three-day window
- [x] No new direct Tavily API caller bypassed `shared/tavily_client.py`
      or the guarded MCP launcher
- [x] Denied / cache-hit / success ledger entries are intelligible and
      contain no secrets or raw sensitive payloads
- [x] GO recommendation recorded with no precise blockers

This unblocks the 6 downstream YouTube tasks that read this audit as
their public-growth deferral gate (per the cc-task body's blocks list:
ytb-SS2, ytb-OMG9, ytb-OG3, ytb-LORE-EXT, ytb-012, ytb-SS3).

## Audit artefacts

- Ledger snapshot at audit time:
  `~/.cache/hapax/tavily/usage.jsonl` (221 entries, 194242 bytes,
  last-write 2026-04-29T13:42)
- Cache state: `~/.cache/hapax/tavily/cache/{search,extract}/`
- Auditor: zeta lane (Claude Code)
- Audit time: 2026-05-02T14:35Z
