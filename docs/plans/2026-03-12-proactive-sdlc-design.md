# Proactive LLM-Driven SDLC — Design Document

**Date:** 2026-03-12
**Layer:** 2 of 3 (LLM-Driven SDLC)
**Status:** Design
**Depends on:** Layer 1 (Reactive CI) operational for 4+ weeks

---

## Problem

Currently, the operator is the sole author, reviewer, and merger of all code. LLMs assist interactively (Claude Code sessions) but don't autonomously handle the full issue → implementation → review → merge pipeline. The goal is to make the SDLC LLM-self-driven while maintaining quality through adversarial review and axiom governance.

## Goals

1. **Issue-to-PR pipeline**: GitHub issues labeled `agent-eligible` are autonomously triaged, planned, implemented, and submitted as PRs.
2. **Adversarial review**: Author and reviewer are separate LLM invocations with no shared context and diverse reasoning strategies.
3. **Axiom-gated merge**: PRs pass through constitutional axiom compliance checks before becoming merge-eligible.
4. **Full observability**: Every agent invocation traced in Langfuse with inputs, outputs, decisions, and costs.

## Non-Goals

- Fully autonomous merge without human approval (research shows 16.2% rejection rate)
- Replacing the operator for architectural decisions
- Cross-repository implementation (single-repo scope initially)
- Real-time pair programming (this is async, issue-driven)

## Critical Design Constraint

**Velocity gains are transient; technical debt increases are persistent** (Watanabe et al. 2025, 807 repos). The system must be designed to resist quality degradation:

- Adversarial review with diverse strategies (not same-model self-review)
- Mutation testing gate for generated tests
- Axiom compliance as a hard merge gate
- Human merge approval always required for application code

## Architecture

```
GitHub Issue (labeled "agent-eligible")
  │
  ▼
┌─────────────────────────────────────┐
│ Triage Agent                        │
│ • Classify: bug / feature / chore   │
│ • Estimate complexity: S / M / L    │
│ • Check axiom relevance             │
│ • Reject if L or ambiguous → human  │
└──────────────┬──────────────────────┘
               │ S/M issues only
               ▼
┌─────────────────────────────────────┐
│ Planning Agent                      │
│ • Read issue + codebase context     │
│ • Identify files to modify          │
│ • Write acceptance criteria         │
│ • Produce implementation plan       │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ Author Agent (sandboxed branch)     │
│ • Implement per plan                │
│ • Run tests locally                 │
│ • Commit + push + open PR           │
│ • Model: Claude Opus               │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ Reviewer Agent (NO shared context)  │
│ • Receives: diff + codebase + axioms│
│ • Does NOT see author's reasoning   │
│ • Model: Claude Sonnet (diverse)    │
│ • Focus: bugs, security, axiom fit  │
│ • Posts review comments on PR       │
├─────────────┬───────────────────────┤
│ APPROVED    │ CHANGES REQUESTED     │
└──────┬──────┴───────────┬───────────┘
       │                  │
       │                  ▼
       │         ┌────────────────────┐
       │         │ Fixer Agent        │
       │         │ • Receives review  │
       │         │   comments + code  │
       │         │ • Max 2 rounds     │
       │         │ • Pushes fix       │
       │         │ • Back to Reviewer │
       │         └────────────────────┘
       │                  │ (max 2 rounds exceeded)
       │                  ▼
       │         ┌────────────────────┐
       │         │ HUMAN ESCALATION   │
       │         │ Label: needs-human │
       │         └────────────────────┘
       ▼
┌─────────────────────────────────────┐
│ Axiom Gate                          │
│ • Structural: tests pass, lint pass │
│ • Semantic: LLM judge evaluates     │
│   diff against 4 constitutional     │
│   axioms                            │
│ • T0 violation → block              │
│ • T1+ violation → precedent review  │
└──────────────┬──────────────────────┘
               │ compliant
               ▼
┌─────────────────────────────────────┐
│ Human Merge Decision                │
│ • PR ready with full audit trail    │
│ • Agent conversation in PR comments │
│ • Langfuse trace link in PR body    │
│ • Operator approves or requests     │
│   changes                           │
└─────────────────────────────────────┘
```

## Agent Isolation Rules

| Principle | Rationale |
|-----------|-----------|
| Author and Reviewer use different models or prompting strategies | Homogeneous multi-agent debate provides minimal benefit over single-pass (DMAD research) |
| Reviewer receives only diff + fresh codebase context, never author's chain-of-thought | Prevents "recognizing own reasoning" bias |
| Fixer is a separate invocation from Author | Author may repeat its mistakes |
| Each invocation is stateless — all context passed in | Reproducibility and auditability |
| Max 2 review-fix rounds before human escalation | Prevents infinite loops and compute waste |

## Context Budget

| Allocation | % of Context Window | Content |
|-----------|-------------------|---------|
| System prompt + axioms + CLAUDE.md | 20% | Always loaded |
| Retrieved codebase context (Qdrant RAG) | 30% | Issue-relevant files |
| Reasoning room | 50% | Agent's working memory |

## Axiom Compliance Gate

Two-tier enforcement:

1. **Structural checks** (deterministic):
   - All CI checks pass
   - No changes to protected paths without human approval
   - Commit message format compliance
   - Diff size within bounds

2. **Semantic checks** (LLM judge):
   - Does this change align with Axiom 1 (single-user)?
   - Does it respect Axiom 2 (executive function)?
   - Does it maintain Axiom 3 (corporate boundary)?
   - Does it preserve Axiom 4 (management governance)?
   - T0 implications enforced as hard blocks
   - T1+ violations generate precedent for review

## Orchestration

State machine with explicit states and timeouts:

```
ISSUE_LABELED → TRIAGING → PLANNING → IMPLEMENTING →
  REVIEWING → {APPROVED | FIXING (max 2)} →
  AXIOM_CHECKING → READY_FOR_HUMAN →
  {MERGED | REJECTED | NEEDS_CHANGES}
```

Each transition:
- Logged to Langfuse as a span within a trace
- Has a timeout (5 min for triage, 15 min for implementation, 10 min for review)
- Has a circuit breaker (if agent errors out, escalate to human)

Implementation: GitHub Actions workflow with job dependencies, or custom orchestrator using LangGraph.

## Technology Stack

| Component | Tool | Why |
|-----------|------|-----|
| Triage/Planning | Claude Sonnet via LiteLLM | Cost-effective for classification |
| Implementation | Claude Opus via claude-code-action | Highest code quality |
| Review | Claude Sonnet (different system prompt) | Diverse reasoning strategy |
| Axiom gate (semantic) | Claude Haiku via LiteLLM | Fast, cheap, focused evaluation |
| Context retrieval | Qdrant (nomic 768d) | Already deployed, indexed |
| Orchestration | GitHub Actions (initially) | No new infra; migrate to LangGraph if needed |
| Observability | Langfuse (localhost:3000) | Full trace of every invocation |

## Cost Model

| Activity | Est. Cost/Run | Monthly Est. (10 issues/wk) |
|----------|--------------|---------------------------|
| Triage (Sonnet) | $0.05 | $2 |
| Planning (Sonnet) | $0.15 | $6 |
| Implementation (Opus) | $1.50-5.00 | $60-200 |
| Review (Sonnet) | $0.20-0.50 | $8-20 |
| Fix rounds (Sonnet, avg 0.5 rounds) | $0.10-0.25 | $4-10 |
| Axiom check (Haiku) | $0.02 | $1 |
| **Total** | | **$81-239/month** |

## Success Metrics

- **PR acceptance rate**: Target > 80% of agent-authored PRs merged without major rework
- **Bug introduction rate**: Post-merge defects from agent PRs vs human PRs
- **Review round count**: Average rounds before approval (target < 1.5)
- **Axiom compliance rate**: % of PRs passing axiom gate on first attempt
- **Human override rate**: % of agent decisions overridden by operator
- **Time to merge**: Issue labeled to PR merged
- **Technical debt metrics**: Ruff warnings, pyright errors, test mutation score — must not increase

## Risks

| Risk | Mitigation |
|------|-----------|
| Agent implements wrong thing | Triage filters to S/M issues; planning produces explicit acceptance criteria |
| Adversarial review misses bugs | Human merge approval always required; test suite as safety net |
| Technical debt accumulation | Mutation testing gate; ruff/pyright error count tracking; periodic human audit |
| Cost overruns | Model selection by task; max-turns caps; monthly budget alerts |
| Axiom gaming (LLM finds loopholes) | Human reviews all precedents; supremacy validation prevents override |
| Context window overflow | 30% retrieval budget; repo map for navigation; agentic RAG |

## Prerequisites

1. Layer 1 (Reactive CI) operational for 4+ weeks with stable metrics
2. `ANTHROPIC_API_KEY` in repo secrets (shared with Layer 1)
3. Qdrant codebase index populated and accessible from CI
4. Axiom enforcement module (`shared/axiom_enforcement.py`) stable
5. Langfuse accessible from GitHub Actions runners (or trace export configured)

## Rollout Strategy

1. **Week 1-2**: Triage-only mode. Agent labels issues, does not implement. Human validates triage quality.
2. **Week 3-4**: Planning mode. Agent produces plans, human reviews before implementation.
3. **Week 5-8**: Full pipeline on `chore` issues only (dependency bumps, doc fixes, test additions).
4. **Week 9-12**: Expand to `bug` issues (small/medium only).
5. **Week 13+**: Evaluate feature implementation based on accumulated metrics.
