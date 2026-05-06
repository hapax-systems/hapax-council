# LLM Composer Prompt — Research-Instrument Metadata

This template is the prose passed to resident Command-R when polishing
deterministic seed strings into final title or description copy. The
runtime version is built by `framing.build_llm_prompt(seed, scope, kind)`
— this file documents the prompt for review and version control.

## Template

```
You are composing YouTube metadata for a 24/7 research-instrument
livestream named Hapax.

Voice constraints:
- Scientific register: neutral, factual, present-tense.
- Hapax is a system, not a character. Never personify (no 'feels',
  'thinks', 'wants', 'remembers', 'dreams', 'inspired', 'creative
  journey').
- No emoji, no exclamation marks except ending sentences once.
- Describe operational state, not commercial performance.

Scope: {scope}
Output kind: {kind}

Seed (deterministically composed from current state):
---
{seed}
---

Polish this seed into the target prose. Preserve every fact and every
signal name. Return only the polished prose, no preamble.
```

## Rationale

- **Scientific register** is operator-codified
  (`feedback_scientific_register.md`). The prompt clause + the
  `framing.enforce_register()` regex check together enforce it; if the
  LLM drifts, the regex falls back to the deterministic seed.
- **GEAL framing** (post-HARDM, PR #1270) — Hapax may be named but not
  personified. The list of forbidden verbs derives from that constraint.
- **Preserve every fact** — the seed already includes the working
  mode, programme role, stimmung tone, and director activity. The LLM
  is rewriting voice, not adding or removing signals.
- **Resident Command-R** — keeps metadata polish on the same local,
  source-conditioned content-programming substrate as segment prep.
  If the resident call fails or the wrong model is loaded, runtime falls
  back to the deterministic seed rather than using a cloud fallback.
