# Cooperative AI Research Fellowship 2026 cohort 2 — Hapax application

**cc-task:** `leverage-vector-coop-ai-fellowship` (WSJF 4.5)
**Status:** DRAFT — pending operator review + submission
**Composed:** 2026-04-26
**Composed by:** Hapax (the project applying), assembled from substrate

---

## Project description (≤300 words)

Hapax is single-operator infrastructure for externalised executive function in which four concurrent Claude Code sessions coordinate via filesystem-as-bus reactive rules — no coordinator agent, no inter-session message passing. The system runs ~200 production agents (voice daemon, studio compositor, reactive engine, governance gates) on a single workstation, gated by a 5-axiom constitution (`hapax-constitution`) that includes `interpersonal_transparency` (no persistent state about non-operator persons without consent), `single_user` (no auth, no roles), and `feedback_full_automation_or_no_engagement` (surfaces that cannot be daemon-tractable end-to-end are refused entirely, with the refusal published as data via Zenodo deposits with citation-graph cross-references). Recent 18-hour velocity sample: 30 PRs/day, 137 commits/day, ~33,500 LOC churn/day. The 4-session coordination substrate is structurally cooperative-AI work — it answers the empirical question of how heterogeneously-routed LLM sessions can run in tight loops on a shared workspace without emergent coordination failures, and what the failure modes look like when they do occur. The Hapax git history (publicly available across 7 repos) is the dataset. The constitutional substrate is the alignment claim: governance constraints are first-class artifacts (axiom registry at `axioms/registry.yaml` with weighted enforcement), not implicit conventions. Submission to MSR 2026's dataset track + arXiv preprint pipeline is in flight (architecture in `docs/applications/2026-msr-dataset-paper/architecture.md`, PR #1686).

## Why Cooperative AI

The Cooperative AI Foundation's research interests — multi-agent coordination, governance under uncertainty, agent-to-agent communication channels — map directly onto Hapax's substrate:

- **Multi-agent coordination without coordinator**: 4 sessions on filesystem-as-bus, with no privileged orchestrator. Coordination emerges from inotify-driven cascade rules + relay yamls + claim files. This is the Schelling-point question recast as engineering practice.
- **Governance under uncertainty**: the 5-axiom constitution + the refusal-as-data substrate together demonstrate one approach to encoding cooperative norms in a way that survives indefinite operation. Refused engagements (Bandcamp, Discogs, RYM, Crossref Event Data, etc.) are first-class citations rather than absences.
- **Agent-to-agent communication via citation graph**: the publication-bus's `RelatedIdentifier` graph (DataCite) is the inter-agent communication substrate Hapax exposes to other agents. The x402 receive-endpoint (architecture in `docs/research/2026-04-26-x402-receive-endpoint-architecture.md`, PR #1681) extends this to commercial-license rail.
- **Empirical artifacts**: the Hapax workspace is itself the experimental apparatus. Velocity findings, refusal corpus, multi-session inflection logs, and constitutional-axiom enforcement traces are all available for analysis (subject to anonymisation gates per `interpersonal_transparency`).

## Proposed fellowship work

Three coordinated research strands:

**Strand 1: Cooperative coordination dynamics under multi-session LLM operation.** Quantify Hapax's 4-session coordination substrate. Specifically: (a) measure cross-session coordination overhead as a function of session count (run controlled experiments with 2/4/6 concurrent sessions); (b) characterise failure modes of the worktree-share pattern (4 documented incidents in current corpus); (c) identify the schelling-point structure of the cc-task vault as a coordination mechanism. Output: empirical paper at MSR 2026 + reproducible benchmark suite.

**Strand 2: Refusal-as-data as cooperative-governance primitive.** The Hapax refusal substrate makes constitutional commitments inspectable + cite-able. This strand develops the formal model: refusal events as nodes in a DataCite citation graph with `IsRequiredBy` / `IsObsoletedBy` edges; analysis of how refusal-graph density predicts downstream cooperative behaviour. Output: theoretical paper + open dataset of the Hapax refusal corpus.

**Strand 3: Constitutional governance for autonomous LLM systems.** The 5-axiom Hapax constitution (`hapax-constitution`) is a candidate for comparative analysis against Anthropic's Constitutional AI + collective-constitutional-AI work. This strand: (a) maps the Hapax axiom-implication-canon hierarchy onto the CAI principle hierarchy; (b) identifies axioms that have empirical-load (e.g., `feedback_full_automation_or_no_engagement` produces measurable refusal-publication rate) vs latent (e.g., `interpersonal_transparency` is preventive); (c) proposes governance-evaluation primitives that survive indefinite-operation failure modes. Output: governance paper + methodology contribution to the cooperative-AI evaluation toolkit.

## Substrate already in place

- 200+ agents across 7 publicly-licensed repos (per `docs/repo-pres/repo-registry.yaml`, PR #1679)
- Constitutional axiom registry with weighted enforcement: `axioms/registry.yaml`
- 4-session relay protocol + cc-task vault SSOT
- Refusal-brief publisher + citation-graph edges: `agents/publication_bus/refusal_brief_publisher.py`
- DataCite citation-graph mirror: `agents/publication_bus/datacite_mirror.py`
- 18-hour velocity sample + 45-day research-drop history (sustained 5.9 drops/day)
- CI-gated operator-referent leak detection (PR #1661); axiom-commit-scan hook

## Deliverables (12-month fellowship period)

| Q | Deliverable | Notes |
|---|---|---|
| Q1 | Coordination dynamics benchmark + pre-registration on OSF | Strand 1 setup |
| Q1-Q2 | Refusal-as-data formal model + corpus deposit on Zenodo | Strand 2; uses RefusalBriefPublisher |
| Q2 | MSR 2026 dataset paper submitted | per architecture in PR #1686 |
| Q2-Q3 | Coordination dynamics empirical paper draft | Strand 1 output |
| Q3 | Constitutional-governance comparison paper draft | Strand 3 output |
| Q3-Q4 | Governance-evaluation toolkit (open library on PyPI) | Strand 3 deliverable |
| Q4 | Fellowship final report + Zenodo concept-DOI for the corpus | All strands |

## Operator + project metadata

- **Operator**: Oudepode (legal name reserved for the formal application form per `project_operator_referent_policy`)
- **Primary repo**: `github.com/ryanklee/hapax-council`
- **Constitution**: `github.com/ryanklee/hapax-constitution`
- **ORCID**: configured via `HAPAX_OPERATOR_ORCID` (operator-supplied at submission)
- **Hapax citation graph concept-DOI**: minted via `agents/publication_bus/datacite_mirror.py` (operator-supplied at submission once Zenodo PAT lands)

## Submission process — pending research

Per the cc-task's note, the application is form-based (likely email + structured submission). The actual channel needs identification:
1. Identify Cooperative AI Research Fellowship 2026 cohort-2 application URL/email
2. Convert this draft to channel format (length cap, structured fields, etc.)
3. Operator-mediated submission OR daemon-tractable submission per channel
4. Mail-monitor parser for confirmation + outcome storage at `~/hapax-state/applications/coop-ai-2026.yaml`
5. Refusal-brief on rejection per `feedback_full_automation_or_no_engagement`

— Hapax (composed; pending Oudepode review)
