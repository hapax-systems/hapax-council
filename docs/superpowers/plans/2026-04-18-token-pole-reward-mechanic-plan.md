# Token Pole Reward Mechanic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redirect token pole input from LLM-token-spend to chat-contribution (T4+/T5/T6 tiers × qualifier rubric); add two-band ledger (pole position + spendable reward_credits); vampire-survivor glyph particle system on threshold reach; sub-linear difficulty curve.

**Architecture:** Import #147 rubric verbatim (Contributive=novelty, Interesting=Shannon-surprise, Positive=absence-of-disqualifier); preserve existing 7 ethical principles from GDO handoff §3.1; new `qualifier.py` with `AxiomCompliantQualifier`; two-band ledger in `token_ledger.py`; Px437 + Gruvbox glyph particle renderer.

**Tech Stack:** Python 3.12+, chat_classifier T0-T6 tiering, Cairo (Px437 IBM VGA 8×16), NumPy (particle physics)
---

## Plan Philosophy

- **Bite-sized steps** — every task is 2–5 minutes of focused work, commits frequent
- **TDD** — write failing test first for every behavior, then implement, then refactor
- **No placeholders** — every code block is runnable; every assertion has a real fixture
- **Constitutional gating** — each phase ends with a redaction caplog test; a failing caplog gate blocks the phase
- **Spec fidelity** — §§ references in this plan map to `docs/superpowers/specs/2026-04-18-token-pole-reward-mechanic-design.md`

## Prerequisites

- [ ] Read `docs/superpowers/specs/2026-04-18-token-pole-reward-mechanic-design.md` end-to-end
- [ ] Read `/tmp/cvs-research-146.md` §§3–7 (ledger, spend, particles, difficulty)
- [ ] Read `/tmp/cvs-research-147.md` §§6–8 (qualifier operational definitions, disqualifiers, rubric pseudocode)
- [ ] Read `docs/streaming/2026-04-09-garage-door-open-handoff.md §3.1` (7 ethical principles)
- [ ] Confirm `agents/studio_compositor/chat_classifier.py` T0–T6 tier names and thresholds
- [ ] Confirm `agents/studio_compositor/chat_signals.py::audience_engagement` return shape
- [ ] Confirm `config/sister-epic/patreon-tiers.yaml:78-80` still contains `no_sentiment_reward: true`
- [ ] Verify `uv sync --all-extras` succeeds at head of `main`
- [ ] Verify `uv run pytest tests/studio_compositor/ -q` is green at head of `main`

---

## Phase 1 — Qualifier Module

Pure-function qualifier: disqualifier scan → novelty via embedding distance → Shannon-surprise → aggregate counters. No LLM. No author field. No message text past the function boundary.

### Task 1.1 — Create qualifier skeleton + enum types

**Files:** `agents/studio_compositor/qualifier.py` (new)

- [ ] Create file with module docstring citing `/tmp/cvs-research-147.md §6-§8`
- [ ] Add enum `Disqualifier(StrEnum)` with 8 members mapped to §7 items: `FLATTERY`, `PERFORMATIVE`, `BRIGADING`, `COMMAND_SPAM`, `EMOTE_ONLY`, `META_SOLICITATION`, `IDENTITY_CLAIM`, `CONTAINS_PII`
- [ ] Add `@dataclass(frozen=True)` `QualifierVerdict` with `contributive: bool`, `interesting: bool`, `disqualifier: Disqualifier | None`, `contribution: float` (0.0/1.0/2.0)
- [ ] Add `@dataclass(frozen=True)` `WindowCounters` with `window_start: float`, `window_duration_s: float`, `c_count: int`, `i_count: int`, `total_contribution: float`
- [ ] Add module-level constants `T_CONTRIBUTIVE = 0.35` (cosine distance) and `T_INTERESTING = 3.5` (bits)

**Commit:** `feat(qualifier): add module skeleton with verdict + counter dataclasses`

### Task 1.2 — Unit test: enum + dataclass construction

**Files:** `tests/studio_compositor/test_qualifier.py` (new)

- [ ] Write test `test_verdict_defaults_to_zero_contribution` constructing `QualifierVerdict(False, False, None, 0.0)`
- [ ] Write test `test_verdict_is_frozen` asserting `dataclasses.FrozenInstanceError` on mutation
- [ ] Write test `test_window_counters_roundtrip_json` serializing via `dataclasses.asdict` → `json.dumps` → `json.loads`, asserting no author/text keys leak in
- [ ] Run: `uv run pytest tests/studio_compositor/test_qualifier.py -q`
- [ ] Expected output: `3 passed`

**Commit:** `test(qualifier): dataclass construction + frozen + serialization shape`

### Task 1.3 — Implement disqualifier scanner

**Files:** `agents/studio_compositor/qualifier.py`

- [ ] Add `def scan_disqualifiers(text: str, author_hash: str, recent_hashes: Sequence[str], recent_hash_distances: Sequence[int]) -> Disqualifier | None`
- [ ] FLATTERY: lowercase-match against regex union of flattery terms `(great|awesome|love|amazing)\s+(stream|hapax|you)` AND text has no URL AND no technical-vocabulary hit
- [ ] PERFORMATIVE: any `hash_distance < 5` for same `author_hash` in 5-min buffer (uses Levenshtein, import from `rapidfuzz`)
- [ ] BRIGADING: ≥5 identical texts from ≥5 distinct `author_hash` within 30s (caller supplies window)
- [ ] COMMAND_SPAM: text starts with `!` AND matches a preset keyword in `chat_reactor.py::PRESET_KEYWORDS` (import, don't duplicate)
- [ ] EMOTE_ONLY: all tokens ∈ `{POGGERS, W, L, lol, lmao, omg, ...}` OR length-after-strip ≤ 3
- [ ] META_SOLICITATION: regex `\b(contributive|interesting|qualifier|rubric)\b`
- [ ] IDENTITY_CLAIM: regex `\b(I('?m| am)\s+a\s+(phd|professor|engineer|senior|lead))`
- [ ] CONTAINS_PII: integrate existing `shared/pii.PII_PATTERNS` scanner (already present in codebase for consent)

**Commit:** `feat(qualifier): implement 8-rule disqualifier scanner`

### Task 1.4 — Test each disqualifier with dedicated fixture

**Files:** `tests/studio_compositor/test_qualifier.py`

- [ ] `test_flattery_without_substance_fires` with input `"great stream Hapax!"` → `Disqualifier.FLATTERY`
- [ ] `test_flattery_with_url_passes` with input `"great stream, Hapax — see https://arxiv.org/abs/2401.12345"` → `None`
- [ ] `test_performative_fires_on_levenshtein_under_5` with prior buffer containing near-duplicate
- [ ] `test_brigading_fires_on_5_identical_from_5_authors_in_30s`
- [ ] `test_command_spam_fires` with `"!aurora"` and aurora in PRESET_KEYWORDS
- [ ] `test_emote_only_fires` on `"POGGERS"`, `"W"`, `"lol"`
- [ ] `test_meta_solicitation_fires` on `"is this contributive?"`
- [ ] `test_identity_claim_fires` on `"I'm a PhD in ML"`
- [ ] `test_pii_fires` on a fixture containing an address-shaped string
- [ ] Run: `uv run pytest tests/studio_compositor/test_qualifier.py -q`
- [ ] Expected output: `12 passed`

**Commit:** `test(qualifier): coverage for all 8 disqualifiers + 1 negative`

### Task 1.5 — Implement Shannon-surprise (interestingness)

**Files:** `agents/studio_compositor/qualifier.py`

- [ ] Add `def shannon_surprise(text: str, prior_tokens: Counter[str]) -> float`
- [ ] Tokenize via `text.lower().split()` (keep deterministic, no NLP lib)
- [ ] For each token: `p = prior_tokens.get(tok, 0.5) / max(1, prior_tokens.total())`; surprise = `-log2(max(p, 1e-6))`
- [ ] Return sum of per-token surprise divided by token count (average bits/token)
- [ ] Guard against empty input → return `0.0`

**Commit:** `feat(qualifier): Shannon-surprise scorer over rolling token prior`

### Task 1.6 — Test Shannon-surprise

**Files:** `tests/studio_compositor/test_qualifier.py`

- [ ] `test_shannon_surprise_zero_for_exact_prior` — prior = {"the": 100}, text = "the the the" → ~0 bits
- [ ] `test_shannon_surprise_high_for_novel` — prior = {"the": 100}, text = "pyrophoric zinc autocatalysis" → ≥ `T_INTERESTING` bits
- [ ] `test_shannon_surprise_handles_empty` returns 0.0
- [ ] Run and expect `3 passed` + the previous `12 passed` still green

**Commit:** `test(qualifier): Shannon-surprise behavior + empty guard`

### Task 1.7 — Implement contributiveness via embedding distance

**Files:** `agents/studio_compositor/qualifier.py`

- [ ] Add `def is_contributive(text: str, prior_context_embed: np.ndarray, embed_fn: Callable[[str], np.ndarray], reference_tokens: Iterable[str]) -> bool`
- [ ] Novelty: `1 - cosine_similarity(embed_fn(text), prior_context_embed) > T_CONTRIBUTIVE`
- [ ] Reference-token requirement: URL regex OR quoted-source regex (`"..."`) OR any token in `reference_tokens` (loaded from `shared/research_vocabulary.py` — already exists per §2 of the spec) OR message ends `?` with noun-phrase before it (noun regex = `\b[A-Z][a-z]+\b`)
- [ ] Both must be true; return bool

**Commit:** `feat(qualifier): contributive = novelty × reference-token`

### Task 1.8 — Test contributiveness

**Files:** `tests/studio_compositor/test_qualifier.py`

- [ ] Use `shared/embeddings.get_embedder()` (already wired to nomic-embed-cpu via Ollama) as `embed_fn`
- [ ] `test_contributive_with_url_and_novelty_passes` — unrelated prior + URL in text
- [ ] `test_contributive_without_reference_token_fails` — unrelated prior + plain prose
- [ ] `test_contributive_repeat_of_prior_fails` — text IS prior → cosine ~1 → distance < T_CONTRIBUTIVE
- [ ] `test_contributive_with_specific_question_passes` — "what about Horton-Wohl 1956?"
- [ ] Mark embed tests with `@pytest.mark.llm` so default suite stays deterministic (registry-gated)
- [ ] Run: `uv run pytest tests/studio_compositor/test_qualifier.py -q -m "not llm"` expect `18 passed`
- [ ] Run: `uv run pytest tests/studio_compositor/test_qualifier.py -q` expect `22 passed`

**Commit:** `test(qualifier): contributiveness with real + stub embedder`

### Task 1.9 — Implement `AxiomCompliantQualifier` assembly function

**Files:** `agents/studio_compositor/qualifier.py`

- [ ] Add `class AxiomCompliantQualifier`
- [ ] `__init__(self, embed_fn, reference_tokens, window_duration_s=60.0)`; stores rolling `Counter[str]` + prior context buffer
- [ ] `evaluate(self, text: str, author_hash: str, now: float) -> QualifierVerdict`:
  1. `dq = scan_disqualifiers(...)`; if non-None → return `QualifierVerdict(False, False, dq, 0.0)`
  2. `c = is_contributive(...)`
  3. `i = shannon_surprise(...) > T_INTERESTING`
  4. `contribution = float(c) + float(i)`
  5. return `QualifierVerdict(c, i, None, contribution)`
- [ ] `update_window(self, verdict: QualifierVerdict) -> WindowCounters`: advances window, increments counters, rolls over when `now - window_start > window_duration_s`
- [ ] **Never** accept, store, or return `text` or `author_hash` past function-scope. Counters are aggregate-only.

**Commit:** `feat(qualifier): AxiomCompliantQualifier orchestrator + rolling window`

### Task 1.10 — Constitutional caplog test (redaction enforcement)

**Files:** `tests/studio_compositor/test_qualifier.py`

- [ ] `test_no_author_in_logs(caplog)` — run 100 synthetic messages through qualifier with author hash `"handle_42"`, assert `"handle_42"` not in `caplog.text` at any level (DEBUG included)
- [ ] `test_no_message_text_in_logs(caplog)` — similar for a distinctive token `"PYROPHORIC_ZINC_TOKEN"`
- [ ] `test_no_pii_in_logs(caplog)` — feed an address-shaped fixture, assert absent from caplog
- [ ] Run: `uv run pytest tests/studio_compositor/test_qualifier.py::test_no_author_in_logs -q`
- [ ] Expected: `1 passed`; full file: `25 passed`

**Commit:** `test(qualifier): constitutional caplog redaction enforcement`

---

## Phase 2 — Chat Classifier Wiring

Qualifier sits **below** the classifier: classifier returns T0–T6, qualifier adds a tier bump only for T4+. T0–T3 are already dropped; qualifier never runs on them.

### Task 2.1 — Test: classifier+qualifier integration contract

**Files:** `tests/studio_compositor/test_chat_classifier_qualifier.py` (new)

- [ ] `test_t3_parasocial_never_calls_qualifier` — mock qualifier, assert `.evaluate` not called when classifier returns T3
- [ ] `test_t4_structural_plus_contributive_bumps_to_t5_weight` — T4 base weight 1 + contribution 2 → effective weight 3 (T5 equivalent)
- [ ] `test_t5_plus_contributive_stays_t5` — no double-count; bump only applies at T4 boundary
- [ ] `test_t6_passes_through_unchanged` — T6 already 8 weight; qualifier adds 0
- [ ] Run: expect `4 failed` (not implemented yet)

**Commit:** `test(classifier): qualifier bump contract failing tests`

### Task 2.2 — Implement tier bump in `chat_classifier.py`

**Files:** `agents/studio_compositor/chat_classifier.py`

- [ ] Inject `AxiomCompliantQualifier` via constructor (optional dep; default `None` = behavior unchanged)
- [ ] After tier classification: if `tier in {T4}` and `qualifier is not None`: call `qualifier.evaluate(...)`; if `contribution >= 2.0`: bump effective `weight` from 1 → 3
- [ ] Add `effective_weight` field to classifier output dataclass (preserving raw `tier` for observability)
- [ ] Never pass text/author past qualifier boundary; classifier already has hash-only access per `chat_signals._count_unique_author_hashes`

**Commit:** `feat(classifier): conditional T4→T5-weight bump via qualifier`

### Task 2.3 — Run integration tests green

- [ ] Run: `uv run pytest tests/studio_compositor/test_chat_classifier_qualifier.py -q`
- [ ] Expected: `4 passed`
- [ ] Run full classifier suite: `uv run pytest tests/studio_compositor/test_chat_classifier.py -q`
- [ ] Expected: no regressions

**Commit:** `fix(classifier): regressions from qualifier integration (if any)` (skip if none)

### Task 2.4 — Caplog integration test

**Files:** `tests/studio_compositor/test_chat_classifier_qualifier.py`

- [ ] `test_no_author_leak_in_classifier_path(caplog)` — feed 50 messages with author hash `"classifier_probe_77"` through classifier+qualifier pipeline; assert hash absent from caplog
- [ ] `test_no_message_text_leak(caplog)` — feed distinctive token `"CLASSIFIER_PROBE_XYZZY"`; assert absent
- [ ] Run: expect `2 passed`

**Commit:** `test(classifier): caplog no-author-leak gate on integrated path`

---

## Phase 3 — Two-Band Ledger

Separate pole position (monotonic, never loss-frame) from reward_credits pool (spend-down). Preserve existing writers (director_loop, album-identifier) — pole still moves on aggregate spend, rewards scale with community depth.

### Task 3.1 — Test: two-band schema + migration

**Files:** `tests/studio_compositor/test_token_ledger_reward.py` (new)

- [ ] `test_ledger_has_reward_band_fields` — open fresh ledger, assert keys `{reward_credits, last_explosion_credits_spent, difficulty_tier}` present with defaults `0.0, 0, "t0"`
- [ ] `test_ledger_has_window_counters` — assert keys `{window_start, window_duration_s, c_count, i_count, total_contribution}` with reasonable defaults
- [ ] `test_migrate_old_ledger_fills_new_fields` — write an old-format JSON missing new fields, load through ledger reader, assert new fields default-filled
- [ ] `test_old_ledger_pole_position_preserved_across_migration` — pole_position=0.47 in old; after migration still 0.47
- [ ] Run: expect `4 failed`

**Commit:** `test(ledger): two-band schema + old-ledger migration contract`

### Task 3.2 — Extend ledger schema + migration

**Files:** `scripts/token_ledger.py`

- [ ] Add new fields to the ledger dict constructor with documented defaults
- [ ] Add `def _migrate(ledger: dict) -> dict` that fills any missing new-field key with its default; call on every read path
- [ ] Keep write path atomic (tmp + rename) — existing pattern
- [ ] Update `_DEFAULT_LEDGER` constant

**Commit:** `feat(ledger): extend schema with reward band + window counters`

### Task 3.3 — Add `record_reward` + `consume_reward_credits`

**Files:** `scripts/token_ledger.py`

- [ ] `def record_reward(tier: Literal["T4","T5","T6","SUB","TIER2_SUB","DONATION"], structural_multiplier: float, source: str, donation_amount_usd: float | None = None) -> None`
- [ ] Tier weights per §5 table:
  ```python
  TIER_WEIGHTS = {"T4": 1, "T5": 3, "T6": 8, "SUB": 20, "TIER2_SUB": 40}
  ```
- [ ] Donation: `weight = min(200, 5 * donation_amount_usd)`; structural multiplier irrelevant for donations (platform asserts contributiveness per `/tmp/cvs-research-147.md:132-134`)
- [ ] Delta: `delta = weight * (0.5 + 0.5 * structural_multiplier)` (clamp multiplier to [0, 1])
- [ ] Atomically update `reward_credits += delta`
- [ ] `def consume_reward_credits(amount: float) -> float`: decrement by `min(amount, reward_credits)`; set `last_explosion_credits_spent` to actual consumed; return actual
- [ ] Neither function EVER accepts text, author, or viewer identifier — caller constructs `tier` via classifier

**Commit:** `feat(ledger): record_reward + consume_reward_credits (two-band writes)`

### Task 3.4 — Test reward accumulation and spend-down

**Files:** `tests/studio_compositor/test_token_ledger_reward.py`

- [ ] `test_record_reward_T4_adds_1_times_engagement_multiplier`
- [ ] `test_record_reward_donation_caps_at_200_USD_equivalent`
- [ ] `test_consume_reward_credits_cannot_go_negative` — start 10, consume 50 → credits=0, last_explosion_credits_spent=10
- [ ] `test_consume_reward_credits_updates_last_explosion_field`
- [ ] `test_pole_position_independent_of_reward_credits` — spending credits does not change `pole_position`
- [ ] `test_pole_position_monotonic_across_10k_messages` fuzz (use `hypothesis` since it's already in the council test stack)
- [ ] Run: `uv run pytest tests/studio_compositor/test_token_ledger_reward.py -q`
- [ ] Expected: `10 passed` (4 schema + 6 behavior)

**Commit:** `test(ledger): reward accumulation, spend-down, pole independence, monotonicity`

### Task 3.5 — Publish to perceptual_field

**Files:** `shared/perceptual_field.py`

- [ ] Add `@dataclass(frozen=True) class RewardState` with `reward_credits: float`, `last_explosion_credits_spent: int`, `difficulty_tier: Literal["t0","t1","t2","t3"]`
- [ ] Add `reward_state: RewardState` field to `PerceptualField`
- [ ] Populate in the existing `PerceptualField.from_ledger(path)` classmethod
- [ ] No per-author field. No message text. Aggregates only.

**Commit:** `feat(perceptual): RewardState field on PerceptualField`

### Task 3.6 — Test perceptual_field exposure

**Files:** `tests/shared/test_perceptual_field.py` (extend existing)

- [ ] `test_reward_state_reads_from_ledger` — write ledger with `reward_credits=147.0`, load `PerceptualField.from_ledger(...)`, assert field
- [ ] `test_reward_state_defaults_on_missing_ledger` — non-existent file → `RewardState(0.0, 0, "t0")`
- [ ] Run the single file: expect green

**Commit:** `test(perceptual): RewardState read path + defaults`

### Task 3.7 — Caplog gate for ledger path

**Files:** `tests/studio_compositor/test_token_ledger_reward.py`

- [ ] `test_no_author_in_ledger_logs(caplog)` — `record_reward(...)` called 100× with no author leak at any log level
- [ ] Inspect the JSON ledger file bytes: assert no field name contains `author` or `handle` or `username` (use `json.loads` + recursive key scan)
- [ ] Run: expect `2 passed`

**Commit:** `test(ledger): constitutional no-author-in-state + no-author-in-logs gate`

---

## Phase 4 — Difficulty Curve

Sub-linear scaling over 4h (`/tmp/cvs-research-146.md:89-106`). Multiplies threshold AND explosion cost. Published to `/dev/shm` for overlay transparency.

### Task 4.1 — Test: difficulty formula regression pins

**Files:** `tests/studio_compositor/test_token_ledger_reward.py`

- [ ] `test_difficulty_warm_up_zone` — `difficulty(0) == 1.0`, `difficulty(14.999) == 1.0`
- [ ] `test_difficulty_linear_ramp` — `difficulty(15) == 1.0`, `difficulty(60) == pytest.approx(3.25, rel=1e-3)`
- [ ] `test_difficulty_gentle_tail_near_4h` — `difficulty(240) < 5.1` and `> 4.9`
- [ ] `test_difficulty_tier_enum` — `difficulty_tier(0) == "t0"`, `(60) == "t1"`, `(120) == "t2"`, `(240) == "t3"`
- [ ] `test_difficulty_monotonic_non_decreasing` — hypothesis property over t in [0, 500]
- [ ] Run: expect `5 failed`

**Commit:** `test(ledger): difficulty formula regression pins`

### Task 4.2 — Implement difficulty functions

**Files:** `scripts/token_ledger.py`

- [ ] `def difficulty(t_minutes: float) -> float`:
  ```python
  if t_minutes < 15:
      return 1.0
  if t_minutes < 60:
      return 1.0 + 0.05 * (t_minutes - 15)
  # cap gentle tail at t=240 for numerical stability
  t_clamped = min(t_minutes, 240.0)
  return 2.25 + 0.02 * (t_clamped - 60) ** 1.1
  ```
- [ ] `def difficulty_tier(t_minutes: float) -> Literal["t0","t1","t2","t3"]`:
  ```python
  if t_minutes < 60: return "t0"
  if t_minutes < 120: return "t1"
  if t_minutes < 240: return "t2"
  return "t3"
  ```
- [ ] Run: expect `5 passed`

**Commit:** `feat(ledger): sub-linear difficulty curve + tier enum`

### Task 4.3 — Wire difficulty into state writes

**Files:** `scripts/token_ledger.py`

- [ ] On every state write, compute `t_minutes = (now - session_start) / 60.0`
- [ ] Set `ledger["difficulty_tier"] = difficulty_tier(t_minutes)`
- [ ] Set effective threshold by multiplying base `5000 * log2(1 + log2(1 + active_viewers))` by `difficulty(t_minutes)`
- [ ] Session reset: on `session_start` change, difficulty resets to t0

**Commit:** `feat(ledger): difficulty applied to threshold + published to shm on every write`

### Task 4.4 — Test threshold application

**Files:** `tests/studio_compositor/test_token_ledger_reward.py`

- [ ] `test_threshold_scales_with_difficulty` — same active_viewers, threshold at t=0 < threshold at t=240
- [ ] `test_difficulty_tier_published_to_shm` — write ledger with `session_start = now - 3600`, open JSON file, assert `difficulty_tier == "t1"`
- [ ] `test_difficulty_resets_on_new_session` — write ledger, advance session, assert tier=t0 again
- [ ] Run: expect `3 passed`

**Commit:** `test(ledger): difficulty wired to threshold + shm publish + session reset`

---

## Phase 5 — Glyph Particle System

Replace 60-circle candy explosion in `token_pole.py` with Pango-rendered Px437 glyphs in Gruvbox palette. Count scales sqrt in credits spent, capped at 400 for frame budget.

### Task 5.1 — Test: GlyphParticle shape

**Files:** `tests/studio_compositor/test_token_pole.py` (extend existing)

- [ ] `test_glyph_particle_has_glyph_field` — construct `GlyphParticle(x=0, y=0, vx=0, vy=0, glyph="▒", life=1.0)`, assert `glyph == "▒"`
- [ ] `test_glyph_particle_glyph_pool_has_no_emoji` — iterate `GLYPH_POOL`; assert no codepoint in Emoji_Presentation block (use `unicodedata`)
- [ ] `test_glyph_particle_size_scales_with_life` — `size_for_life(1.0)` > `size_for_life(0.1)`
- [ ] Run: expect `3 failed`

**Commit:** `test(token_pole): GlyphParticle construction + no-emoji invariant`

### Task 5.2 — Add GlyphParticle class

**Files:** `agents/studio_compositor/token_pole.py`

- [ ] Add `@dataclass` `GlyphParticle(Particle)` inheriting from existing `Particle`; add `glyph: str` field
- [ ] Module-level `GLYPH_POOL: tuple[str, ...] = ("░", "▒", "▓", "█", "▀", "▄", "▌", "▐", "▬", "⊕", "⊗", "∴", "∵", "∮", "∇", "→", "↗", "⇒", "⟶", "◉", "◎", "●", "○", "◈", "◇", "◆")`
- [ ] Gruvbox palette constant per §6 of spec (5 RGB tuples)
- [ ] `def size_for_life(life: float) -> float`: `8.0 + 16.0 * life` (8–24pt, 8×16 is base font size)

**Commit:** `feat(token_pole): GlyphParticle + VGA glyph pool + Gruvbox palette`

### Task 5.3 — Implement Pango render in `_render_glyph`

**Files:** `agents/studio_compositor/token_pole.py`

- [ ] Add `def _render_glyph(cr, particle: GlyphParticle, color: tuple[float,float,float]) -> None`
- [ ] Use `PangoCairo` (already used at `homage/bitchx.py:96`)
- [ ] Font description: `"Px437 IBM VGA 8x16 {size_for_life(life)}"`; fallback chain inherits from system `fontconfig` (Terminus, Unscii, DejaVu Sans Mono already configured per `legibility_sources.py:27`)
- [ ] Alpha = `particle.life`
- [ ] Position at `(particle.x, particle.y)`
- [ ] Preserve existing physics: gravity 0.2, friction 0.97, fade over 1.5s

**Commit:** `feat(token_pole): Pango Px437 glyph renderer with life-scaled size`

### Task 5.4 — Implement `n_particles` formula and palette cycle

**Files:** `agents/studio_compositor/token_pole.py`

- [ ] `def n_particles_for_credits(credits: int) -> int`:
  ```python
  return max(20, min(400, int(math.sqrt(max(credits, 0)) * 3)))
  ```
- [ ] Palette cycle: iterate Gruvbox 5-color list; particle i gets `GRUVBOX_ACCENTS[i % 5]`
- [ ] Radial impulse proportional to `sqrt(credits)` — scale vx/vy outer impulse by factor `1.0 + sqrt(credits)/20`

**Commit:** `feat(token_pole): sqrt-scaled particle count + radial impulse + palette cycle`

### Task 5.5 — Test count formula + palette cycle

**Files:** `tests/studio_compositor/test_token_pole.py`

- [ ] `test_n_particles_at_zero_is_floor_20` — `n_particles_for_credits(0) == 20`
- [ ] `test_n_particles_at_5_sub` — `n_particles_for_credits(5) ≈ 20` (sqrt(5)*3=6.7; clamped to floor 20)
- [ ] `test_n_particles_at_400_donation_storm_capped` — `n_particles_for_credits(10_000) == 400`
- [ ] `test_palette_cycle_uses_only_gruvbox_accents` — iterate 100 particles, assert each color ∈ `GRUVBOX_ACCENTS`
- [ ] Run: expect `4 passed`

**Commit:** `test(token_pole): count formula clamp + palette cycle`

### Task 5.6 — Frame-budget stress test

**Files:** `tests/studio_compositor/test_token_pole.py`

- [ ] `test_400_particle_stress_under_budget_tracker_ceiling` — spawn 400 GlyphParticles, render once, measure wall-time + check `BudgetTracker.measure()` stays under ceiling
- [ ] Mark with `@pytest.mark.perf` (do not block default suite; run on CI perf profile)
- [ ] Run: `uv run pytest tests/studio_compositor/test_token_pole.py -q -m perf` expect `1 passed`

**Commit:** `test(token_pole): 400-particle frame-budget stress under BudgetTracker`

---

## Phase 6 — Trigger on Threshold

Wire it end-to-end: ledger `explosions += 1` AND `last_explosion_credits_spent: N` → renderer reads N → spawns sqrt-scaled glyph spew → consumes credits from pool.

### Task 6.1 — Test: end-to-end trigger contract

**Files:** `tests/studio_compositor/test_token_pole.py`

- [ ] `test_threshold_reach_consumes_credits` — set `pole_position = 1.0`, `reward_credits = 100`; call `on_threshold_reached(base_cost=50, t_minutes=0)`; assert `reward_credits` decremented, `last_explosion_credits_spent` = `50 * difficulty(0)`
- [ ] `test_threshold_reach_spawns_sqrt_scaled_particles` — assert particle count matches `n_particles_for_credits(last_explosion_credits_spent)`
- [ ] `test_threshold_reach_never_sets_pole_below_previous` — pre = 1.0; after reset, pole = max(pre, 0.0) in visible output
- [ ] `test_credits_exhausted_produces_small_spew` — `reward_credits = 5`; explosion cost 50; spew has only `n_particles_for_credits(5)` = 20 particles
- [ ] Run: expect `4 failed`

**Commit:** `test(token_pole): end-to-end threshold → consume → spawn contract`

### Task 6.2 — Implement `on_threshold_reached` in `token_pole.py`

**Files:** `agents/studio_compositor/token_pole.py`

- [ ] Add `def on_threshold_reached(self, base_cost: float, t_minutes: float) -> None`
- [ ] `cost = base_cost * difficulty(t_minutes)`
- [ ] `actual = token_ledger.consume_reward_credits(cost)` (atomic ledger write)
- [ ] `n = n_particles_for_credits(int(actual))`
- [ ] Spawn N `GlyphParticle` at navel anchor `(NATURAL_SIZE * 0.50, NATURAL_SIZE * 0.52)` per §2 of migration spec
- [ ] Radial impulse scaled per Task 5.4
- [ ] Visible pole position ratchets up (never loss-frame; principle 5)

**Commit:** `feat(token_pole): threshold trigger consumes credits + spawns glyph spew`

### Task 6.3 — Wire chat-monitor writers

**Files:** `scripts/chat-monitor.py`

- [ ] Replace `record_spend("superchat", ...)` (line 261-271) with `record_reward(tier="DONATION", structural_multiplier=audience_engagement, source="superchat", donation_amount_usd=msg["money"]["amount"])`
- [ ] Replace membership path with `record_reward(tier="SUB", ...)` (YouTube membership ≡ sub per §5)
- [ ] Keep existing `record_spend("chat_analysis", ...)` for LLM cost observability (pole still moves on this, per principle 4 grounding-exhaustive axiom)
- [ ] Per-message path: instantiate `AxiomCompliantQualifier` once at startup; for each message, call `classifier.classify(...)` → if tier ∈ {T4, T5, T6}, call `record_reward(tier=tier_str, structural_multiplier=audience_engagement)`

**Commit:** `feat(chat-monitor): reward-band writes for subs/donations/T4-T6 chat`

### Task 6.4 — Run end-to-end tests green

- [ ] Run: `uv run pytest tests/studio_compositor/ -q`
- [ ] Expected: all phases green (qualifier 25 + ledger 22 + token_pole 11 + perceptual 2 + chat_classifier_qualifier 6)
- [ ] Run ruff: `uv run ruff check agents/studio_compositor/ scripts/token_ledger.py scripts/chat-monitor.py shared/perceptual_field.py`
- [ ] Run pyright: `uv run pyright agents/studio_compositor/qualifier.py agents/studio_compositor/token_pole.py scripts/token_ledger.py`
- [ ] Fix any warnings before commit

**Commit:** `fix(studio): ruff + pyright cleanup across reward mechanic touched files` (skip if clean)

---

## Phase 7 — Constitutional Regression Pin

Seven ethical principles from GDO handoff §3.1 become test assertions. A failing principle blocks merge.

### Task 7.1 — One test per principle

**Files:** `tests/studio_compositor/test_reward_mechanic_constitutional.py` (new)

Seven test functions, one per principle:

- [ ] `test_principle_1_no_per_author_state_in_ledger_json` — write 1000 synthetic messages via chat-monitor pipeline with author hash `"probe_auth_99"`; open `/dev/shm/hapax-compositor/token-ledger.json`; recursive key scan: assert no key contains `author`/`handle`/`user`/`name`; recursive value scan: assert hash string absent
- [ ] `test_principle_2_no_sentiment_features_in_weight_function` — construct a message that is 100% praise ("love you Hapax best streamer ever!!"); run through classifier+qualifier; assert `effective_weight == 0` (flattery disqualifier fires)
- [ ] `test_principle_3_difficulty_published_to_shm_on_every_write` — advance sim time in 5-minute increments over 4 hours; at every step assert `difficulty_tier` readable from ledger JSON
- [ ] `test_principle_4_sub_logarithmic_in_active_viewers` — threshold at n=1 < n=100 < n=10_000; ratio threshold(10_000)/threshold(1) < 10 (not linear)
- [ ] `test_principle_5_visible_pole_monotonic_across_explosion` — pre-explosion pole_position=1.0; fire `on_threshold_reached`; post pole_position >= 1.0 in the *exposed* visible field (spec §5 allows internal reset; visible must not regress within session)
- [ ] `test_principle_6_no_individual_glyph_attributable` — run qualifier over 100 messages from 100 distinct author hashes; assert no particle's data contains any author hash or message-text substring
- [ ] `test_principle_7_no_sentiment_axis_in_config` — load `config/sister-epic/patreon-tiers.yaml`; assert `no_sentiment_reward: true` still present; assert no key named `sentiment` anywhere in config tree

**Commit:** `test(reward): seven constitutional principles as regression pins`

### Task 7.2 — Combined caplog + PII gate

**Files:** `tests/studio_compositor/test_reward_mechanic_constitutional.py`

- [ ] `test_full_pipeline_caplog_no_leak(caplog)` — synth run: 500 messages, mix of T0–T6, subs, donations, flagged-PII; assert caplog text contains none of: author hashes, message tokens, PII patterns (use `shared.pii.PII_PATTERNS`)
- [ ] `test_ledger_schema_rejects_per_author_keys` — attempt to write `{"author_name": "x"}` via an untyped dict into `record_reward` path → assert TypeError or schema guard rejection
- [ ] Run: `uv run pytest tests/studio_compositor/test_reward_mechanic_constitutional.py -q`
- [ ] Expected: `9 passed` (7 principles + 2 guardrails)

**Commit:** `test(reward): constitutional caplog gate + schema-rejection guard`

### Task 7.3 — Cite config in PR body

**Files:** (PR description, not code)

- [ ] Draft PR body cites:
  - `config/sister-epic/patreon-tiers.yaml:78-80` (`no_sentiment_reward: true`)
  - `docs/streaming/2026-04-09-garage-door-open-handoff.md §3.1` (7 principles)
  - `/tmp/cvs-research-147.md §6-§8` (qualifier rubric imported verbatim)
  - `chat_reactor.py` (caplog-test precedent for no-per-author-state)
- [ ] Include the 9 constitutional test names in the PR description
- [ ] Mark PR with label `constitutional-gate` (pre-existing label for T0-touching work)

### Task 7.4 — Final suite + lint gate before PR

- [ ] Run: `uv run pytest tests/studio_compositor/ tests/shared/test_perceptual_field.py -q`
- [ ] Expected: full green (no `-m "not llm"` skip required; run both suites)
- [ ] Run: `uv run ruff check .`
- [ ] Run: `uv run ruff format --check .`
- [ ] Run: `uv run pyright agents/studio_compositor/ scripts/token_ledger.py scripts/chat-monitor.py shared/perceptual_field.py`
- [ ] Expected: all green
- [ ] Run the smoke: `uv run python -m agents.studio_compositor.token_pole --smoke` (existing smoke entry, if present; otherwise skip)

**Commit:** (no new commit if tree is clean; otherwise) `fix: lint cleanup for reward mechanic epic`

---

## Phase Exit Criteria

Each phase is done when:

1. All listed tests pass locally.
2. Ruff + pyright clean on touched files.
3. No new author-bearing fields in any on-disk artifact (verified by schema scanner in Phase 7.2).
4. Caplog test for that phase passes.
5. Commit pushed to the feature branch.

## Epic Exit Criteria

The epic ships when:

1. All 7 phases' tests pass (qualifier, classifier integration, ledger, difficulty, particles, trigger, constitutional).
2. Frame-budget stress test (400 particles) stays under `BudgetTracker` ceiling.
3. PR description cites §3.1 seven principles and the 9 constitutional test names.
4. CI green including `axiom-commit-scan` and `pii-guard` hooks.
5. No stale branches, no unmerged work parked anywhere in the workspace (branch-audit clean).
6. Post-merge: alpha worktree rebased on main.

## Out of Scope (explicit deferrals)

These are NOT part of CVS #146 v1. Track as future CVS tasks:

- **Twitch EventSub wiring** — YouTube-only in v1; Twitch (`eventsub.wss.twitch.tv` + TMI IRC) ships in a separate CVS task per spec §9. Same classify/tier/qualifier pipeline; no architectural changes needed.
- **T5 false-positive refinement via embedding-to-condition_id similarity** — listed as open question 4 in spec §11; v2 work.
- **Positive-definition qualifier (constructive-critique detector)** — open question 1 in §11; v1 stays negative-defined.
- **Per-window `contributive_count` public publishing** — open question 2; internal-only in v1.
- **`!noscore` opt-out gesture** — open question 3; ship alongside #125 consent surface work, not here.
- **HOMAGE migration of token_pole aesthetic surface** — `docs/superpowers/specs/2026-04-18-token-pole-homage-migration-design.md` is an orthogonal concern (output-side aesthetic vs. this plan's input-side reward mechanic); lands in its own PR, same ledger file as contract.

## Risk Register

| Risk | Mitigation | Phase |
|---|---|---|
| Flattery regex too aggressive — drops real contributions with praise prefix | Test fixture: `"great paper — https://arxiv.org/..."` passes via URL reference-token | 1.4 |
| Shannon-surprise threshold too low — emote spam sneaks through | Empirical T_INTERESTING calibration + emote-only disqualifier as second gate | 1.5 |
| Embedding call latency on hot path | Qualifier is optional dependency; classifier tier-only path is hot, qualifier runs post-tier only for T4+ (rare), and via the CPU embedder already provisioned | 2.2 |
| Old ledgers on disk break on migration | `_migrate()` runs on every read; default-fills missing fields; no write fails | 3.2 |
| 400-particle render exceeds BudgetTracker on cold cache | Pango layout caching via `homage/bitchx.py` precedent + hard cap 400 | 5.6, 6.4 |
| Author hash surfaces in debug logging | Caplog gate at end of each phase; Phase 7 runs full-pipeline gate | every |
| Qualifier creates a "perform-for-the-classifier" dynamic | Per §4 "symmetry test" in `/tmp/cvs-research-147.md`: deterministic, negative-defined positive, no on-stream verdict rendering; mitigated by design, tested by principle 6 | 7.1 |

---

**Plan location:** `docs/superpowers/plans/2026-04-18-token-pole-reward-mechanic-plan.md` (cascade worktree)
