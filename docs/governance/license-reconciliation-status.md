# License reconciliation status

**Status:** RESOLVED — all four canonical surfaces declare PolyForm Strict 1.0.0.

## Current state

| Surface | Declared license |
|---|---|
| `LICENSE` (file) | PolyForm Strict 1.0.0 |
| `NOTICE.md` | PolyForm Strict 1.0.0 |
| `CITATION.cff` | `license: PolyForm-Strict-1.0.0` |
| `codemeta.json` | `https://polyformproject.org/licenses/strict/1.0.0/` |
| `README.md` | Defers to `NOTICE.md` / `CITATION.cff` / `codemeta.json` |

## Decision rationale (2026-05-09)

Path 1 adopted per operator directive ("research best license for me and go with it"). Research agent evaluated Apache 2.0, AGPL-3.0, BSL, Elastic 2.0, SSPL, PolyForm Noncommercial, and CC BY-NC-SA against six requirements:

1. **Academic citation / priority:** License is irrelevant — priority comes from public disclosure + Zenodo DOI timestamps. PolyForm Strict does not impede.
2. **Defensive IP / patent blocking:** PolyForm Strict includes patent grant + defensive termination, structurally equivalent to Apache 2.0. Disclosure creates prior art regardless of license permissiveness.
3. **Revenue from consulting/methodology:** Apache 2.0 actively undercuts consulting value by allowing free commercial forks. PolyForm Strict preserves the code as a visible portfolio piece.
4. **Visible/inspectable but not freely reusable:** The literal design purpose of PolyForm Strict — source-available, not open-source.
5. **No obligation to supporters:** Zero CLAs, no copyleft enforcement, no reciprocal sharing.
6. **Constitutional alignment:** `single_user` axiom (weight 100) and NOTICE.md's refusal stance are philosophically coherent with PolyForm Strict.

## Remaining items

- ✅ All four metadata surfaces converged
- ⏳ Verify GitHub `licensee` gem detects PolyForm Strict in repository settings
- ✅ Profile README at correct public GitHub location (`ryanklee/ryanklee/README.md`)
- ✅ README/profile drift checks in `tests/docs/test_readme_current_project_spine.py` and `tests/docs/test_github_profile_readme_spine.py`
