# Self-Improving Systems — Design Document

**Date:** 2026-03-12
**Layer:** 3 of 3 (LLM-Driven SDLC)
**Status:** Design
**Depends on:** Layer 1 (Reactive CI) + Layer 2 (Proactive SDLC) operational

---

## Problem

Post-merge, the system has no automated response to regressions, drift, or coverage gaps. Health checks detect problems but remediation is manual. Drift detection identifies divergence but doesn't generate fixes. Test coverage gaps are known but unaddressed. The system observes but does not self-correct.

## Goals

1. **Auto-revert on regression**: When health checks degrade after a merge, correlate with the commit and auto-revert (with human approval gate).
2. **LLM hotfix generation**: When auto-revert is insufficient or impossible, LLM generates a targeted fix, opens a PR.
3. **Drift-to-refactor pipeline**: High-severity drift items automatically generate refactoring PRs.
4. **Test coverage improvement**: Identify coverage gaps, generate tests, validate with mutation testing.
5. **Continuous learning**: Build a structured knowledge base of (failure, fix, outcome) triples from incident history.

## Non-Goals

- Self-modification of oversight systems (health monitor, alerts, axioms, backup scripts)
- Fully autonomous merge of hotfixes (human gate always required for application code)
- Production deployment automation (out of scope — this is a single-machine system)
- Replacing the operator for architectural decisions

## Critical Safety Constraint: Modification Classification Matrix

| Target | Auto-fix | Review Required | Never Auto-Modify |
|--------|----------|-----------------|-------------------|
| Documentation | Yes | - | - |
| Config files (non-auth) | - | Yes | - |
| Test files | - | Yes | - |
| Application code | - | Yes | - |
| Health monitor | - | - | Yes |
| Alert/escalation system | - | - | Yes |
| Axiom definitions | - | - | Yes |
| Backup/recovery scripts | - | - | Yes |
| Auth/secrets code | - | - | Yes |
| shared/config.py | - | - | Yes |

**Rationale**: A system that can modify its own oversight mechanisms has no oversight. The axiom governance system (VetoChain, compliance_check, precedent_store) enforces this boundary.

## Architecture

```
                    ┌─────────────────────┐
                    │   Human Operator     │
                    │  (review, approve,   │
                    │   override, teach)   │
                    └─────────┬───────────┘
                              │ approval/veto
                    ┌─────────▼───────────┐
                    │  Axiom Governance    │
                    │  (VetoChain,         │
                    │   compliance_check,  │
                    │   precedent_store)   │
                    └─────────┬───────────┘
                              │ compliant actions only
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼──────┐ ┌─────▼──────┐ ┌──────▼─────────┐
    │  Auto-Revert   │ │  Hotfix    │ │  Refactor PR   │
    │  Engine        │ │  Generator │ │  Generator     │
    │                │ │            │ │                │
    │  git revert +  │ │  LLM +    │ │  drift item →  │
    │  human approve │ │  SWE-agent │ │  code change   │
    │                │ │  pattern   │ │                │
    └────────────────┘ └────────────┘ └────────────────┘
              ▲               ▲               ▲
              │               │               │
    ┌─────────┴──────┐ ┌─────┴──────┐ ┌──────┴─────────┐
    │  Alert State   │ │  Incident  │ │  Drift         │
    │  Machine       │ │  Knowledge │ │  Detector      │
    │                │ │  Base      │ │                │
    │  escalation,   │ │  (failure, │ │  doc vs code   │
    │  dedup, cycles │ │  fix,      │ │  vs reality    │
    │                │ │  outcome)  │ │                │
    └────────────────┘ └────────────┘ └────────────────┘
              ▲               ▲               ▲
              └───────────────┼───────────────┘
                    ┌─────────┴───────────┐
                    │  Health Monitor      │
                    │  80+ checks,         │
                    │  structured output,  │
                    │  remediation cmds,   │
                    │  git commit tagging  │
                    └─────────────────────┘
```

## Component Designs

### 1. Auto-Revert Engine

**Trigger**: Health check transitions healthy → failed within N minutes of a merge to main.

**Mechanism**:
- Health monitor records current `HEAD` commit hash with each run
- When a check transitions healthy → failed, tag the alert with the most recent commit
- If commit age < 30 minutes, flag as "likely regression from {commit}"
- Auto-generate `git revert {commit}` on a branch
- Run tests on the revert branch
- If tests pass, open PR with `[auto-revert]` tag and request urgent human review
- Never auto-merge reverts — always human approval

**Circuit breaker**: Max 1 auto-revert attempt per commit. If revert itself fails tests, escalate to human.

### 2. Hotfix Generator

**Trigger**: Remediation command from health monitor fails, or auto-revert is not appropriate (regression is in data/config, not code).

**Mechanism**:
- Receive structured context: `{check_name, status, message, detail, remediation_that_failed, recent_diff, stack_trace}`
- Query incident knowledge base for similar past failures
- LLM generates fix on a branch with `[auto-hotfix]` tag
- Full test suite must pass
- Diff must be < 50 lines
- PR created with full context for human review

**Circuit breaker**: Max 2 hotfix attempts per check per 24-hour window. After that, create a GitHub issue labeled `needs-human-fix` and notify via ntfy.

### 3. Drift-to-Refactor Pipeline

**Trigger**: Drift detector finds high-severity code-fixable items.

**Extension to existing DriftItem**:
```python
@dataclass
class DriftItem:
    # existing fields...
    fix_type: str = "doc"  # doc | code | config | infra
    source_files: list[str] = field(default_factory=list)  # relevant source paths
```

**Mechanism**:
- Drift detector categorizes items by `fix_type`
- `doc` fixes: auto-apply and PR (already partially implemented)
- `code` fixes: pass `{drift_item, source_files, architecture_docs}` to LLM agent
- Agent generates refactoring patch on branch
- Axiom compliance gate (compliance_veto) must pass
- Tests must pass
- PR created for human review

### 4. Test Coverage Improvement

**Trigger**: Coverage report identifies uncovered modules, prioritized by risk tier.

**Priority order**:
1. T0 axiom-enforced code (health_monitor, alert_state, axiom_enforcement)
2. Agent core logic (watch_receiver, profiler_sources, briefing)
3. Shared utilities
4. UI/presentation code

**Quality gate**: Mutation testing (mutmut or cosmic-ray).
- Generated tests must kill > 50% of injected mutants in the target module
- Tests that only increase line coverage without killing mutants are rejected
- Human review mandatory for all generated tests

### 5. Incident Knowledge Base

**Structure**:
```yaml
# ~/.cache/hapax-council/incident-knowledge.yaml
patterns:
  - id: "qdrant-connection-refused"
    failure_signature:
      check: "connectivity.qdrant"
      status: "failed"
      message_pattern: "connection refused"
    root_causes:
      - "Docker container crashed"
      - "Port conflict"
    fixes:
      - command: "docker compose restart qdrant"
        success_rate: 0.95
        last_verified: "2026-03-10"
        times_used: 12
    related_commits: []
```

**Build process**:
1. Log every alert action to `incidents.jsonl`: `{timestamp, check, status, cycles, fix_applied, fix_outcome}`
2. After each `--fix` run, record whether the next health check recovers
3. Weekly: LLM analyzes incident log, extracts patterns, updates knowledge base
4. Knowledge base queried by Hotfix Generator before attempting LLM fix

## Existing Infrastructure Leverage

| Existing Component | Role in Self-Improvement |
|-------------------|-------------------------|
| Health monitor (80+ checks, --fix, --json) | Sensor layer: detects regressions, provides structured failure context |
| Alert state machine (dedup, escalation, tiers) | Signal processing: identifies sustained failures vs transient blips |
| Drift detector (LLM semantic comparison, --fix) | Strategic drift sensor: detects slow-moving divergence |
| Axiom governance (VetoChain, compliance, precedents) | Safety layer: ensures auto-modifications comply with system values |
| Capability health veto | Circuit breaker: blocks actions when dependencies are degraded |
| Langfuse tracing | Observability: full audit trail of every automated action |

## Implementation Phases

### Phase 1: Instrument (weeks 1-2)
- Add git commit hash to health check reports
- Add incident logging (JSONL) to alert_state.py
- Add fix outcome tracking after --fix runs
- Add `fix_type` field to DriftItem

### Phase 2: Auto-Remediation for Known Fixes (weeks 3-4)
- Extend `--fix --yes` to run remediation commands on timer
- Circuit breaker: max 2 auto-fix attempts per check per 24h
- Apply modification classification matrix
- Log all auto-fix actions with full context

### Phase 3: Auto-Revert + LLM Hotfix (weeks 5-8)
- Implement auto-revert engine (commit correlation, revert branch, PR)
- When remediation fails, pass context to LLM for hotfix generation
- Hotfix goes to branch, runs tests, creates PR for human review
- Track accept/reject rate

### Phase 4: Drift-to-Refactor PRs (weeks 5-8, parallel)
- Extend drift detector with fix_type and source_files
- LLM generates refactoring patches for code-type drift
- Axiom compliance gate via compliance_veto
- PR workflow with human review

### Phase 5: Continuous Learning (weeks 9-12)
- Build incident knowledge base from Phase 2-3 logs
- Weekly LLM pattern extraction from incident log
- RAG over incident history for fix suggestions
- Chaos testing scripts for validation
- Calibrate confidence scores from historical success rates

### Phase 6: Graduated Autonomy (weeks 13+)
- Auto-merge doc-only fixes with high confidence
- Auto-merge config fixes that pass 30-min soak period
- Auto-merge test additions that pass mutation testing gate
- Application code always requires human review
- Track revert rate as the key quality metric

## Cost Model

| Activity | Est. Cost/Run | Monthly Est. |
|----------|--------------|--------------|
| Hotfix generation (Opus) | $1.50-5.00 | $15-50 (est. 10/mo) |
| Drift refactor (Sonnet) | $0.50-1.50 | $10-30 (est. 20/mo) |
| Test generation (Sonnet) | $0.30-1.00 | $6-20 (est. 20/mo) |
| Pattern extraction (Haiku) | $0.05 | $1 (weekly) |
| Axiom compliance checks | $0.02 | $2 |
| **Total** | | **$34-103/month** |

## Success Metrics

- **Mean time to recovery (MTTR)**: Time from health check failure to automated fix (target: < 5 min for known patterns)
- **Auto-revert accuracy**: % of auto-reverts that correctly identify the regressing commit
- **Hotfix acceptance rate**: % of LLM-generated hotfixes merged by human
- **Drift item closure rate**: % of drift items automatically resolved
- **Mutation score improvement**: Increase in mutation testing score from generated tests
- **Incident knowledge base growth**: Number of validated (failure, fix, outcome) patterns
- **False positive rate**: % of auto-reverts/hotfixes that were unnecessary

## Risks

| Risk | Mitigation |
|------|-----------|
| Fix cascades (fix introduces new bug) | Circuit breaker (2 attempts/24h), revert-first policy, diff size limit |
| Self-modification of oversight | Modification classification matrix, axiom governance, protected paths |
| Hallucinated fixes (suppress error instead of fixing) | Second LLM reviews fix for root cause adequacy; full test suite gate |
| Semantic drift from accumulated patches | Periodic human code audit; ruff/pyright metrics tracking |
| Causality misattribution | Only flag commits < 30 min old; canary comparison when possible |
| Coverage theater (tests that don't catch bugs) | Mutation testing gate; human review of all generated tests |

## Open Questions

1. Should chaos testing run against the real system or a staging copy? (Recommendation: lightweight chaos only — stop/start containers, not corrupt data)
2. What's the right soak period for auto-merged config fixes? (Proposal: 30 min)
3. Should the incident knowledge base be in YAML, SQLite, or Qdrant? (Proposal: YAML initially, migrate to Qdrant if > 500 patterns)
4. How should the system handle health check flapping (rapid healthy/failed oscillation)? (Existing: alert_state dedup handles this via 30-min window)
