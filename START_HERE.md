# Start Here: Evidence-Bound Agent Work

This is the short dossier for readers arriving from the GitHub profile, a
weblog post, a research application, a funding review, or an automated repo
triage surface.

## One-Sentence Claim

Hapax Council is source-visible research/runtime for AI-agent work where task
authority, route evidence, claim review, refusal, and public egress are treated
as controls that must be inspectable.

## Why This Exists

Most agent demos ask whether an agent completed a task. Hapax asks what had to
be true before the task, during the task, and after the task for a claim-bearing
action to be justified.

That larger path includes:

- task authority and parent specification,
- route capability, quota, and model-family evidence,
- source freshness and claim support,
- refusal or hold behavior when evidence is missing,
- review, CI, merge, and publication receipts,
- public/private boundary handling for weblog, RSS, archive, support, and other
  egress channels.

The repository is valuable because those controls are visible in code, tests,
records, and generated public-surface artifacts. The value is not a pitch that
Hapax is a better generic harness. The value is that a live agent estate can be
studied as an evidence system.

## Reader Value

| Reader | What to look for | Why it matters |
|---|---|---|
| Skeptical technical readers | dispatch gates, route receipts, public-surface checks, refusal records | Concrete machinery for agent work that can be inspected and argued with. |
| Technical directors | task authority, PR gates, Reins previews, `agentgov` extraction | A pilotable way to reduce agent-delivery risk without pretending agents are banned or magically safe. |
| Researchers | claim ceilings, grounding attempts, stale-source behavior, publication refusals | Material for studying agentic claim authority and correction in a real operating environment. |
| Harness builders | capability registry, review routes, lane state, evidence ledgers | An outlier case where governance and publication are part of the mechanism, not a wrapper around it. |
| Security/privacy reviewers | redaction, egress controls, public-current receipts, support boundaries | A way to inspect where public claims fail closed. |
| Narrow-tool adopters | [agentgov](https://github.com/hapax-systems/agentgov) | A small MIT hook surface that does not require adopting the Hapax estate. |

## Review Path

If you have five minutes:

1. Read [`README.md`](README.md), especially the reader map, mechanism table,
   and public-current standard.
2. Check [`NOTICE.md`](NOTICE.md), [`SUPPORT.md`](SUPPORT.md), and
   [`CONTRIBUTING.md`](CONTRIBUTING.md) for license, support, and intake
   boundaries.
3. Skim [`docs/repo-pres/public-surface-registry.yaml`](docs/repo-pres/public-surface-registry.yaml)
   and [`scripts/check-public-surface-claims.py`](scripts/check-public-surface-claims.py)
   for how claim-bearing public surfaces are registered and checked.

If you have fifteen minutes:

1. Inspect `scripts/hapax-methodology-dispatch`, `scripts/cc-claim`, and
   `scripts/cc-close` for task authority and lane mechanics.
2. Inspect `shared/github_public_claim_gate.py` and
   `scripts/check-public-surface-claims.py` for public-claim checks.
3. Inspect `agents/publication_bus/` for publication egress and refusal paths.
4. Inspect `config/platform-capability-registry.json` and the route receipt
   scripts for capability and route evidence.

If you have an hour:

1. Follow one recent PR from task note to route evidence, tests, review, merge,
   and public-surface reconciliation.
2. Compare this repository with [agentgov](https://github.com/hapax-systems/agentgov),
   [reins](https://github.com/hapax-systems/reins), and
   [hapax-constitution](https://github.com/hapax-systems/hapax-constitution)
   to see which surfaces are adoption commons, product/front-door, governance
   spec, and live research/runtime.
3. Read [`docs/research/2026-04-28-velocity-report-evidence-baseline.md`](docs/research/2026-04-28-velocity-report-evidence-baseline.md)
   as an example of evidence-boundary reconciliation.

## Claim Ceilings

- This repository is a source-visible research/runtime case study, not a
  reusable platform, public support surface, or open-source project.
- Reins is the cockpit/read-preview product surface. Council is the live estate
  and evidence substrate behind it.
- `agentgov` is the narrow MIT adoption surface. Its rights and support posture
  do not extend to council, Reins, spine, Officium, phone, watch, coord, or
  assets.
- Claim Verification Council, route receipts, and public-surface gates are
  evidence mechanisms. They do not prove truth by themselves.
- A README, package page, or weblog post is not a freshness witness. Current
  claims require current receipts.

## Current Research Frame

The research frame is evidence-bound agent work: how a system decides what it
may claim, what it may do, what it must refuse, and what may become public
evidence.

Potential outputs include:

- replayable grounding and claim-authority cases,
- refusal and correction records,
- public-egress and publication-bus receipts,
- claim-ceiling schemas and surface contracts,
- technical reports on single-operator live grounding as an empirical safety
  instrument.

Those outputs are not automatic publication commitments. Public release depends
on source freshness, privacy/rights review, redaction, and publication-bus
receipts.

## What Not To Infer

- A single-operator live estate is not a general benchmark by itself.
- Source-visible does not mean open source, staffed support, or product access.
- Public records do not imply all internal records can or should be public.
- The system studies operational grounding and claim authority; it does not
  claim human mental states.
- Funding or citation does not create support, priority, access, influence, or
  license expansion.

## Public Anchors

- Repository: <https://github.com/hapax-systems/hapax-council>
- Governance specification: <https://github.com/hapax-systems/hapax-constitution>
- Portable hook surface: <https://github.com/hapax-systems/agentgov>
- Reins cockpit: <https://github.com/hapax-systems/reins>
- Public weblog: <https://hapax.weblog.lol/>
- Refusal Brief: <https://hapax.weblog.lol/2026/04/refusal-brief-an-automation-tractability-disclosure>
- Velocity evidence baseline: <https://hapax.weblog.lol/2026/04/hapax-velocity-report-2026-04-25>

## Search Terms

Useful terms inside this repository:

- `claim authority`
- `publication bus`
- `route authority`
- `public surface`
- `refusal`
- `freshness`
- `cc-task`
- `hapax-methodology-dispatch`
- `platform capability`
- `Reins`
