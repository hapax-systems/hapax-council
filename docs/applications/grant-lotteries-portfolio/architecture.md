# Grant Lotteries Portfolio — Architecture

**cc-task:** `leverage-vector-grant-lotteries-portfolio` (WSJF 4.5)
**Composed:** 2026-04-26

## Premise

Several research-funding programs explicitly use partial randomisation for marginal-acceptance decisions, treating evaluator subjectivity as a noise term and resolving the long tail of "good-but-not-distinctive" applications by lottery. Submitting a portfolio of applications to such programs has expected-value properties that single-application targeting does not — many small bets at uncorrelated lotteries beat one large bet at a correlated peer-review process.

This architecture identifies the candidate programs, the per-program submission shape, and the daemon-tractable composition path that reuses the cco-application + msr-paper draft substrate already shipped (PRs #1684, #1686).

## Candidate programs (research required for current cycles)

The following programs are documented as using partial randomisation in 2024–2025; current 2026 cycles need verification before submission. Each row is a *candidate*, not a confirmed-open call.

| Program | Country | Mechanism | Suited for | Verify status |
|---|---|---|---|---|
| **HRC New Zealand Explorer Grants** | NZ | Lottery on top X% by quality threshold | Single-investigator infra projects | Annual cycle; check current dates |
| **NFRF Exploration (Tri-Council)** | Canada | Random allocation across pre-screened applicants | Cross-disciplinary research with high-risk/reward profile | Annual; spring cycle |
| **British Academy / Leverhulme small grants** | UK | Some weighted-lottery elements at marginal-tier decisions | Humanities / interdisciplinary | Multiple cycles per year |
| **Volkswagen Foundation Lichtenberg / Experiment!** | Germany | Explicit lottery for "Experiment!" call | Bold/risky research | Periodic — ~biennial |
| **Future of Life Institute (FLI) — General Support** | International | Open submissions, partial randomisation in shortlist | AI safety + governance work | Continuous |
| **Open Philanthropy — discretionary grants** | International | Some randomisation in independent-researcher track | Independent research with public-good aspect | Continuous |

## Hapax-specific application angles

Each program's standard "we need a project" framing is satisfied by Hapax's existing surface in different ways:

- **HRC NZ Explorer**: Hapax as single-investigator distributed-infrastructure project demonstrating new modes of human-AI cognitive collaboration. Velocity findings + refusal-as-data substrate are the novel-contribution claim.
- **NFRF Exploration**: cross-disciplinary by construction (CS-HCI + science studies + governance). The constitutional-LLM-collaboration framing fits the "high-risk/reward" rubric.
- **British Academy / Leverhulme**: refusal-as-data has direct humanities-research relevance (epistemology of absence). The CC BY-NC-ND 4.0 hapax-constitution surface is the deposit substrate.
- **Volkswagen Experiment!**: full-automation-or-no-engagement is a bold methodological claim suited to "Experiment!" framing.
- **FLI General Support**: AI safety work via constitutional governance + refusal-as-data is direct fit.
- **Open Philanthropy — independent track**: demonstrably-public-good (CC-BY-NC-ND constitution + open citation graph) + independent-research posture.

## Composition approach

Per `feedback_full_automation_or_no_engagement`: each application's daemon-tractable composition path reuses the cco-application substrate (PR #1684) with per-program section reordering + emphasis adjustment, NOT a from-scratch rewrite per application. The same `agents/composer/` infra (still pending — see cco-application architecture) handles all of them.

A `compose-grant-lottery-application.py` script, modeled on `scripts/build-velocity-findings-preprint.py` (PR #1677), takes a per-program YAML config and a substrate-pointer set, emits a `PreprintArtifact` (or appropriate publisher-kit subclass shape) into the orchestrator inbox.

## Per-program YAML config shape

```yaml
# config/grant-lotteries/hrc-nz-explorer.yaml
program: hrc-nz-explorer
program_url: https://hrc.govt.nz/grants-funding/explorer-grants/
randomisation_mechanism: top-percentile-lottery
deadline: <ISO date>
max_words: 1500
required_sections:
  - lay_summary
  - methodology
  - timeline
  - budget
substrate_emphasis:
  - velocity-findings  # Use the velocity preprint as headline evidence
  - refusal-as-data    # Frame as novel methodology
substrate_deemphasise:
  - constitutional-LLM-collaboration  # Less suited to HRC's biomedical lean
operator_action_required:
  - Sign declaration of single-investigator status
  - Provide ORCID iD at submission time
```

## 6-component shipping plan

| # | Component | Path | Effort |
|---|---|---|---|
| 0 | This architecture doc | shipped here | 30 min |
| 1 | Per-program research drop confirming current-cycle dates | `docs/research/2026-04-XX-grant-lottery-cycles-2026.md` | 2-3h research-agent dispatch |
| 2 | Per-program YAML configs | `config/grant-lotteries/*.yaml` | 1-2h |
| 3 | Composer script | `scripts/compose-grant-lottery-application.py` | 2h (built on velocity-findings composer pattern) |
| 4 | Per-application draft content (substrate-driven) | `docs/applications/grant-lotteries/<program>/draft.md` × N | 2-3h per program |
| 5 | Submission daemon (operator-mediated for portals; daemon for email) | `agents/grant_lottery_daemon/` | 4-6h |

**Daemon-tractable scope:** ~9-13h infra + N × 2-3h per program. Submission step is operator-mediated for any program with a web-form portal; daemon-tractable for email-driven programs.

## Constitutional posture

- `feedback_full_automation_or_no_engagement`: composition is daemon-tractable; submission is operator-mediated only when the channel is operator-mediated by program design.
- `feedback_co_publishing_auto_only_unsettled_contribution`: applications credit Hapax + Claude Code as co-authors per the canonical pattern.
- `feedback_no_operator_approval_waits`: per-application drafts ship without per-application operator review; operator reviews the BUNDLE at submission time per their own cadence.
- Refusal-as-data: any rejection is published as a refusal brief with a stable slug for citation-graph cross-reference. Lotteries explicitly invite rejection as the modal outcome; the substrate is built for it.

## Cross-references

- Anthropic CCO application (template substrate): `docs/applications/2026-anthropic-claude-for-oss/draft.md` (PR #1684)
- MSR 2026 dataset paper architecture: `docs/applications/2026-msr-dataset-paper/architecture.md` (PR #1686)
- Velocity findings (substrate evidence): `docs/research/2026-04-25-velocity-comparison.md` + Zenodo deposit `velocity-findings-2026-04-25` (PR #1677)
- License matrix for per-program license declarations: `docs/repo-pres/repo-registry.yaml` (PR #1679)
- Refusal-as-data substrate for rejected applications: `agents/publication_bus/refusal_brief_publisher.py`

— alpha
