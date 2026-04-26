# Audit-yaml schema (tier-aware)

P-1 of the absence-class-bug-prevention-and-remediation epic. Per-PR `audit-PR-<N>.yaml` files declare a structured attestation that the PR has been substrate-verified, not just text-fluent. Tier determines which fields are required.

## Why

The 8-hour audit identified the absence-class bug pattern: PRs that pass tests, look fluent in description, and merge cleanly — but the production data path doesn't connect because the symbol described in one file is never authored in the file the substrate consumes from. "All the right words" is a signal of LLM-fluent prose, not correct wiring.

The audit-yaml schema closes that gap by requiring authors to *attest* to specific substrate properties in machine-checkable fields. Auditors consume the yaml; CI validates the schema.

## Tiers

A PR is one of three tiers, determined by what it touches:

| Tier | Touches | Required fields | Velocity cost |
|---|---|---|---|
| 0 | docs only (`.md`, `docs/**`, `CLAUDE.md`) | none beyond title/summary | 0 |
| 1 | tests, scripts, configs (no daemon code) | `tests_run`, `lint_passed` | <30s |
| 2 | daemon code (`agents/**`, `shared/**`, `logos/**`) | tier-1 fields PLUS the 4 substrate-truth fields below | ~2 min |

## Tier-2 substrate-truth fields

Each is a boolean (with optional `note:` if `false`).

### `data_flow_traced`

Author has traced the production data path end-to-end for any new symbol introduced. For a new producer: identified at least one consumer that calls it. For a new consumer: identified the producer that supplies its expected input. Trace path documented in `note:` when this field is `false` (e.g., "deferred — wiring lands in PR N+1").

Catches v1, v3, v5 of the 2026-04-26 voice-silence corpus (orphan voice_state probe; TTS chain → L-12 only; passive node).

### `production_path_verified`

Author has verified the changed code path runs against production fixtures (or substrate smoke tests), not just unit-test fixtures the author imagined. For wiring changes: the new wiring was loaded by the actual daemon at least once and produced expected output. For pure refactors: at least one happy-path runtime invocation of the refactored function was witnessed.

Catches: any PR where 72/72 unit tests pass but `pgrep` of the daemon shows it never called the function.

### `peer_module_glob_match`

For PRs that introduce or modify a glob/regex/path constant referenced from multiple files (e.g., `HAPAX_*_DIR`, `SUBDIRS=("active","closed")`, vault path traversals): all peer modules that read or write the same logical surface use coherent glob bases.

Catches B2 P0-A/B/C/D — three downstream readers of `iter_refused_tasks()` walked `active/` only when the classifier walked both.

### `new_function_call_sites`

A list (possibly empty) of file:line locations where any newly-introduced public function or method is called. Empty list means "no new public callable" OR "tier-0 / tier-1 PR" — author asserts via the empty list, audit job verifies.

Catches B1's 30-strong "defined but never called" cluster directly.

## File location

Each PR ships its audit-yaml at `audits/audit-PR-<N>.yaml`. The yaml is part of the PR commit; CI validates the schema before merge.

For PRs landing without a yaml (most pre-P-1 PRs in flight): tier-0 default applies. The schema validator at `scripts/validate-audit-yaml.py --tier <N>` returns 0 for missing files at tier-0/1 + non-zero only when a tier-2 PR's yaml is missing required fields.

## Sequencing

P-1 is the schema + validator + templates only. Subsequent items in the epic:

- **P-7** cross-session audit invariant — hook that prevents a session from auditing its own merges (audit goes to a peer); requires P-1 to define what an audit *is*
- **P-3** substrate smoke tests — per-substrate fixtures that exercise the production path; complement to `production_path_verified`
- **P-5** post-merge-trace.service — daemon-side runtime witness that confirms the production path actually fired post-merge (counterpart to the static attestation here)

## Cross-references

- Voice-silence postmortem (R-20 part 1): `docs/research/2026-04-26-voice-silence-multi-incident-postmortem.md`
- Synthesis (full epic context): `~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md` § 3.2 P-1
- 8-hour audit (the seed): `~/.cache/hapax/relay/research/2026-04-26-8hr-audit.md`
