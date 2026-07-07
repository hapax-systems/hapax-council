# License reconciliation status

**Status:** LOCAL LICENSE POSTURE RECONCILED — live GitHub/license-detection
closure is tracked separately in the public-surface live-state report. Zenodo's
machine `license` field uses `other-closed` because PolyForm Strict is not a
standard Zenodo license id; the same Zenodo record carries the explicit
repository-license note. Verify that note from the checked-in `.zenodo.json`
object itself; GitHub diff views may truncate before the `notes` field.

## Current Local State

| Surface | Declared license |
|---|---|
| `LICENSE` (file) | PolyForm Strict 1.0.0 |
| `NOTICE.md` | PolyForm Strict 1.0.0 |
| `CITATION.cff` | `license: PolyForm-Strict-1.0.0` |
| `codemeta.json` | `https://polyformproject.org/licenses/strict/1.0.0/` |
| `.zenodo.json` | `license: other-closed`; `notes` names PolyForm Strict 1.0.0 |
| `README.md` | Defers to `NOTICE.md` / `CITATION.cff` / `codemeta.json` |
| Public prose | Uses "source-visible" to describe inspectability, not an open-source license |

## Decision rationale (2026-05-09)

Path 1 adopted per operator directive ("research best license for me and go with it"). Research agent evaluated Apache 2.0, AGPL-3.0, BSL, Elastic 2.0, SSPL, PolyForm Noncommercial, and CC BY-NC-SA against six requirements:

1. **Academic citation / priority:** License is irrelevant — priority comes from public disclosure + Zenodo DOI timestamps. PolyForm Strict does not impede.
2. **Defensive IP / patent blocking:** PolyForm Strict includes patent grant + defensive termination, structurally equivalent to Apache 2.0. Disclosure creates prior art regardless of license permissiveness.
3. **Revenue from consulting/methodology:** Apache 2.0 actively undercuts consulting value by allowing free commercial forks. PolyForm Strict preserves the code as a visible portfolio piece.
4. **Visible/inspectable but not freely reusable:** The literal design purpose of PolyForm Strict — source-available, not open-source.
5. **No obligation to supporters:** Zero CLAs, no copyleft enforcement, no reciprocal sharing.
6. **Constitutional alignment:** `single_user` axiom (weight 100) and NOTICE.md's refusal stance are philosophically coherent with PolyForm Strict.

## Remaining Items

- ✅ Repository license posture converges on PolyForm Strict 1.0.0; Zenodo uses
  `other-closed` only as its platform compatibility field and carries the
  PolyForm Strict note in `notes`
- ⏳ Reconcile live GitHub/licensee detection where the live-state report still
  records blocking license-detection drift
- ✅ Profile README at correct public GitHub location (`hapax-systems/.github/profile/README.md`)
- ✅ README/profile drift checks in `tests/docs/test_readme_current_project_spine.py` and `tests/docs/test_github_profile_readme_spine.py`

## Recheck

```bash
uv run python scripts/github-public-surface-reconcile.py
gh api repos/hapax-systems/.github/contents/profile/README.md --jq '{path,sha,html_url}'
gh api repos/hapax-systems/hapax-council --jq '{repo:.full_name,license:.license}'
python - <<'PY'
import json, pathlib, yaml
assert yaml.safe_load(pathlib.Path("CITATION.cff").read_text())["license"] == "PolyForm-Strict-1.0.0"
assert json.loads(pathlib.Path("codemeta.json").read_text())["license"].endswith("/strict/1.0.0/")
zenodo = json.loads(pathlib.Path(".zenodo.json").read_text())
assert zenodo["license"] == "other-closed" and "PolyForm Strict 1.0.0" in zenodo["notes"]
PY
uv run pytest tests/docs/test_readme_current_project_spine.py::TestLicenseReconciliationStatusDoc tests/shared/test_github_public_surface.py -q
```
