---
Date: 2026-05-11
Title: Constitutional Governance for AI Agents: Beyond Prompt Engineering
Type: post
Location: /weblog
Tags: ai-governance, constitutional-ai, autonomous-agents, agent-architecture
Slug: constitutional-governance-beyond-prompt-engineering
---

# Constitutional Governance for AI Agents: Beyond Prompt Engineering

Your AI agent's system prompt is not a governance system. It's a suggestion box.

I've spent the last eighteen months building a system where autonomous AI agents — Claude Code, Codex, Gemini CLI — produce code 24 hours a day. They've merged thousands of pull requests. The revert rate is under 0.3%. And the thing that makes it work has nothing to do with careful prompting.

It has to do with constitutions.

## The Prohibition Treadmill

Every production AI agent deployment eventually discovers the same problem: the agent does something you didn't anticipate. It persists behavioral data about a colleague. It generates coaching language from calendar patterns. It infers emotional state from response latency. None of these were prohibited, because none of them existed when you wrote the prohibitions.

The standard response is to add a rule. "Don't infer emotional state." "Don't generate coaching language." "Don't persist behavioral patterns about team members." Each incident produces a new prohibition. The prohibition list grows. It never converges.

This is the **prohibition treadmill**, and it has three failure modes that no amount of careful enumeration can fix:

**Latent uncovered space.** Your rules cover what has already gone wrong. The agent generates behaviors that have never gone wrong before. The rules say nothing about them. Worse, an agent that correctly observes "no rule prohibits this" may treat the absence as permission.

**Combinatorial brittleness.** Rules accumulated by incident cluster by violation type, not by underlying value. Two rules may forbid related behaviors for unrelated reasons. When a third behavior combines features of both, the rules give no consistent answer because they share no common ground.

**No principled override.** When a legitimate edge case genuinely requires the rule to bend — a debugging scenario, a research task, an explicit operator override — the rule offers no provision for its own suspension. Either it's rigid and blocks legitimate work, or it's bypassed and its authority erodes.

## Constitutive vs. Regulative

The alternative comes from legal theory, and it's a distinction that matters: **constitutive** rules versus **regulative** rules.

A regulative rule presupposes the activity it regulates. "Drive on the right" presupposes driving. A constitutive rule defines an activity that doesn't exist without the rule. "Checkmate" isn't something you can do without the rules of chess.

The prohibition treadmill produces regulative rules. Each one says "don't do X" about an activity the system already performed. The constitutive alternative says "here's what counts as operator data, what counts as consent-bound data, what counts as work-domain data." Once those classifications exist, behavioral constraints derive mechanically. You don't need a rule for every possible violation — you need a classification scheme that makes violations recognizable.

## Five Axioms, Not Fifty Rules

The system I built holds five axioms. That's the entire constitution:

1. **single_user** (weight 100): This system has exactly one operator. All decisions respect that. No authentication, no roles, no multi-tenant abstractions.

2. **executive_function** (weight 95): The system exists to externalize cognitive work for an operator with ADHD and autism. Every feature must compensate for executive function challenges, not add to cognitive load.

3. **corporate_boundary** (weight 90): Home infrastructure and employer infrastructure are separate substrates. Data doesn't cross the boundary without explicit routing.

4. **interpersonal_transparency** (weight 88): No persistent state about non-operator persons without an active consent contract. Opt-in, inspectable, revocable, purge-on-revoke.

5. **management_governance** (weight 85): The system aggregates signals and prepares context. It never generates language about individual people. LLMs prepare; humans deliver.

The weights resolve conflicts. When two axioms disagree, the higher weight wins. In eighteen months of operation, the hierarchy has resolved every conflict without operator escalation.

These axioms are short enough to memorize. The operator memorized the text, the weights, and the scopes within a week. This is by design. If your governance document requires a reference manual, it has the wrong shape.

## How Axioms Become Enforcement

The axioms alone are too abstract to hand to an agent. The system derives approximately ninety concrete implications from the five axioms, each traced back to its constitutional ground.

Here's how one derivation works:

**interpersonal_transparency** says: no persistent state about non-operator persons without a consent contract.

The literal reading produces four invariants: explicit opt-in, inspection access, revocability, purge-on-revoke. These become database gates — every write to a person-adjacent collection must pass a consent check. Fail-closed.

But the literal reading would also forbid voice activity detection on the operator's microphone — a visitor's voice might be transient state. So a **defeater** is derived: transient environmental perception doesn't require a contract, provided no persistent state about a specific identified person results. The general rule holds; the specific exception preserves the rule's purpose.

The derivation process resembles common law more than statutory code. When a new case arises — a new publication surface, a new perception modality — the question isn't "have we written a rule for this?" It's "which axiom does this fall under, and what would the existing precedents produce?"

New implications are derived deliberately (operator review, multiple LLM consistency checks, commit), not accumulated by silent LLM improvisation. The implication set grows sub-linearly: most new cases match existing implications rather than requiring new ones.

## Four Enforcement Tiers

Not every rule should block with the same force. The system uses four tiers:

**T0 — Regimentation.** The violation is structurally impossible. A hook rejects any commit containing `RateLimiter` (a multi-user primitive) and suggests `QuotaBucket` (single-tenant). The code can't express the violation.

**T1 — Boundary enforcement.** The rule fires at a specific architectural boundary. Every Qdrant write to a person-adjacent collection passes through a consent gate. The code can be written; the database write is refused at the boundary.

**T2 — Monitoring.** The rule observes and reports. A monthly timer checks CLAUDE.md files against rotation thresholds and notifies the operator. The system continues; the operator decides.

**T3 — Advisory.** Lint-level suggestions. A CI gate flags polysemic terms that might be misread across registers. The operator rewrites or acknowledges.

The four tiers map to a spectrum of enforcement strength. Multi-user primitives in source code are high-cost violations with low false-positive rates: T0 is correct. A polysemic term in a draft is low-cost (correctable anytime) with high false-positive rates: T3 is correct.

## What This Looks Like in Practice

Three concrete cases where the constitutional framing was load-bearing:

**The redaction registry.** Sixteen publication surfaces each needed different field redactions. The inline approach produced duplicated patterns and a silent no-op when a transform name drifted during a rename. The axiom derivation traced redaction discipline to interpersonal_transparency, produced a centralized RedactionTransform registry, and a CI linter that catches name drift at PR time. The constitutive framing made the solution architecturally discoverable.

**The operator-referent leak.** Eight omg.lol publisher surfaces used the operator's legal name in attribution. The single_user axiom's non-formal-referent policy required rewriting to non-formal forms. The same derivation process that produced the redaction discipline for non-operator fields produced the leak guard for operator attribution.

**Worktree isolation.** Subagent commits were being lost when temporary worktrees were cleaned up. The single_user axiom's textualist reading — there are no workmates to recover lost code from — produced a binding precedent: subagent code that must persist must not live in an isolated worktree. The precedent propagates to every subagent dispatch without further LLM deliberation.

Each case follows the same shape: a concrete problem arose; the axiom derivation produced a structural solution; the structural solution is more robust than the procedural one because it propagates to every code path that touches the boundary.

## What This Is Not

This is not a universal framework. The system is single-operator by axiom — the constitution would be wrong for multi-tenant deployment. It's not a product pitch. The substrate is open source; the approach is replicable, but the specific axioms are personal.

The advisory tiers (T2/T3) can be bypassed by the operator. In a single-operator system, this is appropriate — the operator is the constitutional authority. In a multi-operator system, it would be a weakness.

The defeasibility framework is expressed in prose, not in formal logic. The full apparatus of defeasible reasoning — preference orders, attack relations, dialogue trees — is referenced but not compiled. Future work could tighten this.

## The Point

The distinction between constitutive and regulative governance is not academic. It determines whether your agent governance scales or drowns.

A regulative system grows linearly with violations observed. Every incident adds a rule. The rule set never converges.

A constitutive system grows sub-linearly. Most new cases match existing classifications. The five-axiom frame hasn't been amended in eighteen months; the implication set has expanded to cover new surfaces under the existing frame.

If you're building autonomous AI agents and your governance approach is "write better system prompts" — you're on the prohibition treadmill. The exit is upstream: define what counts, not what's forbidden.

The classifications are small. The derivations are mechanical. The enforcement is structural.

That's the constitutional difference.

---

*This is the first in a series on the engineering decisions behind Hapax, a single-operator cognitive infrastructure running autonomous AI agents. The system, its governance framework, and its deployment record are open source.*
