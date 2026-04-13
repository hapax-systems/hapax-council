---
title: Reverie bridge repair — implementation plan
date: 2026-04-12
status: PR-1 merged; audit follow-up PR in flight; PR-2/PR-3 unassigned
author: delta
spec: docs/superpowers/specs/2026-04-12-reverie-bridge-repair-design.md
---

# Reverie bridge repair — implementation plan

Execution plan for
[`2026-04-12-reverie-bridge-repair-design.md`](../specs/2026-04-12-reverie-bridge-repair-design.md).
Originally three PRs, now four after the audit follow-up.

## Execution state (2026-04-12T20:10)

| PR | Title | State |
|---|---|---|
| **PR-1** | Core bridge fix | ✅ Merged as `991cfbe03` |
| **PR-1b** | Audit follow-up (this PR) | 🟡 In flight — reverts Requires=, drops content.intensity, adds 6 tests, corrects design doc |
| **PR-2** | Reverie monitor extension (watchdog hapax-imagination-loop) | ⚪ Unassigned |
| **PR-3** | Observability CLI + Prometheus metric | ⚪ Unassigned (now composable with beta's `pool_metrics()` from #697) |

## PR-1 — Core bridge fix (MERGED as `991cfbe03`)

**Branch:** `fix/reverie-bridge-v2`
**Owner:** delta
**Scope:** core Finding A + Finding B unit hygiene + design/plan docs.
**Post-merge audit found three issues that required a follow-up PR — see
PR-1b below.**

### Files

| Path | Change |
|---|---|
| `agents/reverie/_uniforms.py` | Add `_iter_passes()` helper; rewrite `_load_plan_defaults()` to walk v1 and v2; add `content.intensity` passthrough |
| `tests/reverie/test_uniforms_plan_schema.py` | New file — 5 cases (v1, v2 single, v2 multi, empty, live-shape regression) |
| `systemd/units/hapax-imagination-loop.service` | Move `StartLimitIntervalSec` + `StartLimitBurst` + `OnFailure` to `[Unit]`; add `Requires=hapax-dmn.service` |
| `hapax-council/CLAUDE.md` § Tauri-Only Runtime | Update "hosts the actuation loop as a concurrent async task" → "runs as an independent systemd daemon …" |
| `docs/superpowers/specs/2026-04-12-reverie-bridge-repair-design.md` | This design |
| `docs/superpowers/plans/2026-04-12-reverie-bridge-repair-plan.md` | This plan |

### Steps

1. ✅ Research complete — root causes localized, claims verified against
   source.
2. ✅ Worktree created at `~/projects/hapax-council--reverie-bridge`,
   branch `fix/reverie-bridge-v2` off `origin/main`.
3. Write design + plan (this document + its sibling spec).
4. Patch `agents/reverie/_uniforms.py`:
   a. Add `_iter_passes(plan)` helper at module scope.
   b. Rewrite `_load_plan_defaults()` body to use `_iter_passes()`.
   c. Add `uniforms["content.intensity"] = salience × silence` below the
      existing `content.salience` line.
5. Write `tests/reverie/test_uniforms_plan_schema.py` covering:
   - `_iter_passes` v1 flat
   - `_iter_passes` v2 single-target
   - `_iter_passes` v2 multi-target key merge
   - `_load_plan_defaults` on a tmpfile v2 plan
   - `_load_plan_defaults` empty / malformed (no raise)
6. Patch `systemd/units/hapax-imagination-loop.service` per § 2.3.
7. Update `hapax-council/CLAUDE.md` § Visual surface one-liner per § 2.5.
8. `uv run pytest tests/reverie/ -q`
9. `uv run ruff check agents/reverie/_uniforms.py tests/reverie/test_uniforms_plan_schema.py`
10. `uv run ruff format agents/reverie/_uniforms.py tests/reverie/test_uniforms_plan_schema.py`
11. `uv run pyright agents/reverie/_uniforms.py` (if clean-baseline)
12. Conventional commit:
    `fix(reverie): repair visual-chain → GPU bridge after plan schema v2 drift`
13. Push `fix/reverie-bridge-v2` → `origin`.
14. `gh pr create` with body linking design + plan.
15. Monitor CI (axiom gate, triage, adversarial review) through to green.
16. On merge, update local memory files
    (`project_reverie.md`, `project_reverie_autonomy.md`) to reflect fixed
    state + architectural ratification.

### Post-merge verification (run on host, not in CI)

Commands listed in design § 5. Operator can copy-paste.

### Rollback

`git revert <merge SHA>` is safe. The change is purely additive on the read
path. No data migration, no state change.

## PR-1b — Audit follow-up (this PR)

**Branch:** `fix/reverie-audit-followup`
**Owner:** delta
**Scope:** Corrections surfaced by the 2026-04-12 post-merge self-audit.
See design § 7 for the full finding list.

### Files

| Path | Change |
|---|---|
| `agents/reverie/_uniforms.py` | Revert `content.intensity` passthrough; add code comment explaining the dead `content.*` routing (F8) |
| `systemd/units/hapax-imagination-loop.service` | Revert `Requires=hapax-dmn.service` (cascade-death regression); keep the `[Unit]`-section fixes |
| `tests/test_reverie_uniforms_plan_schema.py` | +6 new tests: None-target edges, last-wins collision, file-deletion cache, direct write_uniforms, silence attenuation, silence floor |
| `docs/superpowers/specs/2026-04-12-reverie-bridge-repair-design.md` | Inline ⚠ audit corrections + new § 7 audit-findings section; add follow-ups F6–F10 |
| `docs/superpowers/plans/2026-04-12-reverie-bridge-repair-plan.md` | This file — execution-state update, DoD corrections, PR-1b block |

### What does NOT change in this PR

- `_iter_passes` helper — remains unchanged, it is correct.
- `_load_plan_defaults` body — unchanged, correct.
- The core v1/v2 schema fix from PR-1 — unchanged, verified in production.
- Memory files — updated locally by the author, not in the repo diff.

### Steps

1. ✅ Read current _uniforms.py / unit file / test file / design / plan.
2. ✅ Revert Requires= from unit file.
3. ✅ Revert content.intensity passthrough; add explanatory comment.
4. ✅ Add 6 new test cases.
5. ✅ Update design doc inline + add § 7.
6. ✅ Update plan doc (this edit).
7. `uv run pytest tests/test_reverie_uniforms_plan_schema.py -q` → expect 17 passing.
8. `uv run ruff check` + `ruff format` on changed files.
9. `uv run pyright agents/reverie/_uniforms.py`.
10. Conventional commit:
    `fix(reverie): audit follow-up — revert Requires=, drop content.intensity, docs + tests`
11. Push + `gh pr create`.
12. Monitor CI, merge, verify.
13. Update memory files locally.
14. Close delta session.

### Rollback

`git revert <merge SHA>` is safe. Changes are purely removals (Requires=,
content.intensity) plus doc edits plus new tests. No data migration.

## PR-2 — Reverie monitor extension (can ship after PR-1)

**Branch:** `feat/reverie-monitor-imagination-loop`
**Owner:** delta (or beta if picked up from queue)
**Depends on:** nothing; orthogonal to PR-1 but only becomes valuable
once PR-1 is merged so that a restart actually produces correct output.

### Files

| Path | Change |
|---|---|
| `agents/reverie_monitor.py` (or wherever the monitor lives) | Extend unit list from `[hapax-reverie]` → `[hapax-reverie, hapax-imagination-loop]`; restart if inactive; chronicle event |
| `tests/reverie/test_reverie_monitor.py` | Cover both units; mock `subprocess.run`; assert restart attempt fires |

### Steps

1. Locate the current monitor script — likely `agents/reverie_monitor.py`
   or a shell script under `scripts/monitoring/`. First grep target.
2. Parameterise the unit list.
3. Add structured chronicle emission on restart (non-fatal if chronicle is
   unreachable).
4. Test with a killed loop; monitor should restart within the timer
   cadence.
5. Ship as a tiny, one-file PR.

## PR-3 — Observability follow-ups (nice to have)

**Branch:** `feat/reverie-uniform-observability`
**Owner:** unassigned; picked up at next R&D slot
**Depends on:** PR-1 merged

### Files

| Path | Change |
|---|---|
| `agents/reverie/debug_uniforms.py` | New CLI — `python -m agents.reverie.debug_uniforms` prints current keys, expected keys, diff |
| `logos/api/routes/predictions.py` | Add `reverie_uniforms_key_count` Prometheus metric |
| `grafana/dashboards/reverie-predictions.json` | Add panel "Uniforms keys written" with alert `< 20` |

### Steps

1. Write the debug CLI using the same `_iter_passes` + `_load_plan_defaults`
   already fixed in PR-1. Import, don't duplicate.
2. Add the metric endpoint; scrape config already covers
   `localhost:8051/metrics`.
3. Import the dashboard panel; set alert threshold to `< plan_default_count - 5`
   rather than a hardcoded value, so it doesn't need updating with new
   dimensions.

## Coordination

- **Alpha (Stream A, compositor)** — no overlap. Alpha's `hapax-logos/crates/`
  work does not touch `agents/reverie/` or the imagination-loop unit.
  Status file note so alpha does not also try to fix a visual symptom.
- **Beta (Stream B, reverie + voice)** — overlap risk. Beta is currently
  executing `B4 — wire TransientTexturePool into DynamicPipeline`. B4 is
  Rust-side; it does not touch `agents/reverie/_uniforms.py`. No merge
  conflict expected. Beta should *pick up PR-2 and PR-3* from its queue once
  PR-1 ships.
- **Convergence** — PR-1 fixes a symptom beta was probably going to blame on
  their own wiring during B4 ("dimensions not responding"). Log as
  COMPLEMENTARY.

## Open questions

- Does the Python wgsl compiler always emit v2, or is there a codepath
  that still writes v1? Impact: if v1 is still possible, the fallback in
  `_iter_passes` is real coverage rather than belt-and-braces. Low priority
  to answer — the fix is robust either way.
- Is the `hapax-reverie-monitor` script already checking
  `hapax-imagination-loop`? If so, PR-2 collapses to a one-line change.
  If not, PR-2 is ~20 lines. Either way, small.

## Definition of done

PR-1 (merged as `991cfbe03`):

- [x] `_uniforms.py` patch lands
- [x] New test file passes (11 cases)
- [x] ruff + pyright green
- [x] Unit file patch lands
- [~] ~~CLAUDE.md updated~~ ⚠ audit: not needed. CLAUDE.md never carried the
      stale "DMN-hosted" claim — the original design doc misremembered
      this. The Tauri-Only Runtime § Visual surface paragraph already
      described reverie as a standalone systemd daemon. No edit needed.
- [x] PR merged as `991cfbe03`
- [x] Post-merge verification commands run on host and output captured
      (44 keys live, frame_time 9.54-16.21ms, warmth varying)
- [~] ~~Memory files updated (local; no commit needed)~~ ⚠ audit: not
      actually done as part of PR-1. Moved to PR-1b scope.
- [x] Relay status files (`alpha.yaml`, `beta.yaml`, `delta.yaml`) updated
      with completion note + convergence entry + context artifact

PR-1b (audit follow-up, this PR):

- [ ] `Requires=hapax-dmn.service` reverted
- [ ] `content.intensity` passthrough reverted + comment added
- [ ] 6 new test cases added and passing (17 total)
- [ ] Design doc § 1, § 2.2, § 2.3, § 2.5, § 3, § 6, + new § 7 updates
- [ ] Plan doc execution-state header + PR-1b block + DoD corrections
- [ ] ruff + pyright green
- [ ] PR merged
- [ ] Memory files updated locally: `project_reverie.md`,
      `project_reverie_autonomy.md`
- [ ] Relay `delta.yaml` updated with audit closure note
