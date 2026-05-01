# Token Pole Reward Qualifiers — Governance Rubric

**Status:** Normative. Every PR touching the reward mechanic
(`agents/studio_compositor/token_pole.py`, `scripts/chat-monitor.py`
accumulator logic, `scripts/token_ledger.py`) MUST preserve all
qualifiers in this document.
**CVS Task:** #147 (qualifier rubric for the token pole reward
mechanic).
**Paired with:** #146 (reward-mechanic implementation).
**Companion spec:** `docs/superpowers/specs/2026-04-18-token-pole-reward-mechanic-design.md`.
**Ethical constraint source:** `docs/streaming/2026-04-09-garage-door-open-handoff.md §3.1`.

---

## 1. Why this rubric exists

The reward mechanic turns viewer activity into a visible climb on
the token pole and, at threshold, a glyph spew. Any reward
mechanic is a training signal for the viewer population. A mechanic
that rewards the wrong signal will drift the chat toward that
signal. The operator's directive (2026-04-06, cited in
`docs/superpowers/specs/2026-04-18-token-pole-reward-mechanic-design.md §1`):

> "research ways of determining those qualifiers that are actually
> healthy, not patronizing, not cheesy, not manipulative and
> actually likely to lead to positive results. The risks here are
> considerable."

The risks are considerable because the operator is visibly active
on the stream and will see, in real time, whatever the reward
mechanic produces. An unhealthy reward loop produces an unhealthy
stream. This document is the list of what "healthy,
non-manipulative, non-cheesy" means in enforceable terms.

## 2. Three qualifier axes

The rubric partitions every proposed reward into three independent
axes. A reward is only admissible if it clears all three.

### 2.1 Healthy

Reward design that does not foster compulsive engagement or
chat-population pathology. Specifically:

- **Diminishing returns per author.** Already implemented in #146:
  author-hashed message counts enter the window with a hash-based
  per-author cap. A single viewer emitting N contributive messages
  in a window must not produce N units of reward — the marginal
  contribution decays after the first few. This is structural, not
  cosmetic, so "spam your way to the top" fails by construction.
- **Rate cap at the window level.** The qualifier window has a
  hard cap on `total_contribution`. Exceeding it is silently
  clipped. The pole cannot climb faster than the cap allows,
  regardless of chat volume. Prevents feedback loops where a brief
  flood of activity pulls the pole past threshold and re-triggers
  the spew within the same minute.
- **Refractory period after reward.** Immediately after a glyph
  spew, the pole enters a refractory window (≥ one full qualifier
  window, `≥60s`) during which no further climb registers. The
  refractory period is not hidden — `difficulty_tier` shifts and
  the overlay reflects the current state. Prevents trigger-spew
  oscillation and lets chat reset to baseline.

Operationalization: the `Band A — Qualifier Window Counters`
schema in the reward spec §5 already carries `window_duration_s`
and a summed `total_contribution`. The rate cap is a clip on that
sum. The refractory period extends `window_start` past a spew.
Implementation lands in `scripts/chat-monitor.py` accumulator
(#146 PR series).

### 2.2 Non-manipulative

Reward design that does not train the operator or the viewers in
patterns they did not consent to.

- **No named-player callouts. Aggregate-only.** The reward spec's
  constitutional constraint §3.1 already bars per-author state in
  the ledger. This rubric extends the bar to the visible reward:
  no viewer name, no viewer count-of-name, no "top contributor"
  board, no glyph attributable to a specific handle. The spew is a
  collective artefact of the window, not a leaderboard moment.
  Enforcement: `chat_reactor.py` caplog test pattern — the reward
  code path emits no author text at any log level. Duplicate this
  test for the token-pole module.
- **No variable-ratio reinforcement schedule.** Variable-ratio
  reinforcement (slot-machine scheduling — reward fires on an
  unpredictable number of inputs) is the load-bearing addictive
  mechanism in gambling and compulsive-engagement design. It is
  structurally excluded. Spew fires on a deterministic threshold
  crossing, not on a randomized trigger. The spec §4 already
  commits to this: "Spew fires deterministically on threshold,
  never variable-ratio." This rubric pins the constraint as a PR
  gate.
- **Threshold visible; no "surprise" jackpots.** The current
  `pole_position` and threshold are published to
  `/dev/shm/hapax-compositor/token-ledger.json` and rendered in
  the overlay. Viewers see how far the pole is from threshold at
  all times. No hidden multipliers, no "10x tonight" events, no
  time-limited bonuses. The mechanic is boring by design — boring
  is the feature.

The "surprise jackpot" exclusion is not performative. In practice
the temptation to add one comes from the operator's own engagement
drift: a slow stream feels like it needs a "moment," and a surprise
multiplier is the cheap way to produce one. The rubric catches this
by making the threshold publicly visible — adding a surprise
multiplier now requires changing the published threshold, which is
a visible schema change that triggers review.

### 2.3 Non-cheesy

Reward design that matches the BitchX / HOMAGE register. The
livestream carries a scientific-register voice (research mode) or a
sparse, non-performative voice (R&D mode). Cheesy rewards break
register and signal to viewers that the stream is a performance,
not a workspace.

- **BitchX register over cutesy pop-up alerts.** The active HOMAGE
  package (§4.2) is BitchX — IRC terminal aesthetic. Cyan accents,
  TEXTMODE voice register, monospace markers. A "🎉 New tier
  reached!" toast fails register. A terminal-style
  `[hapax] --- new tier ---` marker passes.
- **Marker text in scientific register.** The glyph spew is
  accompanied by a marker text describing the event, not praising
  the viewers. Correct: `FROM {N}` where `N` is the aggregate
  contribution count (a structural descriptor, literally "from N
  contributions"). Wrong: `AMAZING CHAT!! {N} of you!`,
  `THANK YOU!`, or any form of direct viewer address. The rubric
  bars second-person pronouns in marker text entirely.
- **Glyph selection reflects the signature-artefact corpus.** Spew
  glyphs are drawn from the active HOMAGE package's artefact
  corpus (spec §4.3). The corpus is a fixed set of
  operator-curated signatures — not emoji, not cute icons,
  not logo-adjacent decoration. This keeps the visual register
  consistent with the rest of the surface.

## 3. Disqualifiers — single-strike exclusions

Imported from the #146 reward spec §4 and pinned here as governance
gates. A message triggers zero contribution if any disqualifier
fires. These are pre-accumulator gates — the message never enters
the qualifier window counters.

- **Flattery without substance.** Pattern match on flattery-phrase
  corpus (`wow`, `amazing`, `love this`, `best stream`, etc.)
  without any of: a reference token, a technical term, a specific-
  referent question.
- **Performative engagement.** Levenshtein distance < 5 vs any of
  the last 20 messages from the same author hash (detects
  copy-paste and "me too" repetition).
- **Brigading.** N identical (or Levenshtein-similar) messages
  from N distinct author hashes within a 30s window. Suggests
  coordinated inflation.
- **Command-spam double-count.** A message that already triggered
  a `!`-prefixed command cannot additionally contribute via the
  qualifier path.
- **Emote / ASCII / single-word.** Messages whose token count
  after emote-stripping is < 3 contribute zero.
- **Direct rubric solicitation.** Messages asking how the pole
  works, how to climb it, or how to trigger a spew are excluded.
  The mechanic is visible but not gameable.
- **Out-of-band identity claims.** Messages claiming to be the
  operator, a moderator, or any named third party. Identity
  claims are not classifier-gated but zeroed here so they can't
  farm contribution.
- **Non-operator PII.** Any message containing detected PII (email,
  phone, address, employer) about a non-operator party. Failing
  closed protects the axiom `interpersonal_transparency` at the
  reward layer.

## 4. Subs / donations — platform-gated

Subs, donations, and memberships bypass the qualifier rubric. The
platform's payment gesture already asserts the contributive act;
the rubric does not re-evaluate it. Fixed token increments per
support surface (`config/support-surface-registry.json` enumerates
the post-Patreon-refusal surfaces under `no_perk_support_doctrine`:
liberapay_recurring, lightning_invoice_receive, nostr_zaps). The
per-surface increment is operator-set and not dynamic.

Note: an earlier draft of this section referenced
`config/sister-epic/patreon-tiers.yaml` as the tier source. Patreon
is REFUSED per `docs/refusal-briefs/leverage-patreon.md`; that file
is now a `superseded_refusal` artifact (`tiers: []`,
`activation_allowed: false`) and the canonical tier-source is the
support-surface-registry above.

Rationale: re-evaluating a paid gesture via the qualifier rubric
would (a) silently disqualify some paid messages, which breaks
the platform contract, and (b) invite the operator to drift the
rubric toward or away from paid messages based on income
considerations, which is a manipulation vector against the
operator's own decisions.

## 5. Enforcement — how this doc bites

1. **Caplog pattern test.** The existing `chat_reactor.py` test
   enforces that reward code paths emit no author/message text
   at any log level. Duplicate the pattern in a test for the
   token-pole module. PRs that log author text fail.
2. **Schema pin.** The token-ledger JSON schema is pinned in
   `scripts/token_ledger.py` — adding a per-author field or a
   surprise-multiplier field fails schema validation in the
   accumulator test.
3. **Spec-gate on PR description.** PRs touching the reward
   mechanic must cite this document in the PR body and state
   which qualifier axes the change affects. The CODEOWNERS
   entry for this file requires operator review.
4. **Prometheus visibility.** The refractory window, rate cap,
   and per-author decay are visible as counters
   (`hapax_token_pole_contribution_clipped_total`,
   `hapax_token_pole_refractory_active`). A non-zero
   `_clipped_total` is expected (the cap fires); a stuck
   `_refractory_active` flag suggests the refractory logic
   drifted.

## 6. Not in scope

- **Sentiment scoring.** Architecturally excluded. The three
  axes above use structural signals only (novelty, Shannon
  surprise, disqualifier fires). Sentiment reward drifts chat
  toward flattery; the rubric forbids it.
- **Leaderboards.** The mechanic is collective. No per-viewer
  ranking, no "top N" display, no MVP highlight.
- **Time-limited events.** No "2x tokens tonight", no "holiday
  mode". The mechanic is stationary — viewers who return after
  a month should find the same rules.
- **Operator-visible reward.** The reward spew is for the
  livestream surface, not for operator attention. The pole
  climbs in peripheral vision. No sound cue, no notification,
  no operator-directed "nice work" signal.

## 7. Cross-references

- **Reward spec:** `docs/superpowers/specs/2026-04-18-token-pole-reward-mechanic-design.md`
- **Reward plan:** `docs/superpowers/plans/2026-04-18-token-pole-reward-mechanic-plan.md`
- **Ethical constraints source:** `docs/streaming/2026-04-09-garage-door-open-handoff.md §3.1`
- **Research inputs:** `/tmp/cvs-research-146.md`, `/tmp/cvs-research-147.md`
- **HOMAGE package registry:** `agents/studio_compositor/homage/`
- **Per-surface increments:** `config/support-surface-registry.json`
  (post-Patreon-refusal canonical source; `config/sister-epic/patreon-tiers.yaml`
  remains as a `superseded_refusal` artifact only)
- **Ledger schema:** `scripts/token_ledger.py`

## 8. Decisions imported from #146

The #146 spec already committed the following; this document pins
them as governance rather than leaving them as spec text only:

- Aggregate-only counters; no per-author state in the ledger
  (spec §3 constraint 1).
- Measure structure, not quality — T-tier structural classifier
  is the entire signal (spec §3 constraint 2).
- Transparent mechanics — difficulty curve published, no surprise
  jackpots (spec §3 constraint 3).
- Sub-logarithmic scaling in active viewers (spec §3 constraint 4).
- Never loss-frame — pole position monotonically non-decreasing
  in a session (spec §3 constraint 5).
- No individual glyph attributable to a specific viewer (spec §3
  constraint 6).
- No sentiment reward (spec §3 constraint 7).
- Deterministic payout `{0, 1, 2}` per message (spec §4).
- Subs / donations not classifier-gated (spec §4).

The commit body for the PR that lands this document must cite
these #146 decisions by constraint number so the audit trail is
traceable from either direction (spec → governance doc, or
governance doc → spec).
