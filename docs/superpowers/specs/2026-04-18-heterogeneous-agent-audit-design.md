# Heterogeneous Agent Audit — Dormant Policy Design

**Task:** CVS #151
**Date:** 2026-04-18
**Status:** Spec stub (dormant activation)
**Research source:** CVS research #151 (cross-agent audit preparedness)

---

## 1. Goal

Codify the five-surface audit checklist for heterogeneous-agent output (any non-Claude author — Gemini today, other CLIs tomorrow) **without consuming operational attention while no such agent is active**. The audit affordances already exist in-tree (pr-review-toolkit, superpowers, axiom-check, beagle-*, gemini-tool-adapter). What is missing is the **policy wrapper** that names them mandatory when the author is not Claude, and a **single detection surface** that activates the wrapper on demand.

## 2. Context

- Gemini takeover lasted ~1 day (started 2026-04-15, collapsed 2026-04-16T22:31Z per `docs/superpowers/handoff/2026-04-16-lrr-single-session-takeover-handoff.md`).
- Operator directive (2026-04-15): "I also want to make sure that claude is totally prepared to audit EVERYTHING gemini does."
- Steady state is Claude-only. A permanent global-CLAUDE.md addition would add noise with no payload.
- Hooks are already agent-agnostic via `hooks/scripts/gemini-tool-adapter.sh` — runtime safety gates fire identically for both agents.
- The prototype audit (`docs/research/2026-04-15-gemini-claude-hook-drift-check.md`) is the template for surface #4 below.

## 3. Five-surface audit checklist

| # | Surface | Trigger | Check | Tooling |
|---|---|---|---|---|
| 1 | Commits / PRs | PR created with non-Claude author trailer | Intent matches diff; no silent behavior change | `/pr-review-toolkit:review-pr all`, `code-reviewer`, `silent-failure-hunter` |
| 2 | Plans (`docs/superpowers/plans/*`) | Plan file added/edited | Axiom compliance; all research findings addressed (no cherry-picks) | `superpowers:writing-plans` read-through, `axiom-check` |
| 3 | Research (`docs/research/*`, `docs/superpowers/research/*`) | Research file added | Citation of prior audits/precedents; scientific register (neutral, no pitch) | `feedback_cross_reference_audits`, `feedback_scientific_register` criteria |
| 4 | Hooks / settings (`hooks/scripts/*`, `.claude/settings*.json`, `.gemini/settings*.json`) | Hook or settings edited | No silent disable; parity between Claude and Gemini gate sets; basename diff (adapter path differs) | jq diff methodology from 2026-04-15 drift-check |
| 5 | Axioms (`axioms/contracts/*`, `axioms/implications/*`, `shared/axiom_*.py`) | Axiom file edited | No breaking change without amendment precedent; T0 gates intact | `axiom-check`, `axiom-review`, `axiom-sweep` |

## 4. Policy document

**Path:** `docs/policies/heterogeneous-agent-audit-policy.md` (new, under 150 lines).

**Contents:**
- §0 Scope (any non-Claude author).
- §1 Inventory of existing audit affordances (pr-review-toolkit, superpowers code-review, axiom-*, beagle-*, hook parity).
- §2 Five-surface checklist (verbatim from §3 above, expanded with invocation commands).
- §3 Review workflow (Gemini creates branch in spontaneous slot → PR labeled `gemini-authored` → Claude runs `/pr-review-toolkit:review-pr all` → approve or request-changes).
- §4 Relay protocol deltas (`relay/gemini.yaml`, `last_author_type` field).
- §5 Activation procedure (operator announces heterogeneous engagement → flip advisory hook to blocking → reference policy from council CLAUDE.md active-epics).

The policy is **not referenced from CLAUDE.md while dormant**. Activation adds the reference.

## 5. Advisory detection hook

**Path:** `hooks/scripts/heterogeneous-agent-detect.sh` (new).

**Matcher:** `PreToolUse` Bash with command matching `gh pr create`.

**Logic:**
1. Read current branch HEAD SHA.
2. Inspect commits on the branch (since merge-base with `origin/main`) for:
   - `via Gemini CLI` commit trailers, or
   - langfuse trace spans referencing `gemini-tool-adapter.sh` (if instrumentation is reachable), or
   - author/committer email patterns registered as non-Claude.
3. If detected, emit advisory to stderr — **not blocking**:
   > [heterogeneous-agent-detect] Non-Claude author detected on branch. Operator directive (2026-04-15) requires Claude-authored review via `/pr-review-toolkit:review-pr all` before merge. See `docs/policies/heterogeneous-agent-audit-policy.md`.
4. Exit 0 regardless.

**Why advisory, not blocking:** Steady state is Claude-only. A false positive (e.g., commit imported from another workspace) blocking a PR wastes a session. Advisory stderr keeps the reviewer honest without creating a new failure mode.

Registration: add to `.claude/settings.json` PreToolUse matcher list and `.gemini/settings.json` equivalent (so Gemini itself sees the advisory when opening its own PR).

## 6. Activation flow

When operator announces "starting a new gemini session" (or equivalent heterogeneous engagement):

1. Create `relay/gemini.yaml` status file (or confirm it exists).
2. Flip `heterogeneous-agent-detect.sh` from advisory (exit 0) to blocking (exit 2) via a single line-edit — behavior flagged by `ADVISORY_ONLY=1` env var in settings.
3. Add this line to council CLAUDE.md § Active epics:
   > **Heterogeneous-agent audit active.** Policy: `docs/policies/heterogeneous-agent-audit-policy.md`. Every non-Claude PR requires `/pr-review-toolkit:review-pr all` before merge.
4. When the engagement ends (handoff collapse, operator dismissal): revert all three changes in one commit, back to dormant.

## 7. Rejected alternatives

- **Global CLAUDE.md meta-directive.** Permanent noise for all sessions across all projects. Current steady state is Claude-only, so the directive would fire zero times per week. Violates CLAUDE.md governance rubric (`docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md`).
- **CODEOWNERS rule blocking non-Claude authors on main.** Requires repo-admin setup; heavyweight for a dormant concern; false-positive blast radius includes all human commits that pass through the shared git identity.
- **Scheduled cross-agent drift audit timer.** The one-shot drift audit at `docs/research/2026-04-15-gemini-claude-hook-drift-check.md` is sufficient until next heterogeneous engagement.
- **Full scripted enforcement now.** Violates dormancy principle — consumes attention with no current payload.

## 8. File-level plan

| File | Action | Est. LOC |
|---|---|---|
| `docs/policies/heterogeneous-agent-audit-policy.md` | Create | ~150 |
| `hooks/scripts/heterogeneous-agent-detect.sh` | Create | ~40 |
| `.claude/settings.json` | Add PreToolUse entry for the hook (advisory mode) | +5 |
| `.gemini/settings.json` | Add PreToolUse entry (adapter path, advisory mode) | +5 |
| `docs/superpowers/handoff/` | Reference policy in next heterogeneous-handoff doc (activation-time only) | 0 now |

Total new code under 200 LOC; no existing file edits beyond settings entries.

## 9. Open questions

1. **Detection heuristics for non-Claude commits.** Commit trailers are the most reliable signal but depend on the agent emitting them. Langfuse trace inspection requires the hook to reach the Langfuse API; acceptable latency budget for a PreToolUse hook? Fallback to "branch-level touched-by-gemini-adapter-script" grep on hook logs?
2. **Advisory→blocking toggle mechanism.** Env-var flag in settings vs in-script constant vs separate hook file. Env-var flag is the smallest diff but requires settings reload on toggle — acceptable?
3. **Review-required label automation.** Should PR-create auto-apply a `needs-heterogeneous-review` label, or is advisory stderr sufficient? (Label requires `gh` auth in hook context.)
4. **Scope of "non-Claude".** Today: Gemini. Does the policy extend to Aider, Cursor agents, human-authored commits coming through the shared identity? Recommend: policy names "non-Claude" generically, advisory hook triggers on detectable non-Claude signal only.
5. **Policy-doc-from-CLAUDE.md linkage at activation.** Add to "Active epics" section (per file-level plan) vs a dedicated "Heterogeneous collaboration" section that stays in CLAUDE.md even while dormant, just empty. Recommend the former — keeps CLAUDE.md free of empty sections.
