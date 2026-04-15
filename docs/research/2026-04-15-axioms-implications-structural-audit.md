# `axioms/implications/` directory structural audit

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #125)
**Scope:** Structural audit of `axioms/implications/` directory. Depends on queue item #109 (axiom registry drop-62 §10 alignment audit, shipped in PR #867). Verify each implication file maps to a registry entry, frontmatter consistency, no orphaned files, drop #62 §10 ratified implications present.
**Register:** scientific, neutral

## 1. Headline

**`axioms/implications/` is structurally clean.** 5 implication files map 1:1 to the 5 axioms in `axioms/registry.yaml`. All 90 implications use consistent 2-letter prefix IDs matching their parent axiom. Zero orphaned files, zero missing files.

**Drop #62 §10 ratified implications status (unchanged from queue item #109 finding):** 4 of 5 ratified amendments are MISSING from the implication files. This is expected drift — waits for LRR Phase 6 joint `hapax-constitution` PR per Q5 ratification.

## 2. 1:1 mapping verification

| Registry axiom | Implication file | Count | Prefix |
|---|---|---|---|
| `single_user` | `axioms/implications/single-user.yaml` | 25 implications | `su-*` |
| `executive_function` | `axioms/implications/executive-function.yaml` | 42 implications | `ex-*` |
| `management_governance` | `axioms/implications/management-governance.yaml` | 7 implications | `mg-*` |
| `interpersonal_transparency` | `axioms/implications/interpersonal-transparency.yaml` | 9 implications | `it-*` |
| `corporate_boundary` | `axioms/implications/corporate-boundary.yaml` | 7 implications | `cb-*` |

**Perfect 1:1 mapping.** Every axiom has exactly one implications file + every file has a corresponding axiom. **No orphaned files.** **No missing files.**

**Total implications:** 90 across 5 files.

## 3. Frontmatter consistency

All 5 implication files share a consistent frontmatter schema:

```yaml
axiom_id: <underscore_id>
derived_at: <ISO-8601 date>
model: balanced
derivation_version: <int>
implications:
  - id: <prefix-category-NNN>
    tier: <T0|T1|T2>
    text: ...
    enforcement: <block|warn|advisory>
    canon: <textualist|purposivist>
    mode: <compatibility|sufficiency>
    level: <component|system>
```

### 3.1 Variance within schema

`single-user.yaml` has an `amended_at` field not present in the other 4:

```yaml
axiom_id: single_user
derived_at: '2026-03-03'
amended_at: '2026-03-17'
model: balanced
derivation_version: 2
```

This is intentional — `su-*` implications have been amended once since initial derivation (per the `derivation_version: 2` vs the others' `derivation_version: 1`). The `amended_at` field is optional but correct when present.

### 3.2 ID prefix consistency

| File | Prefix pattern | Count | Verdict |
|---|---|---|---|
| `corporate-boundary.yaml` | `cb-*` | 7/7 | ✓ consistent |
| `executive-function.yaml` | `ex-*` | 42/42 | ✓ consistent |
| `interpersonal-transparency.yaml` | `it-*` | 9/9 | ✓ consistent |
| `management-governance.yaml` | `mg-*` | 7/7 | ✓ consistent |
| `single-user.yaml` | `su-*` | 25/25 | ✓ consistent |

**90/90 implication IDs use the correct 2-letter axiom prefix.** Zero drift.

## 4. Drop #62 §10 ratified implications status

Per queue item #109 (`docs/research/2026-04-15-axiom-registry-drop-62-alignment-audit.md`, shipped in PR #867), drop #62 §10 ratifies 5 constitutional amendments. Their current state in `axioms/implications/`:

| # | Amendment | Expected file | Status |
|---|---|---|---|
| 1 | `it-irreversible-broadcast` | `axioms/implications/interpersonal-transparency.yaml` | **MISSING** |
| 2 | `su-privacy-001` | `axioms/implications/single-user.yaml` | **PRESENT** ✓ |
| 3 | `corporate_boundary` Q4 clarification | `axioms/implications/corporate-boundary.yaml` (new entry) OR `registry.yaml` text edit | **MISSING** |
| 4 | `mg-drafting-visibility-001` | `axioms/implications/management-governance.yaml` | **MISSING** |
| 5 | `sp-hsea-mg-001` precedent | `axioms/precedents/sp-hsea-mg-001.yaml` (new file — not an implication) | **MISSING** (out of scope for implication audit) |

**4 of 5 are MISSING.** This was already flagged in queue item #109 and is NOT a drift-in-code bug — the amendments wait for the LRR Phase 6 joint `hapax-constitution` PR vehicle per §10 Q5 ratification.

This audit confirms the queue item #109 finding structurally: the 4 missing implications are absent from the directory + the 1 present implication (`su-privacy-001`) is correctly in `single-user.yaml`.

## 5. Count distribution across axioms

```
executive_function:    42 implications (47%)
single_user:           25 implications (28%)
interpersonal_transparency: 9 implications (10%)
corporate_boundary:     7 implications (8%)
management_governance:  7 implications (8%)
```

`executive_function` has the most implications at 42 because it's the "zero-config agents, errors include next actions, routine work automated" axiom — lots of operational consequences. `single_user` has 25 because "one operator, no auth, no roles" has wide blast radius across auth/user/tenant code. The domain-scoped axioms (`management_governance`, `corporate_boundary`) have fewer implications because their scope is narrower.

**No structural concern.** The distribution matches the axiom weighting in `registry.yaml` (weights 100, 95, 88, 90, 85).

## 6. Orphaned files check

```
$ ls -la axioms/implications/
total 32
-rw-r--r-- corporate-boundary.yaml
-rw-r--r-- executive-function.yaml
-rw-r--r-- interpersonal-transparency.yaml
-rw-r--r-- management-governance.yaml
-rw-r--r-- single-user.yaml
```

**5 files, 5 axioms, zero orphans.** No `.yaml.bak`, no `.yaml.old`, no stale `legacy-*.yaml`. Clean directory.

## 7. Related directories

`axioms/` top-level contains:

- `registry.yaml` — canonical axiom definitions (5 entries)
- `implications/` — this audit's subject (5 files, 90 implications)
- `precedents/` — **contains only a `seed/` subdirectory, no YAML files**
- `contracts/` — consent contracts (out of scope)
- `schemas/` — schema definitions (out of scope)
- `constitutive-rules.yaml`, `enforcement-exceptions.yaml`, `enforcement-patterns.yaml`, `README.md` — supporting files

**`axioms/precedents/` is essentially empty** — the `seed/` subdirectory exists but no precedent YAMLs have been committed yet. This is where `sp-hsea-mg-001` + the 70B reactivation guard should land during the LRR Phase 6 joint PR. Currently both are missing.

**Scope note for the Phase 6 opener:** creating `axioms/precedents/sp-hsea-mg-001.yaml` + `axioms/precedents/lrr-70b-reactivation-guard-001.yaml` is the first population of the `precedents/` directory. Authoring session should use `seed/` as a template pattern if any seed files exist there (alpha did not spot-check seed contents).

## 8. Recommendations

1. **No immediate action needed.** The `axioms/implications/` directory is structurally clean + consistent.
2. **LRR Phase 6 joint PR must add 3 implications** (per queue item #109):
   - `it-irreversible-broadcast` to `interpersonal-transparency.yaml`
   - `corporate_boundary` Q4 clarification — prefer new implication entry in `corporate-boundary.yaml` over `registry.yaml` text edit (keeps axiom text stable)
   - `mg-drafting-visibility-001` to `management-governance.yaml`
3. **LRR Phase 6 joint PR must also create 2 precedent files** in the empty `axioms/precedents/` directory:
   - `sp-hsea-mg-001.yaml` (drafting-as-content precedent, substrate-agnostic)
   - `lrr-70b-reactivation-guard-001.yaml` (substrate-specific, status: dormant)
4. **Spot-check `axioms/precedents/seed/`** during the Phase 6 authoring session to see if there's a template pattern. Alpha did not walk into the seed dir in this audit; it's a low-priority follow-up.

## 9. Closing

`axioms/implications/` is structurally clean. The queue item #109 finding about the 4 missing drop #62 §10 implications is reconfirmed from the structural-audit angle. No orphaned files, no frontmatter drift, 90/90 implications use correct prefix IDs.

Branch-only commit per queue item #125 acceptance criteria.

## 10. Cross-references

- Queue item #109: `docs/research/2026-04-15-axiom-registry-drop-62-alignment-audit.md` (shipped in PR #867)
- `axioms/registry.yaml` — canonical axiom definitions
- `axioms/implications/*.yaml` — the 5 audited files
- `axioms/precedents/` — empty dir where LRR Phase 6 joint PR should land 2 new precedent files
- Drop #62 §10 Q5 ratification: `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` §10 + §12

— alpha, 2026-04-15T18:02Z
