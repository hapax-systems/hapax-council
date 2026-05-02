# License reconciliation status

**Status:** OPERATOR-ACTION REQUIRED — license metadata is not internally consistent.

Per cc-task `github-readme-profile-current-project-refresh`, the README must not contradict the canonical project metadata. This document records the current divergence so the README's posture (point at NOTICE/CITATION/codemeta as the canonical statement) is auditable rather than implicit.

## Current state

| Surface | Declared license |
|---|---|
| `LICENSE` (file) | Apache License 2.0 |
| `NOTICE.md` | PolyForm Strict 1.0.0 |
| `CITATION.cff` | `license: PolyForm-Strict-1.0.0` |
| `codemeta.json` | `https://polyformproject.org/licenses/strict/1.0.0/` |
| `README.md` (this PR) | Defers to `NOTICE.md` / `CITATION.cff` / `codemeta.json` |

Three of the four canonical surfaces have converged on PolyForm Strict 1.0.0. The fourth — the on-disk `LICENSE` file — still carries Apache 2.0 boilerplate, which contradicts the public project posture (single-operator, source-available archive, not seeking contributors, no redistribution).

## Why the README defers

The README cannot author a license decision; it can only describe one. Three of four authoritative surfaces have converged on PolyForm Strict, so the README points at those as the canonical statement and removes the legacy Apache badge that previously appeared in the project header. The on-disk `LICENSE` file remains unchanged in this PR — overwriting it without explicit operator authorization would be a significant change to public licensing terms.

## What unblocks the next step

Operator decision on which license is authoritative. Two coherent paths:

1. **Adopt PolyForm Strict 1.0.0 as authoritative** (matches the three already-converged surfaces and the no-redistribution posture documented throughout `NOTICE.md` and the Hapax Manifesto). Concrete actions:
   - Replace `LICENSE` with the PolyForm Strict 1.0.0 license text.
   - Verify the GitHub repository "license" detection picks up the new `LICENSE` (PolyForm Strict is recognized by the `licensee` Ruby gem GitHub uses for SPDX detection; no extra metadata required).
   - No README change required after that point — the README already defers to the canonical surfaces.

2. **Retain Apache 2.0** (would require updating `NOTICE.md`, `CITATION.cff`, and `codemeta.json` to match, and reconciling the public posture in `NOTICE.md` with the Apache redistribution permissions; the Hapax Manifesto's "not seeking contributors / refusal as data" stance is in tension with Apache 2.0's open-redistribution defaults). Concrete actions:
   - Update `NOTICE.md` to declare Apache 2.0 and rewrite the "no contributors / no redistribution" framing.
   - Update `CITATION.cff` `license:` field to `Apache-2.0`.
   - Update `codemeta.json` `license:` URL to `https://www.apache.org/licenses/LICENSE-2.0`.
   - Restore the Apache 2.0 badge in `README.md`.

Path 1 is the lower-friction option since three of four surfaces already point at PolyForm Strict. Path 2 would require the most extensive metadata rewrite.

## Out of scope for this PR

- Choosing between path 1 and path 2.
- Editing `LICENSE` directly. License changes are operator-action by policy.
- Adding renderer-side drift checks (the cc-task's seventh acceptance item lists this — a follow-on PR can ship the check once the canonical license decision is recorded here).

## Relation to the cc-task

`github-readme-profile-current-project-refresh` cc-task acceptance:

- ✅ README first screen makes the current Hapax operating environment legible without marketing or contributor language. (Project spine block + status disclosure replace the previous Clark-&-Brennan-only lead.)
- ✅ README explicitly says not a product, not a service, not seeking contributors, and points to refusal/governance surfaces.
- ⚠️ README no longer contradicts NOTICE/CITATION/CodeMeta/Zenodo — *partial*: the README defers to those three surfaces (which agree with each other), and this status doc records the remaining `LICENSE`-file divergence.
- ⏳ Profile README at the correct public GitHub user/profile location — deferred; depends on `github-public-surface-live-state-reconcile` cc-task to identify the correct surface (`ryanklee/ryanklee` vs another).
- ✅ Research status separated by evidence ceiling — the status disclosure table makes the ceilings explicit (release / empirical / governance / license).
- ✅ No public text implies current live system health, monetization readiness, public artifact release, or empirical validation without evidence refs.
- ⏳ Renderer / drift check — deferred to follow-on PR, gated on the license reconciliation decision above.
