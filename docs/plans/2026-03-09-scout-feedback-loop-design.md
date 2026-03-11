# Scout Feedback Loop Design

**Date**: 2026-03-09
**Status**: Approved
**Scope**: Make scout decision-aware (respect dismiss/defer cooldowns) and surface scout context in Claude Code sessions.

## Problem Statement

Scout recommendations are ephemeral — each run replaces the entire report with no awareness of prior operator decisions. Dismissing a recommendation has no effect on the next run. Additionally, Claude Code sessions have no awareness of active scout recommendations, so the operator lacks ambient context about flagged components while working.

## Design Decisions

1. **Decision-aware scout runs**: Scout reads `profiles/scout-decisions.jsonl` at run start. Dismissed and deferred components are suppressed for 90 days. Adopted components are not suppressed — scout continues evaluating the external landscape normally.
2. **Scout stays external-facing**: No migration tracking or follow-up assessment for adopted components. Scout evaluates "does reality match the frontier?" — migration progress is a separate concern.
3. **Session hook integration**: One-line scout summary in Claude Code session context showing all actionable recommendations regardless of repo. Matches density of existing hook lines (health, GPU, profile).
4. **90-day cooldown**: Single constant. Cooldown resets if the operator dismisses/defers again. After expiry, the component is re-evaluated normally.

## Section 1: Decision-Aware Scout Runs

### Decision loading

New function `load_decisions()` in `agents/scout.py` reads `profiles/scout-decisions.jsonl` and returns a `dict[str, ScoutDecision]` mapping component key to the most recent decision for that component. When multiple decisions exist for the same component, the latest timestamp wins.

### Suppression logic

In `run_scout()`, before scanning each component:

1. Look up component key in decision map.
2. If decision is `dismissed` or `deferred` and timestamp is within 90 days: skip. Log the skip. Add to report's `skipped` list.
3. If decision is `adopted` or cooldown has expired: evaluate normally.
4. No decision: evaluate normally.

### Report changes

`ScoutReport` gains a new field:

```python
skipped: list[str] = Field(default_factory=list, description="Components skipped due to active decisions")
```

Skipped components appear in the markdown report under a "Skipped (decision cooldown)" section. The JSON report includes the list for downstream consumers.

### Constants

```python
DECISION_COOLDOWN_DAYS = 90
```

## Section 2: Session Hook Integration

New block in `hapax-system/hooks/scripts/session-context.sh` after the cycle mode section.

### Logic

1. Check if `~/projects/ai-agents/profiles/scout-report.json` exists.
2. Use `jq` to extract recommendations where tier is "adopt" or "evaluate".
3. Compute report age in days from `generated_at`.
4. If age > 8 days or zero actionable items: emit nothing.
5. Otherwise emit one line:

```
Scout: 2 actionable (adopt: component-a, evaluate: component-b) | 3d ago
```

Format: comma-separated component names grouped by tier. Age in days.

### Implementation

Pure bash + jq. No Python dependency. Graceful failure — if jq fails or file is missing, block emits nothing.

## Section 3: Testing

### Backend tests (ai-agents)

4 tests in `tests/test_scout_decision_awareness.py`:

- `test_dismissed_within_cooldown_skipped`: Component dismissed 30 days ago is not scanned.
- `test_dismissed_past_cooldown_evaluated`: Component dismissed 100 days ago is scanned normally.
- `test_deferred_within_cooldown_skipped`: Component deferred 60 days ago is not scanned.
- `test_adopted_not_skipped`: Adopted component is always scanned.

Tests mock JSONL content and scout internals. No real API calls.

### Session hook

Manual validation only — create mock scout-report.json, run hook, verify output format.
