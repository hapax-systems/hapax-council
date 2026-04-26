# AAIF (Linux Foundation Agentic AI) — Hapax spec contribution proposal

**cc-task:** `leverage-vector-aaif-spec-donation` (WSJF 4.0)
**Status:** DRAFT — pending operator review + AAIF outreach
**Composed:** 2026-04-26
**Composed by:** Hapax (the project contributing) + Claude Code (epsilon session), assembled from substrate

---

## Contribution proposal (≤500 words)

Hapax proposes contributing two coupled spec primitives to the Linux Foundation's Agentic AI Foundation (AAIF):

1. **Axiom-weighted enforcement registry** — a YAML schema for declaring constitutional axioms with explicit weights, T0/T1/T2 violation tiers, implications, and per-implication enforcement modes. Hapax operates 5 such axioms (`single_user`, `executive_function`, `corporate_boundary`, `interpersonal_transparency`, `management_governance`) with weighted enforcement at commit-time, runtime, and deploy-chain layers. The schema is extracted from `hapax-constitution/axioms/registry.yaml` and is re-usable as a generic agentic-substrate primitive.

2. **Refusal-as-data substrate** — the architectural pattern in which each refused-by-design surface emits a structured refusal-event into a canonical log, accompanied by a refusal-brief markdown document with rationale, lift-conditions, and DataCite RelatedIdentifier graph edges (`IsRequiredBy` / `IsObsoletedBy`). Refusals become first-class citations rather than absences. Hapax has shipped this substrate at production scale: 39 active refusal-cc-tasks span the surfaces an autonomous agent might be tempted to touch (Stripe payment links, Wikipedia auto-edit, native Slack/Discord DM bots, ML-based inbox classifiers, mass-market grant funnels), each with constitutional rationale + audit-replay scaffold.

Both primitives ship as PolyForm Strict Python packages (donation-compatible per AAIF charter): `hapax-axioms` (the axiom registry + enforcement primitives) and `hapax-refusals` (the refusal-event log + refusal-brief renderer + DataCite graph composer). PolyForm Strict permits non-commercial / personal / research use, which aligns with AAIF's open-spec posture; commercial relicensing is the operator's discretion via separate license-request mail-routing (`agents/mail_monitor/processors/license_request.py`).

## Why AAIF specifically

AAIF's spec mandate covers agent-to-agent communication, governance schemas, and multi-agent coordination patterns. Hapax's refusal substrate addresses a subspace of (3) that current AAIF working groups have flagged as load-bearing-but-underspecified: how does an agent declare *what it will not do*, in a form other agents can audit and cite? The publication-bus's RelatedIdentifier graph composition (`agents/publication_bus/related_identifier.py`) is one concrete answer.

The contribution is not a unilateral push: Hapax welcomes AAIF's spec-process review, including amendments to the YAML schema, alternative refusal-event log shapes, and broader integration with other AAIF-recognised governance frameworks.

## Concrete first-PR targets

- AAIF spec repository under `linuxfoundation/aaif-spec` (or equivalent venue when AAIF publishes its draft repository structure)
- Submission shape: GitHub PR adding (a) `governance/axiom-registry-schema.json` (JSON Schema for the axiom registry YAML), (b) `governance/refusal-event-log.md` (the log shape spec), (c) reference implementation pointers to the two PyPI packages above
- Co-authorship: Hapax + Claude Code (per the project's authorship-indeterminacy stance)

## Risk profile

- AAIF rejection: refusal-brief annex captures the rationale; the donation lands at Zenodo as a deposit anyway, citation-graph-anchored
- License compatibility: PolyForm Strict is donation-compatible per AAIF charter, but charter language may evolve. Operator action: monitor AAIF licensing FAQ quarterly
- Spec process latency: AAIF working-group cycles run 6-12 months. The contribution is a Day 60-90 milestone in the 90-day plan; PR submission is async-friendly

## Operator-action queue (Phase 2)

The actual submission requires:
- `pass insert linuxfoundation/aaif-cla-token` (one-time CLA signing token, if required)
- Operator's GitHub identity bound to the AAIF CLA per their contributor agreement
- The two PyPI packages (`hapax-axioms`, `hapax-refusals`) shipped first — both are upstream of this contribution

## Cross-references

- Existing axiom registry: `hapax-constitution/axioms/registry.yaml`
- Existing refusal substrate: `agents/refusal_brief/writer.py`, `agents/refused_lifecycle/`, `docs/refusal-briefs/`
- DataCite graph composer: `agents/publication_bus/related_identifier.py`, `agents/publication_bus/refusal_brief_publisher.py`
- Sister doc-only PRs in the same wave: #1684 Anthropic CCO, #1689 Coop AI Fellowship, #1691 third-party prizes

— Hapax (epsilon session, 2026-04-26)
