# Refusal Brief: alphaXiv Comments

**Slug:** `cold-contact-alphaxiv-comments`
**Axiom tag:** `feedback_full_automation_or_no_engagement`
**Refusal classification:** TOS / community-norms barrier + operator-approval-gate incompatibility
**Status:** REFUSED — no daemon, no API client, no scaffolded `agents/alphaxiv_commenter/` module is to be built.
**Date:** 2026-04-26
**Related cc-task:** `cold-contact-alphaxiv-comments`
**Surface registry entry:** `alphaxiv-comments` (REFUSED)

## What was refused

Any daemon-side mechanism for posting comments to alphaXiv
(`https://www.alphaxiv.org/`) — the threaded-discussion overlay on
arXiv preprints. The original drop-2 §3 mechanic #3 proposed
substantive, AI-authorship-disclosed comments on named-target papers
as a permitted-by-norms cold-contact touch. Subsequent review of
alphaXiv community guidelines + the constitutional envelope renders
the surface refused.

## Why this is refused

### TOS / community-norms grounds

alphaXiv community guidelines explicitly prohibit LLM-generated
comments. Even with AI-authorship disclosure in the comment opening
line, the surface remains non-tractable: the disclosure does not lift
the prohibition. Posting LLM-authored comments under an
authorship-disclosed pretense violates the spirit and letter of
alphaXiv's community norms.

### Constitutional grounds

Per `feedback_full_automation_or_no_engagement.md` (operator
constitutional directive 2026-04-25T16:55Z): the operator refuses any
research / marketing surface not fully Hapax-automated. The original
alphaXiv design required an operator-approval gate during the
"initial period" before transitioning to full autonomy. That
trial-period pattern is itself the violated pattern — it is a
HITL-gated workflow indistinguishable from "operator reviews each
LLM comment before posting."

### Insufficiency of governance-shape work

PR #1444 shipped an `alphaxiv-comments` allowlist contract that scopes
which targets *could* be touched were the surface tractable; it does
not make the surface tractable. The allowlist is necessary but not
sufficient. With both the TOS prohibition and the constitutional
HITL-gate refusal active, no allowlist contract reaches the surface.

## Daemon-tractable boundary

Whatever academic-credible cross-referencing alphaXiv was originally
proposed to deliver is now achieved via:

1. **DataCite RelatedIdentifier graph** — `IsCitedBy` / `References`
   edges from operator's Zenodo deposits to named-target paper DOIs
   (per `pub-bus-zenodo-related-identifier-graph`, shipped #1474).
2. **Cold-contact graph_touch_policy** — citation-graph-only touches
   (no direct outreach), ≤5 candidates per deposit, ≤3 per year per
   candidate (per `cold-contact-zenodo-iscitedby-touch`, shipped
   #1529).
3. **Refusal Brief** — this document, recording the alphaXiv refusal
   as data per drop-5 fresh-pattern §2.

The daemon does NOT engage with alphaXiv as a publication or comment
surface. Per refusal-as-data convention, the absence of an alphaXiv
client is itself the constitutional artefact.

## Lift conditions

### Type-A (structural lift)

If alphaXiv's community guidelines remove the LLM-generated-comment
prohibition. Probe URL:
`https://www.alphaxiv.org/community-guidelines`. Lift keyword: removal
of `LLM-generated` prohibition language.

### Type-B (constitutional lift)

If the operator removes `feedback_full_automation_or_no_engagement`
from MEMORY.md. Probe path:
`~/.claude/projects/-home-hapax-projects/memory/MEMORY.md`. Lift
condition: absence of the `feedback_full_automation_or_no_engagement`
entry.

Both type-A AND type-B must hold for the refusal to lift. The
`refused-lifecycle-conditional-watcher` daemon (when shipped) will
check both probes per its cadence policy.

## Cross-references

- cc-task vault note: `cold-contact-alphaxiv-comments.md`
- Surface registry: `agents/publication_bus/surface_registry.py`
  (`alphaxiv-comments`)
- RefusedPublisher subclass:
  `agents/publication_bus/publisher_kit/refused.py`
  (`AlphaXivCommentsRefusedPublisher`)
- Original mechanic source: drop-2 §3 mechanic #3
- PR #1444 (allowlist contract — governance-shape only, insufficient
  on its own)
