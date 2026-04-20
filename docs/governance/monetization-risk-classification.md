---
date: 2026-04-20
status: active
authority: de-monet go-live gate 1 rubric (task #165)
plan-reference: docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md §2 Phase 2
research-reference: docs/research/2026-04-19-demonetization-safety-design.md §1.1
---

# Monetization Risk Classification

## Rubric

Every `CapabilityRecord` carries a `monetization_risk` annotation on its
`OperationalProperties`. The `MonetizationRiskGate` in
`shared/governance/monetization_safety.py` filters the affordance pipeline's
candidate pool based on this tag, so a capability whose output could
trigger YouTube monetization loss is blocked from recruitment unless the
active `Programme` explicitly opts it in.

Four levels:

| Level | Semantics | Filter behaviour |
|-------|-----------|------------------|
| `high` | Unfiltered profanity-eligible speech; raw-audio broadcast of non-provenanced music; graphic-content emitters; arbitrary third-party imagery. | **Unconditionally blocked.** Cannot be opted in by a Programme. Operator must use a curated-pipeline alternative for the same intent. |
| `medium` | Occasional-profanity narrative registers; reaction-content whose input is third-party; LLM-generated text with partial safety filtering; phone media metadata; third-party news/trademarks. | **Blocked unless** the active `Programme.monetization_opt_ins` set contains the capability name. |
| `low` | Content that is monetization-safe under normal circumstances but flagged for prudence (e.g., CC-BY-SA text like Wikipedia excerpts). | **Passes through.** Tagged for telemetry + audit. |
| `none` (default) | Perception/state-reading capabilities that do not emit content to the broadcast surface. | **Passes through.** Implicit default for the majority of the catalog. |

## Default assumption

Most of the capability catalog is perception (env.*, body.*, space.*,
digital.*, system.*, knowledge.vault_search, knowledge.episodic_recall,
knowledge.profile_facts, world.astronomy, world.weather_elsewhere,
world.music_metadata) or internal control (studio.*, node.*, shader_graph,
visual_chain). These do NOT emit to the broadcast surface and therefore
default to `none`. No explicit annotation is required; the
`OperationalProperties.monetization_risk` field defaults to `"none"`.

Only capabilities that can reach the livestream broadcast surface — by
speaking, by rendering text/images on visible surfaces, or by emitting
audio — require explicit non-default annotation.

## Explicit annotations (2026-04-20 audit)

### speech_production (medium)

Hapax TTS emission. `shared/speech_safety.py` redacts known slur forms
pre-TTS, persona constrains register (`agents/hapax_daimonion/persona.py`),
but the LLM remains the source-of-record for speech. Programme opt-in
governs broadcast surfaces. Declared in
`agents/hapax_daimonion/init_pipeline.py`.

### content.narrative_text (medium)

LLM-generated text rendered on the visible surface. Same argument as
speech_production — safety filter is partial, Programme gates broadcast.

### knowledge.web_search (medium)

Returns third-party web content; may contain brand-name / trademarked /
copyrighted text. Programme opt-in required.

### knowledge.image_search (high)

Open-web image search returns arbitrary third-party imagery. Both
Content-ID fingerprint risk and potential graphic content. **Unconditionally
blocked from broadcast.** Operator must resolve images via a curated
pipeline instead.

### knowledge.wikipedia (low)

Wikipedia text is CC-BY-SA licensed; monetization-safe for short
excerpts but tagged low for prudence + telemetry.

### world.news_headlines (medium)

Third-party headlines may include brand-name / political / graphic
content. Programme opt-in required for broadcast.

### social.phone_media (medium)

Phone media metadata (song/podcast/video titles) may surface third-party
copyrighted titles; broadcasting titles is generally safe (fair use)
but Programme should opt in for confidence.

### vinyl_chain.* (all 9 dims, medium)

Mode D granular-wash capability for Content-ID defeat on vinyl source.
The capabilities are medium-risk because the intended use **is** to
broadcast granular-processed third-party vinyl audio; the safety comes
from the granular re-synthesis defeating the fingerprint. A Programme
whose `monetization_opt_ins` contains `mode_d_granular_wash` declares
the operator's intent to engage Mode D on broadcast surfaces.

## Adding new capabilities

When you add a new `CapabilityRecord`:

1. Ask: does this capability's output ever reach the broadcast surface?
   - If no → leave `monetization_risk` at default (`"none"`).
   - If yes → continue.
2. Can the output contain third-party content (music, video, images,
   text, branded / trademarked names)?
   - If yes → at least `medium`. If also graphic / uncurated → `high`.
3. Is the output LLM-generated?
   - If partially filtered (speech_safety, persona, etc.) → `medium`.
   - If fully pre-vetted (templated phrases only, curated word list) → `low`.
4. Set `risk_reason` to a one-sentence rationale that cites which
   filter/pipeline/justification applies. Future auditors need this.

## Future work (post-go-live)

- **Ring 2 pre-render classifier** (plan Phase 3): a `local-fast` LLM
  pass that inspects the rendered text/audio about to emit and raises
  a `content.flagged` impingement if it catches something the capability-
  level annotation missed. Currently deferred; the capability-level
  classification ships first.
- **CI-blocking catalog-coverage test**: a pytest that asserts every
  registered record has been explicitly audited (even the `"none"`
  ones). Deferred because it touches ~100 records; ships after the
  higher-leverage surfaces are annotated.
- **Programme opt-in UX**: when operator creates a Programme, surface
  the list of medium-risk capabilities the Programme could opt into,
  so the opt-in decision is explicit rather than implicit.
