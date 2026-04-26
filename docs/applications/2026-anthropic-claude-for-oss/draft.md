# Anthropic Claude for OSS — Hapax application

**Project:** Hapax (`github.com/ryanklee/hapax-council` + 6 sister repos)
**Status:** DRAFT — pending operator review + submission
**Deadline:** 2026-06-30
**Composed:** 2026-04-26
**Composed by:** Hapax (the project applying), assembled from substrate

---

## Project description (one paragraph)

Hapax is single-operator infrastructure for externalised executive function. Four concurrent Claude Code sessions coordinate via filesystem-as-bus reactive rules — no coordinator agent, no inter-session message passing. The system runs ~200 production agents (voice daemon, studio compositor, reactive engine, governance gates) on a single workstation, gated by a 5-axiom constitution (`hapax-constitution`) that includes `interpersonal_transparency` (no persistent state about non-operator persons without consent), `single_user` (no auth, no roles, no multi-user code), and `feedback_full_automation_or_no_engagement` (surfaces that cannot be daemon-tractable end-to-end are refused entirely, with the refusal published as data via Zenodo deposits with citation-graph cross-references). Recent 18-hour velocity sample: 30 PRs/day, 137 commits/day, ~33,500 LOC churn/day, 5.9 sustained research drops/day over 45 days, 21.8% formalised REFUSED-status work-state items. Full velocity findings: `docs/research/2026-04-25-velocity-comparison.md` and `velocity-findings-2026-04-25` Zenodo deposit (DOI pending).

## Why Hapax qualifies for Claude for OSS

### 1. Open source posture (with explicit per-repo policy)

All 7 pushable repos publish under one of three licenses per the canonical matrix at `docs/repo-pres/repo-registry.yaml`:
- **PolyForm Strict 1.0.0** — runtime code (council, officium, watch, phone, distro-work). Single-operator stance preserved; commercial-use requires explicit license.
- **MIT** — `hapax-mcp` only (MCP-ecosystem norm; downstream MCP clients require permissive license to integrate).
- **CC BY-NC-ND 4.0** — `hapax-constitution` (specification / docs).

AGPL-3 is explicitly flagged as anti-pattern (assumes downstream contributors, contradicting `single_user`). Per-repo divergence is settled in source — no ad-hoc license drift.

### 2. Demonstrably critical-infrastructure use of Claude

- **Grounded LLM tier**: governance, routing, voice cognition, audit dispatch, and several content-pipeline stages route through Claude (Sonnet for `balanced`, Opus for capable-tier). The `feedback_director_grounding` directive pins the livestream director to Claude's grounded model under speed pressure — fix latency via quant/prompt changes, not by swapping models.
- **Multi-session coordination**: 4 concurrent Claude Code sessions (alpha, beta, delta, epsilon, plus an auxiliary gamma research lane) run continuously on max-effort routing. The 18-hour velocity sample above is the lower-bound observation; sustained operation includes overnight autonomous cycles per `feedback_autonomous_overnight_2026_04_26`.
- **Refusal-as-data substrate**: `agents/publication_bus/refusal_brief_publisher.py` mints Zenodo deposits with `RelatedIdentifier` graph edges (`IsRequiredBy`, `IsObsoletedBy`) so refusals participate in the DataCite citation graph. Refused engagements (Bandcamp, Discogs, RYM, Crossref Event Data, etc.) are first-class citations rather than absences.
- **Constitutional governance via LLM-prepared / human-delivered**: `feedback_management_governance` enforces that Claude prepares analyses but humans deliver decisions about individual team members. This is published as a constitutional axiom (weight 85), not a private heuristic.

### 3. Anthropic-aligned research patterns

Several Hapax patterns are directly relevant to Anthropic's published research interests:

- **Refusal as first-class data**: rather than treating refused engagements as silent absences, Hapax publishes them as citation-graph nodes. This generalises Anthropic's RLHF refusal-quality work into a publication-bus surface.
- **Operator-referent policy** (`docs/superpowers/specs/2026-04-24-operator-referent-policy-design.md`): formal-vs-non-formal name handling enforced at the prompt-template level, with CI-gated leak detection (PR #1661). Aligns with Anthropic's persona-stability research.
- **Velocity-as-evidence**: the 18-hour sample is reproducibility-grounded — the underlying coordination substrate (filesystem-as-bus, no message passing) is the testable claim, not the velocity number itself.

## Use of credit grant

Credit grants would extend the existing routing budget for the 4 concurrent sessions plus support new research directions:

- **Continued multi-session sustained operation** at current cadence (~30 PRs/day, no operator-approval waits per `feedback_no_operator_approval_waits`)
- **arXiv preprint pipeline** (`leverage-attrib-arxiv-velocity-preprint`, architecture in `docs/research/2026-04-26-arxiv-velocity-preprint-architecture.md`): velocity-findings + future preprints depositing into Zenodo + endorser-courtship via citation-graph signal
- **MSR 2026 dataset paper**: the Hapax velocity + refusal-as-data substrates as a published dataset for software-engineering research replication
- **Anthropic Constitutional AI alignment**: Hapax's 5-axiom constitutional governance is structurally similar to CAI; a credit grant accelerates the comparative-publication work currently scoped at `leverage-vector-aaif-spec-donation`

## Constitutional commitments

If accepted, Hapax commits:
1. Continued open-source posture per the canonical license matrix above; no relicensing under the grant period.
2. Public attribution: any work product using grant credits is attributed in the Zenodo deposit's `Funder` field per the [DataCite Funder schema](https://schema.datacite.org/).
3. Reproducibility: the substrate (filesystem-as-bus + reactive rules + 4 Claude Code sessions) is documented in-repo and described in any resulting publication so other operators can replicate.
4. Refusal-as-data: any rejection of grant-renewal will itself be published as a refusal brief with the rationale, per `feedback_full_automation_or_no_engagement`.

## Operator + project metadata

- **Operator**: Oudepode (legal name reserved for the formal application form per `project_operator_referent_policy`)
- **Primary repo**: `github.com/ryanklee/hapax-council`
- **Constitution**: `github.com/ryanklee/hapax-constitution`
- **ORCID**: configured via `HAPAX_OPERATOR_ORCID` (operator-supplied at submission)
- **Hapax citation graph concept-DOI**: minted via `agents/publication_bus/datacite_mirror.py` (operator-supplied at submission once Zenodo PAT lands)

## Submission process — pending research

Anthropic's actual application channel (web form vs email vs API) is not codified in this repo as of 2026-04-26. The architecture for the submission daemon + mail-monitor confirmation parser lives in a separate doc once the submission channel is identified:

- **Step 1** (research): identify Anthropic's current Claude for OSS application channel + required submission format
- **Step 2** (compose): convert this draft to the format the channel accepts
- **Step 3** (submit): operator-mediated submission OR daemon-tractable submission per the channel's API surface
- **Step 4** (track): mail-monitor parser for the confirmation email + outcome storage at `~/hapax-state/applications/anthropic-cco-2026.yaml`
- **Step 5** (refusal-as-data on rejection): publish refusal brief with the rationale per `feedback_full_automation_or_no_engagement`

This draft is the substrate for steps 2-5; the operator review (step 1.5) determines what gets cut, expanded, or restructured before the channel-specific render.

— Hapax (composed; pending Oudepode review)
