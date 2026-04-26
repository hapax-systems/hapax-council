# AAIF Linux Foundation Agentic AI Foundation — Spec Donation

**cc-task:** `leverage-vector-aaif-spec-donation` (WSJF 4.0)
**Composed:** 2026-04-26

## Premise

The Linux Foundation's Agentic AI Foundation (AAIF, launched 2025) is consolidating spec work across multi-agent systems, governance under uncertainty, and inter-agent communication standards. Hapax has shipped two infrastructure substrates that map directly onto the AAIF spec landscape:

1. **5-axiom constitutional governance** with weighted enforcement (`axioms/registry.yaml`) + `__init_subclass__`-driven refusal hooks (`agents/publication_bus/refusal_brief_publisher.py`). This is a candidate contribution for AAIF's governance / safety-charter spec track.

2. **Refusal-as-data citation graph** with DataCite `RelatedIdentifier` edges (`IsRequiredBy` / `IsObsoletedBy`). This is a candidate contribution for AAIF's inter-agent communication / artifact-attribution spec track.

This architecture identifies what to donate, the licensing path (depends on `leverage-workflow-hapax-axioms-pypi` cc-task), and the contribution-routing surface.

## Donation candidates

### 1. Axiom enforcement primitives (governance track)

**What ships**: the 5 constitutional axioms + their implication hierarchy + the weighted-enforcement model + the commit-hook integration pattern.

**Code surface**:
- `axioms/registry.yaml` — 5 axioms with weights (single_user 100, executive_function 95, corporate_boundary 90, interpersonal_transparency 88, management_governance 85)
- `axioms/implications/` — per-axiom implication chains
- `axioms/contracts/` — concrete consent-contract artifacts the axioms reference
- `shared/axiom_enforcement.py` — runtime check helpers
- `hooks/scripts/axiom-commit-scan.sh` — pre-commit + CI-time enforcement

**License path**: PolyForm Strict 1.0.0 by default per the council license matrix. The donation requires a separate permissive-license mode for AAIF spec inclusion. Per `leverage-workflow-hapax-axioms-pypi` cc-task, the `hapax-axioms` PyPI package is the dual-license vehicle (MIT for the package, PolyForm Strict for the council runtime that uses it). AAIF donation = PyPI package contents only.

**Donation shape**: candidate AAIF Spec Track 1 (Governance) section. Hapax's contribution is the methodological pattern (axiom + implication + canon + weighted enforcement + commit-time verification) rather than the specific axiom values. The 5 Hapax axioms are illustrative.

### 2. Refusal-as-data inter-agent attribution (communication track)

**What ships**: the refusal-brief publisher's `IsRequiredBy` / `IsObsoletedBy` edge composition + the canonical refusal-log JSONL schema + the publisher-kit's `__init_subclass__` auto-wiring for REFUSED-tier surfaces.

**Code surface**:
- `agents/publication_bus/refusal_brief_publisher.py` — composer + scanner
- `agents/publication_bus/related_identifier.py` — DataCite RelatedIdentifier dataclass
- `agents/publication_bus/publisher_kit/` — `__init_subclass__` REFUSED-tier auto-wiring
- `tests/publication_bus/test_refusal_*` — pinning the contract

**License path**: same dual-license dance as §1 — the spec-eligible surface is the publisher-kit's interface contract, not the council-runtime implementation.

**Donation shape**: candidate AAIF Spec Track 3 (Inter-Agent Communication / Attribution) section. The pattern is "non-engagement is data" — agents publish their refusals as first-class citation-graph nodes so other agents can reason about absence. Pre-existing analogues exist in (a) the OAI-PMH `<deletedRecord>` schema and (b) the schema.org `archivedAt` property; the Hapax pattern adds the citation-graph edge semantics.

## Submission process

1. **Identify AAIF current spec-contribution channel** (research drop required). Likely candidates: GitHub PR to a `linuxfoundation/aaif-spec` repo, mailing-list submission to `aaif-spec-dev@lists.linuxfoundation.org`, or RFC-style proposal to a working group.
2. **Prepare PyPI dual-license package** (`leverage-workflow-hapax-axioms-pypi` cc-task — dependency, not yet shipped). Without this, the donation can't carry a permissive license that AAIF spec inclusion requires.
3. **Compose donation artifact**: spec-style document referencing the candidate sections + linking to the PyPI package + linking to council's reference implementation as canonical example.
4. **Submit + track**: per AAIF's submission process. Daemon-tractable if PR-based; mail-monitor confirmation parser if email-based.
5. **Refusal-as-data on rejection**: explicit refusal brief recording the AAIF response + rationale. Self-referential: the donation is itself partly about refusal-as-data, so a rejection becomes test data for the contributed methodology.

## Effort scope

| # | Component | Effort | Dependency |
|---|---|---|---|
| 0 | This architecture doc | 30 min | none — shipped here |
| 1 | AAIF channel research drop | 1-2h research-agent dispatch | none |
| 2 | hapax-axioms PyPI package | per `leverage-workflow-hapax-axioms-pypi` cc-task | not yet started |
| 3 | Donation artifact composition | 3-4h authoring | #2 |
| 4 | Submission via identified channel | 30 min - 2h | #3 |
| 5 | Confirmation/outcome parser | 1-2h | #4 |

**Total daemon scope:** ~6-12h across 5 follow-up PRs (excluding #2 which is its own cc-task).

## Constitutional posture

- `feedback_full_automation_or_no_engagement`: the donation artifact + submission are daemon-tractable; only the AAIF working-group review process is third-party-mediated.
- `single_user`: the council runtime stays PolyForm Strict; only the donatable surface (PyPI package) flips to MIT for spec inclusion.
- `interpersonal_transparency`: the donation contains no operator-identifiable content beyond the formal-context attribution (Oudepode + ORCID per `project_operator_referent_policy`).
- Self-referential: refusal-as-data is itself part of what gets donated. Aesthetic feature, not a flaw.

## Cross-references

- Council license matrix (per-repo policy): `docs/repo-pres/repo-registry.yaml` (PR #1679)
- PyPI dual-license dependency: `leverage-workflow-hapax-axioms-pypi` cc-task
- Refusal-brief publisher: `agents/publication_bus/refusal_brief_publisher.py`
- DataCite RelatedIdentifier graph: `agents/publication_bus/related_identifier.py`
- Anthropic CCO application (parallel governance-research argument): `docs/applications/2026-anthropic-claude-for-oss/draft.md` (PR #1684)
- Coop-AI Fellowship application (parallel coordination-research argument): `docs/applications/2026-coop-ai-fellowship/draft.md` (PR #1689)

— alpha
