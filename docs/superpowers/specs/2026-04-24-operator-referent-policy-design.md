# Operator Referent Policy — Design

**Status:** Ratified 2026-04-24 by operator directive (3 decisions confirmed: canonical spelling `Oudepode`, sticky-per-utterance picker, new implication under `single_user`).

**Session:** epsilon. One foundation PR + coordination notes to alpha (ytb-008) and beta (ytb-010).

## Problem

Hapax references the operator by a single string (`Oudepode`, legal name, or `"the operator"`) depending on surface. Directive 2026-04-24: in **non-formal contexts** — livestream narration, direct voice address, rendered captions, social-surface posts, research-instrument metadata — the operator must be referred to using one of four **equally-weighted** referents:

```
["The Operator", "Oudepode", "Oudepode The Operator", "OTO"]
```

Legal name remains in use for **formal-address-required** contexts only (consent contracts, axiom precedents, formal partner-in-conversation role declaration in persona, git author metadata if ever set).

Canonical spelling is `Oudepode` (with `e`). Already in `shared/speech_lexicon.py` with IPA `uˈdɛpoʊdeɪ`; codebase is consistent; operator's directive spelled `Oudopode` as a typo, corrected in conversation.

## Design decisions (ratified)

| Decision | Choice | Rationale |
|---|---|---|
| Canonical spelling | `Oudepode` (with `e`) | Pre-existing lexicon + codebase + memory all use `Oudepode` |
| Picker regime | **Sticky-per-utterance** | One referent per director LLM call; rotates across calls; optional reset at VOD boundary |
| Governance container | **New implication** under `single_user` | Audit-verifiable via axiom sweep; prevents silent drift when new narration sites land |

## Architecture

### Two contexts, two functions

The `formal` / `non-formal` cleavage already exists architecturally:

- **Formal** — `logos.voice.operator_name()` reads the operator's legal name from profile. Used by: daimonion persona `_operator_partner_block()` ("The partner in conversation is {name}"), briefing/orientation formal surfaces, notification templates declaring relational role. **Unchanged by this design.**
- **Non-formal** — narration, commentary, scope nudges, captions, social posts, YouTube metadata, chat attribution of operator utterances. **Routes through the new picker.**

### The picker

`shared/operator_referent.py`:

```python
REFERENTS = ("The Operator", "Oudepode", "Oudepode The Operator", "OTO")

class OperatorReferentPicker:
    """Equal-weighted picker with sticky-per-utterance determinism.

    Stateless by default. When a caller wants sticky behavior within a
    single LLM call or narration construction, they pass a seed (e.g., an
    utterance id, a director tick count, a VOD boundary timestamp) and
    receive a deterministic choice for that seed.
    """

    @staticmethod
    def pick(seed: str | None = None) -> str:
        if seed is None:
            return random.choice(REFERENTS)
        # Deterministic: hash(seed) % 4
        idx = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(REFERENTS)
        return REFERENTS[idx]

    @staticmethod
    def pick_for_tick(tick_id: int) -> str:
        return OperatorReferentPicker.pick(f"director-tick-{tick_id}")
```

Zero external deps. Zero state. Tests prove equal-weight distribution over N=10_000 seeds and stability (same seed → same referent).

### LLM prompt integration (sticky-per-utterance realized)

The director loop picks ONE referent at the top of its system-prompt construction and injects it into the prompt as a style rule:

```
In this narration tick, refer to the operator EXCLUSIVELY as: "Oudepode The Operator".
Do not use their legal name in livestream narration. Do not mix other forms
(e.g., "OTO") in this tick. Use this form consistently throughout your output.
```

The picker is seeded on `tick_id` (or VOD-segment id when ytb-007 rotation occurs), so each director tick is internally consistent, varies across ticks, and aligns with VOD-boundary rotation when present.

### Speech lexicon entries

Three new entries (`Oudepode` already canonical):

| Term | IPA | Rationale |
|---|---|---|
| `Oudepode` | `uˈdɛpoʊdeɪ` | **Already canonical** — no change |
| `OTO` | `oʊ tiː oʊ` | Letter-by-letter acronym pronunciation (NATO-style, not word-form) |
| `The Operator` | not required — standard English words, misaki handles natively |
| `Oudepode The Operator` | `Oudepode` gets overridden via existing regex; "The Operator" flows natively |

Only `OTO` needs a new lexicon entry. The existing lexicon pattern (longest-first alternation) handles `Oudepode The Operator` automatically — the `Oudepode` prefix gets wrapped; `The Operator` flows through misaki's default G2P.

### Axiom implication

New file: `axioms/implications/non-formal-referent-policy.yaml`

```yaml
implication_id: su-non-formal-referent-001
axiom_id: single_user
version: 1
tier: T1
enforcement: review
canon: purposivist
mode: sufficiency
level: system
text: |
  In non-formal contexts — livestream narration, voice commentary,
  rendered text/captions, social-surface posts, YouTube metadata,
  chat attribution of operator utterances — the operator is referred
  to exclusively by one of the four ratified referents: "The Operator",
  "Oudepode", "Oudepode The Operator", "OTO". The legal name is
  reserved for formal-address-required contexts only (consent contracts,
  axiom precedents, partner-in-conversation role declaration, git
  author metadata).
scope:
  applies_to:
    - director_narration
    - daimonion_spontaneous_speech
    - cccombiner_captions
    - youtube_video_metadata
    - cross_surface_federation_posts
    - chat_attribution_of_operator_messages
    - scope_nudges_and_prompt_framing
  excludes:
    - persona._operator_partner_block (formal relational declaration)
    - axioms/contracts/ subject_name fields
    - axioms/precedents/*.yaml
    - git author metadata
    - operator profile persistence
authority:
  ratified_by: operator
  ratified_at: "2026-04-24T00:30Z"
  ratification_vehicle: "epsilon session direct operator confirmation"
cross_references:
  - shared/operator_referent.py (picker)
  - shared/speech_lexicon.py (OTO IPA)
  - logos/voice.py (formal operator_name() unchanged)
```

## Call sites

### Runtime-visible (must change)

`agents/studio_compositor/director_loop.py`:

| Line | Context | Change |
|---|---|---|
| 996 | Vinyl narration f-string | `f"{referent} is spinning vinyl: …"` |
| 1000 | Music queue narration f-string | `f"Music is playing from {referent}'s curated queue: …"` |
| 1043 | Activity-capability prompt text | Generic `"the operator"` + injected style rule |
| 1956 | Audience framing prompt | `f"{referent} is always present in the room as your first-class audience. Whatever moves you pick, they see them …"` |
| 2070 | Chat attribution when author is `oudepode` | `f'{referent}: "{text}"'` |
| 2492 | Scope-nudge prompt text | `f"the music {referent} is playing …"` |

All six sites take the tick-seeded picker result constructed once per `_build_reactor_context()` call.

### Historical comments (housekeeping, not critical)

Lines 576, 992, 998–999, 1953 are comments describing prior operator directives. Leave as-is — they're pre-ratification historical record, editing them would destroy traceability.

### Unchanged (formal contexts)

- `logos/voice.py:operator_name()` — legal name, formal surfaces
- `agents/hapax_daimonion/persona.py:_operator_partner_block()` — partner-in-conversation relational declaration (formal role)
- `axioms/contracts/*.yaml`, `axioms/precedents/*.yaml` — operator legal name where required
- `agents/soundcloud_adapter/__main__.py:256`, `agents/local_music_player/programmer.py:14,211` — internal comments describing historical directives, no runtime effect

### Downstream (coordination notes, not shipped in this PR)

- **ytb-008 research-instrument metadata composer (alpha)** — must consume the picker from day one; seed on `video_id` for per-VOD consistency
- **ytb-010 cross-surface federation (beta)** — same pattern; seed on broadcast-session id
- **ytb-007 broadcast orchestrator (delta)** — already-shipped `metadata_seed.compose()` should route title/description generation through picker as a small follow-up

## Non-goals

- Does not modify profile storage or legal-name infrastructure.
- Does not touch wards (token-pole, HOMAGE, album-id, vitruvian) — verified to have no hardcoded operator name; consent-safe by design.
- Does not touch officium briefing desk, Logos UI, email/calendar agents — all formal-context surfaces.
- Does not introduce new picker regimes (fully-random-per-reference or sticky-per-session were considered and rejected).

## Acceptance

1. Fresh ruff + pyright clean.
2. 21+ picker unit tests (equal-weight distribution, stability, invalid seed handling, edge cases).
3. Director loop smoke test: construct 100 reactor contexts over a simulated tick range, verify each context uses exactly ONE of the four referents, and over 100 ticks each referent appears within 25 ± 10 times (χ² bound).
4. New implication yaml passes `shared.axiom_scan` (existing regression test).
5. `apply_lexicon("OTO")` produces `[OTO](/oʊ tiː oʊ/)`.
6. Live director narration (post-deploy screenshot) shows a non-Oudepode referent when picker rotates.

## Rollout

Single PR: spec + plan + picker + lexicon + implication + director_loop.py fixes + tests. No feature flag — this is a policy change that should land atomically. Rebuild timer picks up the director in ≤5 min.

Three coordination notes filed in `~/.cache/hapax/relay/`:
- `epsilon-to-alpha-2026-04-24-referent-policy-for-ytb-008.md`
- `epsilon-to-beta-2026-04-24-referent-policy-for-ytb-010.md`
- `epsilon-to-delta-2026-04-24-referent-policy-ytb-007-followup.md`
