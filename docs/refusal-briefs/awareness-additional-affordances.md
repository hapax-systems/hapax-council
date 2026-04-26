# REFUSED — Awareness Surface: Additional Affordances

**Status:** REFUSED (constitutional)
**Domain:** operator awareness surfaces (state spine + refusal log + 6 consumer surfaces)
**Sibling brief:** `awareness-acknowledge-affordances.md` (#1513)
**HFE canon:** Sarter & Woods (1995); Endsley (1995); Bainbridge (1983); Parasuraman & Riley (1997); Lee & See (2004)

This brief refuses **four sibling affordances** on the operator-awareness
surface that share the same anti-pattern as acknowledge / mark-read /
dismiss / triage:

1. tile-tap-action (interactive watch/phone tile drill-in or modal)
2. scheduled-summary-cadence (digest-every-4h, end-of-day rollup, etc.)
3. calendar-reminder-injection (auto-create calendar events from awareness items)
4. operator-curated-filters (per-operator hide/include lists)

All four are refused for the same reason: they convert an **ambient,
read-only, refusal-as-data** surface into an **interactive
queue-management** surface. Doing so reintroduces the exact
automation-surprise / mode-error pathology the awareness epic was
designed to prevent.

## Common anti-pattern

Each refused affordance has the same structural failure mode:

- **Operator-believes-state-is-bounded.** Once an item can be
  tapped/digested/calendared/filtered, the operator treats absence of
  the item from the surface as "the item has been handled." This is
  the same illusion `acknowledge` would create.
- **System-believes-operator-is-triaging.** The presence of a
  per-item or per-cohort affordance implies that downstream behavior
  (alerting, retry, escalation) can depend on operator action — which
  it cannot, because awareness is constitutionally NOT a queue.
- **Loss of refusal-as-data.** Hiding, summarizing, or rescheduling
  refusals destroys the canonical refusal-log timeline that downstream
  research artifacts (e.g. refusal annex series #1506, #1510, #1514)
  depend on.

## Per-affordance refusals

### 1. tile-tap-action — REFUSED

**Proposed behavior:** Tapping an awareness tile on the watch or phone
opens a detail modal, marks the item "seen," or links to a related
artifact.

**Refusal grounds:**
- Watch and phone surfaces are read-only by constitutional design;
  the surface IS the broadcast. Tapping introduces a hidden mode
  (item is "seen" / "unseen") that the operator must mentally model.
- Detail modals create a bounded-attention illusion: the operator
  closes the modal and feels the item is handled. It is not — the
  underlying system state is unchanged.
- The watch-summary endpoint (~256 byte tile-friendly view, #1504)
  is the entire interaction surface. Adding tap-affordances would
  require a parallel "what has this operator tapped" state, which
  is queue-management by another name.

**Build instead:** the existing read-only tile renderer. If the
operator needs more detail, the SSE stream (`/api/awareness/stream`)
and the daily-note vault extension (#1491) provide the full
unredacted view at the operator's own cadence.

### 2. scheduled-summary-cadence — REFUSED

**Proposed behavior:** Hapax emits a periodic digest (every 4h, EOD,
weekly) that summarizes awareness activity since the last digest.

**Refusal grounds:**
- The weekly review (#1511) is **deterministic rollup of vault
  daily-notes**, NOT a digest. It does not emit verdicts, does not
  carry forward "unread" state, and is not push-delivered.
- A scheduled digest implies the operator did NOT see the underlying
  events at the time they happened — but the awareness surface IS
  always-on and always-visible. Digests would be redundant in the
  golden case and misleading in the failure case (operator reads
  the digest, assumes coverage, and the underlying surface drifts).
- Push-cadence digests create the same operator-believes-bounded
  illusion as `acknowledge`: the operator treats the digest as the
  edge of a triage horizon.

**Build instead:** the omg.lol fanout (#1508) which emits a
≤280 char factual line on state change, NOT on a schedule. The
Mastodon/Bridgy public log is the cadence.

### 3. calendar-reminder-injection — REFUSED

**Proposed behavior:** Awareness items can be auto-created as Google
Calendar events ("Remind me about X tomorrow at 9am").

**Refusal grounds:**
- Calendar is **operator-authored content**. Auto-injection
  introduces machine-authored events into a surface the operator
  uses for life planning, violating the
  `feedback_full_automation_or_no_engagement` constitutional rule
  in the opposite direction (machine writes into operator-curated
  space, not operator into machine-curated space).
- Calendar events imply commitment + acknowledgment-on-fire (the
  notification banner becomes an ack-affordance by proxy). This is
  the same `acknowledge` failure mode wearing a Google badge.
- Awareness state is **already always-visible**; converting items
  to calendar reminders implies they would otherwise be missed,
  which contradicts the surface's design.

**Build instead:** the SSE stream + watch tile + vault daily-note
already provide always-visible context. If the operator wants a
calendar event for a specific item, they create it manually — and
that authorship choice itself becomes refusal-log data if Hapax
proposed it and the operator declined.

### 4. operator-curated-filters — REFUSED

**Proposed behavior:** Operator-defined hide-lists or include-only
lists ("don't show me X", "only show me Y").

**Refusal grounds:**
- Filters create **invisible state**: the operator looks at the
  awareness surface and sees a filtered view, then reasons about
  the world based on that view. The filter becomes a hidden
  trust-asymmetry between Hapax-state and operator-belief.
- Filters destroy refusal-as-data: a refusal that the operator has
  filtered out is no longer in the canonical refusal log from the
  operator's vantage. Downstream artifacts (refusal annex series,
  weekly review) would diverge from operator-perceived reality.
- The `public_filter` pattern (server-side block-level redaction,
  shipped in #1493 / #1508) is a **constitutional** filter — it
  enforces interpersonal-transparency and corporate-boundary axioms.
  Operator-curated filters would be the inverse: hiding system
  state from the operator on operator request, which is exactly
  what awareness refuses to do.

**Build instead:** the always-on full-fidelity stream. If a class
of awareness item is genuinely noise, the fix is to refuse emitting
it at the producer (with a refusal-log entry recording the refusal),
NOT to filter at the consumer.

## Cross-references

- Sibling: `docs/refusal-briefs/awareness-acknowledge-affordances.md` (#1513)
- Substrate: `agents/refusal_brief/writer.py` + `rotator.py` (#1478, #1479)
- State spine: `agents/operator_awareness/aggregator.py` (#1489)
- Read API: `logos/api/routes/awareness.py` (#1493, #1504)
- Vault append: `agents/vault_context_writer.py` (#1491)
- Weekly rollup: `agents/operator_awareness/weekly_review.py` (#1511)
- Public fanout: `agents/operator_awareness/omg_lol_fanout.py` (#1508)
- Constitutional axiom: `feedback_full_automation_or_no_engagement`

## What this brief does NOT refuse

- **Read-only legibility surfaces** added to the awareness epic.
  The watch tile, phone view, SSE stream, vault daily-note section,
  weekly rollup, and omg.lol fanout are all in-scope and already
  shipped.
- **Producer-side refusals.** Refusing to emit an awareness item
  (with a refusal-log entry) at the producer is the right place to
  reduce noise — not consumer-side filters.
- **Unstructured operator authorship.** The operator can manually
  create calendar events, vault notes, todos, etc. from awareness
  data at their own cadence; what's refused is **automated injection**.

## Refusal-log shape

When any of the four affordances is proposed (in spec, plan, audit,
or PR), the refusal-brief substrate records:

```jsonl
{"timestamp": "<iso>", "surface": "operator_awareness",
 "refused": "<one of: tile_tap_action | scheduled_summary_cadence |
            calendar_reminder_injection | operator_curated_filters>",
 "brief": "docs/refusal-briefs/awareness-additional-affordances.md",
 "axiom": "interpersonal_transparency"}
```

Downstream artifacts (refusal annex series, weekly rollup) inherit
the refusal as data; nothing is aggregated, judged, or summarized
into a verdict.
