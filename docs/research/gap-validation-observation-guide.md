# Phase 3: Practitioner Observation Guide

## Purpose

Remote contextual inquiry protocol for validating research gaps that remain
ambiguous after Phase 1 (automated sweep) and Phase 2 (community probe).
Use when the decision matrix yields fewer than 4 agreeing signals.

## When to Use

- Phase 1 sweep returned "low_confidence_needs_phase2" or "medium_confidence_novel"
- Phase 2 community probes returned mixed or no responses
- The gap involves tacit knowledge that published sources may not capture

## Participant Selection

Target 3-5 domain practitioners who:
- Work in the intersection area described by the gap
- Have 5+ years domain experience
- Are NOT the gap author (avoid confirmation bias)
- Represent different organizational contexts (academic, industry, open source)

## Interview Protocol (Remote Contextual Inquiry)

Duration: 30-45 minutes, recorded with consent.

### Opening (5 min)

Explain the purpose: "I'm validating whether a specific research gap is
genuinely novel. I'll describe a capability intersection and ask whether
you've encountered anything similar."

### Core Questions (20-30 min)

1. **Current practice:** "In your work on [domain], how do you currently
   handle [core capability described by the gap]?"

2. **Combination awareness:** "Have you seen a system that combines
   [component A] with [component B] in a single architecture? If so,
   what were the results?"

3. **Barrier identification:** "What prevents practitioners in your field
   from building something like [gap description]? Is it technical
   complexity, lack of need, or something else?"

4. **Prior attempts:** "Are you aware of any projects — published or
   unpublished — that attempted this combination? What happened to them?"

5. **Tacit knowledge:** "Is there domain knowledge about why this
   combination is difficult or unnecessary that wouldn't appear in
   published literature?"

6. **Community awareness:** "If someone had solved this, where would you
   expect to find evidence? Which conferences, forums, or communities?"

7. **Validation of novelty:** "On a scale of 1-5, how surprised would
   you be to learn that no existing system combines these capabilities?
   (1 = not surprised at all, 5 = very surprised)"

### Closing (5 min)

- Ask for referrals to other practitioners
- Offer to share findings
- Confirm consent for anonymized use in publications

## Scoring

Map each interview to a signal vote:
- Surprise score 4-5 + no prior examples cited → **novel**
- Surprise score 2-3 + some partial examples → **inconclusive**
- Surprise score 1 + specific prior art cited → **prior_art_exists**

Aggregate across 3-5 participants. Majority vote becomes the
`practitioner_observation` signal in the decision matrix.

## Output

Write results to `{gap_id}-phase3-observation.json` with:
- participant_count
- anonymized responses per question
- individual votes
- aggregate vote
- referenced prior art (if any)

## Ethics

- Obtain informed consent before recording
- Anonymize all participant data in outputs
- Do not name participants in publications without explicit permission
- Offer co-authorship if contributions are substantial
