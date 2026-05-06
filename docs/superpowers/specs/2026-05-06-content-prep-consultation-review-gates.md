# Content-Prep Consultation And Review Gates

Status: implemented in deterministic review and artifact validation.

## Purpose

Professional content prep cannot rely on improvised model taste. Before a
segment is drafted or accepted, prep must consult explicit role standards,
exemplars, counterexamples, counter-references, and quality ranges. These
materials are calibration surfaces for judgment, not scripts and not an
expert-rule system.

The consultation layer exists to prevent two failures at once:

- prompt-vibes: the model improvises a segment from generic host instincts.
- rule crutching: the model mechanically satisfies labels while the segment
  still lacks a live bit, source consequence, or visible/doable counterpart.

## Artifact Shape

Prepared segment artifacts carry four review-facing objects:

- `consultation_manifest`: role standard refs, exemplar refs,
  counterexample refs, quality range refs, and advisory-only consultation refs.
- `source_consequence_map`: per-beat evidence that a source changes a claim,
  ranking, contrast, pause, or visible action.
- `live_event_viability`: evidence that the segment is more than polished prose:
  it has a role shape, a source-dependent turn, multiple visible/doable action
  kinds, and a reachable excellent range.
- `readback_obligations`: proposal-only layout obligations that runtime
  readback must witness before layout success can be claimed.

All four objects are advisory prep/review metadata. They do not grant source,
layout, broadcast, script, or runtime authority.

## Eligibility Gates

Eligibility gates are hard safety and integrity floors. A segment that fails
any of these is not eligible for excellence selection:

- no Qwen or fallback model path in content prep.
- resident Command-R route only; no unload, reload, or swap workflow.
- artifact authority remains `prior_only`.
- provenance hashes bind raw artifact, source packet, prompt packet, and LLM
  phase receipts.
- prepared layout metadata is proposal-only and cannot command runtime layout.
- no static/default layout success for responsible hosting.
- no camera or spoken-only laundering until witnessed runtime loops exist.
- no public/broadcast bypass or runtime-looking success fields in prep.
- no fake human personage: feeling, empathy, concern, taste, memory, trust,
  private intuition, selfhood, or "human host" leakage.
- no detector-trigger theater: a detector, metric, readback, gauge, or sensor
  cannot be claimed as proof unless the visible/doable payload is receipted.
- no framework vocabulary in spoken script, including internal review terms
  such as "eligibility gate", "excellence selection", "source consequence", or
  "consultation_manifest".

Eligibility is not approval. It means the artifact is safe enough to judge.

## Excellence Selection

Excellence selection asks whether the canary is good enough to seed the next
nine. It requires positive evidence, not just absence of failure:

- role-standard fit: the selected role has consulted standards, exemplars,
  counterexamples, and quality ranges.
- live bit viability: the segment would be visibly or practically eventful on
  a livestream, not merely fluent narration.
- source consequence: cited sources alter a claim, ranking, contrast, pause,
  or action.
- non-anthropomorphic force: the voice is forceful and intelligible to humans
  without pretending to have human feelings, memories, preferences, empathy,
  or private intuition.
- no detector theater: claims about what changed are tied to real visual or
  doable payloads, not just diagnostic readbacks.
- layout responsibility: every spoken claim that asks the audience to see or
  do something has proposal-only obligations that runtime can witness.

Team receipts must bind this positive evidence to the exact raw artifact hash,
programme id, and iteration id. Reusable approvals or stale checkbox receipts
do not pass.

## Prompt-Facing Vocabulary Boundary

The implementation may name review concepts in code, tests, docs, and receipts.
Prompt-facing drafting surfaces should translate them into craft language:

- Say "the source changes the claim" rather than exposing
  `source_consequence_map`.
- Say "make the visible or doable counterpart clear" rather than exposing
  "layout responsibility gate".
- Say "consult role examples and counterexamples" rather than exposing
  internal receipt schemas.

This prevents the model from optimizing for review jargon instead of segment
quality.

## External Knowledge Recruitment

When local know-how is thin, content prep should recruit available external
guidance or sources, evaluate that material, and convert it into priors and
receipts before drafting. External guidance can shape criteria, examples,
counterexamples, and source packets. It never transfers authority to the
source, the script, static defaults, prep metadata, or runtime commands.

Freshness must be selected by topic:

- current: news, live products, schedules, law, pricing, active standards.
- rolling: active scholarly or technical debates.
- evergreen: stable role craft, archival texts, durable genre forms.
- Hapax-constitutional/operator-local: operator corrections, vault notes,
  runtime authority rules, and local design rubrics.

## Publication And Ledger

The predictive evaluation ledger is the durable Obsidian record for this
design problem. After implementation changes, it must be republished through
the vault publication bus, not merely edited locally. The canonical units for
automatic reposting live in `systemd/units/`:

- `hapax-segment-prep-ledger-publish.path`
- `hapax-segment-prep-ledger-publish.service`

The publisher queues the ledger only; it does not generate segments, call
models, alter model residency, or command runtime layout.
