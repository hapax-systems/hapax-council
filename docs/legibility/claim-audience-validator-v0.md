# Claim/Audience Validator v0

The legibility validator binds `LegibilityEvidenceRecord` receipts to bounded
`ClaimRecord` objects and audience-specific `AudienceProfile` rules. It is not
a publication engine; it is the first fail-closed gate that future canonical
surface generators and determination-exchange packets must call before
rendering or exporting a claim.

## Contract

- Current-state claims require at least one referenced evidence record.
- Missing evidence blocks.
- Failed evidence blocks.
- Stale evidence blocks current-state claims.
- Public-targeted claims require `status: approved_public`.
- Public-targeted claims may only use evidence where `public_safe: true` and
  `privacy_class` is `public` or `public_registry`.
- Enterprise/testbed claims block known unsafe inferences, including employer
  endorsement, production readiness without pilot evidence, and transferability
  of private Hapax runtime state.

## Initial Audiences

The default registry covers:

- `operator`
- `worker_lane`
- `enterprise_testbed`
- `public_adopter`
- `paid_buyer`
- `security_legal_reviewer`
- `intellectual_audience`

The profiles are intentionally conservative. Operator and worker-lane contexts
may consume private evidence; public and buyer-facing contexts require
public-safe evidence; enterprise/testbed contexts are treated as bounded pilots,
not endorsements or production-readiness proof.
