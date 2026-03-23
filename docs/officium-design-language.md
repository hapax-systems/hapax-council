# Officium Design Language

Authority document for the visual surfaces of hapax-officium. This document governs color, typography, spatial organization, and mode-driven theming for the officium desktop application and its management decision support interface.

**Status:** Normative
**Parent:** [`docs/logos-design-language.md`](logos-design-language.md) — inherited principles, shared palette, shared mode system
**Scope:** officium-web React frontend, future Tauri desktop shell

---

## 1. Relationship to Logos Design Language

Officium inherits from the Logos design language and must not diverge on shared foundations. The following are **inherited without modification**:

- §1 Governing principles (functionalism, minimalism, 2px base unit, color=meaning, JetBrains Mono)
- §2 Mode system (R&D = Gruvbox Hard Dark, Research = Solarized Dark)
- §3.1 Palette tokens (identical hex values, identical CSS custom property names)
- §3.7 Severity ladder (green → yellow → orange → red → zinc)
- §6 Animation vocabulary (breathing, transitions, decay — where applicable)
- §8 Synchronization requirements (ThemeProvider, no hardcoded hex, two access patterns)

The following are **officium-specific** and defined in this document:

- Spatial model (briefing desk, not geological terrain)
- Signal categories (management domain, not system perception)
- Staleness system (relational health, not infrastructure stimmung)
- Safety boundary (what the UI must never render)
- Prose density rules (reading-mode typography)
- Tauri architecture (shared pattern, officium-specific commands)

---

## 2. Purpose and Philosophy

> Officium is a briefing desk, not a terrain.

The operator approaches it before conversations, reviews, and planning sessions. It shows what they need to know: who is overdue for attention, what loops are open, what patterns the system has observed. It never shows what to do about any of it. The system's authority ends at pattern recognition; the operator's authority begins at decision-making.

**Logos** is about ambient awareness — you stand on terrain and feel the system's self-state through stimmung, signals, and depth. **Officium** is about deliberate preparation — you sit at a desk and review structured context before high-stakes relational work.

| | Logos | Officium |
|---|---|---|
| Cognitive mode | Ambient awareness, peripheral monitoring | Focused preparation, deliberate review |
| Time horizon | Real-time (perception, voice, biometrics) | Reflective (hours/days — last 1:1, pending feedback) |
| Primary signal | System health (stimmung) | Relational health (staleness) |
| Interaction | Depth cycling into geological strata | Urgency-driven sidebar expansion |
| Density | High — small signals, many simultaneous | Lower — prose-heavy briefings, structured data |
| Core axiom | Executive function (automate routines) | Management safety (prepare, never prescribe) |

---

## 3. Mode System

Officium uses the **same** working mode system as the rest of the hapax environment. Mode is read from `~/.cache/hapax/working-mode` (values: `research` or `rnd`). Mode drives palette selection across all visual surfaces.

The legacy `cycle_mode` (dev/prod) system is removed. All references to `CycleMode`, `cycle-mode`, and `hapax-mode` in officium are to be replaced with `WorkingMode`, `working-mode`, and `hapax-working-mode`.

### 3.1 Implementation requirements

- Backend: Replace `shared/cycle_mode.py` with `shared/working_mode.py` (copy from council, read `~/.cache/hapax/working-mode`)
- API: Replace `GET/PUT /api/cycle-mode` with `GET/PUT /api/working-mode` (match council's endpoint signature)
- Frontend: Replace `useCycleMode()` / `useSetCycleMode()` hooks with `useWorkingMode()` / `useSetWorkingMode()`
- ThemeProvider: Create `officium-web/src/theme/ThemeProvider.tsx` and `palettes.ts` (identical to council's)
- App entry: Wrap root component with `<ThemeProvider>`
- CSS: `index.css` @theme block becomes build-time fallback; runtime values injected by ThemeProvider

---

## 4. Color Contract

### 4.1 Shared palette

All palette tokens from Logos §3.1 apply identically. The same 88 hex values across 11 color scales, the same CSS custom property names (`--color-green-400`, `--color-zinc-700`, etc.), the same `useTheme()` hook returning `palette` and `colors`.

### 4.2 Management signal categories

Officium defines its own signal categories for management domain surfaces. These replace Logos's 8 system categories.

| Category | Token | Meaning | Used for |
|----------|-------|---------|----------|
| `people` | `blue-400` | Person-related signals | Stale 1:1s, load changes, team member status |
| `goals` | `yellow-400` | Goal/OKR-related signals | At-risk KRs, stale goals, overdue reviews |
| `operational` | `red-400` | Incidents and actions | Open incidents, postmortem items |
| `review` | `fuchsia-400` | Review cycles | Calibration dates, assessment gaps |
| `practice` | `green-400` | Management self-awareness | Profiler dimensions, practice patterns |
| `context` | `zinc-400` | General context | Briefing, status reports |

### 4.3 Staleness ladder

Staleness is officium's primary visual signal — the management equivalent of Logos's stimmung. Every person, goal, and commitment has an age. The visual treatment escalates with staleness:

| Staleness | Threshold | Token | Visual treatment |
|-----------|-----------|-------|-----------------|
| Fresh | < 7 days | (none) | No emphasis, default text color |
| Aging | 7–14 days | `yellow-400` | Subtle accent on age indicator |
| Stale | 14–30 days | `orange-400` | Visible accent, age indicator prominent |
| Critical | > 30 days | `red-400` | Strong accent, sidebar auto-expands |

The staleness ladder applies to: 1:1 recency, coaching check-in dates, feedback follow-up dates, goal review dates, OKR update dates.

Implementation: age indicators (e.g., "5d ago", "23d ago") use the staleness token as their text color. The sidebar auto-expand threshold is "any person or goal at critical staleness."

---

## 5. Spatial Model

### 5.1 Briefing desk layout

Officium uses a split-pane layout, not a terrain grid:

```
┌─────────────────────────────────────────────────────┐
│ Header (nav, mode indicator, command palette hint)   │
├───────────────────────────────────┬─────────────────┤
│                                   │                 │
│  Center panel                     │  Urgency        │
│  (primary work area)              │  sidebar        │
│                                   │  (auto-expand)  │
│  - Incident banner (if open)      │                 │
│  - Nudge list (action items)      │  - Team panel   │
│  - Agent grid                     │  - Briefing     │
│  - Output pane (streaming)        │  - OKRs         │
│                                   │  - Reviews      │
│                                   │  - Goals        │
│                                   │                 │
├───────────────────────────────────┴─────────────────┤
│ Command Palette (Ctrl+P overlay)                     │
└─────────────────────────────────────────────────────┘
```

### 5.2 Urgency-driven sidebar

The sidebar is the defining interaction pattern. It **auto-expands when relational health degrades**:

| Trigger | Condition | Panel |
|---------|-----------|-------|
| Stale 1:1s | Any person > 14 days since last 1:1 | Team |
| High/critical nudges | Priority nudge present | Nudge (center) |
| At-risk OKRs | Any KR flagged at-risk | OKR |
| Overdue reviews | Review past calibration date | Reviews |
| Open incidents | Active incident without postmortem | Incidents (center) |
| Stale briefing | Briefing > 24h old | Briefing |

When collapsed, the sidebar shows an icon strip with status dots (green/yellow/red) per panel. Click to expand.

### 5.3 No terrain, no depth

Officium does not use:
- Terrain regions (horizon, field, ground, watershed, bedrock)
- Depth states (surface, stratum, core)
- Depth cycling keyboard shortcuts (H/F/G/W/B)
- Stimmung border visualization
- Signal pips with breathing animations
- Ambient canvas / GLSL shaders

These are Logos-specific. Officium's information architecture is flat: panels expand and collapse based on urgency, not depth.

---

## 6. Safety Boundary

The `management_safety` axiom (T0, weight 95) constrains what the UI may render. This is a design requirement, not just a backend rule.

### 6.1 What the UI must NEVER show

- Feedback language directed at individuals (even as templates)
- Coaching recommendations or hypotheses about what a person should work on
- Performance evaluation language or narrative
- Suggested conversation topics with prescriptive framing
- Auto-generated development suggestions for individuals
- Any text that could be copy-pasted into a conversation about a person

### 6.2 What the UI MUST show

- Signals: stale 1:1s, unresolved items, load signals, patterns
- Preparation material: meeting agendas, team snapshots, context summaries
- Data freshness: when was each person's cognitive-load last updated?
- Open loops: flagged action items, pending feedback records
- Descriptive patterns: "This team's cognitive load trended up 15% in 3 weeks"
- Operator-authored context: person's stated career goals, feedback style, growth vectors (from frontmatter)

### 6.3 Visual distinction

Preparation material and action items should be visually distinct:

- **Preparation** (read-mode): `blue-400` tinted headers, generous line spacing, markdown rendering, no action buttons. This is context for the operator's own judgment.
- **Action items** (act-mode): severity-colored borders (§3.7 ladder), act/dismiss buttons, command hints. These invite operator action.

The distinction must be clear at a glance: preparation is blue and calm; action items are colored by urgency.

---

## 7. Prose Density

Officium renders management briefings, meeting prep, and team snapshots — prose content, not telemetry. The design language must accommodate readable text.

| Property | Value | Rationale |
|----------|-------|-----------|
| Body text size | 13px (0.8125rem) | Readable at arm's length, denser than 16px default |
| Line height | 1.6 | Prose needs breathing room between lines |
| Max reading width | 72ch | Prevent long lines that tire the eye |
| Paragraph spacing | 0.75rem | Distinct paragraphs without wasting space |
| Heading size | 14px bold | Minimal hierarchy — briefings are flat, not deeply nested |
| Code/data blocks | 12px monospace, `zinc-900` background | Inline structured data (frontmatter, metrics) |

These apply to markdown-rendered content (briefings, prep docs, meeting notes). UI chrome (headers, badges, labels) uses the standard Logos density (10-12px).

---

## 8. Tauri Architecture

Officium must be a Tauri 2 desktop application, matching council's architecture for consistency and native integration.

### 8.1 What to include

| Component | Source | Purpose |
|-----------|--------|---------|
| Tauri 2 shell | New `src-tauri/` | Native window, IPC bridge |
| Command modules | Adapt from council | File I/O for management state, working mode |
| Directive watcher | Copy from council | Agent-driven UI control via `/dev/shm/hapax-officium/directives.jsonl` |
| Browser engine | Copy from council | Agent web access (headless Chromium) |
| Dual-mode API client | Copy pattern | `tauriOrHttp()` for seamless Tauri/browser fallback |

### 8.2 What to exclude

| Component | Reason |
|-----------|--------|
| Visual surface (`visual/`) | No GPU rendering needed — officium is prose, not ambient visuals |
| Studio commands | No camera/compositor integration |
| Perception commands | No perception pipeline |
| System flow commands | No DAG topology (officium has no equivalent) |

### 8.3 Officium-specific commands

| Command | Purpose |
|---------|---------|
| `get_working_mode` / `set_working_mode` | Mode switching (read `~/.cache/hapax/working-mode`) |
| `get_management_state` | People, coaching, feedback snapshot |
| `get_nudges` / `act_nudge` / `dismiss_nudge` | Nudge management |
| `get_briefing` | Morning briefing |
| `get_goals` / `get_okrs` | Goal tracking |
| `get_incidents` | Open incidents |
| `get_review_cycles` | Review cycle status |
| `get_agents` / `run_agent` | Agent execution |
| `get_profile` | Management self-awareness dimensions |

### 8.4 Configuration

```json
{
  "productName": "hapax-officium",
  "identifier": "com.hapax.officium",
  "build": {
    "devUrl": "http://localhost:5175",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [{
      "title": "Hapax Officium",
      "width": 1400,
      "height": 900
    }],
    "security": {
      "csp": "default-src 'self'; connect-src 'self' http://127.0.0.1:8050 ws://127.0.0.1:*; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-eval'"
    }
  }
}
```

Dev port `5175` to avoid collision with council's `:5173`.

### 8.5 SHM paths

| Path | Purpose |
|------|---------|
| `/dev/shm/hapax-officium/directives.jsonl` | Agent-driven UI directives |
| `/dev/shm/hapax-officium/state.json` | Aggregated management state (optional cache) |

---

## 9. Migration: cycle_mode → working_mode

The legacy `cycle_mode` (dev/prod) system must be fully replaced:

| File | Action |
|------|--------|
| `shared/cycle_mode.py` | Delete. Replace with `shared/working_mode.py` (copy from council) |
| `logos/api/routes/cycle_mode.py` | Delete. Replace with `logos/api/routes/working_mode.py` (copy from council) |
| `officium-web/src/api/client.ts` | Remove `cycleMode()` / `setCycleMode()`. Add `workingMode()` / `setWorkingMode()` |
| `officium-web/src/api/hooks.ts` | Remove `useCycleMode()` / `useSetCycleMode()`. Add `useWorkingMode()` / `useSetWorkingMode()` |
| `officium-web/src/api/types.ts` | Remove `CycleModeResponse`. Add `WorkingModeResponse` |
| `~/.cache/hapax/cycle-mode` | Obsolete. System reads `~/.cache/hapax/working-mode` only |

---

## 10. Document Hierarchy

| Document | Status | Governs |
|----------|--------|---------|
| `logos-design-language.md` | **Parent normative** | Shared palette, mode system, principles, severity ladder |
| **This document** (`officium-design-language.md`) | **Normative** | Officium spatial model, signal categories, staleness, safety, prose density, Tauri |
| `logos-ui-reference.md` | **Council-only** | Logos region content — does not apply to officium |

When documents conflict: this document wins on officium-specific concerns (spatial model, staleness, management categories). The parent Logos design language wins on shared foundations (palette, mode, typography, proportions).
