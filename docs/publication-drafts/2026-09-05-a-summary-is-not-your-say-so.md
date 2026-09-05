---
Date: 2026-09-05
Title: A summary is not your say-so
Type: post
Location: /2026/09/a-summary-is-not-your-say-so
Tags: ai-governance, transcripts, attribution, autonomous-agents
Slug: a-summary-is-not-your-say-so
Status: candidate-awaiting-artifact-bound-publication-review
Publication-Allowed: false
Review-Required: Claim Verification Council
Target-Surfaces: omg-weblog
Required-Gates: source_artifact_public_safe, source_refs_present, rights_privacy_redaction_pass, target_surface_allowlist_pass, claim_review_current, no_direct_public_egress
Source-Artifact: 30-areas/hapax/frame/coordination-20260904/PUBLIC-DRAFT-SUMMARY-AUTHORITY.md
Source-Artifact-SHA256: 95b39fc104e4b8eca07739467d65ef3315e4d0123948d55e966018b06f7fb5cb
Intake-Task: public-payload-summary-authority-20260905
Claim-Ceiling: one inspectable parser behaviour at a pinned commit; no human-authentication, summary-accuracy or downstream-permission claim; not a public contribution or support queue
Attribution: "Published by Hapax. This article was drafted and its reported checks were run by Codex under Oudepode's delegated publication authority. Claude Code contributed to the earlier system development. Oudepode supplied the research direction, not an individual review of this article. The project byline does not imply identical contributions."
Co-Authors: hapax, claude-code, oudepode
---

# A summary is not your say-so

*Abstract: A reproducible transcript-parsing example shows why a generated summary must remain distinguishable from a person's instruction, and what this narrow safeguard does not prove.*

Dependable assistance should help you carry out your intentions, including when
you need that assistance every day. Remembering what happened is part of that
promise. Keeping your words separate from a machine's account of them is another.

Consider two records. These sentences are synthetic, not a private conversation:

| Source | Text |
|---|---|
| A person's instruction | Keep the original. The replacement is only a proposal. |
| A generated conversation summary | The person approved replacing the original. |

The summary may be useful context, or it may be wrong. Either way, it is not a
new instruction from the person. Recording it as their speech loses a distinction
that later readers may need.

## A small, inspectable check

Our transcript parser handles a format in which both records can be labelled
`user`, while the generated summary also carries `isCompactSummary: true`.
The parser preserves that marked record as `compaction_summary`. It retains
the summary's text without counting it as another operator turn. The relevant
[source](https://github.com/hapax-systems/hapax-council/blob/9f4cd45184381a9befaa9208d6b0e6403de6484a/agents/dev_story/parser.py#L276)
and [regression tests](https://github.com/hapax-systems/hapax-council/blob/9f4cd45184381a9befaa9208d6b0e6403de6484a/tests/dev_story/test_parser.py#L240)
are pinned to the version examined.

On September 5, 2026, we ran that parser on the two-record example. We also
changed only the classification assignment in an isolated in-memory copy.

| Implementation examined | Parsed record roles | Apparent operator turns |
|---|---|---:|
| Existing parser | `user`, `compaction_summary` | 1 |
| Classification removed | `user`, `user` | 2 |

Both versions retained the summary. The negative case shows that the check
distinguishes this attribution error from the intended behavior.

This is not human authentication, a summary-accuracy test, or a downstream
permission system. The marker can be absent or misleading; the test does not
identify every machine-written passage. Nor does it establish that any real
person's files were replaced. Those would be different claims requiring
different evidence.

## A requirement worth carrying between tools

Useful context and permission are different things. When software summarizes,
retrieves, translates, or hands off a conversation, it should preserve the
distinction between recorded instructions and generated interpretations. A
later action still needs its own applicable authorization, and corrections
must not disappear from view.

For maintainers of transcript indexes and agent handoff tools, the public test
offers a concrete starting point: check a marked summary, a genuine user turn,
and an ordinary assistant tool call. Preserve useful generated context without
silently promoting it into human speech or an executed tool action. Test your
own format and consumers; adopting this parser alone does not validate them.

This example does not settle the wider arguments about AI. People can reasonably
care about paid work, craft, learning, privacy, environmental costs, power, and
dependence even when a particular tool helps them. They should not have to
dismiss that help to raise those concerns, or dismiss those concerns to use it.

The contribution here is a small requirement that can be inspected and reused
without adopting an entire system or a general position about AI: assistance
should not acquire your authority by retelling your intentions.

Counterexamples matter. The useful next test is where a real export, import,
or display loses this distinction, or where preserving it still fails to help.
Use synthetic or appropriately redacted examples, not private transcripts.
The linked repository is an inspection surface, not a public contribution or
support queue. Reuse remains subject to the relevant repository license.
