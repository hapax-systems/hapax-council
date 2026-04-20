# D-31 Unplanned Specs Triage (Gap Audit NEW-10)

**Date:** 2026-04-20
**Scope:** Specs in `docs/superpowers/specs/` dated 2026-04-18, 2026-04-19, 2026-04-20 with no corresponding plan in `docs/superpowers/plans/`.
**Trigger:** Gap audit item NEW-10 — "Unplanned specs are invisible work; classify them or they accumulate as dark inventory."
**Outcome:** 19 specs classified; 15 closed (shipped or governed elsewhere); 4 surfaced as active vault cc-tasks.
**Register:** scientific (neutral, no advocacy).

---

## 1. Method

The audit ran a slug-overlap match between `docs/superpowers/specs/` and `docs/superpowers/plans/` filenames, stripping the date prefix and conventional suffixes (`-design.md`, `-spec.md`, `-plan.md`, `-epic.md`). For each spec without a plan-side match in the date window 2026-04-18 to 2026-04-20, the following evidence was gathered:

1. **Spec header** read for goal + scope statement.
2. **Implementation status** verified by `git log --all --oneline --grep="<concept>|#<task-id>"` against the dossier task IDs cited in spec headers.
3. **Successor-document check** for plans/research files that subsume the spec (e.g. unified-audio-architecture-plan).
4. **Classification** assigned per the rubric in the audit charter (shipped-without-plan / superseded / still-relevant-needs-plan / stale).
5. **Vault cc-task** filed under `~/Documents/Personal/20-projects/hapax-cc-tasks/{active|closed}/` with frontmatter linking back to the spec path.

The full classification rubric is unchanged from the gap audit charter; this run did not extend it.

The 2026-04-19 and 2026-04-20 ranges yielded zero unplanned specs in scope — every spec in those days has a paired plan (cc-task-obsidian-ssot, homage-ward-umbrella). All 19 unplanned specs cluster on 2026-04-18 — the spec-burst day flagged in the audit charter. Whole-corpus sweep (all dates) found 105 unplanned specs going back to 2026-03-10; that backlog is out of scope for this triage but warrants a follow-on sweep.

## 2. Per-Spec Classification

| # | Spec | CVS task | Class | Evidence (commit) | Vault note |
|---|---|---|---|---|---|
| 1 | audio-pathways-audit | #134 | still-relevant-needs-plan | partial: AEC `c7bc1d62b`; superseded-by-wrapper: `2026-04-20-unified-audio-architecture-plan.md` | active/spec-2026-04-18-audio-pathways-audit.md |
| 2 | audio-reactivity-contract | #149 | shipped-without-plan | `904761e05` (#1091) | closed/spec-2026-04-18-audio-reactivity-contract.md |
| 3 | camera-naming-classification | #135 | shipped-without-plan | `ca00f7004` (#1077) | closed/spec-2026-04-18-camera-naming-classification.md |
| 4 | chat-ambient-ward | #123 | shipped-without-plan | `11e563bae` cascade phase 5; later dropped from default layout `b60704c88` | closed/spec-2026-04-18-chat-ambient-ward.md |
| 5 | control-surface-bundle | #140/#141/#142/#143 | shipped-without-plan | `3ffa9b0ab` (#1079), `934e39f0b` (#1081), `9248984e5` (#1092), `3e19f1dab` (#1083) | closed/spec-2026-04-18-control-surface-bundle.md |
| 6 | follow-mode | #136 | shipped-without-plan | `efd50d0e3` (#1084) | closed/spec-2026-04-18-follow-mode.md |
| 7 | hardm-dot-matrix | #121 | shipped-without-plan | `c7bc1d62b` cascade phase 4; `196730f63`; `7f32b1e53`; `95044f91e` | closed/spec-2026-04-18-hardm-dot-matrix.md |
| 8 | heterogeneous-agent-audit | #151 | shipped-without-plan | `7291a0e27` (#1078) | closed/spec-2026-04-18-heterogeneous-agent-audit.md |
| 9 | local-music-repository | #130 | still-relevant-needs-plan | depends on splattribution shipped (#1070); not yet executed | active/spec-2026-04-18-local-music-repository.md |
| 10 | non-destructive-overlay | #157 | shipped-without-plan | `e1d1d8524` (#1076) | closed/spec-2026-04-18-non-destructive-overlay.md |
| 11 | operator-sidechat | #132 | shipped-without-plan | `de83ed89c` (#1080) | closed/spec-2026-04-18-operator-sidechat.md |
| 12 | reverie-substrate-preservation | #124 | shipped-without-plan | `bed6e2f23` (#1094); follow-up `65d0a8bd9` | closed/spec-2026-04-18-reverie-substrate-preservation.md |
| 13 | rode-wireless-integration | #133 | shipped-without-plan | `9248984e5` (#1092) | closed/spec-2026-04-18-rode-wireless-integration.md |
| 14 | role-derivation-research-template | #156 | shipped-without-plan | `f05e78da6` (#1086), `f7969bea2` (#1087) | closed/spec-2026-04-18-role-derivation-research-template.md |
| 15 | soundcloud-integration | #131 | still-relevant-needs-plan (BLOCKED) | credential issuance pending; no commit | active/spec-2026-04-18-soundcloud-integration.md |
| 16 | splattribution | #127 | shipped-without-plan | `ef539334f` (#1070); `ca0e955cc` | closed/spec-2026-04-18-splattribution.md |
| 17 | token-pole-homage-migration | #125 | shipped-without-plan | `d408fb1b3` (#1074); `864f2f6d0` | closed/spec-2026-04-18-token-pole-homage-migration.md |
| 18 | vinyl-image-homage-ward | #159 | shipped-without-plan | `0465049c9` (#1090) | closed/spec-2026-04-18-vinyl-image-homage-ward.md |
| 19 | youtube-broadcast-bundle | #144+#145 | still-relevant-needs-plan | partial infra exists (`scripts/youtube-player.py`, `youtube_description.py`, `youtube_description_syncer.py`, `15e1c15a9`); OAuth + reverse-ducker outstanding | active/spec-2026-04-18-youtube-broadcast-bundle.md |

**Counts:**
- shipped-without-plan: **15** (78.9%)
- still-relevant-needs-plan: **4** (21.1%)
- superseded: 0
- stale: 0

## 3. What this tells us about the 2026-04-18 burst

The 2026-04-18 spec-burst originated from a single source — `docs/superpowers/research/2026-04-18-homage-follow-on-dossier.md` — combined with parallel `cvs-research-{14X,15X,16X}.md` working files in `/tmp/`. Spec stubs were authored against that dossier as a single-day catalogue, then the cascade epic (PRs #1070–#1094, hash range `ef539334f..bed6e2f23`) shipped most of them within ~36 hours.

The pattern is healthy in one sense — a research dossier was cashed out as code in days rather than weeks — and unhealthy in another: 15 of 19 specs shipped without an intermediate plan doc, which violates the (loosely-enforced) workspace policy in the SDLC governance skeleton. The plan-skip is acceptable when the spec itself is small and schedule-disciplined (most of these are < 200-line stubs scoped to a single CVS dossier line), but it leaves no audit trail for change scope, no LOC budget, and no place to record acceptance-criterion drift.

A possible policy refinement: spec stubs in cascade epics should at minimum carry a back-reference to the cascade PR that ships them. Today only the cascade commit messages cite the spec — the spec files themselves have no "shipped in" footer. Adding that footer at PR-merge time (via the same hook that renders cc-tasks) would close the audit loop without forcing an intermediate plan doc for trivial work.

## 4. Cross-references to shipped commits

The cascade-epic hash range is documented in PR descriptions:
- `cf03933c2` — opened the cascade ("2026-04-18 cascade — HOMAGE follow-on research + CVS recovery + 35 spec stubs")
- `ef539334f..bed6e2f23` — phases 2–5 (#1055..#1094) — 14 of the 15 shipped specs land here
- `7f32b1e53`..`b60704c88` — post-cascade follow-on (HARDM rework, ward decommissions)

The four still-relevant specs share a common property: each requires either (a) external infrastructure (OAuth credential, music library curation), (b) a wrapper plan document (audio-pathways folds into unified-audio-architecture), or (c) significant new wiring that the cascade explicitly deferred (YouTube reverse-ducker requires a PipeWire graph touch that #1091 did not cover).

## 5. Recommended priorities for still-relevant items

1. **YouTube broadcast bundle (#144+#145)** — HIGH. Description-update infrastructure already exists; the OAuth consent step is small and unblocks public attribution which the operator has flagged as load-bearing for DMCA posture and brand integrity. Reverse-ducking is the smallest of the four pieces. **Recommend executing in the next plan slot.**

2. **Audio pathways audit (#134)** — HIGH. Already has a wrapper plan in `2026-04-20-unified-audio-architecture-plan.md`. Recommend folding this spec's deliverables into that plan rather than authoring a parallel one. The risk of letting it linger is that the YouTube-crossfeed → phantom-VAD cycle resurfaces as a regression.

3. **Local music repository (#130)** — MEDIUM. Splattribution shipped, so the gate signal exists, but the consumer side has no fallback for `vinyl_playing == False` other than silence. The operator's stated UX is "music never stops"; today the system fails that. Plan size is small (~500 LOC).

4. **SoundCloud integration (#131)** — LOW (BLOCKED). Park behind credential issuance. Operator should kick off API registration in parallel; until credentials land, no plan should be authored. The local-music repo (#130) is the meaningful fallback in the meantime.

## 6. Vault cc-task fingerprint

All 19 notes share frontmatter shape:
- `type: cc-task`
- `task_id: spec-2026-04-18-{first-token}` (uniqueness via spec date + slug head)
- `parent_spec: docs/superpowers/specs/<filename>`
- `tags: [spec-triage, d-31, ...]` (plus topical tag where present)
- `status: done|superseded|withdrawn` (closed/) or `offered` (active/)

`type: cc-task` matches the convention used by `agents.relay_to_cc_tasks.render_task_note` (verified against `~/Documents/Personal/20-projects/hapax-cc-tasks/active/1d79-085-beta-substrate-execution-chain-209-212.md`). The vault-side dashboard (`_dashboard/`) will pick these up on next refresh without any consumer-side change.

## 7. Out-of-scope follow-ons

This triage covered only the 2026-04-18..04-20 window. The whole-corpus sweep flagged **105 unplanned specs** going back to 2026-03-10. Many are likely in the same shipped-without-plan bucket (e.g. fortress-* specs that landed in the DF cascade, perception-primitives that became the perceptual-control-loops plans). A second pass over that backlog is recommended; estimated ~3 hours given the same evidence-gathering pattern. Deferring to a separate D-NN item.

A second follow-on: the audit charter rubric says nothing about specs that ship as a research doc rather than as code (e.g. `2026-04-18-role-derivation-research-template-design.md` — its deliverable IS the methodology doc, not runtime code). Today the rubric forces these into shipped-without-plan, which is correct in outcome but a category mismatch in spirit. A `governance-only` class would be cleaner.

## 8. Total counts by classification

| Class | Count | % |
|---|---|---|
| shipped-without-plan | 15 | 78.9% |
| still-relevant-needs-plan | 4 | 21.1% |
| superseded | 0 | 0% |
| stale | 0 | 0% |
| **total** | **19** | 100% |

Vault notes filed: **19** (15 in `closed/`, 4 in `active/`).
