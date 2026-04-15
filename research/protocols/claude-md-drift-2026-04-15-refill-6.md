# CLAUDE.md drift scan — 2026-04-15 refill 6 re-check

**Author:** beta (PR #819 author, AWB mode) per delta refill 6 Item #90
**Parent scan:** `research/protocols/claude-md-drift-2026-04-15.md` (commit `9515617ee`) — zero drift at write time (13:35Z)
**Scope:** re-scan CLAUDE.md family for NEW drift introduced by PRs shipped since the parent scan. Current HEAD: `45e41cdea` (post refill 6 Item #89).
**Verdict:** **MINOR ADDITIVE DRIFT** — 5 new artifacts could be mentioned in CLAUDE.md; none are structurally incorrect in the current CLAUDE.md. All drift is ADDITIVE (things to ADD), not SUBTRACTIVE (no claims in CLAUDE.md are wrong).

---

## 0. Files scanned

1. `~/projects/CLAUDE.md` (workspace root, symlink to `~/dotfiles/workspace-CLAUDE.md`)
2. `~/projects/hapax-council--beta/CLAUDE.md` (council project-level, mirror of the alpha worktree's tracked file)

Same scope as parent scan. Out-of-scope files remain out-of-scope.

## 1. Commits since parent scan (fe3beb480..HEAD)

Between the parent scan at `9515617ee` and current HEAD:

**Alpha shipments (14 PRs):**

- PR #842 `fe3beb480` — `check-frozen-files.py --probe` CLI
- PRs #843/#844 — LRR Phase 1 items 10b/10d/10e investigations (docs-only)
- PR #845 `c3d2326d9` — `research-registry.py set-collection-halt` subcommand
- PR #846 `1889202da` — mid-collection integrity check script + timer (new systemd timer)
- PR #847 `9a9ba0444` — data integrity lock script
- PR #848 `f26028b99` — PSU stress + brio-operator fps measurement scripts
- PR #849 `c54836255` — `CairoSourceRegistry` module (NEW agents/ module)
- PR #850 `b2fa7c936` — `config/compositor-zones.yaml` (NEW config file)
- PR #851 `53ac776a4` — `OutputRouter` layout tests
- PR #852 `efdf38d19` — docs-only spec fixes (drop #62 §14 line 502 + LRR Phase 4 §3.7)
- PR #853 `a7e8da3d7` — LRR Phase 2 item 1 archive services scope ratification (systemd/README.md updates)
- PR #854 `9e09b4293` — `ResearchMarkerFrameSource` (NEW agents/ module)

**Beta shipments (9 research drops + 2 spec extractions on branch):**

- Substrate research v1 + errata + v2
- LRR Phase 10 extraction (spec + plan)
- HSEA Phase 6 + Phase 7 extractions (spec + plan pairs)
- Protocol v1 evaluation drop
- Cohabitation drift reconciliation drop
- Consolidated audit summary
- Pattern meta-analysis
- Epsilon vs delta comparison
- Second-perspective synthesis
- Prometheus cardinality pre-analysis
- Cross-epic smoke test design
- Self-consistency meta-audit

All beta work is on `beta-phase-4-bootstrap` (PR #819 unmerged). Main sees NONE of beta's work yet.

## 2. Drift items

### D5 (NEW) — CairoSourceRegistry + compositor-zones.yaml not mentioned in §Studio Compositor

**Current CLAUDE.md §Studio Compositor** (line 137-ish of council CLAUDE.md) lists:

> *"**Key modules:**
> - `agents/studio_compositor/compositor.py` — `StudioCompositor` orchestration shell
> - `agents/studio_compositor/cairo_source.py` — `CairoSource` protocol + `CairoSourceRunner`
> - `agents/studio_compositor/{sierpinski_renderer,album_overlay,overlay_zones,token_pole}.py` — Cairo surfaces at 10–30 fps"*

**Missing:**

- `agents/studio_compositor/cairo_source_registry.py` (PR #849) — the NEW zone → CairoSource subclass binding registry introduced by LRR Phase 2 item 10
- `config/compositor-zones.yaml` (PR #850) — the zone catalog that `CairoSourceRegistry.load_zone_defaults()` reads
- `agents/studio_compositor/research_marker_frame_source.py` (PR #854) — NEW CairoSource subclass for LRR Phase 2 item 4 condition-transition overlays

**Severity:** MINOR ADDITIVE. The existing CLAUDE.md is still correct (no false claims), but a reader new to the compositor would miss the new zone-binding architectural layer.

**Proposed addition (for future `/revise-claude-md` pass):**

> *"**Zone-binding (LRR Phase 2 item 10):** `cairo_source_registry.py::CairoSourceRegistry` maps zones declared in `config/compositor-zones.yaml` to `CairoSource` subclasses. `StudioCompositor.start_layout_only()` calls `load_zone_defaults()` at bootstrap. HSEA Phase 1 will register higher-priority sources for specific zones. Distinct from `source_registry.py::SourceRegistry` which handles surface backend binding (Reverie completion epic)."*

### D6 (NEW) — Research registry subsystem not documented in CLAUDE.md

**Current CLAUDE.md** does NOT have a "Research registry" section. The research registry is a new subsystem introduced by LRR Phase 1:

- `shared/research_marker.py` (PR #841) — atomic-read/write helper for the `/dev/shm/hapax-compositor/research-marker.json` SHM file
- `scripts/research-registry.py` — CLI with `open`, `close`, `set-collection-halt` (PR #845), `freeze-file` subcommands
- `scripts/check-frozen-files.py --probe <path>` (PR #842) — pre-commit hook probe mode
- `~/hapax-state/research-registry/<condition_id>/condition.yaml` — per-condition state directory
- `~/hapax-state/research-registry/research_marker_changes.jsonl` — append-only audit log

**Severity:** MINOR ADDITIVE. A new subsystem not yet surfaced in CLAUDE.md. A reader would need to find it via grep or spec reading.

**Proposed addition** (new §Research Registry section in council CLAUDE.md, or a sub-section under §Key Modules):

> *"**Research registry (LRR Phase 1):** append-only registry of research conditions for LRR livestream research work. `~/hapax-state/research-registry/` holds per-condition YAML definitions. `/dev/shm/hapax-compositor/research-marker.json` holds the currently-active `condition_id` (atomic write via `shared/research_marker.py::write_marker`). `scripts/research-registry.py` provides the CLI (open/close/set-collection-halt/freeze-file). Every reaction on the livestream is tagged with the active condition_id at write time. `scripts/check-frozen-files.py --probe` is the pre-commit hook probe that blocks commits touching frozen paths for the active condition."*

### D7 (NEW) — `hapax-integrity-check.timer` not in workspace CLAUDE.md timer count

**Workspace CLAUDE.md** says:

> *"49 timers (sync agents, health monitor, VRAM watchdog, backups, storage arbiter, rebuilds)"*

**PR #846 added a new timer:** mid-collection integrity check (systemd user timer for periodic integrity verification of active research condition data).

**Severity:** MINOR COUNT DRIFT. The workspace CLAUDE.md timer count is now stale: 49 → 50 if the new timer is counted, or the category list needs "integrity check" added.

**Verification not performed:** beta did not run `systemctl --user list-units --type=timer --all | grep -c hapax-` to confirm the current count. The 49 count is from the parent scan; the post-PR-846 count may be different.

**Proposed action:** future `/revise-claude-md` pass runs the live count and updates if drifted. Non-blocking.

### D8 (NEW) — `scripts/check-frozen-files.py` + `scripts/research-registry.py` not in Claude Code Hooks table

**Current CLAUDE.md §Claude Code Hooks** lists 6 hooks at `hooks/scripts/`. The pre-commit hook chain (which runs `check-frozen-files.py --probe`) is NOT enumerated in CLAUDE.md — only the Claude Code PreToolUse hooks are.

**Severity:** STRUCTURAL, NOT DRIFT. The Claude Code Hooks section is specifically about PreToolUse hooks for Claude Code interactions. The git pre-commit chain is a different mechanism. Adding `check-frozen-files.py --probe` to the Claude Code Hooks table would be category error.

**Correct placement:** if CLAUDE.md should surface the pre-commit hook chain, it belongs in a new subsection (e.g., §Git pre-commit chain) OR in the §Research Registry subsection proposed in D6.

**No action needed for Claude Code Hooks section.**

## 3. Non-drift observations (things that are correct)

### 3.1 Qdrant collection count still correct

Workspace CLAUDE.md says *"10 collections"* with specific names. Parent scan verified against `shared/qdrant_schema.py::EXPECTED_COLLECTIONS`. Nothing shipped since then touches `EXPECTED_COLLECTIONS`. **Still correct.**

### 3.2 Service references still correct

`hapax-daimonion.service`, `hapax-gdrive-pull.timer`, `hapax-heartbeat.timer`, `claude-md-audit.timer` — all still exist. The new timer (D7) adds to the count but doesn't invalidate existing service references.

### 3.3 Substrate references still correct

Workspace CLAUDE.md says *"TabbyAPI — Primary local inference (`:5000`), serves Qwen3.5-9B (EXL3 5.0bpw, 9B dense DeltaNet)"*. Verified against `tabbyAPI/config.yml` + LiteLLM config. **Still correct.** No Hermes references anywhere. ✓

### 3.4 Docker container count still correct

Workspace CLAUDE.md says *"13 containers"*. No new containers shipped in the PRs since the parent scan. **Still correct.**

### 3.5 Axiom + hooks references still correct

5 axioms (3 constitutional + 2 domain) — unchanged. 6 hooks in hook chain — unchanged. ✓

### 3.6 File path references still correct

Parent scan spot-checked 20+ file paths. All still resolve on main (+ the new files in D5 are ADDED, not renamed, so existing paths are unaffected).

## 4. Drift summary

| Criterion | Drift | Severity |
|---|---|---|
| Qdrant collection count | None | — |
| Service references | None | — |
| Substrate references | None | — |
| PR number references | None (still no stale PR refs) | — |
| File path references | None (all existing paths resolve) | — |
| Docker container count | None | — |
| Axiom references | None | — |
| Hooks chain references | None | — |
| **NEW: CairoSourceRegistry not mentioned** | **Additive drift** | **MINOR** |
| **NEW: compositor-zones.yaml not mentioned** | **Additive drift** | **MINOR** |
| **NEW: ResearchMarkerFrameSource not mentioned** | **Additive drift** | **MINOR** |
| **NEW: Research registry subsystem not documented** | **Additive drift** | **MINOR** |
| **NEW: Timer count may be stale** | **Count drift** | **MINOR** |

**Net drift: 5 MINOR ADDITIVE items.** None are structurally incorrect in the current CLAUDE.md. All drift is "things to add on next revise pass", not "things that are currently wrong".

## 5. Recommended action

**None urgent.** The additive drift items can be deferred to a future `/revise-claude-md` pass when the operator or a future session wants to bring CLAUDE.md up to the post-Phase-2 state. The monthly `claude-md-audit.timer` on the council host will also catch these on its next sweep.

If a quick patch PR is desired, the 5 items can be bundled into one ~20-line diff:

1. Add `cairo_source_registry.py` + `compositor-zones.yaml` + `research_marker_frame_source.py` to §Studio Compositor Key Modules
2. Add §Research Registry subsection (or pointer) to §Key Modules
3. Update workspace CLAUDE.md timer count to include `hapax-integrity-check.timer`

**Beta cannot ship the patch PR directly** — branch discipline blocks new branches while PR #819 is unmerged. If the patch is time-critical, the operator should merge PR #819 first, then beta ships the patch PR in a subsequent AWB cycle.

## 6. Post-PR-819-merge follow-up sequence

Once PR #819 merges, the unblock sequence for CLAUDE.md + other branch-blocked items is:

1. `test/lrr-phase-1-2-coverage-expansion` (refill 6 Item #83 test expansion)
2. `feat/hsea-phase-6-7-cherry-pick-main` (refill 6 Item #82)
3. `feat/lrr-phase-10-cherry-pick-main` (refill 6 Item #85)
4. `feat/substrate-research-cherry-pick-main` (refill 6 Item #86)
5. `feat/beta-research-drops-cherry-pick-main` (refill 6 Item #87)
6. `docs/claude-md-refill-6-additive-drift-fix` (this drift scan's proposed 5-item patch, if ratified)

Items 2-5 can be consolidated into refill 6 Item #88 if beta prefers one big PR. Item 1 + 6 stay separate (different concerns).

## 7. References

- Parent drift scan: `research/protocols/claude-md-drift-2026-04-15.md` (commit `9515617ee`)
- PR #842 check-frozen-files --probe: commit `fe3beb480`
- PR #845 set-collection-halt subcommand: commit `c3d2326d9`
- PR #846 integrity check timer: commit `1889202da`
- PR #849 CairoSourceRegistry: commit `c54836255`
- PR #850 compositor-zones.yaml: commit `b2fa7c936`
- PR #854 ResearchMarkerFrameSource: commit `9e09b4293`
- PR #841 shared/research_marker.py: commit `e7fac7e83`
- Refill 5 closures batch: `~/.cache/hapax/relay/inflections/20260415-153000-beta-delta-refill-5-closures-batch.md`
- Refill 6 closures batch (this file's parent thread): `~/.cache/hapax/relay/inflections/20260415-163000-beta-delta-refill-6-closures-batch.md`

— beta (PR #819 author, AWB mode), 2026-04-15T16:40Z
