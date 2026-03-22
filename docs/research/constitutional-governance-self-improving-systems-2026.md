# Constitutional Governance for Self-Healing, Self-Correcting, and Self-Improving Software

**Research Date:** 2026-03-12
**Scope:** How the hapax 4-axiom governance model can responsibly improve outcomes across three layers of autonomous software processes: reactive CI (self-correction), proactive SDLC (self-development), and continuous improvement (self-improvement).

---

## Executive Summary

The hapax governance system — 4 constitutional axioms, tiered implications (T0-T3), VetoChain, PrecedentStore, and dual-speed compliance checking — maps onto a well-established pattern from legal systems: **tiered normative governance with precedent-based learning**. This research finds that the governance system can be extended to address *classes* of problems (not just instances) and improve *dimensions* of outcomes (not just pass/fail) across all three layers of autonomous software processes.

The key insight: Constitutional AI's self-critique-revision loop (principles -> critique -> revise) can be applied at deployment time through governance-gated development, where axioms serve as the "constitution" that LLM agents critique their own work against. This is architecturally distinct from Anthropic's training-time CAI but operationally analogous.

Seven concrete recommendations emerge, ordered by impact:

1. **Problem class registry** — Encode recurring problem classes as axiom implications with automated enforcement
2. **Dimension scorecards** — Track outcomes across quality dimensions with governance-tuned feedback loops
3. **Precedent-driven learning** — Extend PrecedentStore with outcome tracking and automated rule refinement
4. **Meta-governance cadence** — Quarterly axiom review with staleness detection and effectiveness metrics
5. **Cross-layer circuit breakers** — Universal governance patterns (escalation, rollback, soak) that apply across all three layers
6. **Constitutional merge gates** — Axiom compliance as a CI/CD gate alongside tests and lint
7. **Graduated autonomy matrix** — Governance rules that relax as confidence builds, tighten on regression

---

## 1. Constitutional AI Applied to SDLC

### The Mapping: Training-Time vs. Deployment-Time Constitution

Anthropic's Constitutional AI (Bai et al., arXiv:2212.08073) operates at training time:

```
Harmful prompt -> Model generates response -> Model self-critiques against principles
-> Model revises response -> Fine-tune on revised outputs -> RLAIF phase
```

The hapax governance system operates at deployment time:

```
Agent action (code write, PR, merge) -> Governance check against axioms
-> If violation: block + recovery hint -> Agent revises -> Re-check
```

These are structurally identical loops: **principles -> critique -> revision**. The difference is enforcement timing and mechanism. CAI shapes model tendencies through weight updates. Hapax governance constrains specific actions through runtime enforcement.

### Can Axioms Serve as Constitutional Principles for Self-Correction?

**Yes, with important qualifications.**

The 4 axioms already function as constitutional principles:

| Axiom | SDLC Application | Self-Correction Role |
|-------|-------------------|---------------------|
| `single_user` | "No multi-tenant code, no auth scaffolding" | Blocks the most common source of accidental complexity |
| `executive_function` | "Errors must have remediation, recurring tasks must be automated" | Forces agents to produce actionable outputs |
| `corporate_boundary` | "Sanctioned providers only, no corporate data leakage" | Gates external API calls and dependency choices |
| `management_governance` | "Surface patterns, don't generate coaching language" | Prevents agents from overstepping into human judgment territory |

The self-correction mechanism works because:

1. **PreToolUse hook** blocks T0 violations before code is written (pre-action)
2. **Recovery hints** tell the agent how to proceed within axiom constraints (guidance)
3. **Drift detector** catches violations that escape runtime checks (post-hoc audit)
4. **PrecedentStore** records decisions for future reference (learning)

This is precisely the "self-critique and revision" loop, applied to code generation rather than conversational outputs.

### What CAI Research Adds

The C3AI paper (arXiv:2502.15861, 2025) on "Crafting and Evaluating Constitutions for Constitutional AI" shows that the *choice of constitutional principles* matters enormously — different principle sets produce different behavioral profiles. This validates the hapax design decision of 4 carefully chosen axioms over a larger set of weaker rules.

The DeepSeek-R1 study (arXiv:2503.17365, 2025) on CAI effectiveness in small LLMs shows that self-critique effectiveness varies by model architecture — some models reduce harm significantly through self-critique, others less so. **Implication for hapax:** the governance system should not assume all LLM agents respond equally well to axiom-based correction. Different agents may need different enforcement strengths (blocking vs. advisory) depending on the underlying model's responsiveness to constitutional guidance.

---

## 2. Problem Class Identification

### From Instances to Classes

The current governance system primarily operates on *instances*: individual file writes are checked against patterns, individual commits are scanned, individual drift items are reported. The leap to *class-level* governance means identifying recurring patterns and encoding rules that address the entire class.

### A Taxonomy of Problem Classes for Governance

| Problem Class | Example Instances | Governance Rule (Class-Level) | Enforcement Layer |
|---------------|-------------------|-------------------------------|-------------------|
| **Persistence changes** | Schema migration, new table, ORM model change | "All changes touching data persistence must have integration tests" | CI gate (axiom implication) |
| **External dependency introduction** | New pip package, new Docker service, new API client | "New external dependencies require explicit justification and must be from sanctioned sources" | PreToolUse hook + corporate_boundary |
| **Error handling patterns** | try/except without remediation, bare except, swallowed errors | "All error handlers must include remediation guidance for the operator" | executive_function axiom implication |
| **Configuration surface expansion** | New env var, new config file, new CLI flag | "New configuration must have defaults; zero-config is the goal" | executive_function sufficiency probe |
| **Security surface changes** | New network listener, new file permission, new secret | "Security surface changes require human review regardless of test status" | T0 blocking + merge gate |
| **Self-modification** | Changes to health monitor, governance hooks, alert system | "The system must not modify its own oversight mechanisms" | T0 blocking, never auto-merge |

### Implementation: Problem Class Registry

Extend the axiom implication system with a `problem_class` field:

```yaml
implications:
  - id: "pc-persistence-001"
    axiom: "executive_function"
    tier: "T1"
    problem_class: "persistence_change"
    description: "Changes to data persistence layer require integration tests"
    detection:
      file_patterns: ["**/models/*.py", "**/migrations/*.py", "**/schema*.sql"]
      content_patterns: ["CREATE TABLE", "ALTER TABLE", "class.*Model.*Base"]
    enforcement: "ci_gate"
    required_evidence: "integration_test_covering_change"
```

This converts ad-hoc pattern matching into a structured registry where:
- Each problem class has explicit detection rules
- Enforcement level is specified (blocking, advisory, CI gate)
- Required evidence (tests, review, justification) is machine-checkable
- New instances of a known class are automatically governed

### Feedback Loop for Class Discovery

```
1. Incident occurs (test failure, regression, drift item)
2. Root cause analysis identifies the problem
3. LLM classifies: "Is this an instance of an existing problem class?"
   - If YES: verify the class rule caught it; if not, refine detection
   - If NO: propose a new problem class with detection rules
4. Human reviews and approves new class / refined rules
5. Rules are added to the problem class registry
6. Future instances are automatically governed
```

This is the "case law" pattern from legal systems — individual decisions build up a body of precedent that governs future similar cases.

---

## 3. Dimension-Based Improvement

### The Dimensions

Software quality is not a single scalar. The governance system should track and optimize across multiple dimensions:

| Dimension | Metrics | Governance Lever |
|-----------|---------|-----------------|
| **Correctness** | Test pass rate, bug introduction rate, revert rate | CI gates, review requirements |
| **Security** | Vulnerability count, dependency audit score, secrets exposure | T0 blocking, corporate_boundary |
| **Performance** | Latency p99, memory usage, startup time | Advisory checks, soak periods |
| **Reliability** | Health check pass rate, MTTR, incident frequency | Auto-revert thresholds, circuit breakers |
| **Maintainability** | Cyclomatic complexity, duplication %, doc coverage | Drift detector, style enforcement |
| **Axiom Compliance** | T0 violation rate, drift item count, precedent consistency | All governance layers |

### Feedback Loops That Enable Dimension Improvement

**Loop 1: Measurement -> Governance Tuning**

```
Measure dimension scores weekly (automated)
  -> Identify dimensions trending negatively
  -> Propose governance rule tightening for that dimension
  -> Human approves or adjusts
  -> Updated rules deployed
  -> Measure again next week
```

Example: If maintainability scores decline (complexity increasing), the governance system could:
- Tighten the diff size limit for auto-approved changes
- Require complexity analysis on PRs touching high-complexity modules
- Flag new functions exceeding a complexity threshold

**Loop 2: Incident -> Dimension Attribution**

```
Incident occurs (regression, security issue, performance degradation)
  -> Attribute to dimension(s) affected
  -> Trace to the governance gap that allowed it
  -> Add or strengthen governance rule for that dimension
  -> Record in PrecedentStore with outcome
```

**Loop 3: Precedent Outcome -> Rule Effectiveness**

```
Governance rule applied (allowed or blocked an action)
  -> Track outcome over next N days
  -> If allowed action caused regression: rule was too permissive
  -> If blocked action was later manually approved and succeeded: rule was too restrictive
  -> Adjust rule parameters (threshold, scope, tier)
```

### Implementation: Dimension Scorecard

Add a weekly dimension scorecard to the briefing agent:

```python
def _collect_dimension_scores() -> dict:
    return {
        "correctness": {
            "test_pass_rate": get_test_pass_rate(),
            "revert_rate": get_revert_rate_last_7d(),
            "bug_introduction_rate": get_bugs_introduced_last_7d(),
        },
        "security": {
            "vuln_count": run_pip_audit(),
            "secrets_exposure": check_secrets_in_recent_commits(),
        },
        "reliability": {
            "health_check_pass_rate": get_health_pass_rate(),
            "mttr_minutes": get_mean_time_to_recovery(),
        },
        "axiom_compliance": {
            "t0_violations": count_t0_violations_last_7d(),
            "drift_items": count_drift_items(),
            "pending_precedents": count_pending_precedents(),
        },
    }
```

Trend analysis (this week vs. last week) surfaces which dimensions are improving and which are degrading, enabling targeted governance adjustments.

---

## 4. Precedent-Driven Learning

### How PrecedentStore Should Evolve

The current PrecedentStore records governance decisions with an authority hierarchy (operator > agent > derived). To function as a learning mechanism, it needs three additions:

#### Addition 1: Outcome Tracking

Every precedent should have an `outcome` field populated after N days:

```python
@dataclass
class PrecedentOutcome:
    precedent_id: str
    recorded_at: datetime
    outcome: Literal["positive", "negative", "neutral", "unknown"]
    evidence: str  # What happened after this decision?
    regression_caused: bool
    dimension_affected: Optional[str]  # Which quality dimension?
```

Example: A precedent allowed a change that removed input validation. 3 days later, a health check failure traced to that change. The outcome is `negative`, `regression_caused=True`, `dimension_affected="reliability"`.

#### Addition 2: Precedent Similarity Search for Decision Support

When a new governance decision is needed, search PrecedentStore for similar past decisions:

```python
def get_relevant_precedents(situation: str, k: int = 5) -> list[Precedent]:
    """Semantic search over precedent descriptions + outcomes."""
    embedding = embed(situation)
    results = qdrant.search(
        collection="precedents",
        query_vector=embedding,
        limit=k,
        query_filter={"must": [{"key": "outcome", "match": {"value": "negative"}}]}
    )
    return results
```

This is the **stare decisis** pattern: past decisions inform future ones. If a similar situation previously led to a negative outcome, the governance system should flag this:

```
"WARNING: Similar precedent (prec-2026-02-15-003) allowed this type of change
and resulted in a regression. That precedent was later marked 'negative'.
Consider blocking or requiring additional review."
```

#### Addition 3: Automated Rule Refinement from Precedent Patterns

Periodically (weekly), analyze precedent outcomes to identify patterns:

```python
def analyze_precedent_patterns():
    """Find patterns in precedent outcomes to suggest rule refinements."""
    negative_precedents = store.get_by_outcome("negative", last_n_days=30)

    # Cluster by axiom domain and problem class
    clusters = cluster_by_domain_and_class(negative_precedents)

    for cluster in clusters:
        if len(cluster) >= 3:  # Recurring pattern threshold
            suggest_rule_tightening(
                domain=cluster.domain,
                problem_class=cluster.problem_class,
                evidence=cluster.precedents,
                suggestion=f"Tighten enforcement for {cluster.problem_class} "
                           f"in {cluster.domain} domain based on {len(cluster)} "
                           f"negative outcomes"
            )
```

### Real-World Precedent: How Courts Handle This

The legal system provides the most mature model for precedent-based learning:

1. **Stare decisis** (stand by decisions): Courts follow prior rulings unless there is compelling reason to overturn. The PrecedentStore should default to following established precedents.

2. **Distinguishing**: A court may "distinguish" a case from prior precedent by identifying material differences. The governance system should support this: "This situation looks similar to precedent X, but differs because Y, so a different decision is warranted."

3. **Overruling**: When prior precedent proved wrong, courts overrule it explicitly. The governance system needs an explicit "overrule" mechanism that records why a precedent is no longer authoritative.

4. **Hierarchy of authority**: Operator decisions overrule agent decisions, which overrule derived implications. This already exists in the PrecedentStore authority hierarchy.

The Shenzhen Intermediate People's Court (2024) provides a modern example: an LLM trained on 2 trillion characters of legal text assists judges by summarizing cases, generating hearing prompts, and suggesting written reasoning — but the human judge makes the final decision. This is exactly the governance system's model: LLM agents propose, governance checks, human decides.

---

## 5. Meta-Governance: Who Governs the Governance System?

### The Problem

Governance rules can become:
- **Stale**: Rules that made sense 6 months ago may no longer apply
- **Overly restrictive**: Rules accumulated over time without pruning create friction
- **Gaming-prone**: Agents learn to satisfy the letter of rules while violating the spirit
- **Circular**: Rules that govern rule-creation create infinite regression

### Who Should Govern

In the hapax single-operator model, the answer is clear: **the operator governs the governance system**. But the operator has ADHD and limited attention. The governance system must make meta-governance easy, not another pull-based task.

### Meta-Governance Mechanisms

#### Mechanism 1: Staleness Detection

Every governance rule should have a `last_applied` timestamp. Rules that haven't fired in 90 days are candidates for removal:

```python
def detect_stale_rules():
    """Find governance rules that haven't been applied recently."""
    all_rules = load_axiom_implications()
    audit_log = load_audit_log(days=90)

    for rule in all_rules:
        if rule.id not in audit_log.rules_applied:
            yield StaleRuleWarning(
                rule_id=rule.id,
                last_applied=audit_log.get_last_application(rule.id),
                recommendation="Review for removal or refinement"
            )
```

Surface stale rules in the weekly briefing (push-based, not pull-based).

#### Mechanism 2: Effectiveness Scoring

Track each rule's true positive rate, false positive rate, and impact:

```python
@dataclass
class RuleEffectiveness:
    rule_id: str
    true_positives: int    # Correctly blocked violations
    false_positives: int   # Incorrectly blocked legitimate actions
    true_negatives: int    # Correctly allowed legitimate actions
    false_negatives: int   # Missed real violations (detected by drift detector)
    impact_score: float    # How many negative outcomes did this rule prevent?
```

Rules with high false positive rates should be refined. Rules with high false negative rates should be strengthened. Rules with zero true positives and zero false negatives for 90 days should be reviewed for removal.

#### Mechanism 3: Quarterly Axiom Review

The axioms themselves should be reviewed quarterly. The review process:

1. **Automated report**: Generate a summary of axiom health — violation rates, precedent outcomes, dimension scores, stale rules, effectiveness scores
2. **LLM analysis**: "Given these metrics, are the axioms still serving their purpose? Are any implications over- or under-enforced?"
3. **Operator review**: Human reads the report and decides what to change
4. **Record the review**: The fact that a review happened (and what was decided) is itself a precedent

**Cadence**: Quarterly is the right interval. Monthly is too frequent for stable axioms. Annually is too infrequent for a rapidly evolving system. Quarterly matches corporate governance review cycles and gives enough time for trends to emerge.

#### Mechanism 4: Anti-Gaming

The governance system should detect patterns that suggest gaming:

- Agent consistently writes code that *barely* passes pattern matching
- Agent uses synonyms or obfuscations to avoid regex detection
- Agent splits changes across multiple small commits to avoid diff size limits
- Agent adds comments that explain why a change is "compliant" without actually being compliant

Detection: The drift detector's LLM semantic audit is the primary anti-gaming mechanism. Pattern matching can be gamed; semantic analysis is harder to game. The session accumulator (cross-file axiom check) provides additional coverage.

#### Mechanism 5: The Non-Negotiable Boundary

**The governance system must not be able to modify itself autonomously.** This is the meta-governance bright line:

- Changes to axiom definitions: human only
- Changes to T0 implications: human only
- Changes to VetoChain predicates: human only
- Changes to PreToolUse hook logic: human only
- Changes to PrecedentStore authority hierarchy: human only

Changes to T1-T3 implications, detection patterns, and advisory rules can be proposed by agents but require human approval. This matches the modification classification matrix from the self-healing systems research.

---

## 6. Cross-Layer Governance Patterns

### The Three Layers

```
Layer 1: Self-Correction (Reactive CI)
  - Trigger: CI failure, lint error, type error
  - Actions: auto-fix, auto-review, conditional auto-merge
  - Timescale: minutes

Layer 2: Self-Development (Proactive SDLC)
  - Trigger: issue triage, feature request, architecture decision
  - Actions: issue-to-PR, adversarial review, axiom-gated merge
  - Timescale: hours to days

Layer 3: Self-Improvement (Continuous)
  - Trigger: regression detection, drift detection, coverage gap
  - Actions: auto-revert, hotfix generation, test generation, refactor PR
  - Timescale: days to weeks
```

### Universal Cross-Cutting Patterns

#### Pattern 1: Escalation After N Failures

```
Attempt automated resolution (max N times)
  -> If resolved: log success, update knowledge base
  -> If not resolved after N attempts: escalate to human
  -> Never attempt N+1 without human approval
```

This applies identically across all three layers:
- Layer 1: Auto-fix lint error, max 2 attempts, then label "needs-human"
- Layer 2: Author/reviewer loop, max 2 rounds, then escalate
- Layer 3: Auto-revert, max 1 attempt, then create incident for human

**Implementation**: A universal `CircuitBreaker` that tracks attempts per (layer, action_type, target):

```python
class GovernanceCircuitBreaker:
    def __init__(self, max_attempts: int = 2, cooldown_hours: int = 24):
        self.max_attempts = max_attempts
        self.cooldown = timedelta(hours=cooldown_hours)

    def can_attempt(self, layer: str, action: str, target: str) -> bool:
        key = f"{layer}:{action}:{target}"
        attempts = self.store.get_attempts(key, since=datetime.now() - self.cooldown)
        return len(attempts) < self.max_attempts

    def record_attempt(self, layer: str, action: str, target: str, outcome: str):
        self.store.append(layer, action, target, outcome, datetime.now())
```

#### Pattern 2: Soak Period Before Finalization

```
Action completes successfully
  -> Enter soak period (duration based on risk level)
  -> Monitor for regressions during soak
  -> If regression detected: auto-revert + escalate
  -> If soak period passes: finalize (merge, deploy, mark complete)
```

Soak periods by risk:
- Documentation changes: 0 (immediate)
- Config changes: 30 minutes
- Test additions: 1 hour
- Application code: 24 hours
- Infrastructure changes: 48 hours
- Governance changes: never auto-finalize

#### Pattern 3: Axiom Compliance Gate

Every automated action, regardless of layer, must pass through axiom compliance:

```
Proposed action
  -> check_fast (hot path: regex patterns, O(ms))
  -> If check_fast fails: block immediately
  -> If check_fast passes AND action is high-risk: full_check (LLM semantic analysis)
  -> If full_check fails: block with explanation
  -> If full_check passes: proceed
  -> Record decision in PrecedentStore
```

This is the VetoChain pattern, applied universally.

#### Pattern 4: Rollback-First

For any automated change that causes a regression:

```
Regression detected
  -> Revert to last known good state (git revert, config rollback, service restart)
  -> THEN investigate root cause
  -> THEN generate fix
  -> Never try to fix-forward without reverting first
```

Rationale: Fix-forward assumes the fix is correct. In an autonomous system, this assumption is dangerous. Revert-first restores safety and gives time for proper analysis.

#### Pattern 5: Audit Trail

Every automated action across all layers must produce an audit record:

```python
@dataclass
class GovernanceAuditEntry:
    timestamp: datetime
    layer: Literal["correction", "development", "improvement"]
    action: str
    target: str
    axiom_check_result: str
    precedents_consulted: list[str]
    outcome: Optional[str]  # Populated after soak period
    human_override: Optional[str]  # If human intervened
```

This is the "flight recorder" from ArbiterOS, applied across all layers.

### The Minimal Cross-Cutting Rule Set

Based on the analysis above, the minimal set of universal governance rules is:

1. **Escalate after N failures** (circuit breaker)
2. **Soak before finalize** (risk-proportional delay)
3. **Check axioms before acting** (VetoChain)
4. **Revert before fixing** (rollback-first)
5. **Log everything** (audit trail)
6. **Never self-modify oversight** (meta-governance boundary)

These 6 rules apply identically across all three layers. Layer-specific rules (diff size limits, review requirements, merge criteria) are additions, not replacements.

---

## 7. Real-World Precedent

### Legal Systems: The Closest Analog

The legal system is the most mature precedent for tiered governance with precedent-based learning:

| Legal Concept | Hapax Analog | How It Works |
|---------------|-------------|--------------|
| **Constitution** | 4 axioms | Supreme, rarely changed, broad principles |
| **Statutes** | T0 implications | Specific rules derived from principles, blocking |
| **Regulations** | T1-T3 implications | Operational rules with varying enforcement |
| **Case law / precedent** | PrecedentStore | Decisions that inform future decisions |
| **Judicial review** | Drift detector | Checking whether actions comply with the constitution |
| **Appeals court** | Operator review | Higher authority overrides lower authority |
| **Separation of powers** | Governor != governed | Enforcement separated from execution |
| **Due process** | Recovery hints | Telling the "accused" how to comply |
| **Sunset clauses** | Staleness detection | Rules that expire unless actively renewed |

The U.S. legal system demonstrates that this architecture scales:
- The Constitution has 27 amendments in 237 years (stable, principled axioms work)
- Federal statutes run to 60,000+ pages (derived implications can grow, but the principles remain stable)
- Case law provides the adaptation mechanism (precedent-based learning handles novel situations without changing the constitution)

### Regulatory Bodies: Tiered Enforcement

Financial regulators (SEC, FINRA) use tiered enforcement remarkably similar to T0-T3:

| Tier | Regulatory Action | Hapax Equivalent |
|------|------------------|------------------|
| Informational | Guidance letter | T3 advisory |
| Corrective | Consent order | T2 warning with required fix |
| Punitive | Fine or sanction | T1 escalation |
| Existential | License revocation | T0 blocking |

The FDA's drug approval process provides another model:
- Phase 1 (safety): Does the change cause harm? (T0 check)
- Phase 2 (efficacy): Does the change work? (test suite)
- Phase 3 (scale): Does it work in production? (soak period)
- Phase 4 (post-market): Long-term monitoring (drift detector)

### Organizational Governance: Board Structures

Corporate governance boards handle the meta-governance problem:

- **Board of directors** reviews governance policies quarterly (meta-governance cadence)
- **Audit committee** independently verifies compliance (drift detector)
- **Compensation committee** prevents self-dealing (the system cannot modify its own oversight)
- **Nominating committee** refreshes membership (preventing staleness)
- **Whistleblower hotline** provides a bypass for governance failures (operator override)

### DAO Governance: Automated Constitutional Systems

Decentralized Autonomous Organizations (DAOs) use on-chain governance that is structurally analogous:

- **Constitutional rules** encoded in smart contracts (immutable, like T0 axioms)
- **Governance proposals** require voting thresholds (like human review for governance changes)
- **Circuit breakers** halt execution when anomalies are detected
- **Time-locks** enforce soak periods before governance changes take effect
- **Multi-sig requirements** for high-impact changes (separation of powers)

DAOs have discovered the hard way that governance rules must be carefully balanced: too restrictive and the system becomes paralyzed (governance theater); too permissive and it becomes ungovernable (governance decay). The hapax system's 4-axiom model is well-positioned — fewer axioms than most DAO constitutions, but enforced with more sophistication.

---

## 8. Concrete Recommendations for the Hapax Governance System

### Recommendation 1: Implement Problem Class Registry

**What:** Extend axiom implications with a `problem_class` field and structured detection rules.

**Why:** Addresses recurring problem *classes* rather than individual instances. Reduces governance maintenance by encoding rules once for an entire class of issues.

**How:** Add a `problem-classes.yaml` alongside existing implication definitions. Each class specifies file patterns, content patterns, required evidence, and enforcement level. The drift detector and PreToolUse hook consume this registry.

**Effort:** Medium (2-3 sessions). **Impact:** High. **Layer:** All three.

### Recommendation 2: Add Outcome Tracking to PrecedentStore

**What:** Every precedent gets an `outcome` field populated after a configurable observation period (7 days default).

**Why:** Without outcomes, precedents record *what was decided* but not *whether it was the right decision*. This is the difference between a filing cabinet and a learning system.

**How:** Extend the PrecedentStore schema with `PrecedentOutcome`. Add a weekly job that correlates recent incidents with precedent decisions made in the prior 7 days. Surface negative-outcome precedents in the briefing.

**Effort:** Low (1 session). **Impact:** High. **Layer:** Primarily Layer 2 and 3.

### Recommendation 3: Implement Universal Circuit Breaker

**What:** A `GovernanceCircuitBreaker` class used across all three layers, tracking attempts per (layer, action_type, target) with configurable max attempts and cooldown periods.

**Why:** The "escalate after N failures" pattern is the single most important safety mechanism across all layers. Without it, automated systems can enter infinite loops.

**How:** Shared module consumed by the auto-fix workflow (Layer 1), the author/reviewer loop (Layer 2), and the auto-revert/hotfix pipeline (Layer 3). State stored in a simple JSONL file.

**Effort:** Low (1 session). **Impact:** Critical for safety. **Layer:** All three.

### Recommendation 4: Add Dimension Scorecard to Weekly Briefing

**What:** Track correctness, security, reliability, maintainability, and axiom compliance as weekly metrics with trend indicators.

**Why:** You cannot improve what you do not measure. Governance rule tuning should be data-driven, not intuition-driven.

**How:** Extend the briefing agent's data collection with dimension-specific metrics. Compare week-over-week. Flag declining dimensions.

**Effort:** Medium (2 sessions). **Impact:** Medium. **Layer:** All three (measurement enables improvement).

### Recommendation 5: Implement Quarterly Axiom Review Process

**What:** A push-based quarterly review that generates an automated governance health report and presents it to the operator.

**Why:** Prevents governance staleness and over-restriction. The review should be automated enough that the operator only needs to read and decide, not gather data.

**How:** A systemd timer that fires quarterly, runs an LLM analysis over governance metrics (violation rates, false positive rates, staleness, precedent outcomes), and generates a structured report. Delivered via the notification system (ntfy), not a pull-based cockpit.

**Effort:** Medium (2 sessions). **Impact:** High for long-term governance health. **Layer:** Meta-governance.

### Recommendation 6: Implement Constitutional Merge Gates

**What:** Axiom compliance as a required CI check alongside tests and lint, using the existing `check_fast` for hot-path and `full_check` for PRs touching sensitive paths.

**Why:** This is the bridge between governance and SDLC automation. Without merge gates, governance only catches violations post-merge (drift detector) or pre-write (hooks). The merge gate covers the critical commit-to-main transition.

**How:** GitHub Action workflow that runs axiom compliance check on PR diffs. Uses the existing pattern registry. Blocks merge on T0 violations. Posts advisory comments on T1 violations.

**Effort:** Medium (2-3 sessions). **Impact:** High. **Layer:** Primarily Layer 2.

### Recommendation 7: Implement Graduated Autonomy Matrix

**What:** A matrix defining what autonomous actions are allowed at each confidence level, with governance rules that relax as confidence builds and tighten on regression.

**Why:** The system should start conservative (human review for everything) and gradually allow more autonomy as track record builds. If a regression occurs, autonomy should automatically tighten.

**How:**

```
Confidence Level 1 (initial): Human review required for all changes
Confidence Level 2 (after 20 successful auto-fixes): Auto-merge doc-only changes
Confidence Level 3 (after 50 successful, <5% revert rate): Auto-merge config + test changes
Confidence Level 4 (after 100 successful, <2% revert rate): Auto-merge small code changes (<20 lines)
Confidence Level 5 (aspirational): Auto-merge any change that passes all gates + soak period

Regression trigger: Any auto-merged change that is later reverted drops confidence by 1 level
```

**Effort:** Medium (2 sessions). **Impact:** High for enabling safe autonomy. **Layer:** All three.

---

## Summary: The Governance Stack for Self-Improving Software

```
┌─────────────────────────────────────────────────────────┐
│                   META-GOVERNANCE                        │
│  Quarterly review, staleness detection, effectiveness    │
│  scoring, anti-gaming detection                          │
│  Rule: The system MUST NOT modify its own oversight      │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│              CONSTITUTIONAL LAYER (4 Axioms)             │
│  single_user | executive_function | corporate_boundary   │
│  management_governance                                   │
│  Enforcement: T0 blocking | T1-T3 advisory               │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│              CROSS-CUTTING GOVERNANCE                    │
│  Circuit breaker | Soak period | Rollback-first          │
│  Audit trail | Axiom compliance gate                     │
│  Applied identically across all 3 layers                 │
└────────┬────────────────┬───────────────┬───────────────┘
         │                │               │
┌────────▼──────┐ ┌───────▼──────┐ ┌──────▼──────────┐
│   LAYER 1     │ │   LAYER 2    │ │   LAYER 3       │
│ Self-         │ │ Self-        │ │ Self-            │
│ Correction    │ │ Development  │ │ Improvement      │
│               │ │              │ │                  │
│ Auto-fix CI   │ │ Issue-to-PR  │ │ Auto-revert      │
│ Auto-review   │ │ Adversarial  │ │ Hotfix gen       │
│ Cond. merge   │ │ review       │ │ Drift->refactor  │
│               │ │ Axiom-gated  │ │ Test generation  │
│               │ │ merge        │ │ Learning loop    │
│ Minutes       │ │ Hours-Days   │ │ Days-Weeks       │
└───────────────┘ └──────────────┘ └─────────────────┘
         │                │               │
┌────────▼────────────────▼───────────────▼───────────────┐
│              FEEDBACK & LEARNING                         │
│  PrecedentStore (with outcome tracking)                  │
│  Problem Class Registry (class-level rules)              │
│  Dimension Scorecard (multi-dimensional improvement)     │
│  Incident Knowledge Base (structured failure/fix pairs)  │
│  Graduated Autonomy Matrix (confidence-based relaxation) │
└─────────────────────────────────────────────────────────┘
```

The key insight is that constitutional governance is not a constraint on self-improvement — it is the *mechanism* that makes self-improvement safe. Without governance, autonomous systems drift, oscillate, or diverge. With governance, they can improve within bounds, learn from outcomes, and gradually expand their autonomy as they earn trust.

The hapax system is uniquely positioned because it already has the foundational infrastructure: 4 well-chosen axioms, tiered enforcement, VetoChain, PrecedentStore, structured health checks, and a drift detector. The gap is connecting these into closed feedback loops that drive continuous improvement rather than just continuous monitoring.

---

## Sources

### Academic Papers
- [Constitutional AI: Harmlessness from AI Feedback (Bai et al., 2022)](https://arxiv.org/abs/2212.08073)
- [C3AI: Crafting and Evaluating Constitutions for Constitutional AI (2025)](https://arxiv.org/abs/2502.15861)
- [How Effective Is Constitutional AI in Small LLMs? (2025)](https://arxiv.org/abs/2503.17365)
- [Agent Behavioral Contracts (ABC, 2026)](https://arxiv.org/abs/2602.22302)
- [Policy Compiler for Secure Agentic Systems (PCAS, 2026)](https://arxiv.org/abs/2602.16708)
- [From Craft to Constitution: ArbiterOS (2025)](https://arxiv.org/abs/2510.13857)
- [Governance-as-a-Service (GaaS, 2025)](https://arxiv.org/abs/2508.18765)
- [Self-Healing Software Systems: Lessons from Nature (2025)](https://arxiv.org/abs/2504.20093)
- [Explainable AI Tools for Legal Reasoning about Cases](https://www.sciencedirect.com/science/article/pii/S0004370223000073)
- [Algorithmic Adjudication and Constitutional AI (SMU)](https://scholar.smu.edu/scitech/vol27/iss1/3/)
- [Public Constitutional AI (Georgia Law Review)](https://georgialawreview.org/wp-content/uploads/2025/05/Abiri_Public-Constitutional-AI.pdf)

### Industry Reports and Tools
- [AI Agent Safety: Circuit Breakers for Autonomous Systems](https://www.syntaxia.com/post/ai-agent-safety-circuit-breakers-for-autonomous-systems)
- [AI Agents and Circuit Breakers in DAO Governance](https://blog.tmrwdao.com/posts/ai-agents-and-circuit-breakers-in-dao-governance)
- [Agentic AI Governance for Autonomous Systems (McKinsey)](https://www.mckinsey.com/capabilities/risk-and-resilience/our-insights/trust-in-the-age-of-agents)
- [Self-Healing Software Development (Digital.ai)](https://digital.ai/catalyst-blog/self-healing-software-development/)
- [Self-Healing AI Systems and Adaptive Autonomy](https://www.msrcosmos.com/blog/self-healing-ai-systems-and-adaptive-autonomy-the-next-evolution-of-agentic-ai/)
- [The AI Coding Technical Debt Crisis 2026-2027](https://www.pixelmojo.io/blogs/vibe-coding-technical-debt-crisis-2026-2027)
- [Understanding Self-Healing Software for Modern Systems](https://atozofsoftwareengineering.blog/2025/09/20/understanding-self-healing-software-for-modern-systems/)
- [Stack Overflow: Self-Healing Code is the Future](https://stackoverflow.blog/2023/12/28/self-healing-code-is-the-future-of-software-development/)

### Legal and Regulatory Precedent
- [AI in Global Majority Judicial Systems (Stimson Center)](https://www.stimson.org/2026/ai-in-global-majority-judicial-systems/)
- [Justitia ex machina: Impact of AI on Legal Decision-Making (2024)](https://journals.sagepub.com/doi/full/10.1177/20539517241255101)
- [From Assistant to Agent: Governing Autonomous AI (Credo AI)](https://www.credo.ai/recourseslongform/from-assistant-to-agent-navigating-the-governance-challenges-of-increasingly-autonomous-ai)
- [AIGOV @ AAAI 2026](https://aigovernance.github.io/)
- [Meta-Regulation for Generative AI Governance](https://www.sciencedirect.com/science/article/abs/pii/S0267364924000827)

### Existing Hapax Research (Internal)
- `research/axiom-governance-evaluation.md` — Design pattern analysis and comparison with 7 research systems
- `research/axiom-gap-analysis.md` — 4 gaps with concrete solutions
- `research/llm-sdlc-automation-2026.md` — Issue-to-PR, adversarial review, axiom-gated merges
- `research/llm-ci-cd-reactive-automation-2026.md` — Auto-fix, auto-review, auto-merge patterns
- `research/landscape-analysis-self-healing-systems-2026.md` — Auto-revert, hotfix generation, test generation, continuous learning
- `docs/plans/2026-03-05-axiom-governance-hardening.md` — Implementation plan for governance gap closure
