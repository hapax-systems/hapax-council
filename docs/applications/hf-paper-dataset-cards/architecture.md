# HuggingFace Paper Page + Dataset Card — Architecture

**cc-task:** `leverage-mktg-hf-paper-dataset-cards` (WSJF 4.5)
**Composed:** 2026-04-26

## Premise

HuggingFace's paper page + dataset card surfaces are cite-able citations + discoverability hooks for AI/ML research. Hapax's velocity findings + refusal-as-data corpus are a natural fit: the velocity preprint becomes a paper page (linked to the arXiv submission once that ships) and the underlying corpus (refusal briefs + research-drop history + multi-session inflection logs) becomes a dataset card (linked to the Zenodo deposit DOI from PR #1677).

This architecture identifies the two HF surfaces, their content shapes, the cross-link structure, and the daemon-tractable composition path.

## Surface 1: paper page

`huggingface.co/papers/<arxiv-id>` is auto-created when an arXiv preprint with a HF-recognised category lands. The community can add: tagged datasets, related models, comments. Hapax-relevant adds:

- **Tagged dataset**: link to the Hapax velocity-meter dataset card (Surface 2)
- **Related models**: none directly (Hapax doesn't ship trained weights), but cite the LLM models the substrate uses (Claude Sonnet/Opus, Gemini Flash for vision)
- **Authorship attribution**: Hapax + Claude Code + Oudepode per `feedback_co_publishing_auto_only_unsettled_contribution` — HF's author field defaults to arXiv authors so this propagates from the preprint.

Daemon-side action: none directly. The page auto-creates from the arXiv submission. The action is **populating the page metadata** via HF API once the page exists. New helper: `agents/marketing/hf_paper_page_publisher.py`.

## Surface 2: dataset card

`huggingface.co/datasets/<org>/<dataset-name>` is fully under operator control. Hapax-relevant card:

- **Name**: `oudepode/hapax-velocity-meter` (or similar; depends on the operator's HF org/account)
- **Description**: condensed velocity findings + corpus inventory (reuses the substrate from PRs #1677, #1686)
- **Files hosted**: anonymised cc-task vault export + refusal-brief corpus + research-drop frontmatter index + relay-yaml schema documentation. NOT raw inflection logs (those need anonymisation per `interpersonal_transparency`).
- **License**: CC BY-NC-ND 4.0 (matches `hapax-constitution` per the council's per-repo matrix in PR #1679).
- **Citation**: BibTeX referencing the Zenodo concept-DOI + the arXiv preprint
- **Linked papers**: the HF paper page (Surface 1)
- **Linked Spaces**: none initially; future cards can link Hapax demo Spaces if/when shipped

Daemon-side action: full composition + upload via HF API. New helper: `agents/marketing/hf_dataset_card_publisher.py`.

## HF API auth

HuggingFace API requires a write token for both surfaces. Bootstrap path:

```
pass insert huggingface/access-token  # one-time operator action
```

Then `hapax-secrets` injects `HAPAX_HF_ACCESS_TOKEN` per the existing secrets pattern. Without the token, the publishers emit a `RefusalEvent` to the canonical refusal log and disable themselves (same pattern as `lightning_receiver.py`'s Alby token absence).

## Composition reuse

Both publishers are publisher-kit subclasses (per `agents/publication_bus/publisher_kit/`). `surfaces_targeted` extension to `PreprintArtifact`:

- `hf-paper-page` — the paper-page metadata layer
- `hf-dataset-card` — the dataset card itself

The `velocity-findings-2026-04-25` artifact composed in PR #1677 already has `surfaces_targeted=["zenodo-doi"]`; the follow-up PR adds `"hf-dataset-card"` to that list, and a separate HF-paper-page artifact is composed once the arXiv submission lands (depends on the arxiv path from PR #1663's architecture).

## 5-component shipping plan

| # | Component | Path | Effort | Dependency |
|---|---|---|---|---|
| 0 | This architecture doc | shipped here | 30 min | none |
| 1 | HF API auth bootstrap (one-time operator action) | `pass insert huggingface/access-token` | 1 min operator | none |
| 2 | `hf_dataset_card_publisher.py` | `agents/marketing/` | 2-3h | #1 |
| 3 | `hf_paper_page_publisher.py` | `agents/marketing/` | 1-2h | #1, arxiv submission #1663 |
| 4 | Anonymisation pass on the corpus before upload | `scripts/anonymise-hapax-corpus-for-hf.py` | 2-3h | none |
| 5 | Integration test against HF sandbox | `tests/integration/test_hf_publishers.py` | 1-2h | #2, #3 |

**Total daemon scope:** ~6-10h across 4 follow-up PRs (excluding operator-action bootstrap).

## Constitutional posture

- `feedback_full_automation_or_no_engagement`: composition + upload daemon-tractable; only the operator-action HF token bootstrap is one-time human.
- `interpersonal_transparency`: anonymisation pass (#4) is a hard precondition for upload; no third-party PII reaches HuggingFace.
- `single_user`: dataset card credits the operator (Oudepode) per `project_operator_referent_policy` for non-formal HF surface; legal name only in formal-attribution fields.
- Refusal-as-data: token-absence emits refusal event; HF API rejections become refusal briefs.

## Cross-references

- Velocity findings preprint (substrate evidence): PR #1677 + `docs/research/2026-04-25-velocity-comparison.md`
- arXiv velocity preprint architecture (paper-page parent): `docs/research/2026-04-26-arxiv-velocity-preprint-architecture.md` (PR #1663)
- MSR 2026 dataset paper architecture (corpus framing parent): `docs/applications/2026-msr-dataset-paper/architecture.md` (PR #1686)
- License matrix for dataset card license declaration: `docs/repo-pres/repo-registry.yaml` (PR #1679)
- Operator-referent policy: `project_operator_referent_policy`

— alpha
