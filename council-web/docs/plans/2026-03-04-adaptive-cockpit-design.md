# Adaptive Cockpit — UX Overhaul Design

**Date:** 2026-03-04
**Status:** Approved
**Approach:** B — Adaptive Cockpit
**Scope:** ~30 files, holistic polish pass

## Design Principles

- **Beauty through coherence:** every element follows the same rules
- **Adaptive density:** the UI responds to system state — calm when nominal, informative when action needed
- **Functionalism:** every pixel serves a purpose; decoration that doesn't inform gets cut
- **Executive function support:** lower initiation barriers, surface action items, reduce cognitive load

## 1. Adaptive Sidebar

The sidebar operates in two modes with automatic transitions.

### Calm Mode (default when all nominal)

- Width: ~48px
- Content: vertically stacked Lucide icons with colored status dots (green/yellow/red)
- Icons map 1:1 to the 12 panel categories, in priority-sorted order
- Hover: tooltip with one-line summary (e.g., "Health: 75/75 passing")
- Click: expands just that panel inline (sidebar stays at 48px, panel overlays or pushes)

### Alert Mode (automatic when action needed)

- Width: 288px (w-72, current size)
- Expanded content for panels that need attention
- Nominal panels compress to header + checkmark (single line)
- Transition: `transition-[width] duration-200 ease-in-out`, content fades with `animate-in fade-in duration-150`

### Trigger Logic

Alert mode activates when ANY of:
- Health status is degraded or failed
- Any nudges exist with priority >= medium
- VRAM usage >= 80%
- Drift count > 0
- Briefing age > 24h

Calm mode returns when all triggers clear.

## 2. Typography Scale

Four levels, no exceptions:

| Role | Class | Use |
|------|-------|-----|
| Label | `text-[10px]` uppercase tracking-wider | Status badges, timestamps, metadata tags |
| Caption | `text-xs` (12px) | Secondary content, descriptions, panel body text |
| Body | `text-sm` (14px) | Primary content — nudge titles, briefing headlines, chat messages, banner text |
| Heading | `text-sm` font-medium uppercase tracking-wide | Section headers |

**Kill `text-[11px]`** everywhere. Items at 11px migrate to label (10px) or caption (12px).

## 3. Spacing Rhythm

Base unit: 4px (Tailwind default).

| Context | Spacing | Value |
|---------|---------|-------|
| Within a panel (between items) | `space-y-1.5` | 6px |
| Between panels/sections | `gap-4` or dividers | 16px |
| Card internal padding | `p-3` | 12px |
| Major section padding | `p-4` | 16px |
| Page margins | `px-4` | 16px |

## 4. Component Changes

### CopilotBanner + SystemSummary Merge

Absorb SystemSummary metrics into CopilotBanner as a secondary line:
- Line 1: status message (existing)
- Line 2: `74/75 checks · 12 containers · 22.2GB VRAM free · Briefing 3h ago`

Delete `SystemSummary.tsx`. Remove from `DashboardPage.tsx`.

### Remove QuickInput

Delete `QuickInput.tsx`. The command palette (Ctrl+P) and Chat nav link serve this purpose. Removing it reduces vertical noise on the dashboard.

### OutputPane Empty State

When no agent is running and no output exists: zero height, no border, completely invisible. Currently shows a border-t even when empty.

### StatusBar (Chat)

- Promote `text-[10px]` to `text-xs`
- Remove "mode: chat" label (noise — only one mode visible)

### HealthHistoryChart

Fix `margin: { left: -20 }` hack. Use proper `YAxis width={25}` instead.

### ManualDrawer

Add `transition-transform duration-200` for slide-in animation. Match modal backdrop treatment (`bg-black/50 backdrop-blur-sm`).

## 5. Interaction Polish

### Focus Rings
All interactive elements: `focus-visible:ring-1 focus-visible:ring-zinc-500 focus-visible:outline-none`

### Button Press Feedback
Primary action buttons: `active:scale-[0.97]` (Run agent, Send message, Act on nudge)

### Modal Entrance
DetailModal: `animate-in fade-in zoom-in-95 duration-150` (matching CommandPalette)

### Card Hover Depth
Agent cards and nudge items: `hover:shadow-sm hover:shadow-black/20`

### Toast Exit Animation
Add `animate-out fade-out slide-out-to-right` on dismiss instead of instant removal.

### Copy Button Feedback
AssistantMessage copy button: show brief "Copied" text tooltip, not just icon swap.

### Output Pane Expand
`transition-[max-height] duration-200` instead of instant snap.

## 6. Chat Page Refinements

### Suggestion Chips (Empty State)
Replace "Start a conversation." with a compact grid of 3-4 suggestion chips:
- "System health"
- "Run briefing"
- "Search documents"
- "What changed today?"

Clicking pre-fills the input. Supports executive function axiom (lower initiation barriers).

### Message Spacing
- Between messages: `space-y-3` (12px, down from 16px) for tighter dialogue flow
- Tool groups: `space-y-2` (8px, secondary content)

### Streaming Cursor
Replace `h-4 w-1 animate-pulse bg-green-400` with `h-3 w-0.5 animate-pulse bg-green-400/70` — thinner, shorter, subtler.

### Tool Call Indicator
When calling a tool, replace "Thinking..." with the tool name: "Calling health_check..." or "Searching documents...". SSE already provides tool_call events with names.

### Conversation Turn Separators
When time gap between messages exceeds 5 minutes, insert a centered timestamp divider:
- Thin horizontal line (border-zinc-800)
- Centered time label: `text-[10px] text-zinc-600`

### Slash Command Dropdown
Add a subtle left border accent (`border-l-2 border-cyan-400/30`) to each dropdown item for scannability.

## Files Affected

| File | Changes |
|------|---------|
| `src/components/Sidebar.tsx` | Dual-mode refactor (calm strip / alert panels) |
| `src/components/sidebar/SidebarSection.tsx` | Compact mode (header + checkmark) |
| `src/components/sidebar/SidebarStrip.tsx` | **New** — icon strip component for calm mode |
| All 12 sidebar panel files | Add `isNominal()` logic, compact rendering |
| `src/components/dashboard/CopilotBanner.tsx` | Absorb SystemSummary metrics |
| `src/components/dashboard/SystemSummary.tsx` | **Delete** |
| `src/components/dashboard/QuickInput.tsx` | **Delete** |
| `src/pages/DashboardPage.tsx` | Remove SystemSummary + QuickInput |
| `src/components/MainPanel.tsx` | OutputPane empty state |
| `src/components/OutputPane.tsx` | Zero-height empty, expand transition |
| `src/components/chat/StatusBar.tsx` | text-xs, remove mode label |
| `src/components/sidebar/HealthHistoryChart.tsx` | Fix YAxis margin |
| `src/components/shared/DetailModal.tsx` | animate-in entrance |
| `src/components/shared/ManualDrawer.tsx` | Slide transition, backdrop |
| `src/components/shared/ToastProvider.tsx` | Exit animation |
| `src/components/chat/MessageList.tsx` | Spacing, time separators, tool indicator |
| `src/components/chat/StreamingMessage.tsx` | Cursor refinement, tool name |
| `src/components/chat/ChatInput.tsx` | Slash command border accent |
| `src/components/chat/AssistantMessage.tsx` | Copy tooltip |
| `src/components/dashboard/AgentGrid.tsx` | Hover shadow, focus ring |
| `src/components/dashboard/NudgeList.tsx` | Hover shadow, focus ring |
| `src/components/Header.tsx` | Typography scale (text-[11px] -> text-[10px]) |
| `src/components/sidebar/AccommodationPanel.tsx` | Typography scale |
| `src/index.css` | Any additional utility classes needed |

Estimated: ~30 files modified, 2 new, 2 deleted.
