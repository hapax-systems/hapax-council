# Anthropic Claude for OSS — Hapax application

**Project:** Hapax (`github.com/ryanklee/hapax-council` + 6 sister repos)
**Status:** READY FOR OPERATOR REVIEW — channel verified; not submitted
**Deadline:** 2026-06-30
**Composed:** 2026-04-26
**Composed by:** Hapax (the project applying), assembled from substrate
**Submission packet:** `docs/applications/2026-anthropic-claude-for-oss/submission-packet.md`

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

## Submission channel — verified 2026-05-05

Anthropic's current Claude for Open Source application channel is the official
web form at `https://claude.com/contact-sales/claude-for-oss`; the Terms page
also names `https://claude.com/open-source-max`, which currently redirects to
that form. The page was last published on 2026-05-04 at 14:54:33 UTC and embeds
a HubSpot form with portal ID `23987127` and form ID
`64c4f246-3bd4-4d55-ba2b-0c2e52b4a8f2`.

Current channel constraints:

- Applications are reviewed on a rolling basis and capped at up to 10,000
  contributors.
- The benefit is six months of Claude Max 20x if approved.
- The standard maintainer track requires a public GitHub repo with 5,000+
  stars or 1M+ monthly NPM downloads plus recent commits, releases, or PR
  reviews; the page also invites applicants who maintain something the
  ecosystem quietly depends on to apply and explain the impact.
- The form requires first name, last name, email, and GitHub handle. Repository
  URL and "Other info" are optional fields.
- Submitting the form binds the applicant to Anthropic's Claude for Open Source
  terms, including the six-month benefit period, one-per-person limit,
  June 30, 2026 application expiration unless extended, and Anthropic's use of
  the applicant's GitHub profile data, name/email, and application narrative to
  administer the program.

No live submission was performed by the agent because the form requires
operator-only identity/contact fields and the act of submission accepts program
terms. The channel-specific render and operator checklist live in
`submission-packet.md`; the application state is recorded at
`~/hapax-state/applications/anthropic-cco-2026.yaml`.

## Submission process — operator gated

- **Step 1** (done): identify the current Anthropic Claude for OSS application
  channel and required form fields.
- **Step 2** (done): convert this draft into the channel-specific "Other info"
  render in `submission-packet.md`.
- **Step 3** (operator): review/edit/reject the packet, provide first name,
  last name, account email, and GitHub handle, then submit through the official
  form if approved.
- **Step 4** (pending): record the confirmation email or rejection/no-submit
  decision in `~/hapax-state/applications/anthropic-cco-2026.yaml`.
- **Step 5** (pending if rejected): publish refusal brief with the rationale per
  `feedback_full_automation_or_no_engagement`.

— Hapax (composed; pending Oudepode review)
