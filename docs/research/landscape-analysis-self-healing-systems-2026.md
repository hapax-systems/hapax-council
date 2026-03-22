# Self-Improving / Self-Healing Software Systems Driven by LLMs

**Landscape Analysis — March 2026**
**Scope:** Post-merge LLM monitors health checks and auto-reverts or creates hotfix PRs on regression. Drift detection triggers refactor PRs. Test coverage gaps trigger test-writing PRs.

---

## 1. Auto-Revert on Regression

### Existing Patterns

**Progressive delivery tools** are the mature foundation here. They operate at the deployment layer, not the code layer:

- **Flagger** (CNCF): Canary analysis with automatic rollback. Monitors request-success-rate (min 99%) and request-duration (max 500ms) during progressive traffic shifts. Rolls back when failed checks exceed a configurable threshold. No causality analysis — uses temporal correlation (metric degradation during canary window).

- **Argo Rollouts**: Analysis-driven progressive delivery for Kubernetes. Supports Prometheus, Datadog, NewRelic, Kayenta as analysis providers. Runs AnalysisRuns at defined intervals during rollout, auto-promotes or auto-aborts based on metric thresholds.

- **GitOps reconciliation** (Flux/ArgoCD): Pull-based operators continuously compare desired state (git) vs actual state (cluster). Any drift is automatically corrected. This handles *infrastructure* drift, not code-level regression.

- **PagerDuty Runbook Automation**: Event-driven remediation. Pre-built automation jobs trigger on incidents. Supports service diagnostics, failback automation, and governed remediation with audit trails. Not LLM-driven — uses deterministic playbooks.

- **LaunchDarkly / feature flags**: Not auto-revert per se, but kill-switch pattern. Flag-gate new code, monitor metrics, auto-disable flag on regression. The fastest rollback path because it requires no redeploy.

### Causality Determination

This is the hard problem. No production system truly solves it. Current approaches:

1. **Temporal correlation**: If metrics degraded within N minutes of deploy, assume the deploy caused it. High false positive rate (coincident failures).
2. **Canary comparison**: Compare canary cohort metrics against baseline cohort running old code simultaneously. Flagger and Argo Rollouts use this. Much stronger signal, but requires traffic splitting infrastructure.
3. **Change correlation**: Cross-reference deploy timestamps with metric anomaly detection. Tools like Datadog Watchdog and PagerDuty Change Events attempt this.
4. **Blast radius analysis**: If only the service that was deployed shows degradation, causality confidence is higher. Cross-service cascading makes this unreliable.

**Gap**: Nobody uses LLMs for causality analysis yet. An LLM with access to the diff, the health check output, and the timeline could produce a causality confidence score. This is a genuine opportunity.

### Recommendation for hapax-council

The health monitor already has 80+ checks with tier classification (T0 critical through T3 optional). The alert state machine tracks consecutive failure cycles and escalation. The missing piece is **temporal correlation with git events**:

- Record `git log --oneline -1` hash at each health check run
- When a check transitions healthy -> failed, tag the alert with the most recent commit
- If the commit is < N minutes old, flag it as "likely regression from {commit}"
- Auto-revert = `git revert {commit} && deploy` with human approval gate

---

## 2. LLM-Driven Hotfix Generation

### Current State

**SWE-agent** (Princeton) is the most validated system:
- Takes a GitHub issue, autonomously navigates the codebase, edits files, runs tests
- 65% success on SWE-bench verified (Mini-SWE-agent with Claude)
- State-of-the-art among open-source approaches
- Governed by a single YAML config defining tool access and behavior

**GitHub Copilot agents** can now be assigned issues directly, autonomously write code, create PRs, and respond to review feedback. This is the closest production system to the "health check fails -> LLM generates fix -> PR -> merge" loop.

**Meta's TestGen-LLM**: Deployed at scale on Instagram/Facebook. 75% of generated test cases built correctly, 57% passed reliably, 25% increased coverage. 73% of recommendations accepted for production. Validates with filter chains to eliminate hallucinated tests.

**No production system yet implements the full loop**: health check fail -> LLM diagnoses -> LLM writes fix -> PR -> automated merge. The pieces exist but the composition is novel.

### Risks

1. **Fix cascades**: LLM fix introduces new bug -> health check fails again -> LLM generates another fix -> divergent code. This is the primary danger.
2. **Semantic drift**: Accumulation of small LLM patches that individually pass tests but collectively degrade code quality/readability.
3. **Hallucinated fixes**: LLM "fixes" a health check by disabling it or adding a try/except that swallows the real error.
4. **Overfitting to symptoms**: Fixing the check output rather than the underlying cause.

### Preventing Fix Cascades

- **Circuit breaker**: Maximum N auto-fix attempts per check per time window (e.g., 2 attempts per 24h). After that, escalate to human.
- **Revert-first policy**: Always auto-revert first. Only attempt an LLM fix if revert is not possible (e.g., the regression is in data, not code).
- **Diff size limit**: Auto-generated fixes must be < N lines changed. Large fixes require human review.
- **Test gate**: Generated fix must pass full test suite, not just the failing health check.
- **Semantic review**: A second LLM call reviews the fix for "did this actually address the root cause or just suppress the symptom?"

### Minimum Observability Needed

1. Structured health check output (hapax-council already has this: CheckResult with status, message, detail, remediation)
2. Git history correlation (commit hash at time of failure)
3. Diff of the suspected commit
4. Stack traces / error logs from the failing check
5. Historical context: has this check failed before? What fixed it last time?

### Recommendation for hapax-council

The health monitor's `remediation` field on CheckResult already contains fix commands. This is the seed:

```
Phase 1: Auto-run remediation commands (already have --fix flag)
Phase 2: When remediation command fails, pass {check_name, status, message, detail, remediation_that_failed} to LLM
Phase 3: LLM generates a fix, creates a branch, runs tests, opens PR
Phase 4: If tests pass and diff is small, auto-merge with 30-min soak period
```

---

## 3. Drift Detection -> Refactor PRs

### Types of Drift

1. **Documentation drift**: Docs describe system state that no longer matches reality. The hapax-council drift_detector already handles this — it compares live infrastructure manifests against documentation files using LLM semantic analysis.

2. **Architectural drift**: Code violates declared architecture (layer violations, circular dependencies, unauthorized package access).
   - **ArchUnit** (Java): Tests architectural rules against bytecode. Enforces dependency constraints, layer architecture, cycle detection, annotation requirements. Runs as unit tests.
   - **dependency-cruiser** (JS/TS): Validates and visualizes module dependencies against rules. Detects circular dependencies, orphan modules, forbidden paths.
   - **Custom linters**: For Python, typically `import-linter`, `pydeps`, or custom AST-based checks.

3. **Configuration drift**: Deployed configs differ from source-of-truth. The hapax-council `check_systemd_drift()` already does this for systemd units (compares repo files against deployed files byte-for-byte).

4. **Dependency drift**: Dependencies diverge from lockfile, or security patches are available but not applied. Tools: `pip-audit`, `npm audit`, Renovate/Dependabot.

5. **Style drift**: Code style diverges from project norms. Typically handled by formatters (ruff, prettier) and linters, not LLMs.

6. **Goal drift**: System capabilities diverge from stated goals/plans. The hapax-council drift detector categories include `goal-gap` and `axiom-violation`, which is unusual and valuable.

### LLM -> Refactor PR Pipeline

The pattern would be:

```
drift_detector runs (already exists)
  -> produces DriftReport with items (severity, category, doc_claim, reality, suggestion)
  -> for high-severity items:
     -> LLM receives (drift_item, relevant_source_files, architecture_docs)
     -> LLM generates refactoring patch
     -> patch is applied to branch, tests run
     -> if tests pass, PR is created with drift_item as context
```

The drift_detector already has a `--fix` flag that generates corrected doc fragments. Extending this to generate code changes (not just doc edits) is the next step.

### Recommendation for hapax-council

The existing drift detector is well-positioned. Current DriftItem categories already separate doc-fixable drift (stale_reference, wrong_port) from code-fixable drift (config_mismatch, axiom-violation). The extension path:

1. Add `fix_type: doc | code | config | infra` to DriftItem
2. For `code` type drift, include the relevant source file paths
3. Pass to an LLM agent that can edit files and run tests
4. Gate on axiom compliance (the compliance_veto already exists for this)

---

## 4. Automated Test Generation

### Current State

**Qodo Cover Agent** (formerly CodiumAI):
- CLI + GitHub CI integration for automatic test generation
- Architecture: Test Runner -> Coverage Parser -> Prompt Builder -> AI Caller
- Validates that generated tests increase coverage
- Roadmap includes flakiness detection (run tests multiple times)
- No mutation testing in current release

**Meta TestGen-LLM** (production-validated):
- 75% of generated tests build correctly
- 57% pass reliably (43% are flaky or wrong — significant!)
- 25% increase coverage
- 73% of recommendations accepted by engineers
- Key insight: filter chain that eliminates hallucinated tests before presenting to humans

**SWE-agent** for test writing:
- Can be directed to write tests for specific functions/modules
- 65% on SWE-bench verified includes test-related tasks

### Do LLM-Generated Tests Catch Bugs?

The honest answer: **mostly no, currently**. LLM-generated tests primarily increase line/branch coverage metrics. They tend to:

- Test the happy path (input -> expected output)
- Mirror the implementation rather than test the specification
- Miss edge cases that require domain knowledge
- Generate assertions that pass trivially

**Mutation testing** is the quality gate that separates real tests from coverage-padding. A test that fails to kill mutants (small code changes like flipping a conditional, removing a line) is not actually testing anything useful.

### Quality Metrics

1. **Coverage increase**: Necessary but not sufficient. Easy to game.
2. **Mutation score**: Percentage of injected mutants killed by the test suite. The real metric.
3. **Fault detection rate**: How many known bugs does the test suite catch? Requires a bug corpus.
4. **Flakiness rate**: What percentage of generated tests fail intermittently? Meta reports 43% of generated tests don't pass reliably.
5. **Maintenance cost**: Do generated tests break on valid code changes? Brittle tests are worse than no tests.

### Recommendation for hapax-council

The system has an existing test suite. The approach should be:

1. **Coverage-gap analysis**: Run `pytest --cov` to identify uncovered modules
2. **Prioritize by risk**: Focus test generation on T0 axiom-enforced code (health_monitor, alert_state, axiom_enforcement) rather than blanket coverage
3. **Mutation testing gate**: Use `mutmut` or `cosmic-ray` to validate generated tests actually catch bugs
4. **PR workflow**: Generated tests go to a branch, run mutation testing, only PR if mutation score > threshold
5. **Human review mandatory**: LLM-generated tests should never auto-merge. They need human review for specification correctness.

---

## 5. Continuous Improvement Loops

### Feedback Loop Architecture

The ideal loop:

```
Failure occurs
  -> Incident recorded (timestamp, check, error, context)
  -> Fix applied (manual or automated)
  -> Fix outcome recorded (did it work? how long to resolve?)
  -> Pattern extracted (what class of failure? what class of fix?)
  -> Knowledge base updated
  -> Future similar failures matched against knowledge base
  -> Fix suggested or auto-applied with higher confidence
```

### Is This Just RAG Over Incident History?

Partially, but not entirely. RAG over incident history gives you "find similar past incidents and their fixes." That is valuable but limited because:

1. **Retrieval quality depends on embedding similarity**, which may not capture operational similarity. "Qdrant OOM" and "Postgres OOM" are semantically similar but have completely different fixes.
2. **Root cause is often implicit**. Incident notes say "restarted the container" but don't say "because the container had a memory leak caused by unclosed connections."
3. **Fix applicability degrades over time**. A fix that worked 6 months ago may not work after dependency upgrades.

What you actually need is **structured incident knowledge**:

```yaml
- pattern: "qdrant.health check fails with connection refused"
  root_causes:
    - "Docker container crashed (check docker ps)"
    - "Port conflict with another service"
  fixes:
    - command: "docker compose -f ~/llm-stack/docker-compose.yml restart qdrant"
      success_rate: 0.95
      last_verified: "2026-03-10"
    - command: "docker compose -f ~/llm-stack/docker-compose.yml down qdrant && docker compose up -d qdrant"
      success_rate: 0.80
      when: "simple restart doesn't work"
```

### Recommendation for hapax-council

The alert_state.py already tracks consecutive failure cycles and recovery events. The extension:

1. **Incident log**: Append to a JSONL file on each alert action: `{timestamp, check, status, cycles, fix_applied, fix_outcome}`
2. **Fix outcome tracking**: After a remediation command runs (--fix), record whether the next health check shows recovery
3. **Pattern extraction**: Periodically (weekly?) run an LLM over the incident log to extract patterns and update a structured knowledge base
4. **The precedent system is the mechanism**: The axiom governance already has PrecedentStore with `get_pending_review()`. Extend this to store operational precedents (not just governance ones).

---

## 6. Chaos Engineering Meets LLM

### The Idea

Inject controlled failures -> see if the LLM can diagnose and fix them -> use success/failure as a training signal for the remediation system.

### Current Chaos Tools

- **Netflix Chaos Monkey**: Random instance termination in production. Tests resilience but no auto-remediation.
- **LitmusChaos**: Kubernetes-native chaos engineering. Inject pod failures, network partitions, disk stress. Has "chaos probes" that validate steady state.
- **Gremlin**: Commercial chaos platform. Supports CPU, memory, disk, network, process, and state attacks.

### LLM + Chaos Synthesis

Nobody has published this combination in production. The architecture would be:

```
1. Define chaos experiments (kill container X, corrupt config Y, exhaust disk)
2. Inject chaos
3. Health monitor detects failure (already works)
4. LLM receives health check failure + system context
5. LLM proposes remediation
6. Remediation is applied in sandbox/staging
7. Score: did it fix the problem? How fast? Did it cause side effects?
8. Store (chaos_type, failure_signature, successful_fix) as training data
```

### Value

- **Validation**: Proves the auto-remediation system works *before* real incidents
- **Knowledge building**: Generates (failure, fix) pairs for the knowledge base without needing real outages
- **Confidence calibration**: Measures actual success rate of LLM remediation
- **Edge case discovery**: Chaos may reveal failure modes the health monitor doesn't detect

### Risks

- Running chaos in production on a personal system is risky. This should target a staging environment or use lightweight chaos (stop a container, not corrupt a filesystem).
- LLM may "fix" chaos by detecting it's a test and taking shortcuts.

### Recommendation for hapax-council

Start small:

1. Write chaos scripts that exercise known failure modes: `docker stop qdrant`, `systemctl --user stop health-monitor`, corrupt a profile JSON file
2. Run health monitor, capture the failure report
3. Feed failure report to LLM with the remediation field
4. Measure: does the LLM's suggested fix resolve the chaos?
5. Build a scored corpus of (failure, fix, outcome) triples
6. This becomes the training data for the continuous improvement loop (section 5)

---

## 7. Ethical and Safety Boundaries

### When Self-Modifying Code Becomes Dangerous

**Immediate danger zone:**
- Auto-merging LLM-generated code that modifies auth/security code
- Auto-merging changes to the self-improvement system itself (recursive self-modification)
- Auto-merging changes to backup/recovery scripts (could destroy the safety net)
- Auto-applying fixes to production data (irreversible)

**Theoretical limits:**
- An LLM cannot verify the correctness of its own output. It can generate a fix and generate tests for that fix, but the tests may share the same misunderstanding as the fix.
- Self-modifying systems have a convergence problem: there is no proof that iterative LLM modifications converge to a better state rather than oscillating or diverging.
- Halting problem implications: you cannot algorithmically determine whether an arbitrary code change will cause the system to enter an undesirable state.

### Non-Negotiable Human Oversight

1. **Security-critical code**: Auth, encryption, secrets management, backup scripts. Never auto-merge.
2. **Self-modification**: Changes to the health monitor, drift detector, alert system, or axiom enforcement itself. A system that can modify its own oversight mechanisms has no oversight.
3. **Data-touching code**: Anything that writes to databases, deletes files, or modifies user data. Require human approval.
4. **Axiom changes**: The constitutional axioms define the system's values. These must remain human-controlled.
5. **Escalation overrides**: The system must never be able to suppress its own alerts or reduce its own monitoring scope.

### The Axiom Governance System as Safety Rail

The hapax-council axiom system is well-designed for this role:

- **T0 enforcement=block** implications act as hard stops. `ex-routine-001` ("Recurring tasks must be automated") and `ex-attention-001` ("Critical alerts must be delivered through external channels") prevent the system from silencing itself.
- **VetoChain** (capability_health_veto, compliance_veto) provides composable safety predicates. Before any auto-fix merges, it passes through the veto chain.
- **Precedent tracking** creates an audit trail of decisions and their justifications.

### Recommendation

Implement a **modification classification matrix**:

| Target | Auto-fix allowed | Requires review | Never auto-modify |
|--------|-----------------|-----------------|-------------------|
| Documentation | Yes | - | - |
| Test files | - | Yes | - |
| Config files | - | Yes | - |
| Application code | - | Yes | - |
| Health monitor | - | - | Yes |
| Alert/escalation | - | - | Yes |
| Axiom definitions | - | - | Yes |
| Backup scripts | - | - | Yes |
| Auth/secrets code | - | - | Yes |

---

## 8. hapax-council as Foundation for Self-Improvement

### Existing Assets and Their Roles

**Health Monitor (agents/health_monitor.py)**
- 80+ checks across groups: docker, gpu, systemd, qdrant, profiles, endpoints, credentials, disk, ollama, litellm, langfuse, tailscale, ntfy, n8n, obsidian, latency, voice, axiom
- Structured output: CheckResult with name, group, status, message, detail, remediation, duration_ms, tier
- Already has `--fix` flag that runs remediation commands
- Already has `--json` for machine-readable output
- Already has tiered severity (T0 critical through T3 optional)
- **Role in self-healing**: The sensor layer. Detects regressions and provides structured failure context.

**Alert State Machine (shared/alert_state.py)**
- Deduplication (30-min window), escalation (cycle-based), T0 group classification
- Tracks consecutive failure cycles, recovery events
- Grouped notifications by check group
- **Role in self-healing**: The signal processing layer. Prevents alert storms and identifies sustained failures vs transient blips.

**Drift Detector (agents/drift_detector.py)**
- LLM-powered semantic comparison of docs vs live infrastructure
- Categories: missing_service, wrong_port, config_mismatch, goal-gap, axiom-violation, axiom-sufficiency-gap
- Already has `--fix` flag for generating corrected doc fragments
- Runs on systemd timer via drift-watchdog
- **Role in self-healing**: The strategic drift sensor. Detects slow-moving divergence that health checks miss.

**Axiom Governance**
- 4 constitutional axioms with tiered implications (T0-T3)
- check_fast for hot-path compliance enforcement
- VetoChain composable safety predicates
- PrecedentStore for decision audit trail
- Supremacy validation (domain axioms cannot override constitutional)
- **Role in self-healing**: The safety and governance layer. Ensures auto-modifications comply with system values.

**Capability Health Veto**
- Composes health checks into VetoChain predicates
- Can block actions when required capabilities are unhealthy
- **Role in self-healing**: The circuit breaker. Prevents cascading failures by blocking actions when dependencies are degraded.

### Architecture for Self-Improvement

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
    │  (git revert   │ │  Generator │ │  (drift item   │
    │   + redeploy)  │ │  (LLM +    │ │   -> code      │
    │                │ │   SWE-agent │ │   change)      │
    │                │ │   pattern)  │ │                │
    └────────────────┘ └────────────┘ └────────────────┘
              ▲               ▲               ▲
              │               │               │
    ┌─────────┴──────┐ ┌─────┴──────┐ ┌──────┴─────────┐
    │  Alert State   │ │  Incident  │ │  Drift         │
    │  Machine       │ │  Knowledge │ │  Detector      │
    │  (escalation,  │ │  Base      │ │  (doc vs       │
    │   dedup)       │ │  (RAG +    │ │   reality)     │
    │                │ │   patterns)│ │                │
    └────────────────┘ └────────────┘ └────────────────┘
              ▲               ▲               ▲
              └───────────────┼───────────────┘
                    ┌─────────┴───────────┐
                    │  Health Monitor      │
                    │  (80+ checks,        │
                    │   structured output, │
                    │   remediation cmds)  │
                    └─────────────────────┘
```

### Implementation Roadmap

**Phase 1: Instrument (weeks 1-2)**
- Add git commit hash to health check reports
- Add incident logging (JSONL) to alert_state.py on each alert action
- Add fix outcome tracking: after --fix runs, record whether next check recovers
- Add `fix_type` field to DriftItem (doc | code | config | infra)

**Phase 2: Auto-Remediation for Known Fixes (weeks 3-4)**
- Extend `--fix --yes` to run remediation commands automatically on timer
- Add circuit breaker: max 2 auto-fix attempts per check per 24h
- Add modification classification matrix (what can be auto-fixed, what needs review)
- Log all auto-fix actions with full context for audit

**Phase 3: LLM Hotfix Generation (weeks 5-8)**
- When remediation command fails, pass structured context to LLM
- LLM generates a fix on a branch, runs tests
- If tests pass and diff < 50 lines, create PR with full context
- Human reviews and merges (no auto-merge in this phase)
- Track accept/reject rate and reasons

**Phase 4: Drift -> Refactor PRs (weeks 5-8, parallel with Phase 3)**
- Extend drift_detector to output code-fixable items with source file paths
- LLM generates refactoring patches for high-severity code drift
- Gate on axiom compliance via compliance_veto
- PR workflow with human review

**Phase 5: Continuous Learning (weeks 9-12)**
- Build structured incident knowledge base from Phase 2-3 logs
- Pattern extraction: weekly LLM analysis of incident log
- RAG over incident history for fix suggestions
- Chaos testing scripts for validation
- Calibrate confidence scores based on historical success rates

**Phase 6: Graduated Autonomy (weeks 13+)**
- Auto-merge for doc-only fixes with high confidence
- Auto-merge for config fixes that pass soak period
- Auto-merge for test additions that pass mutation testing gate
- Application code fixes always require human review
- Continuous monitoring of auto-merge quality (revert rate as metric)

---

## Summary of Key Findings

1. **The pieces exist but nobody has composed the full loop in production.** Progressive delivery (Flagger, Argo) handles auto-revert. SWE-agent and GitHub Copilot handle LLM code generation. Health monitoring is mature. But "health check fails -> LLM generates fix -> PR -> merge" is novel territory.

2. **Fix cascades are the primary risk.** Circuit breakers, diff size limits, and revert-first policies are essential.

3. **LLM-generated tests mostly increase coverage, not bug detection.** Mutation testing is the quality gate that matters. Without it, auto-generated tests are coverage theater.

4. **Causality determination is unsolved.** Temporal correlation and canary comparison are the best available, but imperfect. LLM-based causality analysis (given the diff + failure + timeline) is an opportunity.

5. **The axiom governance system is the right safety mechanism.** VetoChain, compliance checks, and precedent tracking provide exactly the oversight framework needed. The modification classification matrix maps directly onto the existing tier system.

6. **hapax-council is unusually well-positioned.** The combination of structured health checks with remediation commands, LLM-powered drift detection, tiered axiom governance, and a precedent audit trail is infrastructure that most teams would need to build from scratch. The gap is connecting these systems into a closed loop.

7. **Self-modification of the oversight system itself must remain human-controlled.** This is the one non-negotiable boundary. The system can fix application code, tests, configs, and docs. It must not fix its own health checks, alert mechanisms, axiom definitions, or governance enforcement.
