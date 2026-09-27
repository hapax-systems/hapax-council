# CLAUDE.md Excellence — Design

**Date:** 2026-04-13
**Author:** beta
**Status:** active
**Plan:** [`docs/superpowers/plans/2026-04-13-claude-md-excellence-plan.md`](../plans/2026-04-13-claude-md-excellence-plan.md)
**Audit:** [`docs/superpowers/audits/2026-04-13-claude-md-excellence-audit.md`](../audits/2026-04-13-claude-md-excellence-audit.md)

## 2026-09-20 instruction-source amendment

The rubric and rotation rules govern authored agent instructions regardless of
native filename. Council now authors repository policy in `AGENTS.md`, with a
relative `CLAUDE.md` compatibility alias. Automatic rotation also covers the
shared `config/agent-instructions/AGENTS.md`, native fragments under
`config/agent-instructions/native/`, and extracted domain policy in
`docs/runbooks/council-domain-context.md`. In-tree aliases are checked through
the authored target once. Explicitly selected external aliases remain supported.

For these Council bindings, the earlier non-goals of retaining filenames and
avoiding generated distribution are superseded by one authored policy and
measured native bindings. Generation distributes shared policy; it does not
create another authored policy or erase native differences. Historical audit
scores and per-repository targets below remain the April baseline, not current
measurements. Binding, discovery limits and runnable rechecks are maintained in
[the instruction binding runbook](../../runbooks/agent-instruction-binding.md).

## Problem

`CLAUDE.md` files are the primary channel through which Claude Code absorbs project context on session start. They are loaded into context unconditionally, so every line they contain competes with the user's actual prompt for attention. Across the hapax workspace, they drift in three predictable directions:

1. **Bloat through historical accretion.** Fix notes, PR references, and incident write-ups get appended and never deleted. `hapax-council/CLAUDE.md` reached 405 lines, with roughly 160 of those describing events that belong in commit messages.
2. **Rot through currency gaps.** Claims like "currently non-functional", "migration pending", and "PR #NNN" decay from context into noise as soon as the underlying state changes, but there is no incentive to prune them.
3. **Silent duplication.** The two VS Code extension `CLAUDE.md` files are byte-identical except for a port number; neither says so, so future edits drift.

Left unaddressed, every new session pays for this in context window and attention.

## Goals

1. Establish a rubric that defines what belongs in a `CLAUDE.md` file.
2. Establish a rotation policy that defines what does **not** belong — content that must be purged on a cadence or on specific triggers.
3. Bring every workspace `CLAUDE.md` to the rubric's A-tier (≥90/100) without losing information that is genuinely load-bearing.
4. Close the coverage gaps: every working directory that a Claude Code session might enter should have a `CLAUDE.md` (or an explicit pointer away from one).

## Non-goals

- Restructuring or renaming `CLAUDE.md` files.
- Introducing a templating or generation system — hand-written files are the norm and working as intended.
- Auditing skill, plugin, or hook definitions that live outside `CLAUDE.md`.

## Rubric

Each `CLAUDE.md` is scored against six criteria, 100 points total:

| Criterion | Weight | A-tier threshold |
|---|---|---|
| Commands / workflows | 20 | Copy-paste-ready `uv run …` / `pnpm …` / `./gradlew …` blocks covering build, test, lint, dev, deploy as applicable |
| Architecture clarity | 20 | Reader can name the top-level modules, data flow, and integration seams after one pass |
| Non-obvious patterns | 15 | Gotchas and invariants a new session would not infer from the code are surfaced — but nothing else is |
| Conciseness | 15 | No section exists only because it used to be useful; dense is better than verbose |
| Currency | 15 | Every factual claim is true **right now**; no "currently broken" or "PR #NNN" residue |
| Actionability | 15 | Instructions are executable, not aspirational; pointers resolve |

Grades: A ≥ 90, B ≥ 70, C ≥ 50, D ≥ 30, F < 30.

## What belongs in CLAUDE.md

- **Architecture shape.** Directory layout, tier model, inter-module boundaries. Concrete enough that a new session can orient.
- **Build and run commands.** The exact invocations, with environment prerequisites.
- **Invariants.** Constraints the code assumes but does not enforce. ("Tests must not mock the DB." "Ollama is GPU-isolated — never import it for inference.")
- **Non-obvious dependencies.** External services a reader cannot deduce from imports. Ports, systemd units, volumes.
- **Gotchas.** Recurring mistakes a new session would make. Keep short.
- **Pointers.** "See X for Y" — external spec, design doc, handoff. Pointers age better than prose.

## What does NOT belong in CLAUDE.md

These are the content classes most responsible for decay. They should be removed on sight unless there is a specific argument for keeping them.

- **Bug-fix retrospectives.** "Fixed 2026-04-12: the director loop was silently dropping on max_tokens=300." This is a commit message. Delete.
- **PR number fingerprints.** `(PR #685)`, `(beta PR #705)`. A PR number adds no information after merge. Delete.
- **Incident narratives.** "Observed as an 18h frozen plan.json on 2026-04-12." The incident is recorded in git, telemetry, and chronicle. CLAUDE.md is not the post-mortem venue.
- **"Currently broken" apologies.** Either fix the thing or accept the degradation — do not explain it in the file that every session loads. If it must be documented, point to a tracking issue.
- **Epic narratives after the epic is shipped.** A 30-line retelling of a closed epic is a handoff doc, not project context. Leave a one-line pointer to the handoff.
- **Sprint roadmaps.** Sprint state changes faster than `CLAUDE.md` is edited, so it rots fast.
- **Historical trivia.** "Previous OS was Pop!_OS 24.04." Noise.

## Rotation policy

Content ages. To prevent drift back to the 405-line state, these triggers require review and likely deletion:

1. **On PR merge that fixes a documented rot claim.** If `CLAUDE.md` says "X is broken," and a PR fixes X, the PR must also delete the rot claim. Reviewer responsibility.
2. **On session start, if a claim references a date older than 30 days.** Verify it's still true; delete if not.
3. **On reading a section twice without action.** Ask whether deleting it would cost anything. If not, delete.
4. **On quarterly audit.** Run `/revise-claude-md` (claude-md-management) against the workspace and apply its report.

## Target state

Every `CLAUDE.md` in the workspace at or above 90/100:

| File | Current | Target | Primary work |
|---|---|---|---|
| `CLAUDE.md` (workspace root) | 88 | 95 | Accurate sub-project claim; top-level navigation pointer; external-deps section for tabbyAPI |
| `hapax-council/CLAUDE.md` | 55 | 92 | 405 → ~200 line surgery; delete all fix retrospectives, PR fingerprints, epic narratives |
| `hapax-council/vscode/CLAUDE.md` | 82 | 92 | Add sister-extension sync warning |
| `hapax-constitution/CLAUDE.md` | 90 | 92 | Cosmetic polish |
| `hapax-officium/CLAUDE.md` | 87 | 93 | Remove `cycle_mode.py` rot aside; add vscode pointer |
| `hapax-officium/vscode/CLAUDE.md` | 82 | 92 | Add sister-extension sync warning |
| `hapax-mcp/CLAUDE.md` | 92 | 92 | No change — already at target |
| `hapax-watch/CLAUDE.md` | 91 | 93 | Remove sprint roadmap (rot target) |
| `distro-work/CLAUDE.md` | 89 | 92 | Drop Pop!_OS historical line |

New files to create:

| File | Decision | Rationale |
|---|---|---|
| `hapax-phone/CLAUDE.md` | Create, push to origin | ryanklee-owned repo; pairs with hapax-watch |
| `atlas-voice-training/CLAUDE.md` | Create locally, add to `.git/info/exclude` | Upstream-owned (briankelley/) — cannot push |
| `tabbyAPI/CLAUDE.md` | Create locally, add to `.git/info/exclude` | Upstream-owned (theroyallab/) — cannot push; workspace root carries an external-deps pointer |

## Risks

- **Information loss.** Deleting fix notes may lose institutional knowledge. Mitigation: the original content is preserved in git history and cross-referenced by handoff docs under `docs/superpowers/handoff/`.
- **Re-accretion.** Without the rotation policy, the file drifts back. Mitigation: hook or periodic audit (see Rotation policy §4).
- **Sub-project drift.** Two VS Code extension files will remain separate but nearly identical. Mitigation: both carry an explicit sync warning.

## Success criteria

- Every existing `CLAUDE.md` scores ≥ 90 on the rubric.
- Every sub-project referenced in the workspace root `CLAUDE.md` either has its own `CLAUDE.md` or is explicitly excluded in the external-deps section.
- `hapax-council/CLAUDE.md` contains no content matching `fixed 202[0-9]-[0-9]{2}-[0-9]{2}`, `(PR #[0-9]+)`, or `currently (non-functional|broken|disabled)` outside of a pointer context.
