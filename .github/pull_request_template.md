External pull requests are not an intake path for this repository. This
template is for internal, operator-governed PRs that carry an authority
case.

## Summary


## AuthorityCase

<!-- Required for all PRs under the AuthorityCase methodology.
     Pre-methodology PRs: write "pre-methodology" below.
     Format: CASE-ID / SLICE-ID (e.g., CASE-SDLC-REFORM-001 / SLICE-002) -->

**Case:** <!-- CASE-XXX or pre-methodology -->
**Slice:** <!-- SLICE-XXX or N/A -->

## Test plan


## Agent instruction hygiene

- [ ] If this PR fixes something documented as broken, in-flight, or "currently <X>" in AGENTS.md or CLAUDE.md, update the authored instruction source (follow a compatibility symlink to its target).
- [ ] If this PR closes a documented epic, collapse its instruction-file narrative to a one-line pointer to the handoff doc.
- [ ] This PR adds no new `(PR #NNN)` fingerprints, "fixed YYYY-MM-DD" notes, or "currently broken" claims.
