# Logos UI Content Remediation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate every terrain region with its spec-required content by fixing data paths, command protocol, and staleness prevention.

**Architecture:** Tauri Rust commands read profile data from `~/.hapax/profiles/` but agents write to `$REPO/profiles/` (PROFILES_DIR in shared/config.py). Fix the path mismatch so all data flows through. Extend command registry for direct depth control. Wire freshness-check into automated alerting.

**Tech Stack:** Rust (Tauri commands), TypeScript (command registry), Bash (staleness prevention), Python (agent output paths)

---

## Phase 0: Data Path Fix

### Task 0.1: Create ~/.hapax/profiles symlink + bootstrap

The simplest fix: symlink `~/.hapax/profiles` to the project profiles directory where agents actually write.

**Files:**
- Create: `scripts/bootstrap-profiles.sh`

- [ ] **Step 1: Create bootstrap script** that creates `~/.hapax/profiles` → `$REPO/profiles/` symlink (handles existing dir/symlink gracefully). Also symlinks `~/.hapax/operator.json` → `$REPO/profiles/operator-profile.json` for goals.

- [ ] **Step 2: Run it and verify** Tauri data files are reachable via `ls ~/.hapax/profiles/briefing.md`

- [ ] **Step 3: Restart logos and verify** API returns data for briefing, nudges, goals via curl

- [ ] **Step 4: Commit** `scripts/bootstrap-profiles.sh`

### Task 0.2: Add Rust fallback paths for missing files

Add `read_json_fallback` helper and update `get_goals()` + `get_briefing()` to check project dir as fallback.

**Files:**
- Modify: `hapax-logos/src-tauri/src/commands/state.rs`
- Modify: `hapax-logos/src-tauri/src/commands/governance.rs`

- [ ] **Step 1: Add `read_json_fallback(primary, fallback)` helper** to state.rs
- [ ] **Step 2: Update get_goals** to check `~/.hapax/operator.json` then `$REPO/profiles/operator-profile.json`
- [ ] **Step 3: Update get_briefing** to check `~/.hapax/profiles/briefing.md` then `$REPO/profiles/briefing.md`
- [ ] **Step 4: cargo check** — verify build
- [ ] **Step 5: Commit**

---

## Phase 1: Command Protocol

### Task 1.1: Extend terrain.focus with optional depth parameter

`terrain.focus` currently only accepts `{region}` and cycles depth. Extend to accept `{region, depth}` for direct depth control from WS relay.

**Files:**
- Modify: `hapax-logos/src/lib/commands/terrain.ts`
- Modify: `hapax-logos/src/lib/commands/__tests__/terrain.test.ts`

- [ ] **Step 1: Add tests** for `terrain.focus({region: "ground", depth: "core"})` setting depth directly
- [ ] **Step 2: Run tests** — verify failure (depth param ignored)
- [ ] **Step 3: Implement** — add `depth` to args schema, add `isDepth()` guard, set depth directly when provided, else cycle as before
- [ ] **Step 4: Run tests** — verify pass
- [ ] **Step 5: tsc --noEmit** — verify compile
- [ ] **Step 6: Commit**

### Task 1.2: Document WS relay command format

Create `docs/command-relay-protocol.md` with correct message format (`{type: "execute", id, command, args}`), common commands table, subscribe/response format.

- [ ] **Step 1: Write doc**
- [ ] **Step 2: Commit**

---

## Phase 2: Depth Content Verification

### Task 2.1: Automated visual audit script

Script that navigates every view via WS relay, screenshots, validates content.

**Files:**
- Create: `scripts/visual-audit.sh`

- [ ] **Step 1: Write script** — send terrain.focus commands with depth for every region×depth combination, screenshot each, check API data availability (nudges, briefing, flow, cameras), check screenshot sizes (non-trivial = has content)
- [ ] **Step 2: chmod +x and commit**

---

## Phase 3: Staleness Prevention

### Task 3.1: Wire freshness-check into rebuild timer + auto-restart

**Files:**
- Modify: `scripts/rebuild-logos.sh`

- [ ] **Step 1: Add freshness-check** call after build, send ntfy alert on staleness
- [ ] **Step 2: Add auto-restart** — if binary is newer than running service, restart the service
- [ ] **Step 3: Commit**

### Task 3.2: Add bootstrap-profiles to service startup

**Files:**
- Modify: `systemd/units/hapax-logos.service`

- [ ] **Step 1: Add ExecStartPre** calling `bootstrap-profiles.sh` before Logos starts
- [ ] **Step 2: Deploy and daemon-reload**
- [ ] **Step 3: Commit**

---

## Summary

| Phase | Tasks | What it fixes |
|-------|-------|---------------|
| **0: Data paths** | 0.1, 0.2 | Nudges, briefing, goals, scout, drift panels populate |
| **1: Commands** | 1.1, 1.2 | Direct depth control via WS relay, correct overlay commands |
| **2: Verification** | 2.1 | Automated test that exercises every view |
| **3: Staleness** | 3.1, 3.2 | Auto-detect + alert + restart on staleness, bootstrap on startup |

**Total: 7 tasks across 4 phases. Each phase independently shippable.**
