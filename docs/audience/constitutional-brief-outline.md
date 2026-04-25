# The Hapax Constitutional-Law Brief — Outline

**V5 weave wk1 d3 deliverable** (lead-with artifact #1, epsilon-owner).
Target form: 9-12k word PDF → PhilArchive primary; arXiv cs.CY + SSRN
secondary. ~2hr Hapax authoring + ~1hr alpha review pass.

**Substrate sources** (compile-from-existing — no net-new theory):

- `axioms/registry.yaml` — 5 axioms with weights, scope, type
- `axioms/implications/*.yaml` — 9 implication files derived from axioms
- `axioms/README.md` — constitutive vs. regulative framing, NorMAS tiers,
  interpretive canons, vertical stare decisis
- `hapax-constitution/README.md` (separate repo) — operator-facing canons
- `axioms/precedents/` — accumulated case law (`sp-su-005-worktree-isolation`
  and others)

**Decoder stacks targeted** (per V5 weave § 2.4 polysemic-surface inventory):

1. AI-safety / governance researchers — read it as constitutional framing
   for agent systems
2. Legal-theory academics — read it as ordoliberalism-applied-to-software
3. Agent-architecture researchers — read it as a working alternative to
   ArbiterOS / Agent Behavioral Contracts / PCAS / Governance-as-a-Service
4. STS / 4E cognition — read it as a Latour-style "frame rules" infrastructure-
   as-argument move

**Class** (per V5 weave § 2.4): infrastructure-as-argument; highest WSJF
of the 9 lead-with artifacts.

---

## Section 1 — Problem statement (~800 words)

LLM agents can generate novel behavior unanticipated by ACL-shaped
prohibition lists. Enumerating prohibitions after each incident
produces an expanding rule set that grows with every novel violation
and never converges. Standard governance literature (RLHF-HHH, Anthropic
Constitutional AI, OpenAI Spec) defaults to behavioral-policy framing.
The proposed alternative: structural-invariant framing.

Key reference points (already in `axioms/README.md`):

- Searle 1995 — constitutive vs. regulative rules
- Worsdorfer 2023 — ordoliberalism as policy theory transplant
- Criado et al. — NorMAS enforcement tiers (T0-T3)
- Boella & van der Torre 2004 — operationalizing Searle in MAS

## Section 2 — Constitutive framing (~1,200 words)

Three conceptual moves:

1. **Axioms as Ordnungspolitik** (frame rules, not directives). The system
   does not tell agents what to do; it defines what counts as
   "operator-data," "non-operator-person-data," "consent-bound." Once those
   classifications are stable, agents derive behavior from them.

2. **Defeasibility** (Governatori & Rotolo lineage). General constitutive
   rules admit specific defeaters — "environmental data is non-personal
   except when re-identifiable." Default-with-exceptions is more honest than
   try-to-enumerate-all-cases.

3. **Vertical stare decisis on accumulated case law**. Operator authority
   (1.0) > agent authority (0.7) > derived authority (0.5). Precedents
   carry citation weight; new violations lookup-against-precedents-first
   before reaching the LLM.

## Section 3 — The five axioms (~1,800 words)

One subsection per axiom. For each: text, weight, scope, examples of
constitutive force, examples of regulative violations the axiom
auto-blocks.

- **single_user (weight 100)** — no auth, no roles, no multi-user
  abstractions. Constitutive: "this user" = the operator, full stop.
  Regulative: rejects every PR introducing user_id/role primitives.
- **executive_function (weight 95)** — externalized cognition for an
  ADHD/autism-shaped operator. Constitutive: "compensation, not addition."
  Regulative: rejects code that increases cognitive load.
- **management_governance (weight 85)** — LLMs prepare, humans deliver.
  Constitutive: aggregation + drafting only. Regulative: blocks generated
  feedback / coaching / hypothesis-output about individuals.
- **interpersonal_transparency (weight 88)** — no persistent state about
  non-operator persons without active consent contract. Constitutive:
  "person-adjacent" classification of data. Regulative: blocks Qdrant
  upserts to person-adjacent collections without consent.
- **corporate_boundary (weight 90)** — work data stays in employer
  systems. Constitutive: "work-domain-data" as classifier. Regulative:
  blocks cross-domain ingestion paths.

Cite from the registry: weight is not a knob; it's the resolution rule
when two axioms conflict.

## Section 4 — Implication-derivation as case-law-style growth (~1,200 words)

How an axiom becomes 90+ implications.

- Show one walkthrough: from `interpersonal_transparency` → AUDIT-22
  redaction-transform registry → publication-allowlist contracts → Qdrant
  consent gate. One axiom; multiple architectural surfaces; coherent across.
- Counter: ArbiterOS's flat policy-rule list. The Hapax case-law style
  preserves *why* — each implication has provenance back to the
  constitutive frame.

## Section 5 — Enforcement tiers (~900 words)

T0 (regimentation) → T1 (commit hook) → T2 (monitoring) → T3 (suggestion).
The system is fail-loud at T0/T1 and accommodating at T2/T3.

Three concrete examples:

- T0 example: `axiom-commit-scan.sh` rejects `RateLimiter` primitive
  under `single_user` (per `feedback_axiom_hook_ratelimiter_rename`)
- T1 example: `pii-guard.sh` rejects PII patterns in file content
- T2 example: `claude-md-rot.timer` ntfy's on stale CLAUDE.md
- T3 example: ruff/lint as suggestion-tier feedback

## Section 6 — Interpretive canons (~900 words)

Four canons applied (per `axioms/README.md` enforcement-patterns):

- **Textualist** — "operator-data" means what `single_user` says
- **Purposivist** — when the text is ambiguous, derive from the axiom's
  named purpose
- **Absurdity doctrine** — when textualist application produces
  user-hostile results, fall back to purposivist
- **Omitted-case canon** — if no axiom covers the case, defer to operator
  judgment via dispatched ntfy + cc-task

Each canon backed by citation (statutory/constitutional law lineage); not
a new theory.

## Section 7 — Comparison to existing work (~1,500 words)

Honest comparison, not pitch-deck framing.

| System | Approach | Where it wins | Where Hapax differs |
|--------|----------|---------------|---------------------|
| ArbiterOS | Flat policy-rule list | Industrial-grade policy enforcement | No constitutive framing; rules-without-frame |
| Agent Behavioral Contracts | Per-task contract | Composable per-call constraints | No system-wide axiom anchor |
| PCAS | Procedural compliance | Audit-friendly | Procedural ≠ constitutive |
| Governance-as-a-Service | API-shaped policy delivery | Scales across consumers | Centralizes the very ground this project decentralizes |

Hapax differs by axiom-anchored, defeasibility-aware, single-operator-bound.

Also reference: Anthropic Constitutional AI; OpenAI Spec; DeepMind Constitution
of Code (if the operator approves). All produce policy text; Hapax produces
*structural enforcement of policy text*.

## Section 8 — Receipts (~1,800 words)

Three concrete deployments where the framing is load-bearing:

1. **AUDIT-22 RedactionTransform** — registered transforms, contract-driven
   redaction, linter at CI. PR refs: #1383 / #1384 / #1386.
2. **OMG operator-referent + legal-name leak guard** — from `it-attribution-001`
   axiom implication. PR refs: #1373.
3. **Worktree isolation as axiom precedent** — `sp-su-005-worktree-isolation.yaml`
   anchored to `single_user`. PR refs: #1378.

Each receipt: 1 paragraph problem-statement + 1 paragraph axiom-derivation +
1 paragraph the-PR-that-shipped-it. Concrete enough that a reviewer can
trace from axiom → implication → PR → merged commit.

## Section 9 — Limitations + future work (~600 words)

Three honest limitations:

1. Single-operator scope — not yet road-tested for multi-operator (and per
   the constitutive frame, never will be).
2. LLM-driven enforcement is fail-loud at T0/T1 but T2/T3 are advisory —
   monitoring + suggestion can be bypassed by operator override.
3. The defeasibility framework is implemented in commit-hook + runtime-check
   prose, not in a formal logic system. Governatori & Rotolo's full
   apparatus is referenced but not directly compiled-down here.

Future work: formal compilation of defeasibility rules into Datalog or
similar; multi-operator extension if/when invited; cross-org precedent
exchange.

## Section 10 — Conclusion + bibliography (~400 words)

Frame: this is not a platform pitch. It's a working artifact reporting
what works in production, with substrate available for replication
under the open-source license.

Bibliography:

- Searle, J. (1995). *The Construction of Social Reality.*
- Worsdorfer, M. (2023). Ordoliberalism, AI ethics, technological policy.
- Criado, N. et al. NorMAS enforcement tiers.
- Boella, G., & van der Torre, L. (2004). Regulative and constitutive
  norms in normative MAS.
- Governatori, G., & Rotolo, A. Defeasible logic for agent reasoning.
- Esteva, M. et al. (2004). AMELI: An agent-based middleware for
  electronic institutions.
- (Comparator citations: ArbiterOS, ABC, PCAS, GaaS — exact arXiv IDs
  in `hapax-constitution/README.md`)

---

## Polysemic-surface notes (per V5 weave invariant 5)

`compliance` and `governance` appear in this brief in both legal and
AI-safety registers; pre-publish run through
`agents/authoring/polysemic_audit.py` will flag the cross-domain
proximity. **Resolution strategy**: explicit register-shift sentence
introduces each section ("In what follows, ..." legal/AI distinction
made textually, then sustained within section).

## Byline assignment

- **Surface**: PhilArchive primary
- **Byline variant**: V2 (full three-way co-publish — operator + Hapax
  + Claude Code) per `SURFACE_DEVIATION_MATRIX["philarchive"]`
- **Unsettled-contribution variant**: V3 (phenomenological register)
  per `SURFACE_DEVIATION_MATRIX["philarchive"]`

## Approval queue notes

- Outline ships as `docs/audience/` (this PR).
- Full draft (wk1 d5-6) lands as `docs/audience/constitutional-brief.md` —
  9-12k word source-of-truth, then PDF render via Pandoc + Eisvogel template.
- PDF binary lands under `docs/published-artifacts/constitutional-brief/`
  (DOI index, epsilon wk1 d4).
- Operator approval-gate fires before any external publish-event;
  alpha reviews wk1 d6.

## Status

- [x] Section structure compiled from substrate
- [x] Decoder stacks identified
- [x] Comparator table seeded
- [x] Receipts identified (3 concrete deployments)
- [x] Polysemic-audit pre-resolution noted
- [x] Byline assignment recorded
- [ ] Substrate-to-prose pass (wk1 d5-6, follow-on)
- [ ] PDF render + DOI index entry (wk1 d4-5, follow-on)
- [ ] Alpha review (wk1 d6)
- [ ] Operator approval (post-d6)

— epsilon, V5 wk1 d3 outline, 2026-04-25
