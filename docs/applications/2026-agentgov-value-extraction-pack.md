---
title: "agentgov value extraction pack"
date: 2026-05-12
type: application-pack
status: draft
authority_case: REQ-20260512-epistemic-audit-realignment
tags: [agentgov, value-extraction, governance, ai-agents]
---

# agentgov Value Extraction Pack

## Position

`agentgov` is the validated near-term value surface for Hapax governance work:
a deployment-time control layer for AI coding agents and tool-using assistants.
It turns governance from prompt text into code that can allow, deny, audit, and
explain tool use before an agent mutates files, data, or infrastructure.

The claim is intentionally narrow. `agentgov` is not a certification program,
not an AI Act compliance product, and not dependent on Token Capital, RAG
quality, or corpus retrieval. It is a small, inspectable package of enforcement
primitives extracted from a live single-operator agent system:

- `VetoChain`: deny-wins composition for pre-execution policy gates.
- `ConsentLabel`: DLM-style information-flow labels for consent-scoped data.
- `Labeled[T]`: LIO-style values that preserve labels and why-provenance across
  transformations.
- `Principal` and `Says`: delegated authority and attribution without authority
  amplification.
- `ProvenanceExpr`: algebraic why-provenance that can survive or fail after
  contract revocation.
- `ConsentRegistry` and `RevocationPropagator`: contract loading and cascade
  purge hooks.
- `agentgov.hooks`: portable scanners for PII, multi-user scaffolding,
  attribution drift, ungrounded capability claims, and management-boundary
  violations.

The commercial/public story is: "put the irreversible parts of agent governance
below the model." Prompts still describe preferences. `agentgov` is for
invariants that should execute even when the model is confused, adversarially
prompted, or delegated through another agent.

## Public Copy

Short version:

> `agentgov` is a deployment-time governance layer for AI agents. It packages
> consent labels, provenance, delegated authority, revocation, and deny-wins
> policy gates into a small Python library. Use it when "the prompt says be
> careful" is not enough and an agent needs pre-execution controls with an audit
> trail.

Longer version:

> Most agent governance is advisory: a system prompt tells the model what it
> should not do. `agentgov` makes the boundary mechanical. Data can carry a
> consent label and why-provenance. Agents can run under delegated authority
> that cannot amplify itself. Tool calls can pass through a VetoChain where any
> denial blocks the action and records the reason. Revocation can cascade to
> subsystems keyed by provenance. The result is not a compliance stamp. It is a
> set of runtime controls that make specific failures harder to express.

## Claims That Can Be Made Now

| Claim | Evidence | Boundary |
| --- | --- | --- |
| `agentgov` provides typed governance primitives for agent systems. | [`packages/agentgov/src/agentgov/`](../../packages/agentgov/src/agentgov/) and [`packages/agentgov/README.md`](../../packages/agentgov/README.md). | This is a library claim, not an end-to-end platform claim. |
| Consent labels compose monotonically. | [`packages/agentgov/tests/test_consent_label.py`](../../packages/agentgov/tests/test_consent_label.py). | DLM-style label algebra only; does not prove every downstream integration calls it. |
| Bound agents cannot delegate more authority than they were granted. | [`packages/agentgov/tests/test_principal.py`](../../packages/agentgov/tests/test_principal.py). | Covers the packaged `Principal` model, not arbitrary host identity systems. |
| Veto chains are deny-wins policy composition. | [`packages/agentgov/tests/test_primitives.py`](../../packages/agentgov/tests/test_primitives.py). | Enforces only where host runtimes route decisions through the chain. |
| Why-provenance can be represented and evaluated algebraically. | [`packages/agentgov/tests/test_provenance.py`](../../packages/agentgov/tests/test_provenance.py). | Provenance quality depends on callers attaching the right contracts. |
| Consent revocation can cascade through registered purge handlers. | [`packages/agentgov/tests/test_revocation.py`](../../packages/agentgov/tests/test_revocation.py). | Revocation coverage is only as complete as registered subsystems. |
| The hook scanners catch several production governance failure classes. | [`packages/agentgov/tests/test_hooks.py`](../../packages/agentgov/tests/test_hooks.py) and [`packages/agentgov/CHANGELOG.md`](../../packages/agentgov/CHANGELOG.md). | Scanners are guardrails, not a complete security scanner. |

## External Framework Crosswalk

This section is a positioning map, not a compliance statement.

| Framework | What it asks for | How `agentgov` can support it | What not to claim |
| --- | --- | --- | --- |
| NIST AI RMF | NIST organizes AI risk work around Govern, Map, Measure, and Manage, with governance as a cross-cutting function across the lifecycle. | `VetoChain`, hooks, labels, and provenance can be technical controls inside Govern/Manage activities; tests can supply Measure evidence for specific invariants. | Do not claim NIST AI RMF conformance. `agentgov` is one control library, not an organizational risk program. |
| OWASP Agentic Skills Top 10 | OWASP emphasizes skill inventory, permission review, isolation, audit logging, approval workflows, and governance for agentic execution layers. | `agentgov` maps naturally to over-privileged skills, no-governance risks, approval gates, and audit-log-producing denials. | Do not claim full OWASP coverage. `agentgov` does not scan every skill ecosystem or provide sandboxing by itself. |
| ISO/IEC 42001 | ISO/IEC 42001 frames AI governance as an AI management system with policies, objectives, risk treatment, traceability, transparency, and continual improvement. | `agentgov` can be cited as an implementation control for traceability, runtime policy enforcement, and revocation evidence within an AIMS. | Do not claim ISO certification or management-system completeness. |
| EU AI Act | High-risk AI obligations include risk mitigation, data quality, logging, documentation, deployer information, human oversight, robustness, cybersecurity, and accuracy. | `agentgov` can help with traceable logging, human-authored policy boundaries, least privilege, and documentation of runtime controls. | Do not claim legal compliance, high-risk system readiness, or coverage of dataset quality, conformity assessment, or post-market monitoring. |
| MITRE AI Assurance / ATLAS | MITRE frames assurance as discovering, assessing, and managing risk through the AI lifecycle, with ATLAS as a living adversary tactics knowledge base. | `agentgov` supplies local controls and tests that can become evidence during assurance or red-team exercises. | Do not present `agentgov` as an adversary knowledge base or complete assurance process. |
| CSA Agentic AI Red Teaming Guide | CSA stresses role boundaries, context integrity, anomaly detection, workflow testing, inter-agent dependencies, and blast-radius minimization. | `Principal`, `VetoChain`, and provenance labels are good demo hooks for role-boundary and blast-radius tests. | Do not claim it replaces red teaming or continuous security testing. |

References:

- NIST AI RMF Core: <https://airc.nist.gov/airmf-resources/airmf/5-sec-core/>
- OWASP Agentic Skills Top 10: <https://owasp.org/www-project-agentic-skills-top-10/>
- ISO/IEC 42001 overview: <https://www.iso.org/standard/42001>
- European Commission AI Act overview: <https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai>
- MITRE AI Assurance: <https://www.mitre.org/focus-areas/artificial-intelligence/ai-assurance>
- CSA Agentic AI Red Teaming Guide: <https://cloudsecurityalliance.org/artifacts/agentic-ai-red-teaming-guide>

## Demo, Docs Page, Outreach Artifact

### Demo

Build a five-minute terminal demo called "deny before tool use":

1. Create a `VetoChain` with `budget`, `consent`, and `branch_clean` vetoes.
2. Pass an action context that fails `consent`.
3. Show that the action returns `allowed=False` and records `denied_by`.
4. Wrap a string in `Labeled[str]`, map it through a transformation, and show
   that the consent label and provenance are preserved.
5. Revoke a contract through `RevocationPropagator` and show a registered purge
   handler receiving the contract id.

This demo does not need a live RAG index or Token Capital claims. It runs
entirely from package primitives and can be backed by:

- [`packages/agentgov/tests/test_primitives.py`](../../packages/agentgov/tests/test_primitives.py)
- [`packages/agentgov/src/agentgov/labeled.py`](../../packages/agentgov/src/agentgov/labeled.py)
- [`tests/test_labeled.py`](../../tests/test_labeled.py)
- [`packages/agentgov/tests/test_revocation.py`](../../packages/agentgov/tests/test_revocation.py)

### Docs Page

Use the package README as the first docs page:

- Source: [`packages/agentgov/README.md`](../../packages/agentgov/README.md)
- Required next edit before publication push: add this value-extraction framing
  as a "Where this fits" section, including the "not compliance" boundary.
- Keep install copy tied to the actual package name: `pip install
  hapax-agentgov`; import remains `agentgov`.

### Outreach Artifact

Use the existing governance post as the outreach artifact, with a narrower
call-to-action:

- Draft: [`docs/publication-drafts/2026-05-10-show-hn-governance-that-ships.md`](../publication-drafts/2026-05-10-show-hn-governance-that-ships.md)
- CTA replacement: "Try `hapax-agentgov` if you need pre-execution controls
  for coding agents; treat it as a control library, not as a compliance claim."
- Avoid phrases that imply general certification, universal safety, or proof of
  all production governance outcomes.

## Least-Privilege Package Narrative

The strongest near-term buyer/user problem is not "make agents safe." That is
too broad and not provable. The sharper problem is:

> I want autonomous coding agents to run useful workflows, but I need certain
> actions to be impossible unless runtime facts satisfy explicit policy.

`agentgov` answers that with least-privilege mechanics:

1. A human or host system is a `Principal`.
2. Delegated agents are bound principals with narrower authority.
3. Data is a `Labeled[T]` value with consent labels and why-provenance.
4. Tool use is routed through a `VetoChain`.
5. Denials are explicit, inspectable, and order-independent.
6. Revocation propagates by provenance to registered purge handlers.

This is enough to produce useful demos and docs now. It is not enough to claim
general enterprise compliance, complete agent security, or validated RAG-backed
research conclusions.

## Limitations To Keep Visible

- `agentgov` is a library. It becomes enforcement only when the host runtime
  calls it at the right boundaries.
- Hook scanners are intentionally narrow and should be complemented by normal
  security tooling.
- The current package proves algebraic behavior with tests; it does not prove
  every Hapax runtime integration uses the package path.
- Compliance frameworks require organizational process, documentation,
  assessment, and monitoring beyond this package.
- Public copy must not mention Token Capital compounding as evidence.
- Public copy must not depend on live RAG retrieval until the RAG recovery
  tasks produce measured corpus utilization and retrieval quality reports.

## Verification Hook

Recommended package verification for this pack:

```bash
uv run pytest packages/agentgov/tests -q
```

Recommended claim discipline before publishing any derived page:

```bash
rg -n "compliance|certified|guarantee|Token Capital|token compounding|RAG proves" docs packages/agentgov
```
