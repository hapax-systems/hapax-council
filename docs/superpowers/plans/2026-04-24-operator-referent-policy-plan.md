# Operator Referent Policy — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-04-24-operator-referent-policy-design.md`

Single PR. Foundation-level change; no feature flag. TDD throughout.

## Task 1 — Picker module + tests

**Files:**
- `shared/operator_referent.py` — new
- `tests/shared/test_operator_referent.py` — new

**TDD order:**
1. Write failing tests for: `REFERENTS` tuple shape (4 entries, canonical spelling), `pick()` returns one of four, `pick(seed)` deterministic for same seed, `pick_for_tick(n)` deterministic for same n, equal-weight distribution over 10,000 random seeds (χ² p > 0.05), stable across Python restarts (seed→referent map is not process-local).
2. Implement picker.
3. Green tests.

**Acceptance:**
- `uv run pytest tests/shared/test_operator_referent.py -q` passes
- `uv run ruff check shared/operator_referent.py tests/shared/test_operator_referent.py` clean
- `uv run pyright shared/operator_referent.py` clean

## Task 2 — Lexicon update + tests

**Files:**
- `shared/speech_lexicon.py` — add `OTO` entry, update docstring to enumerate all four referent forms
- `tests/shared/test_speech_lexicon.py` — add tests for `OTO` letter-by-letter IPA, for `Oudepode The Operator` (existing `Oudepode` match extends naturally)

**TDD order:**
1. Failing test: `apply_lexicon("OTO is live")` yields `[OTO](/oʊ tiː oʊ/) is live`.
2. Failing test: `apply_lexicon("Oudepode The Operator")` wraps `Oudepode` via existing regex; `The Operator` passes through natively.
3. Add `_LEXICON["OTO"] = "oʊ tiː oʊ"`.
4. Verify regex still sorts longest-first so `OTO` doesn't shadow future multi-letter acronyms.
5. Green tests.

## Task 3 — Implication YAML

**File:**
- `axioms/implications/non-formal-referent-policy.yaml` — new

**Content:** per spec §Axiom implication. Uses newer single-implication-per-file format (like `mg-drafting-visibility-001.yaml`), tier T1 enforcement review.

**Acceptance:**
- Existing axiom-scan regression test passes
- `shared/axiom_scanner` (if it auto-discovers) picks up the new file
- YAML schema valid

## Task 4 — Director loop runtime sites

**File:** `agents/studio_compositor/director_loop.py`

**Changes (6 runtime sites):**

1. Top of `_curated_music_framing()`: accept optional `referent: str` parameter; fall back to `OperatorReferentPicker.pick()` if not provided
2. Line 996: `f"{referent} is spinning vinyl: {_read_album_info()}."`
3. Line 1000: `f"Music is playing from {referent}'s curated queue: '{slot_title}' by {slot_channel}."`
4. Line 1043: change static prompt text from `"- music: comment on Oudepode's curated music"` to `"- music: comment on the operator's curated music"` (the injected style rule tells the LLM how to refer to them; prompt text uses neutral "the operator")
5. Line 1956: `f"{referent} is always present in the room as your first-class audience. Whatever moves you pick, they see them — even when external viewer count is zero."` (note: also update `"he"` → `"they"` — referent-agnostic pronoun)
6. Line 2070: `f'{referent}: "{text}"'` (chat attribution)
7. Line 2492: `f"the music {referent} is playing, the reverie visual mood, the operator's desk activity, or the active research objective"`

**Construction point:** at the top of `_build_reactor_context()` (where the current tick is known), call:
```python
tick_id = self._tick_counter
referent_for_this_tick = OperatorReferentPicker.pick_for_tick(tick_id)
```
Inject a style rule block into the assembled prompt immediately after the persona section:
```python
parts.append(
    f"\n## Referent policy\n"
    f"In this tick, refer to the operator EXCLUSIVELY as: \"{referent_for_this_tick}\". "
    f"Do not use their legal name in narration. Do not mix other referent forms "
    f"(e.g., 'OTO', 'The Operator') in this tick. Use this form consistently.\n"
)
```

Pass `referent_for_this_tick` into `_curated_music_framing()` + audience-framing + scope-nudge construction.

**Changes (comments, housekeeping):**
- Lines 576, 992, 998–999, 1953 — leave as-is (historical directive traceability)

## Task 5 — Smoke test for director integration

**File:** `tests/test_director_referent_integration.py` — new

Constructs 100 reactor contexts over a simulated tick range (0..99). Verifies:
1. Each context uses exactly ONE referent (no mixing within a single reactor context)
2. Over 100 ticks, each of the 4 referents appears 20–30 times (equal-weight χ² bound)
3. Same tick_id → same referent (determinism)
4. Style rule block appears exactly once per context

## Task 6 — Coordination notes

**Files:**
- `~/.cache/hapax/relay/epsilon-to-alpha-2026-04-24-referent-policy-for-ytb-008.md`
- `~/.cache/hapax/relay/epsilon-to-beta-2026-04-24-referent-policy-for-ytb-010.md`
- `~/.cache/hapax/relay/epsilon-to-delta-2026-04-24-referent-policy-ytb-007-followup.md`

Each note summarizes the policy + spec/plan location + specific integration ask for that session's unshipped work.

## Task 7 — PR

Single PR `feat/operator-referent-policy` off `main`. Title: `feat(governance): operator referent policy + sticky-per-utterance picker`.

**Commit structure (atomic foundation):**
1. `feat(shared): OperatorReferentPicker + equal-weight distribution tests`
2. `feat(lexicon): OTO IPA override + referent-form docstring`
3. `feat(axioms): su-non-formal-referent-001 implication`
4. `feat(director): route operator narration through referent picker`
5. `docs: operator referent policy spec + plan`

**Body:** spec/plan links, acceptance criteria checklist, coordination-note paths.

## Verification before merge

- `uv run pytest tests/shared/test_operator_referent.py tests/shared/test_speech_lexicon.py tests/test_director_referent_integration.py -q`
- `uv run ruff check . && uv run ruff format --check .`
- `uv run pyright shared/operator_referent.py agents/studio_compositor/director_loop.py`
- Axiom regression test passes (picks up new implication)
- Post-deploy: watch 3 director ticks live; confirm narration uses rotating referents

## Risks / open decisions deferred

- **VOD-boundary reset seed**: spec permits optional `pick_for_tick` seed to incorporate VOD segment id when ytb-007 orchestrator rotates. Implementation in this PR uses tick_id only; ytb-007 integration is deferred to delta's follow-up (see coordination note).
- **Voice TTS validation for `OTO` IPA**: first live utterance of `OTO` should be monitored; if misaki pronounces it wrong, IPA is tunable in a one-line PR.
- **Cross-surface posts (ytb-010, beta's lane, not shipped)**: beta's implementation should use the same picker with seed on broadcast-session id for per-VOD consistency across all federated surfaces.

## Not in scope

- ytb-007 `metadata_seed.compose()` follow-up (delta, one-commit)
- ytb-008 composer integration (alpha, greenfield with picker baked in)
- ytb-010 federation integration (beta, greenfield with picker baked in)
- Any migration of historical director-loop comments (intentional retention)
