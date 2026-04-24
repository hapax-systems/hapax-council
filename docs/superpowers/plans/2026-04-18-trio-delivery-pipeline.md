# Trio Delivery Pipeline — delta / beta / alpha

> **2026-04-24 addendum:** epsilon was formalized as a 4th primary session on
> this date. **Epsilon operates outside this pipeline by default** —
> authored PRs independently (e.g., PR #1277 operator-referent-policy was
> epsilon-authored + admin-merged by alpha without beta-audit). For
> epsilon's PRs, beta still performs pre-merge audit per trio-delivery §11
> (beta audits all code-shipping sessions generally), but the "implementation
> → pre-merge audit → smoketest" cadence is delta-centric.
> Full 4-session quad-delivery rewrite deferred until friction observed;
> see `~/.cache/hapax/relay/context/2026-04-24-epsilon-4-session-rebalance-synthesis.md`.

**Status:** Active 2026-04-18 (go-live night). Epsilon addendum 2026-04-24.
**Operator directive:** "Start devising a plan where you can delegate work to two other sessions for safe parallelization... beta audits all work after produced... alpha smoketests all work after it lands on local from all angles."

## 1. Roles

| Session | Responsibility | Worktree | Branch |
|---|---|---|---|
| **delta** (me) | Implementation — ships code, consumes audits, drives next-wave work | `hapax-council--cascade-2026-04-18/` | `2026-04-18-cascade-phase-N` |
| **beta** | Code audit BEFORE merge — reports findings against spec, consistency, completeness, correctness, performance, robustness, missed opportunities | `hapax-council--beta/` | audit-specific (checks out PR branch) |
| **alpha** | Smoketest AFTER merge lands on local and rebuild-timer deploys — exercises all surfaces | `hapax-council/` (primary, always on main) | main (post-merge) |

## 2. Workflow

```
delta ships code  →  opens PR  →  signals beta
                                      ↓
                                  beta pulls PR branch
                                  beta runs audit
                                  beta writes report to relay
                                      ↓
                                  delta reads audit
                                  delta addresses findings (or proceeds if clean)
                                      ↓
                                  admin-merge (delta or operator)
                                      ↓
                                  rebuild-timer deploys to main  →  signals alpha
                                      ↓
                                  alpha runs smoketests
                                  alpha writes report to relay
                                      ↓
                                  delta reads smoketest
                                  delta files follow-ups OR fixes immediately
                                      ↓
                                  delta starts next wave
```

## 3. Relay Files

All under `~/.cache/hapax/relay/` (existing convention).

### Session status files (updated every ~5 min by owning session)

- `delta.yaml` — current PR, expected-audit-by, next-wave-candidates
- `beta.yaml` — audit queue, current audit target, audits-completed-today
- `alpha.yaml` — smoketest queue, last-smoketested sha, regressions-surfaced-today

### Per-PR reports

- `audit-PR-<N>.yaml` — beta's audit of PR #N
- `smoketest-PR-<N>.yaml` — alpha's smoketest after PR #N merged + deployed

## 4. Audit Report Schema (beta writes)

```yaml
pr: 1058
branch: 2026-04-18-cascade-phase-N
head_sha: abc1234
auditor: beta
audit_started_at: 2026-04-19T00:15:00Z
audit_completed_at: 2026-04-19T00:25:00Z

# Spec traceability — every spec deliverable hit?
spec_coverage:
  - spec: docs/superpowers/specs/XXX.md
    deliverables_required: [...]
    deliverables_found: [...]
    gaps: []

findings:
  - severity: high | medium | low
    category: spec | consistency | completeness | correctness | performance | robustness | missed-opportunity
    location: path:line
    description: "..."
    suggested_action: "..."
    blocks_merge: true | false

missed_opportunities:
  # Things that would be cheap to add now, expensive later
  - description: "..."
    effort: S | M | L
    value: S | M | L

decision: approve | approve-with-comments | request-changes
summary: "one-paragraph disposition"
```

## 5. Smoketest Report Schema (alpha writes)

```yaml
pr: 1058
deployed_sha: abc1234
deployed_at: 2026-04-19T00:30:00Z
tester: alpha
smoketest_completed_at: 2026-04-19T00:45:00Z

surfaces:
  - name: studio-compositor
    status: pass | degraded | fail
    evidence_command: "systemctl --user is-active studio-compositor.service"
    evidence_output: "..."
    notes: "..."

  - name: director-loop (no-op invariant)
    status: pass | ...
    evidence_command: "tail -100 ~/hapax-state/stream-experiment/director-intent.jsonl | jq 'select(.compositional_impingements == [])' | wc -l"
    evidence_output: "0"

  - name: livestream-output (RTMP)
    status: pass | ...
    evidence_command: "curl -sI http://127.0.0.1:1935/..."
    evidence_output: "..."

  - name: face-obscure (if active)
    status: ...

  - name: homage-package (active package)
    status: ...

  - name: voice-cpal
    status: ...

  - name: perception-freshness
    status: ...

  - name: logos-api
    status: ...

  - name: reverie-substrate
    status: ...

regressions_surfaced: []
follow_ups_proposed: []

decision: green | yellow-ship | red-revert
summary: "one-paragraph disposition"
```

## 6. Audit Checklist (beta operates from this)

For each PR, check:

### 6.1 Spec coverage
- [ ] Every deliverable in spec §N file-level plan exists
- [ ] Every test listed in spec test-strategy exists
- [ ] Open questions from spec are either resolved (operator calls made) or still-open flags

### 6.2 Consistency
- [ ] Naming matches spec + rest of codebase
- [ ] Type signatures match across files
- [ ] No contradictions between docstring and behavior
- [ ] Imports match existing conventions

### 6.3 Completeness
- [ ] Edge cases covered in tests
- [ ] Error paths have defined behavior
- [ ] Feature flags referenced in spec exist
- [ ] Logging at failure points

### 6.4 Correctness
- [ ] Tests exercise the invariants they claim to pin
- [ ] No silent-failure anti-patterns (see superpowers:silent-failure-hunter)
- [ ] Concurrency safe where relevant
- [ ] Fail-open vs fail-closed decisions match spec

### 6.5 Performance
- [ ] No obvious O(n²) or unbounded growth
- [ ] Latency budget from spec respected
- [ ] Memory budget respected
- [ ] No new per-frame allocations in hot paths

### 6.6 Robustness
- [ ] Missing file / stale data graceful
- [ ] Malformed input rejected cleanly
- [ ] Hook / CI failure modes understood
- [ ] Rollback path documented

### 6.7 Missed opportunities
- [ ] Simple test that would pin a future regression
- [ ] Small docstring that would save downstream confusion
- [ ] Constant that should be exposed as module-level (for tests)
- [ ] Common pattern that should be extracted to a helper

## 7. Smoketest Surfaces (alpha exercises these)

For every PR that merges, alpha must verify:

### 7.1 Services
- [ ] All 7 core services active: studio-compositor, hapax-daimonion, hapax-imagination, VLA, reverie, hapax-logos, logos-api
- [ ] No unexpected restarts in the last 10 min

### 7.2 Livestream pipeline
- [ ] RTMP sink accepting frames
- [ ] HLS playlist fresh (<2s age)
- [ ] OBS V4L2 loopback serving

### 7.3 Director invariant
- [ ] `director-intent.jsonl` trailing 100 lines: zero with `compositional_impingements: []`

### 7.4 Perception
- [ ] `perception-state.json` fresh (<2s old)
- [ ] Key signals present per last deploy

### 7.5 Face obscure (when active)
- [ ] `/dev/shm/hapax-compositor/cam-*.jpg` snapshots have obscured faces (visual check via `feh` or diff)
- [ ] Prometheus face-obscure detection counter incrementing

### 7.6 HOMAGE package
- [ ] Active package = expected (`bitchx` typically)
- [ ] Ward transitions happening per choreographer log

### 7.7 Voice
- [ ] CPAL loop alive (evidence: impingement jsonl cursor advancing)
- [ ] TTS reachable

### 7.8 Governance
- [ ] Anti-personification linter zero findings on frozen persona artifacts
- [ ] Consent gate state consistent with expected surfaces

### 7.9 Grafana
- [ ] Key dashboards green; no red alerts

## 8. Escalation Rules

- **Beta audit = request-changes** → blocks merge. Delta addresses findings, pushes update, re-requests audit.
- **Alpha smoketest = fail** → delta reverts immediately (new PR reverting the offending merge; admin-merge the revert).
- **Alpha smoketest = degraded** → delta files follow-up task in active-work-index, proceeds cautiously.
- **Any session down >15 min** → surface in operator's next check-in (via ntfy or relay).

## 9. Session Synchronization

- Delta pushes PR + signals beta via `relay/delta.yaml`:`current_pr: <N>`
- Beta reads `delta.yaml`, picks up the PR
- When audit complete, beta writes `audit-PR-<N>.yaml` + updates `beta.yaml`:`last_audit: <N>`
- Delta watches `beta.yaml`, reads audit, responds
- After merge + rebuild-timer deploy, delta signals alpha via `relay/delta.yaml`:`last_deployed_sha: <sha>`
- Alpha reads, runs smoketest, writes `smoketest-PR-<N>.yaml`
- Delta consumes smoketest, plans next wave

## 10. Kickoff

- **Next delta push**: when cascade-phase-3 reaches merge readiness, delta requests audit by writing `delta.yaml`:`audit_request: 2026-04-18-cascade-phase-3`
- **Beta onboarding**: beta reads this plan doc + `~/.cache/hapax/relay/onboarding-beta.md`; tells operator when ready
- **Alpha onboarding**: alpha reads this plan doc + `~/.cache/hapax/relay/onboarding-alpha.md`; tells operator when ready

## 11. Failure Modes + Mitigations

| Failure | Mitigation |
|---|---|
| Beta audit takes too long (blocks critical fix) | Delta flags `priority: critical` in `delta.yaml`; beta truncates audit to correctness + spec only |
| Alpha smoketest false positive | Delta consumes with care; re-run on quiet cycle; document false-positive signature |
| Delta merges before beta finishes | Counts as protocol violation — delta should wait for audit OR flag critical |
| Two sessions write to same relay file concurrently | File-bus convention: atomic tmp + rename; last-write wins but single-session-per-file keeps it safe |
| Beta writes findings against merged PR (slow audit) | Findings become follow-up tasks for delta; no revert unless correctness-critical |

## 12. Benefits

- **Parallel throughput** — delta doesn't block on its own review
- **Second pair of eyes** — beta catches what delta misses
- **Live-state check** — alpha catches what audits can't (runtime regressions)
- **Protocol-based** — each session has a file-bus + schema to follow; no handoff ambiguity
- **Audit trail** — audit reports + smoketest reports form a per-PR dossier
