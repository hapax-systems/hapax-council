---
title: "White-Label B2B Legal Posture Research"
type: legal-research
created: 2026-06-30
authority_case: CASE-SDLC-REFORM-001
parent_request: REQ-20260628-mdlc-tax-legal-posture-registry
parent_spec: hapax-council/docs/superpowers/specs/2026-05-30-sdlc-frictionless-self-direction-design.md
cc_task: 20260628-registry-phase5-white-label-subtree
tags: [legal-registry, white-label, b2b, anthropic, ftc, open-weight]
status: active
---

# White-Label B2B Legal Posture Research

This is non-attorney registry research, not legal advice. The rows here keep
white-label cognitive-labor paths fail-closed unless a later operator signature
and concrete contract/model-stack evidence supports a narrower PARTIAL or LIT
posture.

## Method

- Reviewed the phase-0 legal-posture schema and restored rows into
  `docs/monetization/legal-posture-registry.yaml`.
- Verified primary or official sources on 2026-06-30 where possible.
- Treated contractual platform restrictions, disclosure/deception risk, tenant
  isolation, and model-license variance as legal gate concerns, not business
  attractiveness concerns.
- Treated every PARTIAL row as unsigned; under the registry schema, unsigned
  non-DARK rows do not pass g2.

## Source Findings

### Anthropic Commercial Terms

Anthropic's Commercial Terms of Service are the controlling source for the
Anthropic service rows. Section D.4 prohibits using the services to build a
competing product or service, train competing AI models, or resell the services
except as expressly approved by Anthropic.

Registry effect:
`anthropic / anthropic_competing_product_or_resale` remains `DARK` unless the
exact service and resale posture are approved in writing.

Source:
- Anthropic Commercial Terms of Service:
  https://www.anthropic.com/legal/commercial-terms

### Claude Code Subscription-Credential Harnesses

The Claude Code legal/compliance documentation states that third-party
developers may not offer Claude.ai login or route requests through Free, Pro, or
Max plan credentials on behalf of users. Reported OpenClaw/Harness events are
treated as enforcement signal, but the registry row cites Anthropic's current
documentation as the authority.

Registry effect:
`anthropic / anthropic_third_party_harness_subscription_credentials` remains
`DARK`.

Source:
- Claude Code legal and compliance:
  https://code.claude.com/docs/en/legal-and-compliance

### FTC B2B Disclosure And Deception

FTC Act Section 5 supplies the general unfair/deceptive practice authority.
Recent FTC AI-adjacent actions remain relevant to white-label posture because
they show enforcement risk around deceptive AI/business-opportunity claims,
unsubstantiated earnings or performance promises, active-listening claims, and
privacy/confidentiality commitments.

Registry effect:
- `US-FTC / undisclosed_ai_b2b_service` remains `DARK`.
- `US-FTC / disclosed_ai_b2b_service` is only an unsigned `PARTIAL` candidate.
- `US-FTC / multi_tenant_without_contractual_isolation` remains `DARK`.

Sources:
- FTC Act:
  https://www.ftc.gov/legal-library/browse/statutes/federal-trade-commission-act
- FTC, AI Companies: Uphold Your Privacy and Confidentiality Commitments:
  https://www.ftc.gov/policy/advocacy-research/tech-at-ftc/2024/01/ai-companies-uphold-your-privacy-confidentiality-commitments
- FTC Air AI settlement release:
  https://www.ftc.gov/news-events/news/press-releases/2026/03/air-ai-its-owners-will-be-banned-marketing-business-opportunities-settle-ftc-charges-company-misled
- FTC Cox Media Group active-listening settlement release:
  https://www.ftc.gov/news-events/news/press-releases/2026/05/ftc-require-cox-media-group-two-other-firms-pay-nearly-1-million-settle-charges-they-deceived

### Open-Weight Model License Manifest

Open-weight model stacks do not create one uniform legal posture. Apache-2.0,
Llama community licenses, Mistral model-specific licenses, and acceptable-use
policies can impose different commercial, redistribution, attribution, output
use, and scale-threshold constraints. The registry therefore records a PARTIAL
candidate only when a concrete model-stack license manifest exists and the
operator signs the row.

Registry effect:
`* / open_weight_model_stack_license_manifest` is unsigned `PARTIAL`, which
still fails g2 until signed.

Sources:
- Meta Llama license:
  https://ai.meta.com/llama/license/
- Mistral open-model license guidance:
  https://help.mistral.ai/en/articles/347393-under-which-license-are-mistral-s-open-models-available
- Apache License 2.0:
  https://www.apache.org/licenses/LICENSE-2.0

## Encoded Rows

| Registry instrument | Verdict | Disposition |
|---|---|---|
| `anthropic_competing_product_or_resale` | `DARK` | No Anthropic-backed white-label or resale posture without express approval. |
| `anthropic_third_party_harness_subscription_credentials` | `DARK` | No Claude.ai subscription credential routing for a third-party/customer harness. |
| `undisclosed_ai_b2b_service` | `DARK` | No fake-human or materially undisclosed AI service positioning. |
| `disclosed_ai_b2b_service` | `PARTIAL` unsigned | Candidate only with disclosure, substantiation, contract/privacy fit, and operator signature. |
| `multi_tenant_without_contractual_isolation` | `DARK` | No cross-tenant prompt/file/output/log/model artifact reuse without explicit contract authority. |
| `open_weight_model_stack_license_manifest` | `PARTIAL` unsigned | Candidate only after exact model/version/license manifest and operator signature. |

## Minimum Later Evidence For Any Non-DARK White-Label Row

- Exact customer-facing disclosure text for proposals, SOWs, terms, invoices,
  deliverables, and support materials.
- Contract terms for privacy, confidentiality, retention, deletion,
  subprocessors, model training, human review, and tenant isolation.
- Model/provider manifest with exact model IDs, versions, license URLs,
  acceptable-use policies, and downstream flow-down obligations.
- Evidence that no customer work is routed through prohibited subscription
  credentials or used to create a competing/resold Anthropic service without
  written approval.
- Operator signature on the exact tuple being admitted.
