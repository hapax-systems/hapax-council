# Hapax Replay Demo Residency Kit

**For:** institutional viewers — residency selection committees, grant
reviewers, sponsor-safe support program assessors, talk hosts.

**Cc-task:** `replay-demo-residency-kit`
**Generator:** `shared/replay_demo_card.py`
**Upstream contract:** `shared/archive_replay_public_events.py`

This kit packages Hapax as a rights-safe, replayable, n=1 live
epistemic lab — without requiring the operator to perform a custom
manual presentation per audience.

## What you are looking at

Hapax is a single-operator system the operator runs on his own
workstation to externalize executive-function work. Audio, video, IR,
and biometrics flow through programme-aware substrates that the
operator narrates live; replay-able archive segments are the durable
artifact.

Each `ReplayDemoCard` you receive is a verified slice of that
instrument: one archive segment that:

* has a public replay URL (`public_url`),
* carries a chapter mark (`chapter_label` + `chapter_timecode`) so a
  deck slide can deep-link into the moment,
* carries a frame thumbnail (`frame_uri`),
* carries provenance — a token plus the supporting evidence refs the
  upstream archive-replay adapter used to clear the segment,
* declares its rights and privacy posture explicitly, and
* attaches the operator's own n=1 framing (`n1_explanation`) plus a
  suggested audience steer.

Every card the kit emits has been independently gated by the
[archive-replay-public-event-link-adapter](../../shared/archive_replay_public_events.py).
The kit does not re-relax that gate; it tightens it further by
admitting only the public-safe rights and privacy classes:

| Rights class | Admitted? |
|---|---|
| `operator_original` | yes |
| `operator_controlled` | yes |
| `third_party_attributed` | yes |
| `third_party_uncleared` | no |
| `platform_embedded` | no |
| `unknown` | no |

| Privacy class | Admitted? |
|---|---|
| `public_safe` | yes |
| `aggregate_only` | yes |
| `consent_required` | no |
| `operator_private` | no |
| `unknown` | no |

A decision that fails any gate becomes a `ReplayDemoSkip` carrying the
reason. Operator dashboards surface skips so a missing card is
auditable, not silent.

## What this kit is not

This kit is a **projection**. It does not:

* run live broadcast (the operator does, on his own time, on his own
  workstation);
* publish to YouTube, Mastodon, Bluesky, or any social surface (those
  are governed by the publication-bus's own surface-policy gates);
* author institutional copy beyond the n=1 framing the operator
  supplies at generation time;
* infer "publicly replayable" from raw HLS sidecars alone — the
  upstream adapter's
  [temporal-span gate](../../shared/temporal_span_registry.py) must
  pass before the kit will consider a decision.

## Refusal / guardrail appendix

The kit deliberately does not implement several patterns institutional
viewers may expect from a typical demo package. Each is a recorded
refusal, not an oversight.

### No generic-revenue forms

Hapax's monetization rails are receive-only by design (see the
publication bus's `monetization_rails` family). The operator does not
sell tickets, take sponsorships keyed to view-counts, or run
crowdfunding campaigns through this surface. Card emission is
explicitly NOT a revenue or fundraising signal.

### No auto-generated outreach

The kit does not produce email drafts, call-to-action copy, "subscribe
for more" footers, or auto-follow / auto-DM scripts. Each card carries
the operator's own n=1 framing prose; the operator authors it before
generation, not after.

### No third-party-uncleared content

A single `third_party_uncleared` rights-class card would invalidate
the entire kit's claim to be "rights-safe." The kit fails closed at
the rights-class gate — the upstream adapter ALSO fails closed before
the decision reaches us — and the failed decision is recorded as a
skip with the rights class echoed in the detail.

### No private content

`consent_required` and `operator_private` privacy classes are gated
out for the same reason: the kit is for institutional surfaces. Cards
from non-public substrates would leak operator-private state into a
public residency packet. Skipped, with reason recorded.

### No live cuepoints, captions, or curated-queue hallucinations

The kit handles only `archive.segment`-class RVPE events from the
archive-replay adapter. It does not consume `cuepoint.candidate`
(those route through the live cuepoint write path with operator-
supervised smoke), `caption.segment` (those route through the caption
substrate adapter with AV-offset evidence), or any curated-queue
"named music" claim (those flow through `_curated_music_framing`
with its own four-branch gate).

### No re-aggregation across operators

Hapax is single-operator by constitutional axiom (`single_user`).
There is no "team" view, no comparison dashboard, no cross-operator
benchmark. Cards describe one operator's instrument; institutional
synthesis across operators is an out-of-scope category.

## How to consume the cards

```python
from shared.archive_replay_public_events import (
    adapt_hls_sidecar_to_replay_public_event,
)
from shared.replay_demo_card import generate_demo_cards

decisions = [
    adapt_hls_sidecar_to_replay_public_event(
        sidecar=sidecar,
        evidence=evidence,
        registry=registry,
        generated_at=now,
        now=now,
    )
    for sidecar, evidence in operator_pre_approved_pairs
]

cards, skips = generate_demo_cards(
    decisions,
    n1_explanation="<operator-authored prose>",
    suggested_audience="<operator-authored steer>",
)

# Render `cards` in your residency surface; surface `skips` to the
# operator dashboard for audit.
```

The card model is frozen and unambiguous; an institutional surface
adapter consumes it without re-querying upstream state.

## Operator action required before each delivery

The kit is generator-only — it emits cards from verified upstream
state but does not pick which segments to feature. For each
institutional delivery, the operator selects the `(sidecar, evidence)`
pairs to feed in and authors the n=1 framing prose. The kit does not
auto-curate; that judgment is the operator's instrument.
