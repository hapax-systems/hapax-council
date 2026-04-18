# Chat Ambient Ward — Design Spec Stub

**Date:** 2026-04-18
**Task:** HOMAGE follow-on #123 (Livestream Chat as HOMAGE Ward)
**Status:** Stub. Provisionally approved 2026-04-18.
**Source research:** `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` § Rendering → "#123 Livestream Chat as HOMAGE Ward"
**Related:** #147 (qualifier rubric), #121 (HARDM), #146 (token pole)

---

## 1. Goal + Redaction Invariant

Replace the static `ChatKeywordLegendCairoSource` (a fixed legend of `!glitch` /
`!calm` / etc.) with `ChatAmbientWard`: a **dynamic, aggregate-only** surface
that turns live chat flow into ambient BitchX chrome. Viewers read the current
temperature of the room — rate, participation, research-heat — **never
individual messages**.

### Invariant (load-bearing)

Axiom `it-irreversible-broadcast` (T0): **no author handle, no message body,
no derived snippet, and no substring of either EVER reaches pixels, logs at
INFO or above, or any egress tee.** The ward consumes `ChatSignals` (numeric
aggregates over a rolling window) and nothing else. This is the same redaction
floor enforced by `chat_reactor.PresetReactor` — see its caplog discipline at
`chat_reactor.py:254` ("Chat preset switch: %s" — preset name only, never
author, never body).

Author-handle hashes exist upstream in `ChatSignalsAggregator` for
`unique_authors_60s` counting only; they never leave the aggregator. The ward
receives an **integer**, not a hash.

---

## 2. Aggregation Sources

All sources already exist in `chat_signals.ChatSignals` or need a small
extension. No new per-author state.

| Aggregate | Source | Window | Use |
|---|---|---|---|
| `t4_plus_rate_per_min` | new field: count of T4/T5/T6 classifications in rolling 60s ÷ minute | 60 s | userlist row `N` |
| `unique_t4_plus_authors_60s` | new field: distinct hashed authors whose message was T4+ | 60 s | userlist row `N` (**preferred** over raw rate — matches IRC `1/N` semantics) |
| `t5_rate_per_min` | new field: count of T5 classifications ÷ minute | 60 s | `+v` flag brightness |
| `t6_rate_per_min` | new field: count of T6 classifications ÷ minute | 60 s | `+H` flag brightness |
| `message_rate_per_min` | existing `ChatSignals.message_rate_per_min` | 60 s | ambient cadence (cell pulse) |
| `audience_engagement` | existing `ChatSignals.audience_engagement` | 60 s | global brightness multiplier |

Extension to `ChatSignalsAggregator`: accept tier-tagged items from the
classifier pipeline (T0–T6), not just T4 items. The queue today is already
`StructuralSignalQueue` (T4+), so either (a) a parallel `TieredSignalQueue`
alongside it or (b) extend `StructuralSignalQueue.put` to accept `tier:
ChatTier` and bucket at ingest. Open question below.

---

## 3. BitchX Grammar Fit

The ward renders a single row of 4–6 cells in the **lower-content-band**
(coordinate with #121 HARDM for the upper-right-quadrant; chat ward sits in
the lower band so the two don't compete for vertical real estate). Grammar
primitives come from `agents/studio_compositor/homage/bitchx.py` —
`BITCHX_PACKAGE.grammar`, `.palette`, `.typography`.

### Cell layout (left to right)

1. **Userlist row:** `[Users(#hapax:1/N)]` where `N = unique_t4_plus_authors_60s`.
   - `[` `]` `(` `)` `/` `:` in **muted** role (grey punctuation skeleton).
   - `#hapax` in **accent_cyan** role (channel name convention).
   - `1` (operator) and `N` in **bright** role (identity colouring).
   - Font: `Px437 IBM VGA 8x16` @ size class `normal` (14 px).

2. **Mode-flag ladder:** `[Mode +v +H]`.
   - `+v` (voice) flag brightness tracks `t5_rate_per_min` (research-keyword
     rate). Cadence-aware: brightness = `min(1.0, rate / 6.0)` — 6 T5/min
     saturates. Below 0.5 T5/min, flag renders in `muted` role (present but
     dim); above, `accent_green` (IRC op-indicator tradition).
   - `+H` (HOMAGE, literal convention established in `StanceIndicatorCairoSource`)
     flag brightness tracks `t6_rate_per_min`. Saturates at 3 T6/min;
     `accent_cyan` when active, muted when dormant. A T6 citation hit gives
     the whole ward a one-tick brightness kick (packge transition
     `mode-change` vocab, zero-frame instant-cut — see
     `_BITCHX_TRANSITIONS.supported`).

3. **Rate gauge:** text-mode "bar" of CP437 block characters (`░▒▓█`)
   encoding `message_rate_per_min` logarithmically. 0–60 msg/min →
   0–8 cells. Muted role for all cells; **no colour ramp** (refuses
   "flat-ui-chrome" anti-pattern).

4. **Engagement quiet-indicator:** when `audience_engagement < 0.15` for
   >30 s, render `[quiet]` in muted role. When >0.85, render `[active]` in
   bright role. Between: no extra cell.

Total: 3 required cells + 1 conditional cell = 3–4 cells (well under the 6
budget; leaves headroom for HARDM coordination).

### Grammar compliance

- Zero-frame transitions (`transition_frame_count=0`) — cells flip state
  instantly on tick boundary. **No fades.** The flag flicker on T6 hit is a
  single-tick instant-cut, matching IRC mode-change aesthetics.
- `line_start_marker = "»»»"` prepended to the whole row (muted role).
- Container shape `angle-bracket` — wrap the row in `<` `>` at the cell
  band boundaries.
- Raster cell required (`raster_cell_required=True`) — all text on 8-px grid.
- Refuses (from `BITCHX_PACKAGE.refuses_anti_patterns`): no emoji, no
  anti-aliasing (Cairo font hint = none), no rounded corners, no fade
  transitions.

---

## 4. Package Palette Integration

The ward is a `HomageTransitionalSource` subclass (`source_id="chat_ambient"`).
Palette resolution goes through `get_active_package().resolve_colour(role)` —
the same pattern as `legibility_sources.py`. This means if the package
later swaps from BitchX to (say) a future "phrack" or "16colo.rs" package,
the ward re-skins automatically. **No hardcoded hex anywhere.**

Role usage summary: `muted` (skeleton), `bright` (identity numbers),
`accent_cyan` (channel name + `+H` active), `accent_green` (`+v` active),
`terminal_default` (gauge fallback), `background` (flat fill; refuses
gradients).

---

## 5. Redaction Tests

Failure modes here are constitutional violations, not cosmetic bugs.

1. **Caplog hygiene:** unittest asserting `log.info` / `log.warning` calls
   during a synthetic 10k-message burst contain **no** author hash substrings
   and **no** message-body substrings. Pattern: `chat_reactor` test at
   `tests/studio_compositor/test_chat_reactor.py::test_caplog_no_author`.
2. **Property-based no-name-leak** (Hypothesis): feed random message bodies
   containing synthetic author strings into the full `classify →
   aggregate → ward.render_content` pipeline; `cairo.ImageSurface` bytes
   must not contain any input author-substring. Cadence: every body/author
   >=4 chars, 200 trials per CI run.
3. **Aggregate monotonicity:** if zero messages in window, all gauges render
   in muted role (no identity highlight possible without data).
4. **Hash-isolation test:** `ChatAmbientWard.render_content` never accepts a
   parameter of type `str` that could carry an author or body; constructor
   and state dict types are narrowed to `int | float | bool`. Assert via
   runtime `isinstance` guard + mypy/pyright check.

---

## 6. File-Level Plan

- `agents/studio_compositor/chat_signals.py` — extend `ChatSignals` with
  `t4_plus_rate_per_min`, `unique_t4_plus_authors_60s`, `t5_rate_per_min`,
  `t6_rate_per_min`. Teach aggregator to accept tier-tagged items (or add
  `TieredSignalQueue`). Preserve existing `audience_engagement` formula.
- `agents/studio_compositor/legibility_sources.py` — **remove**
  `_CHAT_KEYWORDS` constant and `ChatKeywordLegendCairoSource` class. Leave
  a one-line deprecation comment pointing at `chat_ambient_ward.py`.
- `agents/studio_compositor/chat_ambient_ward.py` — NEW.
  `class ChatAmbientWard(HomageTransitionalSource)` with `render_content`
  reading `/dev/shm/hapax-chat-signals.json` via a small cached reader
  (reuses `_read_narrative_state` pattern from `legibility_sources`).
- `agents/studio_compositor/cairo_sources/__init__.py` — register
  `chat_ambient` source id; remove `chat_keyword_legend` registration.
- Compositor layout (JSON in `config/compositor/` or equivalent) — move
  the chat-ward cell-band from wherever `chat_keyword_legend` currently
  lives to the lower-content-band; coordinate with #121 HARDM geometry
  (which claims the upper-right quadrant per dossier § #121).
- `tests/studio_compositor/test_chat_ambient_ward.py` — NEW. Redaction
  tests (§5 above) + rendering smoke test with a `RecordingSurface`.
- `tests/studio_compositor/test_chat_signals.py` — EXTEND. Tier-tagged
  aggregation; rolling-window correctness under tier mix.

No new dependencies. Hypothesis already in test stack.

---

## 7. Open Questions

1. **Queue extension vs parallel queue:** extend `StructuralSignalQueue` to
   accept tier or add `TieredSignalQueue`? Recommendation: extend in place
   — simpler, one source of truth for window semantics. Pending
   implementation review.
2. **Cell band vs side-bar placement:** lower-content-band assumed here.
   Confirm once #121 HARDM geometry is spec'd — if HARDM lands in
   upper-right, chat ward in lower-content-band has no conflict. If HARDM
   expands, revisit.
3. **Engagement quiet-indicator timing:** 30 s dwell before showing
   `[quiet]` — is that too fast, too slow? Defer to operator observation
   during first livestream window after deploy.
4. **T6 kick intensity:** one-tick full-brightness flash vs 2–3 tick
   held-bright. Zero-frame transition vocab prefers instant-cut, but
   audibility of a single-tick flash at 30 fps is ~33 ms (below notice
   threshold). Recommend 3 frames (100 ms) as "single perceptual beat"
   while staying within instant-cut grammar.
5. **Does the ward participate in `degraded_stream_ward` takeover (#122)?**
   Assumed yes — degraded flag overrides all wards including this one.

---

## 8. Related

- **#147 qualifier rubric** — T4+ classification must align with the
  rubric's sense of "on-topic signal". If #147 shifts the T4/T5 boundary,
  this ward's `+v`/`+H` calibration needs to follow; no separate tuning knob.
- **#121 HARDM** — chat ward sits in lower-content-band; HARDM claims
  upper-right quadrant. Cell-count budget (3–4 of 6) leaves headroom for
  future HARDM expansion into the band without conflict. Coordinate
  explicitly in the integration-pass stub.
- **#146 token pole** — both surfaces have chat-contribution-like inputs
  (vitruvian token pole's limb energy can accept engagement signals), but
  they are **separate surfaces** with separate aggregation. Keep the ward
  unaware of token pole and vice versa; any coupling happens at the
  director intent layer, not here.
