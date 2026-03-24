# Hapax Bar — Cleanup & Gap Resolution

**Date:** 2026-03-24
**Status:** Design
**Scope:** Fix bugs, delete dead code, wire missing connections, resolve design gaps

---

## 1. Bugs to Fix

### 1.1 Temporal Panel Never Updated
`seam/temporal_panel.py` has an `update()` method that is never called. The panel shows stale session duration from process start. Fix: call `update()` when the seam opens (in `toggle()`), not on a timer — the seam is transient.

### 1.2 Session Panel Hardcoded "alpha"
`SessionPanel()` defaults to `my_session="alpha"`. Both monitors create identical panels. Fix: detect session from worktree path (`hapax-council` = alpha, `hapax-council--beta` = beta). Since hapax-bar runs from the alpha worktree always (it's a systemd service), hardcode "alpha" is actually correct for the running service. But add a comment explaining why.

### 1.3 Stimmung Double Perception Read
`stimmung.py._read_visual_layer()` reads `PERCEPTION_PATH` twice — once for consent, once for flow/activity. Fix: single read, cache parsed JSON, extract all fields.

### 1.4 Workspace Occupied Class Never Cleared
`workspaces.py._sync()` appends "occupied" but rebuilds the full class list each call (line 40: `classes = ["workspace"]`), so stale state is NOT actually a bug — the list is rebuilt from scratch. **Verified: not a bug.** The audit was wrong here.

### 1.5 Voice Orb Too Small
`stimmung_field.py` uses `radius = 6.0` regardless of bar height. In the 32px bedrock bar, it should be 10px. Fix: pass bar height to stimmung field, scale orb proportionally.

## 2. Dead Code to Delete

| File | Reason |
|------|--------|
| `hapax_bar/bar.py` | Superseded by horizon.py + bedrock.py |
| `hapax_bar/reactive.py` | Never imported |
| `hapax_bar/modules/clock.py` | Replaced by temporal_ribbon.py |
| `hapax_bar/modules/idle.py` | Not used in dual-bar |
| `hapax_bar/modules/network.py` | Not used in dual-bar |
| `hapax_bar/modules/health.py` | Replaced by seam metrics_panel |
| `hapax_bar/modules/gpu.py` | Replaced by seam metrics_panel |
| `hapax_bar/modules/docker.py` | Replaced by seam metrics_panel |
| `hapax_bar/modules/sysinfo.py` | Replaced by seam metrics_panel |
| `hapax_bar/modules/systemd.py` | Replaced by seam metrics_panel |
| `hapax_bar/modules/cost.py` | Replaced by cost_whisper.py |
| `hapax_bar/modules/privacy.py` | Not used in dual-bar |

12 files to delete. ~800 lines removed.

## 3. Missing CSS

Add rules for:
- `.temporal-ribbon` — transparent background, no border
- `.cost-whisper` — no border, vertical alignment

## 4. Seam Panel Data Flow Fix

The seam panels need to refresh when opened, not continuously. Change `SeamWindow.toggle()` to call a `refresh()` method that updates all child panels with current data. This means each panel needs access to its data source — either via a stored reference or a callback.

**Pattern:** Each seam panel has a `refresh()` method. `SeamWindow` calls `refresh()` on all children when revealing. `app.py` registers data-provider callbacks on each panel at creation time.

## 5. Scope

~200 lines changed/added, ~800 lines deleted. Net reduction of ~600 lines.
