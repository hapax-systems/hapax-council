# Orphan-implications wiring train — phase 1 closeout (2026-05-01)

**Author:** epsilon
**Predecessor catalog:** `docs/research/2026-05-01-coherence-orphan-implications-catalog.md`
**Train arc:** 9 PRs, all merged, all self-directed.
**Final orphan count:** 59 (was 92 at catalog time; 33 gaps closed, 36%).

## Premise

The orphan-implications coherence gap was first surfaced when PR
#1998 (`load_implications` discovers standalone-schema files) made
the full implication corpus visible to `shared.coherence.check_coherence()`.
Before #1998, ~84 implications were visible; the loader fix exposed
+8 standalone-schema implications, raising the count to 92. Catalog
PR #2003 documented the gap distribution and proposed a three-category
triage strategy:

1. **Code-direct annotation** (~30 estimated) — implications enforced
   via direct text-reference in agent code. Annotate with
   `linkage: code-direct`; coherence skips them.
2. **Natural-mapping wiring** (~40 estimated) — implications with
   obvious path/frontmatter patterns. Add constitutive rules in
   `axioms/constitutive-rules.yaml`.
3. **Dead-letter retirement** (~20 estimated) — paper rules with no
   current enforcement. Mark `status: retired`.

This drop documents Phase 1 (code-direct annotation) closeout.

## Phase 1 — what shipped

| PR | Phase | Drop | Cumulative |
|---|---|---|---|
| #2007 | linkage field + 4 standalones | 92 → 88 | 4 |
| #2010 | cb-cluster (5 corporate_boundary) | 88 → 83 | 9 |
| #2013 | mg-cluster (3 management_governance) | 83 → 80 | 12 |
| #2015 | ex-cluster (16 executive_function) | 80 → 64 | 28 |
| #2017 | su+it cluster (3 single_user + 2 interpersonal_transparency) | 64 → 59 | 33 |

**33 of 92 orphan gaps closed (36%).**

The actual code-direct count (33) exceeded the catalog's estimate
(~30) — a few impls in `mg-*`, `ex-*`, and `it-*` had richer
text-reference patterns than the initial scan caught.

## What stays as orphans (59 remaining)

The remaining 59 split into the catalog's other two categories:

### Natural-mapping wiring candidates (~40)

Paper-rule impls that have natural path-pattern or frontmatter
mappings. Examples:

- `su-storage-001` → `~/hapax-state/**` ingestion contexts
- `su-paths-001` → repository path conventions
- `su-deployment-001` → systemd unit file patterns
- `ex-config-001`, `ex-config-005` → `config/*.yaml` patterns
- `mg-selfreport-001` → operator self-report ingestion paths

These need real `axioms/constitutive-rules.yaml` additions: each
rule declares "files matching X count as Y under context Z, governed
by implication W." The wiring is real governance work — it ties
brute facts to institutional facts to regulative implications.

### Dead-letter retirement (~20)

Paper rules with no obvious mapping AND no code references. These
are governance-spec leftovers from earlier axiom-derivation passes
that didn't survive into deployment. Examples:

- `cb-extensible-001`, `cb-parity-001` — broad architectural claims
  without specific brute-fact targets
- `mg-deterministic-001`, `mg-bridge-001` — abstract management-
  governance principles
- Several `ex-*` planning-mode impls

These should be marked `status: retired` (with rationale) so the
coherence check stops flagging them.

## Lessons learned

### 1. Triage discipline matters

The phase-1 train annotated only impls with verified code
references — never pattern-matched on impl ID alone. Each cluster
PR included a "do NOT annotate" list with paper rules deliberately
left as orphans. Without this discipline, the orphan count would
shrink while the audit-coverage gap actually widened (paper rules
masquerading as code-direct).

The test pattern that emerged:

```python
def test_check_coherence_real_tree_drops_N_X_cluster_orphans():
    code_direct = (...)
    for not_orphan in code_direct:
        assert not_orphan not in orphan_ids
    legitimate_orphans = (...)  # paper rules verified no code refs
    for orphan in legitimate_orphans:
        assert orphan in orphan_ids  # CRITICAL: must STILL appear
```

The "still appears as orphan" assertion is the discipline guard. It
prevents future regressions where someone might over-annotate a
cluster.

### 2. Loader fixes had outsized leverage

The two loader fixes (#1998 + #2001) were "infrastructure" work that
unlocked the train's measurable progress. Before #1998, 8
implications were invisible to `check_coherence`; the audit
machinery couldn't even count what it didn't see. Loader infrastructure
is the kind of thing whose value compounds — every subsequent audit
PR depended on the loader working right.

### 3. Natural-mapping work is harder

Phase 1 (annotation) was mechanical: grep for code refs, annotate
verified ones, leave paper rules. Phase 2 (natural-mapping wiring)
requires designing institutional types per implication and writing
real constitutive rules — much more invasive. Each rule needs:

- An `institutional_type` not yet in the registry
- A `brute_pattern` that actually matches the implication's intent
- `linked_implications` cross-reference
- Verification that the constitutive rule fires on the right brute
  facts

A reasonable next batch is 5-10 rules per PR, not 16 like the
ex-cluster annotation batch.

### 4. Audit-as-data composes

Each PR in this train was a self-directed cc-task; the audit
findings drove the work. The catalog (#2003) was the durable
artifact that made the work claimable: future sessions or this
session's continuation could pick up where the train left off
without re-deriving the strategy.

This pattern — audit → catalog → batched wiring train — generalizes
beyond coherence gaps. Other audit-style work (refusal-lifecycle,
publication-bus wiring, ALM-governance) could follow the same
shape.

## Pointers

- Catalog: `docs/research/2026-05-01-coherence-orphan-implications-catalog.md`
- Loader fixes: PR #1998 (standalone-impls), PR #2001 (load_precedents)
- Linkage field + skip logic: PR #2007 (`shared.axiom_registry.Implication.linkage` + `shared.coherence.check_coherence` filter)
- Cluster batches: #2010 (cb), #2013 (mg), #2015 (ex), #2017 (su+it)
- Test discipline pattern:
  `tests/test_axiom_registry.py::test_check_coherence_real_tree_drops_*`
- Final orphan count: 59 (expected to stay around this number until
  Phase 2 natural-mapping wiring lands)
