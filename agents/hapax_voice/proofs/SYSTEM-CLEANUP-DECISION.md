# System Cleanup Decision: Strip to Research Essentials

**Date:** 2026-03-21
**Trigger:** Operator directive — "clean out ALL GUNK from the systemic pathways. No need for ANYTHING here other than what's justified for research."

## The Principle

The voice system has accumulated features, context injections, policy blocks, and environmental signals that serve personal utility but are NOT part of the research model. For Cycle 2, every token in the system prompt must be justified by the grounding model. Incidental utility from the research infrastructure itself is acceptable. Intentional non-research features are not.

## What Must Be Justified

Every element injected into the system prompt must answer: **"What grounding function does this serve?"**

If the answer is "none — it's useful for the operator" → remove for Cycle 2.
If the answer is "it enriches a Clark medium constraint or Traum grounding act" → keep and document why.

## Integration Insights (from this session)

The bands, stimmung, apperception, salience router, and concern graph are NOT separate from grounding — they ARE the grounding substrate:

- **STABLE band** = discourse record (thread + grounding states + pacts)
- **VOLATILE band** = turn-specific grounding directives (effort level, acceptance-actuation)
- **Stimmung** = grounding quality signal (GQI IS a stimmung input)
- **Apperception** = medium constraint enrichment (copresence, audibility, shared referent context)
- **Salience router** = effort calibration (activation × GQI → effort level)
- **Concern graph** = Clark's "sufficient for current purposes" (grounding criterion shifts by concern weight)

## Experiment Lockdown Redesign

Old lockdown froze ALL volatile bands. New lockdown must distinguish:

- **Lock:** model routing (always CAPABLE), non-grounding policy, screen context FORMAT
- **Don't lock:** effort level, acceptance-actuation directives, grounding state injection — these ARE the intervention

## Pending Concerns (DO NOT LOSE TRACK)

After planning, must address:
1. Full audit of current system prompt content — what's in there now, what stays, what goes
2. Band content justification — every injection point mapped to grounding function
3. Stimmung ↔ GQI coupling design
4. Salience router re-enable as effort calibrator (not model selector)
5. Apperception channels mapped to Clark's medium constraints
6. Concern graph → grounding criterion modulation
7. Lockdown redesign for refined model
8. RLHF anti-pattern monitoring (does prompted Opus fight our grounding constraints?)
