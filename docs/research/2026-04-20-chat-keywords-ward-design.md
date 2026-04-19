---
date: 2026-04-20
author: cascade research subagent (dispatched by delta)
audience: alpha (execution), operator (review)
register: scientific, neutral
status: design proposal — no code yet, no commits
scope: new HOMAGE ward `chat_keywords` + producer delta on `ChatSignalsAggregator`
related:
  - docs/superpowers/plans/2026-04-20-orphan-ward-producers-plan.md §11 Q4
  - docs/superpowers/specs/2026-04-18-chat-ambient-ward-design.md
  - docs/superpowers/specs/2026-04-18-homage-framework-design.md
  - docs/research/2026-04-20-ward-full-audit-alpha.md §7
  - agents/studio_compositor/chat_ambient_ward.py
  - agents/studio_compositor/chat_signals.py
  - agents/studio_compositor/chat_classifier.py
  - agents/studio_compositor/homage/bitchx.py
  - axioms/registry.yaml (`interpersonal_transparency`, weight 88, T0)
governing-axioms:
  - interpersonal_transparency (constitutional, T0)
  - single_user (constitutional)
cross-references:
  - HOMAGE framework §3.2, §4.2, §4.4, §4.5, §5.5
  - orphan-ward plan §5 Non-goals, §6 Consent and governance, §11 Q4
  - ward audit §7 chat_ambient
---

# Chat-Keywords HOMAGE Ward — Design

Follow-on to the FINDING-V orphan-ward sweep. The orphan-ward plan §11 Q4
(open question, "Keyword extraction scope") defaulted to **out of scope**
because no consumer read a `chat-keywords.json` file. The operator has
now authorized reopening that question: design a NEW ward —
`ChatKeywordsWard` — that consumes a producer-side extension of the
existing `ChatSignalsAggregator` and renders aggregate keyword texture
alongside the existing `chat_ambient` surface.

This doc is a design proposal. No code ships here. No commits.

---

## 1. Signal semantics — what a keyword stream tells the livestream that rates/tiers don't

The existing `chat_ambient` ward (`agents/studio_compositor/chat_ambient_ward.py`)
renders four axes, all **rate-or-count**:

| Axis | Source field | Grammar cell |
|---|---|---|
| Participation | `unique_t4_plus_authors_60s` | `[Users(#hapax:1/N)]` |
| Research-keyword cadence | `t5_rate_per_min` | `+v` flag brightness |
| Citation cadence | `t6_rate_per_min` | `+H` flag brightness |
| Ambient pulse | `t4_plus_rate_per_min` | CP437 rate gauge `░▒▓█` |
| Engagement scalar | `audience_engagement` | conditional `[quiet]`/`[active]` |

Every one of these is a **structural summary** — the ward can tell you
the room is warm, but not **what the room is warm about**. Three
distinct livestream states are indistinguishable in the rate/tier
surface:

1. Room at 12 msg/min discussing Bachelard's poetics.
2. Room at 12 msg/min debating an MPC-pad cue.
3. Room at 12 msg/min reacting to a reverie shader glitch.

Case 1 wants the `director_loop` to bias up `grounding_provenance_ticker`
(research-mode content bias); case 2 wants the album + token pole
emphasis family (studio programme bias); case 3 wants reverie substrate
emphasis (compositional_impingement toward shader family). Tier counts
cannot disambiguate because all three cases are dominated by T4–T5
structural signals. A keyword texture — **what words are recurring
across independent authors in the window** — is the narrowest signal
that distinguishes them, at the lowest attack surface (no names, no
bodies).

This is the same distinction Twitch chat analytics precedents draw:
15s/60s/5min rolling "word cloud" surfaces complement — not replace —
rate dashboards; trending keywords provide topic-of-conversation
telemetry that volume alone cannot encode ([TwitchViz], [Twitch Chat
Emote Analyzer]).

The ward's contribution to the livestream is therefore **topic texture,
not volume**. Implication for grammar (carried into §5): the ward must
look distinct from `chat_ambient`'s status-bar format, or the two wards
become indistinguishable ambient chrome rather than independent
perceptual channels.

---

## 2. Extraction policy

Keyword extraction runs inside the producer (`ChatSignalsAggregator` or
a sibling class; see §6), not the consumer. The consumer receives a
pre-extracted ranked list. Policy choices and justifications follow;
every choice is reviewable.

### 2.1 What counts as a keyword

- **Unit of extraction: whitespace-split token, NFKC-normalised,
  lowercased, stripped of leading/trailing punctuation** (`!?.,;:()<>[]{}"`).
  No Unicode normalisation beyond NFKC — preserves non-ASCII tokens
  without aggressive folding.
- **Minimum token length: 3 chars**. Filters out `a`, `I`, `ok`, `no`,
  `it`, `so`, plus most stop-word residue.
- **Maximum token length: 40 chars**. Rejects copypasta runs
  (`aaaaaaa...`) and URL tokens; tokens >40 chars are almost always
  garbage.
- **Token class filter**: accept alphanumeric + `-` + `_`. Reject
  pure-digit tokens (date/score noise), reject tokens whose first char
  is digit (`2026`, `9k`).

### 2.2 POS / class taxonomy

No POS tagger. Adding a tagger (spaCy, NLTK) would add a model-load
dependency on a latency-critical producer path (chat-monitor). Use
structural heuristics instead:

- **Hashtags**: tokens starting with `#`, preserved with the `#`.
  Hashtags carry author-intent topic marking and are kept.
- **Mentions**: tokens starting with `@` → **REJECTED AT EXTRACTION**,
  never emitted. This is the primary consent-boundary defence (§3). No
  `@handle` ever reaches the ranked list.
- **Emoji**: single-codepoint Unicode emoji are collapsed into a single
  bucketed token `:emoji:` with a count. They do not compete with word
  tokens. Emoji-only chat is informational signal (high-arousal) but
  not a keyword — the `audience_engagement` scalar in `chat_ambient`
  already covers it. Emit emoji count as a separate aggregate
  (`emoji_fraction`), not as a keyword.
- **Proper nouns** are not syntactically distinguishable without a POS
  tagger. The consent boundary (§3) addresses this via global and
  dynamic stop-word filtering, not at POS-tag time.

### 2.3 Stop-word filter

Multi-layer filter, all applied producer-side before ranking:

1. **Global stop-word list**: the top ~180 English stop words
   (articles, pronouns, auxiliaries, prepositions, common verbs). Seed
   from NLTK's `english` stopword corpus (baked into producer at build
   time — no runtime NLTK dep; freeze to `shared/chat_stopwords.py` as
   a `frozenset[str]`).
2. **Livestream-chat idiom list**: domain-specific terms that carry
   noise, not signal. Seed from observed Twitch/YouTube chat idioms:
   `lol`, `lmao`, `imo`, `tbh`, `ngl`, `fr`, `ngl`, `omg`, `yeah`,
   `yep`, `nope`, `hmm`, `wait`, `just`, `really`, `pretty`, `pog`,
   `kek`, `gg`, `nice`, `good`, `bad`, `cool`, `wow`. Seed of ~60.
   Freeze alongside the general list.
3. **Operator-persona list**: aggressive defensive filter against
   operator identity markers. `hapax`, `ryan`, `rylklee`, `kleeberger`,
   plus the active YouTube channel name(s). Loaded from
   `axioms/contracts/` or a sibling config at producer start. Tokens in
   this list are dropped silently.
4. **Dynamic handle-filter** (§3): every hashed author handle from the
   live window is also in the stop-word set for that window. Stops
   authors mentioning themselves repeatedly from surfacing.

### 2.4 Per-author dedup + minimum distinct-author threshold

This is **the load-bearing consent guardrail**. Without it, one viewer
can rank a keyword by spamming.

- Each author contributes at most **1 count per keyword per rolling
  window**, regardless of how many messages that author sent containing
  the keyword. Implementation: `dict[str, set[str]]` keyed by
  author-hash → set of keywords already counted for this author in the
  window.
- **Minimum distinct-author threshold**: a keyword is eligible for
  ranking only if it appears in messages from **≥ 3 distinct hashed
  authors** in the rolling window. This is the single most important
  filter — it guarantees no keyword trends on the strength of one
  participant's repetition.
- Across authors (i.e., after per-author dedup), the frequency is the
  count of distinct authors who used the token. This is the metric
  ranked.

### 2.5 Rolling window

- **Window size: 60 s.** Matches the existing
  `ChatSignalsAggregator._tier_window_seconds = 60.0` — keeps the
  producer single-window and consistent with `chat_ambient`'s temporal
  semantics.
- **Recompute cadence: 5 s.** Consumer renders at 2 Hz per layout
  default_cadence; producer recomputes on the same 30 s
  `compute_signals` tick. Interpolation is unnecessary because the
  ward crossfades on turnover (§5).
- Optional future work: a second 300 s window for a slower "theme
  arc" layer. Out of scope v1; callers can add a sibling field without
  breaking the schema.

### 2.6 Ranking and top-N

- Rank eligible keywords (distinct-author count ≥ 3) by
  **distinct-author count descending, then alphabetically ascending**
  (stable tie-break; not message count).
- Emit **top 5**. Cell count on the surface (§5) is 5. Top-5 is the
  standard choice in Twitch trending surfaces; beyond 5, the ward's
  320×140 px region saturates.
- Redact counts below the `[bucket_low, bucket_high]` visible on the
  ward — the consumer sees ranks, not raw numbers (see §4 state
  shape). Producer emits counts for observability; ward maps counts to
  a single-character CP437 weight glyph.

### 2.7 Idle state

If fewer than 3 keywords qualify (the most common state during low
chat flow), the producer emits an empty list. The consumer renders
`[no chatter]` in muted role. Never emit a partial list padded with
placeholder tokens — defeats the point of the min-distinct-author
threshold.

### 2.8 Out of scope

- **Sentiment.** Explicitly excluded per `chat_signals.py` module
  docstring and HOMAGE spec §3.2 ("Bundle 9 §2.6 and token pole 7
  principle 7"). No `vaderSentiment`, no emoji-sentiment mapping.
- **N-grams / phrase mining.** 1-grams only, v1. Phrase extraction
  would need a longer window (60 s is too short for statistical
  significance) and a second redaction pass.
- **Embedding-based clustering.** The existing `chat_entropy` /
  `chat_novelty` fields already cover embedding-derived diversity.
  Keyword extraction is the **surface layer** on top.
- **LLM extraction.** Would violate HOMAGE §3.2 "no LLM on chat
  bodies" and `scripts/chat-monitor.py`'s structural contract.

---

## 3. Consent boundary

Axiom `interpersonal_transparency` (weight 88, T0, constitutional,
verbatim from `axioms/registry.yaml`):

> The system must not maintain persistent state about any non-operator
> person without an active consent contract. A consent contract
> requires explicit opt-in by the subject, grants the subject
> inspection access to all data the system holds about them, and is
> revocable by either party at any time. Upon revocation, the system
> purges all subject-specific persistent state.

`ChatSignalsAggregator.compute_signals` already honours this by
hashing author handles at the boundary
(`chat_signals.py:322–323`: `hashlib.sha256(msg.author_handle.encode("utf-8")).hexdigest()[:16]`).
The keyword extension must inherit that discipline and **tighten** it
because keywords, unlike tier counts, may syntactically carry person
data.

### 3.1 Threat model

Three specific failure modes the extraction policy must handle:

**Case A — a single viewer mentioning their own name repeatedly.**
Neutralised by §2.4 per-author dedup and ≥ 3-distinct-author
threshold. Author "jane_cool_247" posts 30 messages each containing
`"jane"`; counts as **one** distinct-author contribution to the
keyword `jane`. With only one distinct author, `jane` never qualifies
for ranking. Confirmed behaviour: one spammer cannot surface their
own name.

**Case B — a controversial handle trending.** Three distinct viewers
post messages each referencing the same non-operator handle, e.g.
`"@bob_troll is being a jerk"`. `@bob_troll` is rejected at
extraction (§2.2 mention filter); it never enters the candidate set.
`bob_troll` (the bare token) could still enter if the handle happens
to be a dictionary word, which is the edge case that motivates 3.2.

**Case C — @-mentions of the operator or other persons.** All tokens
beginning with `@` are dropped at the tokenization stage (§2.2). This
is a hard reject, not a soft filter. The operator's own identity
tokens are additionally in the persona stop-word list (§2.3.3), so
even unprefixed `hapax` / `ryan` drops.

### 3.2 The bare-name leak residual

The residual threat is: three independent viewers use the same bare
(non-`@`-prefixed) proper noun of a non-operator person, and the
token is not in the persona list. Mitigations, in order:

1. **Dynamic handle-filter** (§2.3.4): every hashed author handle in
   the live window joins the stop-word set. This neutralises cases
   where the handle text itself recurs as a bare token (common on
   platforms where handles are English words).
2. **Dictionary-word tolerance.** If a bare name coincides with an
   English word (`bob`, `chris`, `pat`), the global stop-word list
   does not cover it. The min-distinct-author threshold of 3 is the
   only remaining defence. This is a known residual, documented
   openly. Operator can raise the threshold via
   `HAPAX_CHAT_KW_MIN_DISTINCT_AUTHORS` env var if needed
   (default 3, recommend 5 under high-visibility livestreams).
3. **No persistence.** Keywords live only in the rolling 60 s window
   and in the SHM JSON (tmpfs, evaporates at reboot). No Qdrant
   ingestion, no JSONL archive, no Langfuse metadata.
4. **No downstream text surface.** The ward is the only consumer. It
   renders at 320×140 px and disappears in < 60 s. No caption path,
   no archive, no cross-modal leak into the profile pipeline.
5. **Axiom conformance test** (analogous to
   `chat_ambient_ward.py::_coerce_counters`): producer writes only
   `dict[str, int]` to SHM; any string author identifier appearing as
   a **value** (not a key) raises `TypeError` at runtime. Grep test
   in CI: feed a fixture chat stream whose bodies contain known
   fixture names, verify no fixture-name substring lands in the
   emitted SHM JSON.

The residual threat is non-zero but is bounded by the 60 s window,
tmpfs persistence, and the multi-author threshold. This matches the
`chat_ambient` risk profile — both wards sit above the same
consent floor.

### 3.3 Relationship to `chat_ambient` discipline

`ChatAmbientWard._coerce_counters` rejects string values at runtime
(`chat_ambient_ward.py:213–217`). The new ward inverts that contract
— its payload is **string keys** (keywords are strings). The
corresponding runtime guard is:

1. All emitted keyword strings must pass the stop-word pipeline (§2.3)
   before SHM write. Rejection is silent, not a raise.
2. No keyword string in the emitted list may be ≥ 12 characters AND
   match a regex for likely-handle pattern (`^[a-z0-9_]+$` with
   embedded underscore or digit run). This is a defence-in-depth
   heuristic — handles are typically `snake_case` or
   `alpha_numeric_247`. Dictionary words that match the pattern (rare)
   get rejected but the safety margin is worth the lost signal.
3. **Consent-safe package swap.** When the operator is on the
   `BITCHX_CONSENT_SAFE_PACKAGE` (palette flattened to muted grey),
   the keyword ward renders `[chat consent-safe]` in muted role and
   emits no tokens. Matches the existing
   `chat_ambient_ward.py::_fallback_package()` discipline.

---

## 4. State-dict contract

`ChatAmbientWard` exposes its state via the render-state dict (per the
orphan-plan Phase 1 `state()` override). `ChatKeywordsWard` follows
the same pattern.

### 4.1 Keys on the `state` dict

| Key | Type | Semantics |
|---|---|---|
| `keywords` | `list[dict]` | ranked top-N keywords (see 4.2) |
| `window_seconds` | `float` | window size used for extraction (60.0) |
| `window_end_ts` | `float` | unix timestamp of window end |
| `distinct_authors` | `int` | distinct-author count in window (context) |
| `eligible_count` | `int` | keywords passing min-distinct-author threshold |

The `keywords` entries are the only load-bearing field; the rest are
observability context.

### 4.2 Keyword entry shape

```json
{
  "token": "bachelard",
  "distinct_authors": 4,
  "rank": 1
}
```

- `token`: NFKC-normalised lowercased keyword, post all filters.
  Strings only. Max 40 chars.
- `distinct_authors`: int, ≥ 3 (below threshold does not appear).
- `rank`: 1-based rank, 1..N. Ward uses this directly to size the cell
  weight glyph.

### 4.3 Example full state dict

```json
{
  "keywords": [
    {"token": "bachelard", "distinct_authors": 5, "rank": 1},
    {"token": "reverie",   "distinct_authors": 4, "rank": 2},
    {"token": "#homage",   "distinct_authors": 4, "rank": 3},
    {"token": "feedback",  "distinct_authors": 3, "rank": 4},
    {"token": "voronoi",   "distinct_authors": 3, "rank": 5}
  ],
  "window_seconds": 60.0,
  "window_end_ts": 1734730980.17,
  "distinct_authors": 11,
  "eligible_count": 5
}
```

### 4.4 Idle / degraded state

```json
{
  "keywords": [],
  "window_seconds": 60.0,
  "window_end_ts": 1734730980.17,
  "distinct_authors": 2,
  "eligible_count": 0
}
```

Ward renders `[no chatter]` on empty `keywords`.

### 4.5 Implementation note — `state()` override

Following the Phase 1 pattern from the orphan-ward plan, the ward's
`state()` reads `/dev/shm/hapax-chat-keywords.json` (new; §6.1),
filters to the five keys above, and caches last-good for ≤ 120 s
before reverting to idle. Mtime-guarded staleness check — same
discipline as Phase 1.

---

## 5. HOMAGE ward spec

### 5.1 Placement on 1920×1080 canvas

Authored at 1920×1080; the compositor rescales at runtime
(`LAYOUT_COORD_SCALE = OUTPUT_WIDTH / 1920.0`, default 1280/1920).

- **Surface id: `chat-keywords-right`.**
- **Region: right chrome, directly beneath `chat-legend-right`.**
  Placement: `{x: 1560, y: 820, w: 340, h: 160, z_order: 20}`. This
  sits below the existing `chat_ambient` surface
  (`chat-legend-right` at `{x:1760, y:400, w:160, h:400}` per
  `default.json:444–460`) without overlap — `chat_ambient`'s bottom
  edge is y=800, keywords start at y=820.
- **Natural size: 320×140 px** (small margin within the 340×160
  region). Consistent with other right-column chrome (grounding
  ticker at 480×40, stream overlay at 400×200).
- **Z-order: 20.** Same as chat_ambient; below impingement_cascade
  (z=24) and reverie (z=10 pip, non-overlapping). No geometric
  conflict with impingement_cascade which ends at x=1740.
- **Anchored:** fixed placement. No DVD-bounce. Cells reshuffle in
  place on keyword turnover.

### 5.2 Typography

Per HOMAGE framework §4.3 and `chat_ambient_ward.py::_font_description`:

- **Primary font: Px437 IBM VGA 8x16**, size class `normal` (14 px)
  for keyword rows, `compact` (10 px) for the header strip.
- **Rendered via Pango** through
  `agents.studio_compositor.text_render.render_text` — NEVER direct
  Cairo `cr.show_text` (HOMAGE framework §4.3 + ward audit §19
  cross-invariant).
- **Weight: single.** BitchX is single-weight; bold maps to colour
  role, not typography (HOMAGE §4.3).

### 5.3 Colour palette

Per HOMAGE framework §4.4 and `bitchx.py::BITCHX_PALETTE`:

- Background: `background` role (near-black, `(0.04, 0.04, 0.04, 0.90)`).
- Row punctuation (brackets, pipes, markers): `muted` role
  (`(0.39, 0.39, 0.39, 1.00)` — grey skeleton).
- Keyword token text: `terminal_default` role
  (`(0.80, 0.80, 0.80, 1.00)`).
- Rank-1 keyword: `bright` role (`(0.90, 0.90, 0.90, 1.00)`).
- Rank-2 keyword: `accent_cyan` (`(0.00, 0.78, 0.78, 1.00)`).
- Rank-3 keyword: `accent_green` (`(0.20, 0.78, 0.20, 1.00)`).
- Rank-4, 5: `muted` with `terminal_default` token text. Receding
  rank = receding colour.
- Weight-glyph rail (CP437 block character per row indicating
  distinct-author count): `░` for 3, `▒` for 4–5, `▓` for 6–9, `█`
  for ≥10. Always in `muted` role (refuses colour ramp, per
  chat_ambient rate-gauge precedent).

No hardcoded hex; all colour lookups through
`get_active_package().resolve_colour(role)`. Consent-safe package swap
auto-flattens to muted grey, the same machinery that already flattens
chat_ambient.

### 5.4 Aesthetic grammar — ward layout

Cell layout, top-to-bottom, left-aligned:

**Header row** (compact, 10 px):
`»»» [CHAN|#hapax] [W|60s] [N|<eligible>/<distinct>]`

- `»»»` — line-start marker (HOMAGE §4.2, muted).
- `[CHAN|#hapax]` — channel badge, `#hapax` in `accent_cyan`.
- `[W|60s]` — window label, all muted.
- `[N|<eligible>/<distinct>]` — eligible keyword count over distinct
  author count. Digits in `bright`, punctuation muted.

**Keyword rows** (normal, 14 px), 5 rows:
Each row is a single line: `<weight_glyph> <token>`

- `<weight_glyph>`: CP437 block from §5.3 weight rail.
- `<token>`: rendered in rank-indexed colour role (rank-1 bright,
  rank-2 cyan, rank-3 green, rank-4/5 terminal_default).
- Left-aligned on an 8-px raster grid (HOMAGE §4.2
  `raster_cell_required`).
- Row height: 20 px (14 px glyph + 6 px leading). 5 rows = 100 px.
  Plus 16 px header + 16 px top/bottom padding → 132 px total, within
  natural 140.

**Idle state** (no eligible keywords):
Single row `[no chatter]` in muted role, centred vertically.

### 5.5 Transition vocabulary + cadence

Per HOMAGE `TransitionVocab` (§4.5):

- **Entry**: `ticker-scroll-in` on first eligible-keyword appearance
  after idle. Zero-frame cut once settled. 400 ms slide from right
  edge.
- **Keyword turnover** (new rank-1 differs from prior rank-1):
  `topic-change` — 200 ms inverse-flash on the whole ward, then
  zero-cut to new ordering.
- **Row-level turnover** (rank-N changes but rank-1 stable):
  `join-message` / `part-message` pairing — the new row scrolls in,
  the dropped row scrolls out. Simultaneous, choreographer-gated.
- **Exit to idle** (no eligible keywords): `part-message` for each
  row in reverse rank order, then settle to `[no chatter]`.
- **Recompute cadence**: 5 s. Only emit a transition if the ranked
  list **differs** from the prior snapshot. A stable list between
  ticks is a no-op (zero churn).
- **Turnover rate cap**: choreographer-level, inherited from HOMAGE
  framework. Max 2 simultaneous entries/exits per tick. A 5-row
  complete overturn spreads across multiple ticks.

Refusals (HOMAGE §5.5): no fade, no anti-aliasing, no rounded
corners, no emoji rendering inside the ward (emoji fraction is
aggregate-only, not drawn).

### 5.6 1-second cross-fade rationale

The brief proposed a 1 s cross-fade on keyword turnover. HOMAGE
grammar **refuses fades** (§5.5 "Fade/dissolve transitions
(zero-frame only)"). The topic-change flash (200 ms inverse flash →
instant cut) is the BitchX-authentic equivalent and is the
prescribed transition here. 1 s would read as Grafana chrome, not
BitchX.

---

## 6. Producer delta

### 6.1 New SHM file

**Path**: `/dev/shm/hapax-chat-keywords.json`.
**Writer**: `ChatKeywordsAggregator` (new sibling of
`ChatSignalsAggregator`, same module
`agents/studio_compositor/chat_signals.py` or a new file
`chat_keyword_aggregator.py`).
**Atomic write**: same tmp+rename pattern as
`ChatSignalsAggregator.write_shm` (`chat_signals.py:297–316`).

### 6.2 New field on `ChatSignals` — explicit non-addition

Do **NOT** add `keywords` to the existing `ChatSignals` dataclass.
Three reasons:

1. `ChatSignals` is consumed by the stimmung loop (Bundle 9 §2.5 per
   module docstring) and the `audience_engagement` formula. Adding a
   string-list field changes the dataclass's serialization surface
   and risks breaking downstream consumers.
2. The redaction invariant on `ChatAmbientWard` (`_coerce_counters`
   rejects strings) is made stronger by keeping `ChatSignals`
   numeric-only. A string-carrying `ChatSignals` breaks
   `_coerce_counters`'s defence in depth.
3. Keyword extraction is a materially different privacy surface (§3)
   that deserves its own SHM path and its own aggregator class with
   its own tests.

### 6.3 New aggregator shape

```python
class ChatKeywordsAggregator:
    """Tick-driven keyword aggregator, sibling of ChatSignalsAggregator.

    Consumes the same ChatMessage stream as ChatSignalsAggregator but
    extracts ranked top-N keyword tokens over a rolling window with
    strict consent discipline:

    - Per-author dedup (each author contributes ≤ 1 count per keyword
      per window).
    - Min distinct-author threshold (default 3) — no keyword ranks
      unless ≥ 3 distinct hashed authors used it.
    - Stop-word filter (general + idiom + operator-persona +
      dynamic-handle filters).
    - Mention (`@handle`) tokens rejected at extraction.
    - Output: top 5, sorted distinct-author desc then alphabetical.

    Writes /dev/shm/hapax-chat-keywords.json on `write_shm()`.
    """

    # Key method signatures (NO implementation here):
    def record_message(self, *, ts: float, author_handle: str, text: str) -> None: ...
    def compute_keywords(self, *, now: float) -> list[KeywordEntry]: ...
    def write_shm(self, keywords: list[KeywordEntry]) -> None: ...
```

**Critical boundary**: `record_message` accepts `text` because
keyword extraction is the ONE place in the producer chain where the
message body is legally traversed. The body NEVER leaves
`record_message` — the method extracts tokens, updates the internal
`dict[str, set[str]]` (keyword → set of distinct author hashes),
and discards the body. No body string is retained past the method
return. This mirrors the discipline `ChatSignalsAggregator` applies
to author handles (hash, retain hash only, discard raw).

### 6.4 Schema of emitted JSON

```json
{
  "keywords": [
    {"token": "bachelard", "distinct_authors": 5, "rank": 1},
    {"token": "reverie",   "distinct_authors": 4, "rank": 2},
    {"token": "#homage",   "distinct_authors": 4, "rank": 3}
  ],
  "window_seconds": 60.0,
  "window_end_ts": 1734730980.17,
  "distinct_authors": 11,
  "eligible_count": 3
}
```

Exactly the shape §4.3 defines. `tokens` list is length ≤ 5; `rank`
is 1-based dense (no gaps).

### 6.5 Wiring into `chat-monitor.py`

Per the orphan-ward plan §Phase 2, `ChatMonitor._process_message`
already hashes `author_id` and will push to `ChatSignalsAggregator`.
Extend: call `keywords_aggregator.record_message(ts, hashed_handle,
text)` on the same call site. Then on the 30 s compute tick, write
both `hapax-chat-signals.json` (existing) and
`hapax-chat-keywords.json` (new).

Producer freshness gauge (new, parallels existing):
`hapax_ward_producer_freshness_seconds{producer="chat_keywords"}`.
Budget cap from orphan-ward plan §4 remains untouched (keyword
extraction is local compute, no YouTube API calls).

### 6.6 Name for the new artefact

- **SHM file**: `/dev/shm/hapax-chat-keywords.json`.
- **Python class**: `ChatKeywordsAggregator`.
- **Ward class**: `ChatKeywordsWard` (new file
  `agents/studio_compositor/chat_keywords_ward.py`).
- **Source id**: `chat_keywords`.
- **Surface id**: `chat-keywords-right`.
- **Producer freshness label**: `chat_keywords`.

---

## 7. Director-loop recruitment

Yes — the ward participates in the emphasis-dispatch path via
`ward.highlight.chat_keywords.<modifier>` intent family
(`compositional_consumer.py::dispatch_ward_highlight` line 547). The
narrative-director can nominate it by writing to
`compositional_impingements[*].intent_family = ward.highlight.chat_keywords.<modifier>`,
which routes through the standard
`_apply_emphasis("chat_keywords", salience)` path at
`compositional_consumer.py:1248` and lands a
`ward-properties.json` entry that the ward renders as a border glow
(14 px) + 2 Hz pulse.

### 7.1 Affordance registration

One entry in `shared/compositional_affordances.py` (alongside
`ward.highlight.album.foreground` et al. at lines 230–242):

- **Affordance id**: `ward.highlight.chat_keywords.foreground`
  (canonical emphasis variant).
- **Gibson-verb description** (21 words, within 15–30 band):
  > Surface the currently-trending chat keywords when the
  > conversation's topic texture, not its rate, is what the moment
  > needs to legibly carry forward.

- **Companion entry**: `ward.highlight.chat_keywords.dim` — deprioritise
  the keyword ward when the director wants the surface quieter
  (mirrors `ward.highlight.album.dim` / `ward.highlight.captions.dim`
  pattern).

Gibson-verb framing (per `docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`):
surfaces / shows / reveals, cognitive-function framing, not
implementation-framing.

### 7.2 Structural-intent nomination

`structural_intent.ward_emphasis: [chat_keywords]` also recruits the
ward via the parallel path at `compositional_consumer.py:1415`. The
structural director nominates by listing `chat_keywords` in the
`ward_emphasis` array. Same visible envelope (border glow + pulse)
lands via `_apply_emphasis`.

### 7.3 Content programming bias

Per the ward audit §7.6 and `2026-04-20-programme-layer-plan.md`
pattern:

- Research programmes: bias up (topic-texture is informative during
  research-mode grounded-director passes).
- Music-foregrounded programmes: bias down (keyword texture competes
  with album + vinyl wards for attention).
- Hothouse programmes: neutral — ambient.

Programme soft-priors never hard-gate the ward — per the `programmes
enable grounding` memory principle, a programme that nominally
downweights `chat_keywords` must still let it fire when a high-
salience impingement beats the bias.

### 7.4 Idle-state director hook

When the ward sits in idle state (`[no chatter]`) for > 5 min, emit a
passive impingement (`chat.idle.sustained`) that the director loop
can consume. The director might then recruit `prompt_scout`-style
content to re-seed chat, or bias the captions ward brighter to
compensate. This is an **observation**, not a control loop;
implementation deferred to programme layer v2.

---

## 8. Open questions for operator

Three, all answerable with defaults encoded so execution does not
block. If the operator does not answer, execution proceeds on the
indicated defaults.

1. **Min-distinct-author threshold default.** §2.4 + §3.2 set it at 3.
   Under high-visibility livestreams (>200 concurrent viewers), 3 may
   be too permissive — two bots + one confederate can surface a
   coordinated keyword. Options:
   - A. Fixed at 3 (current proposal).
   - B. Fixed at 5.
   - C. Adaptive: `max(3, round(distinct_authors_60s / 4))`.
   **Default if unanswered**: A (fixed at 3). Env var
   `HAPAX_CHAT_KW_MIN_DISTINCT_AUTHORS` overrides.

2. **Persona stop-word list source.** §2.3.3 lists the operator's
   identity tokens. The canonical place to store these is ambiguous:
   `axioms/contracts/operator.yaml`? `shared/chat_stopwords.py`? A
   new `config/chat-extraction.yaml`? Secrets boundary matters —
   real handle names are persistent soft identifiers.
   **Default if unanswered**: `config/chat-extraction.yaml` (new),
   gitignored by default, loaded at producer start. Operator
   manually populates post-deploy; stop-word filter is fail-closed
   if the file is missing (producer refuses to start, not silent
   partial filter).

3. **Hashtag inclusion.** §2.2 keeps `#`-prefixed tokens as first-class
   keywords. Hashtags carry author-intent topic marking but are rare
   in YouTube chat compared to Twitter/X. Drop-all-hashtags
   simplifies the surface and avoids the edge case where a hashtag is
   a person's handle (`#hapax_2026`).
   **Default if unanswered**: Keep hashtags as first-class keywords
   (current proposal) — the dynamic handle-filter (§2.3.4) catches
   handle-coincident hashtags. Revisit after first live bakeoff.

---

## 9. Summary

- New ward: `ChatKeywordsWard`, surface id `chat-keywords-right`,
  natural 320×140 px, right chrome beneath `chat_ambient`.
- Signal: keyword texture complements (does not replace) the existing
  `chat_ambient` rate/tier surface — distinguishes **what** from
  **how much**.
- Extraction: 1-gram, 60 s window, stop-word filtered (global + idiom
  + persona + dynamic-handle), per-author dedup, min 3 distinct
  authors, top 5 ranked by distinct-author count.
- Consent: `@handle` mentions rejected; bare-name residual mitigated
  by multi-layer stop-words + multi-author threshold + tmpfs-only
  persistence; axiom conformance test rejects any string leakage to
  SHM that resembles a fixture handle.
- State contract: five keys on the render-state dict, `keywords` as
  ranked `list[dict]` with `token`/`distinct_authors`/`rank`.
- Producer delta: new `ChatKeywordsAggregator` class, new SHM file
  `/dev/shm/hapax-chat-keywords.json`, wired into `chat-monitor.py`
  alongside `ChatSignalsAggregator` on the 30 s tick, new
  `hapax_ward_producer_freshness_seconds{producer="chat_keywords"}`
  gauge. No addition to `ChatSignals` dataclass.
- HOMAGE grammar: Px437 IBM VGA 8x16, mIRC-16 palette via active
  package, rank-indexed colour roles, 200 ms topic-change flash on
  rank-1 turnover (NOT 1 s cross-fade — fades refused by HOMAGE
  §5.5), choreographer-gated turnover, consent-safe package auto-
  flattens to muted grey.
- Director-loop: one affordance (`ward.highlight.chat_keywords.foreground`,
  21-word Gibson-verb description) + standard `structural_intent.ward_emphasis`
  path; dim-variant also registered.
- Three open questions, each with a sensible default so execution
  proceeds without blocking.

---

## 10. References

- `docs/superpowers/plans/2026-04-20-orphan-ward-producers-plan.md` §11 Q4
  (closed as out-of-scope; reopened by this doc on operator directive).
- `docs/superpowers/specs/2026-04-18-chat-ambient-ward-design.md`
  (sibling ward spec).
- `docs/superpowers/specs/2026-04-18-homage-framework-design.md`
  (§4.2 grammar, §4.4 palette, §4.5 transition vocab, §5.5 refusals).
- `docs/research/2026-04-20-ward-full-audit-alpha.md` §7
  (chat_ambient audit — sibling surface, same consent discipline).
- `agents/studio_compositor/chat_ambient_ward.py`
  (`_coerce_counters` redaction pattern).
- `agents/studio_compositor/chat_signals.py::ChatSignalsAggregator`
  (hashing discipline at `compute_signals`, 60 s window, atomic SHM
  write).
- `agents/studio_compositor/chat_classifier.py::ChatTier`
  (T0–T6 definitions).
- `agents/studio_compositor/homage/bitchx.py`
  (`BITCHX_PACKAGE`, `_BITCHX_PALETTE`, consent-safe package).
- `axioms/registry.yaml` — `interpersonal_transparency` (weight 88, T0,
  constitutional; full text quoted in §3).
- `shared/compositional_affordances.py` — sibling ward-highlight
  affordance registrations (lines 230–242).
- `config/compositor-layouts/default.json` — layout geometry
  conventions.
- Prior art: [TwitchViz], [Twitch Chat Emote Analyzer], YouTube
  Studio blocked-words documentation — confirm 15s/60s/5min rolling
  window norm and stop-word filter pattern.

[TwitchViz]: https://www.researchgate.net/publication/302073979_TwitchViz_A_Visualization_Tool_for_Twitch_Chatrooms
[Twitch Chat Emote Analyzer]: https://github.com/factaxd/Twitch-Chat-Emote-Analyzer
