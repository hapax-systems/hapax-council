# Gap Portfolio Registry Schema

**Co-located with:** `gap-portfolio-registry.yaml`

## Record Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| gap_id | string | yes | Unique identifier (GAP-NNN) |
| title | string | yes | Human-readable gap name |
| request_ref | string | yes | Cross-reference to REQ-* in hapax-requests |
| disposition | enum | yes | `execute` / `publish` / `hold` |
| validation_status | string | yes | Current validation state |
| uniqueness_score | float 0-1 | yes | How unique to this apparatus |
| composability_score | float 0-1 | yes | How well it composes with other gaps |
| decay_rate_halflife_days | int | yes | Time until gap value halves |
| unique_apparatus_required | bool | yes | Whether moat components are necessary |
| apparatus_justification | string | yes | Which moat components and why |
| last_reviewed | date | yes | Last operator review date |

## Disposition Values

- **execute** — actively being implemented/validated. WIP limit: exactly 1.
- **publish** — gap is documented and ready for publication as a gap map or paper.
- **hold** — gap is real but not being worked. Value decays per half-life.

## WIP Invariant

Exactly one gap may have `disposition: execute` at any time. The registry enforces this as a constraint, not a guideline.

## Moat Components

The 7 moat components referenced in `apparatus_justification`:

1. stigmergic_coordination
2. temporal_grounding
3. perceptual_embodiment
4. axiom_governance
5. single_operator_architecture
6. bayesian_claim_tracking
7. publication_bus_provenance
