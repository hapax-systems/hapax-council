# Coherence orphan-implications catalog (2026-05-01)

**cc-task:** `coherence-orphan-implications-catalog` (P3, WSJF 3.5)
**Author:** epsilon
**Predecessors:** PR #1998 (load_implications discovers standalone-schema)
+ PR #2001 (load_precedents canonical loader). Both shipped today
under self-directed audits this session.

## Premise

After the two loader fixes landed, `shared.coherence.check_coherence()`
now sees the full implication corpus — 92 implications across 5
axioms (was: ~84 before the loader fix exposed 8 standalone files).
The coherence check reports **92 orphan-implication gaps**: every
implication currently lacks a constitutive rule
(`shared/constitutive.py::ConstitutiveRule.linked_implications`)
feeding it.

This is structural backlog rather than a single-PR fix. Filing this
catalog so the wiring work is visible + sized + claimable.

## Current state (smoke output)

```
$ uv run python -c "
from shared.coherence import check_coherence
r = check_coherence()
print('Total gaps:', len(r.gaps))
"
Total gaps: 92
```

## Distribution by axiom prefix

| Prefix | Axiom | Orphan implications |
|---|---|---:|
| `ex` | `executive_function` | 42 |
| `su` | `single_user` | 26 |
| `cb` | `corporate_boundary` | 8 |
| `it` | `interpersonal_transparency` | 8 |
| `mg` | `management_governance` | 8 |
| | **Total** | **92** |

The skew toward `executive_function` (42) and `single_user` (26)
matches their breadth: these axioms have the largest implication
sets because they govern the broadest behavioral surface (operator
ergonomics, single-user defaults). Domain axioms (`cb`, `it`, `mg`)
have tighter scopes and correspondingly smaller implication lists.

## What "orphan" means here

`shared/coherence.py::check_coherence()` walks
`axioms/constitutive-rules.yaml` and the implication corpus, then
reports `gap_type='orphan_implication'` for any implication ID
that no constitutive rule lists in its `linked_implications` array.

The `linked_implications` mechanism is documented in
`shared/constitutive.py`:

```yaml
- id: cr-source-gdrive
  brute_pattern: "rag-sources/gdrive/*"
  institutional_type: gdrive-data
  context: ingest
  match_type: path
  linked_implications: [it-consent-001]
  description: "Files in rag-sources/gdrive/ count as Google Drive data"
```

The chain is: brute fact (file at path) → constitutive rule
(institutional fact "this counts as gdrive-data") → regulative
implication (`it-consent-001`: must verify consent contract before
ingestion) → enforcement (block, review, warn, lint).

An orphan implication is the link missing in that chain: an
implication exists with declared enforcement, but no constitutive
rule classifies brute facts in a way that triggers the implication.
Enforcement may still happen via direct text-reference in agent
code (the four standalone implications I made discoverable in #1998
all enforce that way), but the **structural link** between brute
data and the implication isn't auditable through the coherence
machinery.

## Wiring strategy (proposal — not in scope for this PR)

The 92 gaps split into three rough categories per implication
shape:

1. **Implications with natural constitutive-rule mappings**
   (~40 of 92): pattern-based classifications already implicit in
   path conventions or frontmatter. Example: `it-consent-001`
   (consent-contract-required) already has rules for
   `rag-sources/gdrive/*`, `rag-sources/gmail/*`, `rag-sources/proton/*`
   — but newer implications like `it-attribution-001` (attribution
   for redistributed third-party content) don't have constitutive
   rules pointing brute facts under `assets/aesthetic-library/` to
   the implication. These can be wired one-by-one without behavior
   change.

2. **Implications that enforce via code**, not via constitutive
   rule (~30): the four standalone implications I made discoverable
   (`it-irreversible-broadcast`, `mg-drafting-visibility-001`,
   `cb-officium-data-boundary`, `su-non-formal-referent-001`)
   plus the existing direct-text-reference implications. These
   should EITHER ship constitutive rules that capture the same
   enforcement semantics OR be marked `linkage: code-direct` so
   the coherence check stops flagging them.

3. **Implications that are dead letters** (estimated ~20): paper
   rules with no current code path enforcing them at all. These
   need either a constitutive rule + code path OR explicit
   retirement (status: retired in the implication file).

## Acceptance criteria for the follow-up cc-task

- [ ] Per-axiom triage: classify each of the 92 orphans into the
  three categories above.
- [ ] Wire ~40 natural-mapping implications via constitutive rule
  additions (one PR per axiom, batched).
- [ ] Annotate the ~30 code-direct implications with a
  `linkage: code-direct` field (or equivalent) and update
  `check_coherence` to skip them.
- [ ] Retire the dead-letter implications (~20) with explicit
  rationale.
- [ ] After wiring, `check_coherence().gaps` should be ≤ 10 (a
  sustainable ongoing-backlog bar, not zero — new implications
  may temporarily ship without rules).

## Why this is a P3 / WSJF 3.5

Operator pain is currently low (the orphans are paper artifacts;
real enforcement happens via direct text reference + the
constitutive rules already wired for `it-consent-*`). The audit
machinery just doesn't see the linkage. Shipping a wiring train
makes future governance reports trustworthy by closing the
"undercount of active implications" failure mode that PRs #1998
+ #2001 already exposed.

This is the kind of substrate work a future session can pick up
methodically; the catalog is the staging artifact.

## Pointers

- Coherence module: `shared/coherence.py::check_coherence` (returns
  `CoherenceReport` with `gaps: list[CoherenceGap]`).
- Constitutive rules: `axioms/constitutive-rules.yaml` (3
  implications currently linked: `it-consent-001`,
  `it-consent-002`, `it-environmental-001`).
- Loader fixes (this session):
  - PR #1998 — standalone-schema implication discovery (4 files
    previously invisible to canonical loader).
  - PR #2001 — `load_precedents()` canonical loader added (was
    missing entirely).
- Implications corpus: `axioms/implications/*.yaml` (5 list-schema
  + 4 standalone-schema files).
- Total implication count visible to the loader: 92 (includes the
  8 newly-discovered via PRs #1998 + #2001).
