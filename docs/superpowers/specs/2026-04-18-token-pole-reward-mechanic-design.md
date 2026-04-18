# Token Pole Reward Mechanic — Design Spec

**Date:** 2026-04-18
**CVS Task:** #146 (paired with #147 qualifier rubric)
**Status:** Stub — design only, no implementation yet
**Research sources:**
- `/tmp/cvs-research-146.md` (reward mechanic design)
- `/tmp/cvs-research-147.md` (governance qualifier rubric — imported as input constraint)

---

## 1. Goal

Redirect the existing token pole from LLM-token-spend to a chat-contribution-driven reward surface. At pole-top, spew a vampire-survivor-style glyph explosion whose magnitude is proportional to the community depth that caused the climb, not raw throughput.

**Operator quote (2026-04-06, cited `/tmp/cvs-research-147.md:5`):**
> "research ways of determining those qualifiers that are actually healthy, not patronizing, not cheesy, not manipulative and actually likely to lead to positive results. The risks here are considerable."

**Operator quote (2026-04-18, cited `/tmp/cvs-research-146.md:5`):**
> Glyph spew at pole top; tokens spent in proportion to contributive, interesting, positive chat + subs + donations; scales like a video game.

The #147 qualifier rubric is an input constraint to #146. This spec imports §7 (disqualifiers) and §8 (evaluation rubric) of `/tmp/cvs-research-147.md` verbatim into the implementation plan.

---

## 2. Current State

**Renderer:** `agents/studio_compositor/token_pole.py` — 300×300 Cairo source, Vitruvian Man background, golden-spiral token path, 60-particle circle explosion on threshold (`/tmp/cvs-research-146.md:11`).

**Ledger:** `scripts/token_ledger.py` writes `/dev/shm/hapax-compositor/token-ledger.json` (`{total_tokens, total_cost_usd, components, pole_position, explosions, active_viewers, chat}`); pole reads `pole_position`, spawns on `explosions` increment (`/tmp/cvs-research-146.md:13`).

**What drives the pole today (token-ledger.json writers):**
- `director_loop.py:1815-1818` — LLM spend via `record_spend("director", ...)`.
- `scripts/album-identifier.py:74-82` — `record_spend("album-identifier", ...)`.
- `scripts/chat-monitor.py:261-271` — Superchat `$1→500 tokens of "gratitude"`, membership fixed 1000, per-batch Gemini classification spend.
- `scripts/chat-monitor.py:302-304` — `set_active_viewers` drives `threshold = 5000 * log2(1 + log2(1 + n))`.

The pole today moves on aggregate LLM spend that scales with chat volume + platform dollars, not on a purpose-built community-contribution accumulator.

---

## 3. Constitutional Constraints — 7 Ethical Principles

Imported from `docs/streaming/2026-04-09-garage-door-open-handoff.md §3.1`. Every PR touching the reward mechanic MUST preserve all seven:

1. **No per-author state** in ledger, accumulator, or derived artifacts. Author handles enter only as hashes (`chat_signals._count_unique_author_hashes` precedent).
2. **Measure structure, not quality** — T-tier structural classifier is the entire signal. No sentiment features.
3. **Transparent mechanics** — difficulty curve published to `/dev/shm/hapax-compositor/token-ledger.json` and visible in overlay; no surprise jackpots.
4. **Sub-logarithmic scaling** — pole threshold grows `log2(1 + log2(1 + n))` in active viewers; difficulty curve layers on top sub-linearly (§7 below).
5. **Never loss-frame** — visible pole position is monotonically non-decreasing across a session. Spend-down happens in the reward band only.
6. **No individual glyph attributable** to a specific viewer message; reveal as spew, not as dashboard.
7. **No sentiment reward** — flattery, exclamation, emoji-count, performative-niceness features are architecturally excluded. `config/sister-epic/patreon-tiers.yaml:78-80` already enforces `no_sentiment_reward: true` at config level.

Enforcement template: `chat_reactor.py` caplog test pattern (`/tmp/cvs-research-147.md:71`) — code emits no author/message text at any log level.

---

## 4. #147 Qualifier Rubric Integration

Imported wholesale from `/tmp/cvs-research-147.md §6-§8`:

**Contributive** (`/tmp/cvs-research-147.md:79-80`) — novelty, not on-topic. Embedding distance to prior-60s rolling chat context > `T_c` AND message contains reference token (URL, quoted source, research-vocabulary term, specific-referent question). Deterministic; LLM-optional validator.

**Interesting** (`/tmp/cvs-research-147.md:82-83`) — Shannon-surprise of message token distribution against chat-window prior > `T_i`. **No LLM.** Penalizes copy-paste, emote spam, acronym stacks automatically.

**Positive** (`/tmp/cvs-research-147.md:85-86`) — **negative-defined as absence of §7 disqualifier set.** Technical critique / skeptical question / correction all pass; hollow compliment fails via flattery filter. No sentiment axis.

**Deterministic payout** — contribution is `{0, 1, 2}` per message (C+I flags); positive is implicit gate, never adds. Token climb = `window_total / window_duration`. Spew fires deterministically on threshold, never variable-ratio (`/tmp/cvs-research-147.md:26`, variable-ratio is the load-bearing addictive mechanism and is structurally excluded).

**Disqualifiers** (`/tmp/cvs-research-147.md:94-103`, zero-contribution if any fires): flattery-without-substance, performative engagement (Levenshtein <5 repeats), brigading (N identical from N distinct in 30s), command-spam double-count, emote/ASCII/single-word, direct rubric-solicitation, out-of-band identity claims, messages containing non-operator PII.

**Subs/donations** are not classifier-gated — the platform's payment gesture already asserts their contributiveness (`/tmp/cvs-research-147.md:132-134`). Fixed increments per tier (§5 table below).

---

## 5. Two-Band Ledger Schema

**Band A — Qualifier Window Counters** (aggregate-only, `/tmp/cvs-research-147.md:142`):

```json
{
  "window_start": 1713446400.0,
  "window_duration_s": 60.0,
  "c_count": 3,
  "i_count": 7,
  "total_contribution": 9.0
}
```

No author, no message text, no stable viewer identifier. Qualifier verdicts stored as enums only.

**Band B — Reward Credits Pool** (new, drives spew magnitude, `/tmp/cvs-research-146.md:34-38`):

```json
{
  "reward_credits": 147.0,
  "last_explosion_credits_spent": 80,
  "difficulty_tier": "t2"
}
```

Accumulation: `delta = tier_weight * (0.5 + 0.5 * audience_engagement)` per qualifying message; tier weights from `agents/studio_compositor/chat_classifier.py` (`/tmp/cvs-research-146.md:44-49`):

| Source | Weight |
|---|---|
| T0-T3 (injection/harassment/spam/parasocial) | 0 |
| T4 structural_signal | 1 |
| T5 research_relevant | 3 |
| T6 high_value (citation/correction) | 8 |
| Sub / YouTube membership | 20 |
| Tier-2 sub / resub / gift | 40 |
| Donation $N | `min(200, 5*N)` |

Structural multiplier from `agents/studio_compositor/chat_signals.py::audience_engagement` (`/tmp/cvs-research-146.md:53`).

**Spend:** explosion consumes `N = base_cost * difficulty(t)` credits; unspent credits carry across explosions; pole position is independent (always ratchets up per principle 5).

**Exposure:** `shared/perceptual_field.py::PerceptualField.reward_state` — new field `{reward_credits, last_explosion_credits_spent, difficulty_tier}` so `DirectorLoop` and `TwitchDirector` can read for narrative framing (`/tmp/cvs-research-146.md:66`). No LLM call inside the accumulator — pure function over ledger state (grounding-exhaustive axiom: deterministic code outsourced by grounding move).

---

## 6. Glyph Particle System

Replace current 60-circle explosion in `token_pole.py::_spawn_explosion()` with credit-sized glyph spew (`/tmp/cvs-research-146.md:72-85`):

- **`GlyphParticle` subclass** with `glyph: str`, Pango PangoLayout rendered once at spawn, size scales with remaining life.
- **Font:** `Px437 IBM VGA 8x16` (already used in `agents/studio_compositor/homage/bitchx.py:96` and `legibility_sources.py:27`). Fallback chain: Terminus → Unscii → DejaVu Sans Mono.
- **Glyph pool:** VGA block glyphs (`░▒▓█▀▄▌▐▬`), math symbols (`⊕⊗∴∵∮∇`), arrows (`→↗⇒⟶`), Hapax Unicode (`◉◎●○◈◇◆`). **No emoji** — bitchx homage framework explicitly excludes emoji / anti-aliased / proportional-font output.
- **Palette:** Gruvbox Hard Dark accents from `docs/logos-design-language.md §3` — yellow `#fabd2f`, orange `#fe8019`, aqua `#8ec07c`, purple `#d3869b`, blue `#83a598`. Replaces current candy palette; theme-consistent with Logos design-language authority.
- **Physics:** keep vx/vy + gravity 0.2, friction 0.97, fade over 1.5s; add radial impulse proportional to credits_spent so big rewards look visibly bigger.
- **Count formula:** `n_particles = clamp(20, 400, floor(sqrt(credits_spent) * 3))` — sqrt keeps 5-credit sub and 400-credit donation storm visually distinct without melting the cairooverlay budget; cap 400 respects `BudgetTracker` frame ceiling.
- **Emit path:** ledger writes both `explosions += 1` and `last_explosion_credits_spent: N`; pole reads both and passes `N` into `_spawn_explosion(credits=N)`.

---

## 7. Difficulty Curve

Sub-linear scaling ~5× over 4h (`/tmp/cvs-research-146.md:89-106`):

```
difficulty(t_minutes_into_stream) =
    1.0                          if t <  15           # warm-up free zone
    1.0 + 0.05*(t-15)            if 15 <= t <  60    # linear 1.0→3.25
    2.25 + 0.02*(t-60)**1.1      if 60 <= t < 240    # gentle long-tail, caps ~5.0×
```

Multiplies `_threshold(active_viewers)` and explosion credit-cost. Prevents 3h-mark farming plateau ("keep typing to see glyphs").

Published to `/dev/shm/hapax-compositor/token-ledger.json::difficulty_tier` (enum `t0` / `t1` / `t2` / `t3`). Overlay renders small Px437 tier caption under pole — transparency kills Skinner box (principle 3). Reset on session boundary (`session_start` already in ledger).

---

## 8. File-Level Plan

**New:**
- `agents/studio_compositor/qualifier.py` — pure-function qualifier pipeline (disqualifier check → C/I evaluation → counter increments). Caplog-test-enforced no-author-no-text invariant.
- `tests/studio_compositor/test_qualifier.py` — rubric correctness (flattery-without-substance fixture, brigading fixture, novelty threshold, Shannon surprise).
- `tests/studio_compositor/test_token_ledger_reward.py` — two-band integrity, monotonic pole, credit spend-down, difficulty-tier publish.

**Modified** (`/tmp/cvs-research-146.md:142-148`):
- `scripts/token_ledger.py` — add `record_reward(tier, structural_multiplier, source)`, `consume_reward_credits(amount)`, `difficulty_tier(t)`, `last_explosion_credits_spent` field, `window_start/c_count/i_count/total_contribution` counters.
- `agents/studio_compositor/token_pole.py` — `GlyphParticle` class, Pango glyph pool, palette swap to Gruvbox, credits-sized spawn, difficulty-tier caption.
- `scripts/chat-monitor.py` — replace `record_spend("superchat"...)` with `record_reward(tier=SUB/DONATION, ...)`; wire qualifier.py into message loop.
- `shared/perceptual_field.py` — add `reward_state` field (dataclass).

**Unchanged:** `agents/studio_compositor/chat_classifier.py` (tiers are input), `config/sister-epic/patreon-tiers.yaml` (already enforces `no_sentiment_reward: true`, cite in PR).

---

## 9. Twitch EventSub — Orthogonal Follow-On (NOT v1)

`/tmp/cvs-research-146.md:109-121`. Currently only YouTube Live is wired (`scripts/chat-monitor.py` via `chat_downloader==0.2.8`). Twitch EventSub WebSocket + TMI IRC client is a future CVS task. Ship YouTube-only reward mechanic first; Twitch wiring lands later without architectural changes (same classify/tier/qualifier pipeline). No Twitch = no Twitch credits; pole still functions per principle 4 (sub-logarithmic scaling means platforms don't need clean summation).

---

## 10. Test Strategy

**Ledger integrity:**
- Monotonic pole position across 10k-message fuzz.
- Reward_credits can spend down but never negative.
- Two-band independence — pole climb unaffected by credit balance.
- Difficulty tier published at every state write.

**Redaction (constitutional, test-enforced):**
- Caplog test: no author handle, no message text, no PII at any log level across qualifier.py + token_ledger.py + token_pole.py (`/tmp/cvs-research-147.md:141`).
- Ledger JSON schema validation: reject any key that could carry per-author state.
- No qualifier verdict strings rendered on stream (internal-only gate, `/tmp/cvs-research-147.md:140`).

**Qualifier correctness:**
- Contributive fixtures: new URL + technical term → pass; "great paper, Hapax" → fail §7.1 flattery-without-substance.
- Interesting fixtures: Shannon-surprise threshold; copy-paste burst → fail.
- Disqualifier coverage: each of the 8 §7 items has a dedicated fixture.
- Subs/donations bypass classifier per `/tmp/cvs-research-147.md:132-134`.

**Frame-budget:** 400-particle stress case under `BudgetTracker` ceiling.

---

## 11. Open Questions

From `/tmp/cvs-research-147.md §9` — require operator review before v2:

1. **Positive signal shape:** stay negative-defined (absence of disqualifiers) or add constructive-critique positive-definition detector? Recommend start negative-only.
2. **Verdict auditability:** internal-only (recommended v1) or publish per-window `contributive_count` to a consent-bounded channel?
3. **Opt-out gesture:** surface a `!noscore` flag that zeroes contribution for self-identifying viewers, respecting consent without per-viewer contracts? Recommend shipping with v1.

Additional v1/v2 boundary questions:
4. T5 false-positive refinement — gate on embedding similarity to active `condition_id` to block "research keyword injection" credit-farming (`/tmp/cvs-research-146.md:131-134`)?
5. Classifier tier weights vs. prompt-inclusion tiers — decouple into separate layer?

---

## 12. Related Tasks

- **CVS #147** — qualifier rubric research, input to this spec (`/tmp/cvs-research-147.md`).
- **GDO handoff** — `docs/streaming/2026-04-09-garage-door-open-handoff.md §3.1` (7 ethical principles), §6.1 (chat-monitor systemd install).
- **Design language authority** — `docs/logos-design-language.md §3` (Gruvbox Hard Dark palette).
- **Chat classifier spec** — Bundle 9 §2.2-§2.6 (tier definitions), `agents/studio_compositor/chat_classifier.py`.
- **Precedent** — `sp-hsea-mg-001` (draft LLM output is not stream-ready content), `chat_reactor.py` (no per-author state template).
- **Axioms** — `interpersonal_transparency` (T0, weight 88), `it-irreversible-broadcast` (T0), `it-consent-001`, `management_governance` (weight 85).
- **Future** — Twitch EventSub wiring (orthogonal CVS task).
