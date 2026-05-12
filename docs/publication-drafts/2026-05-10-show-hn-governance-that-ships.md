---
Date: 2026-05-10
Title: Show HN: 3,000 PRs in 60 Days with Zero Governance Failures
Type: post
Location: /weblog
Tags: ai-governance, claude-code, autonomous-agents, show-hn
Slug: show-hn-governance-that-ships
---

# Show HN: 3,000 PRs in 60 Days with Zero Governance Failures

I run a fleet of autonomous AI agents — Claude Code, Codex, Gemini CLI — building a system 24 hours a day. They've merged over 3,000 pull requests in 60 days. The revert rate is 0.16%.

That number should make you suspicious. It makes me suspicious too. So here's how it works.

## The Problem Nobody Talks About

Every serious AI agent deployment has the same dirty secret: the agent is one ambiguous prompt away from doing something catastrophic. Delete production data. Commit secrets. Push force to main. Merge its own PR without review.

The standard defense is vibes. "Be careful." "Don't do dangerous things." "Ask before destructive operations." This is the system prompt as seatbelt — it works until it doesn't, and when it doesn't, you find out the hard way.

Prompt-based governance has three fatal flaws:

1. **It's advisory.** The model can ignore any instruction in a system prompt. There is no enforcement mechanism.
2. **It doesn't compose.** When you spawn subagents, your carefully crafted instructions don't propagate. The subagent is a blank slate with sudo access.
3. **It can't say no.** A system prompt can suggest the agent should refuse. It cannot mechanically prevent the agent from complying.

## What We Built

We built mechanical enforcement. Not guidelines — gates.

The system has five constitutional axioms, weighted 85–100, that constrain every action an agent takes. These aren't prompt decorations. They're enforced by 44 hook scripts that intercept tool calls before execution and block violations at the shell level.

Here's what that means concretely:

**Before an agent creates a git branch**, a hook checks whether unmerged branches exist. If they do, the branch creation is blocked — not warned, blocked. The agent physically cannot create a new branch until prior work is resolved.

**Before an agent pushes code**, a hook verifies that tests were run. No test results, no push.

**Before an agent writes to any file**, a hook scans for PII patterns. Social security numbers, email addresses, API keys — if the content matches, the write is refused.

**Before an agent edits code on a feature branch**, a hook checks whether there's already an open PR for that branch. If there is, the edit is blocked until the PR is resolved. This prevents the "infinite WIP" failure mode where agents pile changes onto branches that are already under review.

These hooks run outside the model. The model doesn't get to evaluate whether the hook's concern is legitimate. The hook runs, the hook decides, the hook blocks or allows. The model then works within whatever constraints the hook imposed.

## The Data

Here's what 60 days of mechanically enforced governance produces:

| Metric | Value |
|--------|-------|
| Total pull requests | 3,034 |
| Merged | 2,869 |
| Reverts | 5 |
| Revert rate | 0.16% |
| Days | 60 |
| PRs per day | ~48 |
| Human operators | 1 |
| Concurrent agent sessions | up to 12 |
| Hook scripts | 44 |
| Constitutional axioms | 5 |
| Test files | 2,158 |
| Refused publication surfaces | 12 |
| Refusal briefs (documented) | 48 |

The revert rate deserves scrutiny. Five reverts in 3,034 PRs. All five were audio routing changes where the live system behaved differently from the test environment. None were governance failures — they were domain-specific integration surprises that couldn't be caught by pre-merge testing alone.

Zero reverts were caused by: agents merging broken code, agents pushing to the wrong branch, agents committing secrets, agents bypassing review, or agents doing something they were told not to do.

The hook system didn't just prevent failures — it shaped agent behavior. When an agent hits a `no-stale-branches` block, it doesn't retry the same command. It reads the error, identifies the blocking branches, and cleans them up. The constraint becomes a workflow. After 3,000 PRs, the agents have internalized the governance patterns so thoroughly that hooks fire less frequently now than they did in week one.

## The Trust Angle

This is a system that is constitutionally incapable of certain failures. Not unlikely to fail — incapable.

An agent in this system cannot push code without running tests. Not "shouldn't" — cannot. The hook intercepts the git push and returns an error. There is no prompt that overrides this. There is no system message that bypasses it. The enforcement layer sits below the model's decision-making entirely.

This is a fundamentally different trust model than "we prompted the AI to be careful." It's closer to how we trust bridges: not because the engineer promised to be careful, but because the physics of steel and concrete enforce load limits whether the engineer is paying attention or not.

The system also documents what it refuses to do. We maintain 48 refusal briefs — formal records of platforms and actions the system has evaluated and declined. Reddit, Discord, LinkedIn, Twitter/X, Wikipedia — each has a documented refusal with the specific axiom violation that prevents engagement. The system doesn't silently ignore these platforms. It records *why* it refuses, so the refusal is auditable.

The refused surfaces list is arguably more interesting than the capabilities list. A system that can explain what it won't do, and why, is a system you can reason about.

## The Tool

We're publishing the hook-based governance system as a standalone open-source package: **hapax-agentgov**. It is a `pip install hapax-agentgov` away from adding mechanical enforcement to any Claude Code, Codex, or similar agent deployment. The import and CLI command remain `agentgov`.

The core idea is simple: hooks intercept tool calls. You write shell scripts that check preconditions. If the precondition fails, the tool call is blocked. The agent receives the error and adapts.

No prompt engineering required. No model-specific tuning. The enforcement layer is model-agnostic because it operates at the shell level, below any model's decision-making.

Repository: [github.com/hapax-systems/agentgov](https://github.com/hapax-systems/agentgov)

## Live Evidence

The production system is built to publish live evidence, but public live egress is readiness-gated. Right now the YouTube/OBS gate is red, so this post does not claim an active livestream as evidence.

The same governed fleet builds the production compositor, camera pipeline, audio routing, overlay system, publication bus, and GitHub workflow. When the public egress gate is green, the live channel becomes current evidence again; until then, the repository, PyPI package, weblog, and CI history are the public record.

## What's Next

We're writing this up for CHI 2027 as a case study in constitutional AI governance for autonomous development agents. The core claim: mechanical enforcement produces qualitatively different trust properties than prompt-based governance, and the empirical evidence from 3,000+ PRs supports this.

The practical question isn't whether AI agents should have governance. It's whether governance should be advisory (prompts) or mechanical (hooks). After 60 days, we have a strong opinion: if you can enforce it mechanically, you should. Prompts are for preferences. Hooks are for invariants.

---

*Built by one person and a fleet of governed agents. All code, infrastructure, and governance mechanisms described here are running in production.*
