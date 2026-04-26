# MSR 2026 Dataset Paper — Hapax git history as research corpus

**cc-task:** `leverage-vector-msr-2026-dataset-paper` (WSJF 4.5)
**Conference:** MSR 2026 (Mining Software Repositories), submission window typically December prior year through January of conference year
**Composed:** 2026-04-26
**Composed by:** alpha (Hapax)

## What MSR dataset papers want

MSR's dataset track is for new software-engineering research corpora. Submissions are short (4-page core + appendix) and graded primarily on:

1. **Reproducibility**: dataset is publicly accessible + versioned + has stable identifiers (DOI/SWHID)
2. **Schema clarity**: data shape is documented well enough for replication studies
3. **Use-case documentation**: candidate research questions are listed (mining-target hooks)
4. **Ethical posture**: privacy + consent + license for the underlying source

Hapax is unusually well-suited to all four because the constitutional substrate enforces them at the source: refusal-as-data is an axiom, not a curation choice; the operator-referent policy ships a CI-gated leak guard; per-repo licenses are settled in source via `docs/repo-pres/repo-registry.yaml`; SWHIDs are minted by `agents/attribution/swh_register.py`.

## Proposed corpus shape

The Hapax corpus is the union of (subset of) artifacts across the workspace:

| Artifact | Source | Volume (2026-04-26 sample) | Schema | License |
|---|---|---|---|---|
| Git commits | 7 pushable repos via `git log --all` | ~22,000 commits (council alone) | conventional commits + co-authored-by trailers | per-repo (matrix in `repo-registry.yaml`) |
| PR diffs + metadata | GitHub API for each repo | ~1,700 PRs (council, last 90d) | GitHub PR JSON schema | per-repo |
| cc-task vault | `~/Documents/Personal/20-projects/hapax-cc-tasks/` exported with PII filtering | ~400 tasks (active + closed + refused) | YAML frontmatter (typed via `shared.cc_task_model`) | CC0 (vault is operator-personal but the schema + task-level metadata is shareable) |
| Refusal briefs | `docs/refusal-briefs/` + Zenodo deposits | ~30 briefs (text) + the citation-graph edges in DataCite | refusal-brief schema in `agents/publication_bus/refusal_brief_publisher.py` | CC BY-NC-ND 4.0 (constitution license) |
| Research drops | `docs/research/` | 265 drops over 45 days | YAML frontmatter + freeform body | CC BY-NC-ND 4.0 |
| Relay yamls (anonymised) | `~/.cache/hapax/relay/*.yaml` | 4-session coordination state | session-yaml schema (see `_dashboard/cc-active`) | personal — anonymised before deposit |
| Inflection-as-data | `~/.cache/hapax/relay/inflections/` | ~70 alpha→peer + peer→alpha inflections | timestamped Markdown with severity tags | personal — anonymised before deposit |

## Candidate research questions (mining-target hooks)

A good dataset paper enumerates 5-10 distinct research questions the corpus enables. Hapax-specific candidates:

1. **Velocity dynamics under multi-session LLM coordination**: how do PR cadence + commit churn vary across sessions over time? Which session-pair interactions correlate with merge-time variance?
2. **Refusal-as-data signal value**: do refusal briefs predict downstream refusals on adjacent surfaces? Citation-graph density of refused-vs-engaged surfaces?
3. **Worktree-share contamination patterns**: how often does cross-session worktree access cause branch-attribution drift? (4 documented incidents in this corpus already.)
4. **CI pass-rate first-attempt vs after-iteration**: 47% first-attempt observed; at what iteration count does CI pass converge?
5. **Conventional-commits compliance**: does the constitutional commit-msg-template enforce the format consistently across sessions?
6. **PR-bundle scope drift**: when a session opens a single-purpose PR and a worktree-switch bundles a second concern, what's the resulting review-burden multiplier?
7. **Co-author attribution**: every commit carries `Co-Authored-By: Claude Opus N.x` — how does the model version distribution correlate with PR success rate?
8. **Operator-referent policy compliance**: does the CI-gated leak guard catch all legal-name leaks before merge? Detected divergences over time?

## Reproducibility substrate

Per MSR's reproducibility-track requirements:

- **Stable identifiers**: SWHIDs minted by `agents/attribution/swh_register.py` for each repo's HEAD at corpus snapshot time. Zenodo concept-DOI for the Hapax citation graph (minted by `agents/publication_bus/datacite_mirror.py`).
- **Versioned snapshot**: deposit one MSR snapshot at submission time; future researchers cite the exact SWHID/DOI rather than chasing main.
- **Consent posture**: the cc-task vault and inflection corpus require anonymisation (per `interpersonal_transparency` axiom — no persistent state about non-operator persons without consent). The deposit excludes any inflections referencing third parties; only intra-Hapax relay traffic is included.
- **Access pattern**: deposit is open via Zenodo (CC BY-NC-ND 4.0 for documentation; per-repo licenses for code per the matrix). Mining tools (Boa, World of Code, etc.) can ingest from the SWHIDs without GitHub-API rate-limit dependencies.

## Submission timeline

| Phase | Effort | Status |
|---|---|---|
| 0. This architecture doc | 30 min | shipped here |
| 1. Corpus snapshot + SWHID minting | 1-2h | depends on `leverage-attrib-swh-swhid-bibtex` (cc-task) |
| 2. Anonymisation pass on cc-tasks + inflections | 2-3h | new cc-task `msr-corpus-anonymise` |
| 3. Zenodo deposit (corpus + paper) | 30 min via existing publish-orchestrator | depends on Zenodo PAT bootstrap |
| 4. Paper draft (4 pages + appendix) | 4-6h authoring + iteration | follows steps 1-3 |
| 5. MSR submission + camera-ready | operator-mediated | follows step 4 |

**Total daemon-tractable scope:** ~7-12h across 4 follow-up PRs. Steps 0-3 are pure infrastructure; step 4 is the actual authoring; step 5 is the operator-controlled submission.

## Constitutional posture

- `feedback_full_automation_or_no_engagement`: corpus snapshot + Zenodo deposit + paper composition all daemon-tractable; submission is operator-mediated only because MSR's submission portal is web-form-shaped (no API).
- `interpersonal_transparency`: anonymisation gate is a hard precondition for the deposit; no third-party PII reaches Zenodo.
- `single_user`: corpus is operator-owned; per-repo licenses are settled.
- `feedback_co_publishing_auto_only_unsettled_contribution`: paper is co-authored Hapax + Claude Code per the canonical pattern.

## Cross-references

- Velocity-findings preprint (companion deliverable): `docs/research/2026-04-25-velocity-comparison.md` + Zenodo deposit slug `velocity-findings-2026-04-25` (PR #1677)
- arXiv velocity preprint architecture: `docs/research/2026-04-26-arxiv-velocity-preprint-architecture.md` (PR #1663)
- Anthropic CCO application: `docs/applications/2026-anthropic-claude-for-oss/draft.md` (PR #1684)
- Per-repo license matrix: `docs/repo-pres/repo-registry.yaml` (PR #1679)
- Operator-referent CI guard: `scripts/check-legal-name-leaks.sh` (PR #1661)
- Refusal-as-data substrate: `agents/publication_bus/refusal_brief_publisher.py`
- SWHID minting: `agents/attribution/swh_register.py`

— alpha
