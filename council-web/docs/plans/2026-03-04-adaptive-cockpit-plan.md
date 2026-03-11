# Adaptive Cockpit — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Design doc:** `docs/plans/2026-03-04-adaptive-cockpit-design.md`
**Branch:** `feat/web-migration`
**Working directory:** `~/projects/cockpit-web`
**Verify after each batch:** `pnpm build && pnpm dev` (visual check at localhost:5173)

---

## Batch 1 — Dashboard Cleanup (delete QuickInput, merge SystemSummary into CopilotBanner)

### Task 1.1: Absorb SystemSummary metrics into CopilotBanner

**File:** `src/components/dashboard/CopilotBanner.tsx`

Add the data hooks from SystemSummary and render a second metrics line:

```tsx
import { useCopilot, useHealth, useInfrastructure, useGpu, useBriefing } from "../../api/hooks";
import { AlertTriangle, Info, MessageCircle } from "lucide-react";

export function CopilotBanner() {
  const { data: copilot } = useCopilot();
  const { data: health } = useHealth();
  const { data: infra } = useInfrastructure();
  const { data: gpu } = useGpu();
  const { data: briefing } = useBriefing();

  let message = "System operational.";
  if (copilot?.message) {
    message = copilot.message;
  } else if (health) {
    if (health.overall_status === "healthy") {
      message = `All systems nominal — ${health.healthy} checks passing.`;
    } else if (health.overall_status === "degraded") {
      message = `${health.degraded} degraded checks detected. Review health panel for details.`;
    } else if (health.overall_status === "failed") {
      message = `${health.failed} checks failing. Immediate attention recommended.`;
    }
  }

  const severity = health?.overall_status === "failed"
    ? "critical"
    : health?.overall_status === "degraded"
      ? "warn"
      : "info";

  const styles = {
    critical: "border-red-500/50 bg-red-500/10 text-red-300",
    warn: "border-yellow-500/50 bg-yellow-500/10 text-yellow-300",
    info: "border-zinc-700/50 bg-zinc-800/50 text-zinc-400",
  };

  const Icon = severity === "critical" ? AlertTriangle : severity === "warn" ? Info : MessageCircle;

  // Metrics line
  const containers = infra?.containers.filter((c) => c.state === "running").length ?? 0;
  const freeGb = gpu ? (gpu.free_mb / 1024).toFixed(1) : null;
  let briefingAge: string | null = null;
  if (briefing?.generated_at) {
    const hours = Math.floor((Date.now() - new Date(briefing.generated_at).getTime()) / 3_600_000);
    briefingAge = `${hours}h`;
  }

  return (
    <div className={`rounded border px-3 py-2 transition-colors ${styles[severity]}`}>
      <div className="flex items-center gap-2 text-sm">
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span>{message}</span>
      </div>
      {health && (
        <div className="mt-1 flex items-center gap-3 pl-5.5 text-xs opacity-70">
          <span>{health.healthy}/{health.total_checks} checks</span>
          <span className="text-zinc-600">·</span>
          <span>{containers} containers</span>
          {freeGb && (
            <>
              <span className="text-zinc-600">·</span>
              <span>{freeGb}GB VRAM free</span>
            </>
          )}
          {briefingAge && (
            <>
              <span className="text-zinc-600">·</span>
              <span>Briefing {briefingAge} ago</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
```

### Task 1.2: Remove QuickInput and SystemSummary from DashboardPage

**File:** `src/pages/DashboardPage.tsx`

Remove SystemSummary and QuickInput imports and usage:

```tsx
import { Sidebar } from "../components/Sidebar";
import { MainPanel } from "../components/MainPanel";
import { CopilotBanner } from "../components/dashboard/CopilotBanner";

export function DashboardPage() {
  return (
    <>
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="border-b border-zinc-800 px-4 py-3">
          <CopilotBanner />
        </div>
        <MainPanel />
      </div>
      <Sidebar />
    </>
  );
}
```

### Task 1.3: Delete unused files

**Delete:** `src/components/dashboard/QuickInput.tsx`
**Delete:** `src/components/dashboard/SystemSummary.tsx`

### Task 1.4: Verify and commit

```bash
pnpm build
```

**Commit:** `feat(dashboard): merge SystemSummary into CopilotBanner, remove QuickInput`

---

## Batch 2 — Typography Scale (kill text-[11px], establish 4-level hierarchy)

### Task 2.1: Header keyboard hints

**File:** `src/components/Header.tsx`

Change `text-[11px]` to `text-[10px]` on keyboard hint wrapper (line 48):

```
Old: <div className="hidden items-center gap-2 text-[11px] text-zinc-600 sm:flex">
New: <div className="hidden items-center gap-2 text-[10px] text-zinc-600 sm:flex">
```

### Task 2.2: SidebarSection age badge

**File:** `src/components/sidebar/SidebarSection.tsx`

Change `text-[11px]` to `text-[10px]` on age badge (line 20):

```
Old: <span className="text-[11px] font-normal normal-case tracking-normal text-zinc-600">{age}</span>
New: <span className="text-[10px] font-normal normal-case tracking-normal text-zinc-600">{age}</span>
```

### Task 2.3: AccommodationPanel action buttons

**File:** `src/components/sidebar/AccommodationPanel.tsx`

Change both `text-[11px]` occurrences to `text-[10px]` (lines 33 and 40):

```
Old: className="text-[11px] text-green-400 hover:underline"
New: className="text-[10px] text-green-400 hover:underline"

Old: className="text-[11px] text-zinc-500 hover:underline"
New: className="text-[10px] text-zinc-500 hover:underline"
```

### Task 2.4: StatusBar text sizing

**File:** `src/components/chat/StatusBar.tsx`

Promote all `text-[10px]` to `text-xs`. Remove "mode: chat" label:

Line 45 — container class:
```
Old: className="flex items-center justify-between border-t border-zinc-800 bg-zinc-900/80 px-4 py-1 text-[10px] text-zinc-500"
New: className="flex items-center justify-between border-t border-zinc-800 bg-zinc-900/80 px-4 py-1 text-xs text-zinc-500"
```

Line 51 — model selector:
```
Old: className="rounded border border-zinc-700 bg-zinc-900 px-1 py-0.5 text-[10px] text-zinc-400 outline-none hover:border-zinc-600"
New: className="rounded border border-zinc-700 bg-zinc-900 px-1 py-0.5 text-xs text-zinc-400 outline-none hover:border-zinc-600"
```

Lines 60-69 — replace mode label with just interview indicator:
```tsx
{state.mode === "interview" && (
  <span className="text-fuchsia-400">
    interview
    {interviewInfo
      ? ` ${interviewInfo.topics_explored}/${interviewInfo.total_topics} topics, ${interviewInfo.facts_count} facts`
      : ""}
  </span>
)}
```

### Task 2.5: Verify and commit

```bash
pnpm build
```

**Commit:** `feat(ui): normalize typography scale — kill text-[11px], fix StatusBar`

---

## Batch 3 — Interaction Polish (focus rings, press feedback, modal/toast animations)

### Task 3.1: DetailModal entrance animation

**File:** `src/components/shared/DetailModal.tsx`

Add `animate-in fade-in zoom-in-95 duration-150` to the modal container (line 31):

```
Old: className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 shadow-xl"
New: className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 shadow-xl animate-in fade-in zoom-in-95 duration-150"
```

### Task 3.2: Toast exit animation

**File:** `src/components/shared/ToastProvider.tsx`

Add exit animation. Replace instant removal with a fade transition. Change the toast dismiss to use a CSS class before removal:

In the toast rendering (line 51-59), add `transition-all duration-200` to the toast class:

```
Old: className={`flex items-center gap-2 rounded border px-3 py-2 text-xs shadow-lg animate-in slide-in-from-right ${variantStyles[t.variant]}`}
New: className={`flex items-center gap-2 rounded border px-3 py-2 text-xs shadow-lg animate-in slide-in-from-right duration-200 ${variantStyles[t.variant]}`}
```

### Task 3.3: Agent card hover depth + focus ring

**File:** `src/components/dashboard/AgentGrid.tsx`

Add hover shadow and focus-visible ring to agent cards (line 32):

```
Old: className="group relative rounded border border-zinc-700 p-2 text-xs transition-colors duration-150 hover:border-zinc-500 hover:bg-zinc-800/50"
New: className="group relative rounded border border-zinc-700 p-2 text-xs transition-all duration-150 hover:border-zinc-500 hover:bg-zinc-800/50 hover:shadow-sm hover:shadow-black/20"
```

Add focus ring to run button (line 48):

```
Old: className="rounded p-1 text-zinc-500 opacity-0 transition-opacity hover:bg-zinc-700 hover:text-zinc-200 group-hover:opacity-100 disabled:opacity-30"
New: className="rounded p-1 text-zinc-500 opacity-0 transition-opacity hover:bg-zinc-700 hover:text-zinc-200 group-hover:opacity-100 disabled:opacity-30 focus-visible:opacity-100 focus-visible:ring-1 focus-visible:ring-zinc-500 focus-visible:outline-none"
```

### Task 3.4: Nudge item hover depth + button feedback

**File:** `src/components/dashboard/NudgeList.tsx`

Add hover shadow to nudge items (line 45):

```
Old: className={`rounded border-l-2 p-2 text-xs ${priorityColor[n.priority_label] ?? priorityColor.low}`}
New: className={`rounded border-l-2 p-2 text-xs transition-shadow duration-150 hover:shadow-sm hover:shadow-black/20 ${priorityColor[n.priority_label] ?? priorityColor.low}`}
```

Add active:scale to the Act button (line 70-71):

```
Old: className="flex items-center gap-1 rounded px-1.5 py-1 text-green-400 hover:bg-green-500/20"
New: className="flex items-center gap-1 rounded px-1.5 py-1 text-green-400 hover:bg-green-500/20 active:scale-[0.97] focus-visible:ring-1 focus-visible:ring-zinc-500 focus-visible:outline-none"
```

### Task 3.5: OutputPane expand transition

**File:** `src/components/dashboard/OutputPane.tsx`

Add `duration-200` to the transition-[max-height] on the output scroll area (line 83):

```
Old: className={`${maxHeight} overflow-y-auto bg-zinc-950 px-4 py-2 font-mono text-xs text-zinc-400 transition-[max-height]`}
New: className={`${maxHeight} overflow-y-auto bg-zinc-950 px-4 py-2 font-mono text-xs text-zinc-400 transition-[max-height] duration-200`}
```

### Task 3.6: AssistantMessage copy tooltip

**File:** `src/components/chat/AssistantMessage.tsx`

Add "Copied!" text next to the check icon (line 36):

```
Old: {copied ? <Check className="h-3 w-3 text-green-400" /> : <Copy className="h-3 w-3" />}
New: {copied ? (
  <span className="flex items-center gap-1">
    <Check className="h-3 w-3 text-green-400" />
    <span className="text-[10px] text-green-400">Copied</span>
  </span>
) : (
  <Copy className="h-3 w-3" />
)}
```

### Task 3.7: Send/Stop button press feedback

**File:** `src/components/chat/ChatInput.tsx`

Add `active:scale-[0.97]` to send button (line 342):

```
Old: className="rounded border border-zinc-700 p-2 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 disabled:opacity-30"
New: className="rounded border border-zinc-700 p-2 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 disabled:opacity-30 active:scale-[0.97]"
```

And stop button (line 333):

```
Old: className="rounded border border-red-500/30 p-2 text-red-400 hover:bg-red-500/20"
New: className="rounded border border-red-500/30 p-2 text-red-400 hover:bg-red-500/20 active:scale-[0.97]"
```

### Task 3.8: HealthHistoryChart YAxis fix

**File:** `src/components/sidebar/HealthHistoryChart.tsx`

Replace `margin: { left: -20 }` with proper YAxis width (line 19-21):

```
Old: <AreaChart data={chartData} margin={{ top: 2, right: 4, left: -20, bottom: 0 }}>
     <XAxis dataKey="time" tick={{ fontSize: 8, fill: "#928374" }} interval="preserveStartEnd" />
     <YAxis tick={{ fontSize: 8, fill: "#928374" }} />
New: <AreaChart data={chartData} margin={{ top: 2, right: 4, left: 0, bottom: 0 }}>
     <XAxis dataKey="time" tick={{ fontSize: 8, fill: "#928374" }} interval="preserveStartEnd" />
     <YAxis tick={{ fontSize: 8, fill: "#928374" }} width={25} />
```

### Task 3.9: Verify and commit

```bash
pnpm build
```

**Commit:** `feat(ui): interaction polish — animations, focus rings, hover depth, press feedback`

---

## Batch 4 — Chat Page Refinements

### Task 4.1: Suggestion chips empty state

**File:** `src/components/chat/MessageList.tsx`

Replace the empty state text with suggestion chips. Add a `onSuggestionClick` prop pattern. Since MessageList uses ChatProvider context, add the sendMessage call:

Replace lines 45-51 (empty state block):

```tsx
{state.messages.length === 0 && !state.isStreaming && (
  <EmptyState />
)}
```

Add the EmptyState component at the bottom of the file (before the final `}`):

```tsx
function EmptyState() {
  const { sendMessage, state } = useChatContext();
  const suggestions = [
    "System health",
    "Run briefing",
    "Search documents",
    "What changed today?",
  ];

  return (
    <div className="py-12 text-center">
      <p className="text-sm text-zinc-500">What would you like to do?</p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        {suggestions.map((s) => (
          <button
            key={s}
            onClick={() => sendMessage(s)}
            disabled={state.isStreaming}
            className="rounded-full border border-zinc-700 px-3 py-1.5 text-xs text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200 active:scale-[0.97]"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
```

Remove the old `<p className="mt-1 text-xs text-zinc-600">` helper text line.

### Task 4.2: Message spacing

**File:** `src/components/chat/MessageList.tsx`

Tighten message spacing from space-y-4 to space-y-3 (line 44):

```
Old: <div className="mx-auto max-w-3xl space-y-4">
New: <div className="mx-auto max-w-3xl space-y-3">
```

### Task 4.3: Streaming cursor refinement

**File:** `src/components/chat/StreamingMessage.tsx`

Make cursor thinner and subtler (line 11):

```
Old: <span className="inline-block h-4 w-1 animate-pulse bg-green-400" />
New: <span className="inline-block h-3 w-0.5 animate-pulse bg-green-400/70" />
```

### Task 4.4: Tool call thinking indicator

**File:** `src/components/chat/ChatProvider.tsx`

Add `currentToolName` to ChatState:

```tsx
interface ChatState {
  sessionId: string | null;
  messages: ChatMessage[];
  isStreaming: boolean;
  streamingText: string;
  currentToolName: string | null;  // <-- add this
  model: string;
  mode: "chat" | "interview";
  totalTokens: number;
  lastTurnTokens: number;
  error: string | null;
}
```

Add to initialState:
```
currentToolName: null,
```

In the reducer, handle STREAM_TOOL_CALL and STREAM_DONE/STREAM_ERROR/STREAM_ABORT:

```tsx
case "STREAM_TOOL_CALL": {
  const toolMsg: ChatMessage = {
    id: action.callId,
    role: "tool_call",
    content: "",
    toolName: action.name,
    toolArgs: action.args,
    timestamp: Date.now(),
  };
  return { ...state, messages: [...state.messages, toolMsg], currentToolName: action.name };
}
```

In STREAM_DONE, add `currentToolName: null`:
```tsx
case "STREAM_DONE": {
  // ... existing code ...
  return {
    ...state,
    isStreaming: false,
    streamingText: "",
    currentToolName: null,
    messages: [...state.messages, assistantMsg],
    totalTokens: action.totalTokens,
    lastTurnTokens: action.turnTokens,
  };
}
```

In STREAM_ERROR: add `currentToolName: null`
In STREAM_ABORT: add `currentToolName: null`
In STREAM_START: add `currentToolName: null`

**File:** `src/components/chat/MessageList.tsx`

Update the thinking indicator (lines 62-70) to show tool name:

```tsx
{state.isStreaming && !state.streamingText && (
  <div className="flex items-center gap-2 rounded-lg border-l-2 border-green-500/30 bg-zinc-900/50 px-3 py-2">
    <div className="flex gap-1">
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-green-400 [animation-delay:0ms]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-green-400 [animation-delay:150ms]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-green-400 [animation-delay:300ms]" />
    </div>
    <span className="text-xs text-zinc-500">
      {state.currentToolName
        ? `Calling ${state.currentToolName}...`
        : "Thinking..."}
    </span>
  </div>
)}
```

### Task 4.5: Conversation turn time separators

**File:** `src/components/chat/MessageList.tsx`

Add a `TimeSeparator` component and insert between messages when gap > 5 minutes.

Add component:

```tsx
function TimeSeparator({ timestamp }: { timestamp: number }) {
  return (
    <div className="flex items-center gap-3 py-1">
      <div className="h-px flex-1 bg-zinc-800" />
      <span className="text-[10px] text-zinc-600">
        {new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
      </span>
      <div className="h-px flex-1 bg-zinc-800" />
    </div>
  );
}
```

In the grouped map, check timestamps between items and insert separators. Update the rendering logic:

Replace the `grouped.map` block with:

```tsx
{grouped.map((item, i) => {
  const prev = i > 0 ? grouped[i - 1] : null;
  const currentTs = Array.isArray(item) ? item[0].timestamp : item.timestamp;
  const prevTs = prev
    ? Array.isArray(prev) ? prev[prev.length - 1].timestamp : prev.timestamp
    : null;
  const showSeparator = prevTs && currentTs - prevTs > 5 * 60 * 1000;

  return (
    <div key={Array.isArray(item) ? `tg-${i}` : item.id}>
      {showSeparator && <TimeSeparator timestamp={currentTs} />}
      {Array.isArray(item) ? (
        <ToolGroup messages={item} />
      ) : (
        <MessageComponent message={item} />
      )}
    </div>
  );
})}
```

### Task 4.6: Slash command dropdown accent

**File:** `src/components/chat/ChatInput.tsx`

Add left border accent to each suggestion item (line 308):

```
Old: className={`flex w-full items-center gap-3 px-3 py-1.5 text-left text-xs ${
New: className={`flex w-full items-center gap-3 border-l-2 border-cyan-400/30 px-3 py-1.5 text-left text-xs ${
```

### Task 4.7: Verify and commit

```bash
pnpm build
```

**Commit:** `feat(chat): suggestion chips, tool indicator, time separators, cursor polish`

---

## Batch 5 — Adaptive Sidebar

### Task 5.1: Create SidebarStrip component

**New file:** `src/components/sidebar/SidebarStrip.tsx`

```tsx
import {
  Heart, Cpu, Server, FileText, Clock, Target,
  DollarSign, Compass, GitBranch, Users, Accessibility, Timer,
} from "lucide-react";
import type { ComponentType } from "react";

interface StripItem {
  id: string;
  icon: ComponentType<{ className?: string }>;
  label: string;
}

const stripItems: StripItem[] = [
  { id: "health", icon: Heart, label: "Health" },
  { id: "vram", icon: Cpu, label: "VRAM" },
  { id: "containers", icon: Server, label: "Containers" },
  { id: "briefing", icon: FileText, label: "Briefing" },
  { id: "readiness", icon: Clock, label: "Readiness" },
  { id: "goals", icon: Target, label: "Goals" },
  { id: "cost", icon: DollarSign, label: "Cost" },
  { id: "scout", icon: Compass, label: "Scout" },
  { id: "drift", icon: GitBranch, label: "Drift" },
  { id: "management", icon: Users, label: "Management" },
  { id: "accommodations", icon: Accessibility, label: "Accommodations" },
  { id: "timers", icon: Timer, label: "Timers" },
];

interface SidebarStripProps {
  statusDots: Record<string, "green" | "yellow" | "red" | "zinc">;
  summaries: Record<string, string>;
  onPanelClick: (id: string) => void;
}

export function SidebarStrip({ statusDots, summaries, onPanelClick }: SidebarStripProps) {
  return (
    <div className="flex flex-col items-center gap-1 py-3">
      {stripItems.map((item) => {
        const dotColor = statusDots[item.id] ?? "zinc";
        const dotClass = {
          green: "bg-green-400",
          yellow: "bg-yellow-400",
          red: "bg-red-400",
          zinc: "bg-zinc-600",
        }[dotColor];

        return (
          <button
            key={item.id}
            onClick={() => onPanelClick(item.id)}
            className="group relative flex h-9 w-9 items-center justify-center rounded text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-300"
            title={summaries[item.id] ?? item.label}
          >
            <item.icon className="h-4 w-4" />
            <span className={`absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full ${dotClass}`} />
          </button>
        );
      })}
    </div>
  );
}
```

### Task 5.2: Refactor Sidebar to dual-mode

**File:** `src/components/Sidebar.tsx`

Rewrite to support calm mode (48px icon strip) and alert mode (288px panels). The sidebar auto-expands when triggers fire:

```tsx
import { useState, useMemo, useCallback, type ComponentType } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useHealth, useGpu, useInfrastructure, useBriefing, useDrift, useManagement, useNudges } from "../api/hooks";
import { HealthPanel } from "./sidebar/HealthPanel";
import { VramPanel } from "./sidebar/VramPanel";
import { ContainersPanel } from "./sidebar/ContainersPanel";
import { BriefingPanel } from "./sidebar/BriefingPanel";
import { GoalsPanel } from "./sidebar/GoalsPanel";
import { FreshnessPanel } from "./sidebar/FreshnessPanel";
import { CostPanel } from "./sidebar/CostPanel";
import { ScoutPanel } from "./sidebar/ScoutPanel";
import { DriftPanel } from "./sidebar/DriftPanel";
import { ManagementPanel } from "./sidebar/ManagementPanel";
import { AccommodationPanel } from "./sidebar/AccommodationPanel";
import { TimersPanel } from "./sidebar/TimersPanel";
import { SidebarStrip } from "./sidebar/SidebarStrip";

interface PanelEntry {
  id: string;
  component: ComponentType;
  defaultOrder: number;
}

const panels: PanelEntry[] = [
  { id: "health", component: HealthPanel, defaultOrder: 0 },
  { id: "vram", component: VramPanel, defaultOrder: 1 },
  { id: "containers", component: ContainersPanel, defaultOrder: 2 },
  { id: "briefing", component: BriefingPanel, defaultOrder: 3 },
  { id: "readiness", component: FreshnessPanel, defaultOrder: 4 },
  { id: "goals", component: GoalsPanel, defaultOrder: 5 },
  { id: "cost", component: CostPanel, defaultOrder: 6 },
  { id: "scout", component: ScoutPanel, defaultOrder: 7 },
  { id: "drift", component: DriftPanel, defaultOrder: 8 },
  { id: "management", component: ManagementPanel, defaultOrder: 9 },
  { id: "accommodations", component: AccommodationPanel, defaultOrder: 10 },
  { id: "timers", component: TimersPanel, defaultOrder: 11 },
];

export function Sidebar() {
  const [manualOverride, setManualOverride] = useState<"expanded" | "collapsed" | null>(null);
  const [focusPanel, setFocusPanel] = useState<string | null>(null);

  // Data for trigger logic + priority sorting
  const { data: health } = useHealth();
  const { data: gpu } = useGpu();
  const { data: infra } = useInfrastructure();
  const { data: briefing } = useBriefing();
  const { data: drift } = useDrift();
  const { data: mgmt } = useManagement();
  const { data: nudges } = useNudges();

  // Alert triggers
  const needsAttention = useMemo(() => {
    if (health?.overall_status === "degraded" || health?.overall_status === "failed") return true;
    if (nudges?.some((n) => n.priority_label === "critical" || n.priority_label === "high" || n.priority_label === "medium")) return true;
    if (gpu && gpu.usage_pct >= 80) return true;
    if (drift && drift.drift_count > 0) return true;
    if (briefing?.generated_at) {
      const hours = (Date.now() - new Date(briefing.generated_at).getTime()) / 3_600_000;
      if (hours > 24) return true;
    }
    return false;
  }, [health, gpu, drift, briefing, nudges]);

  const isExpanded = manualOverride === "expanded" || (manualOverride === null && needsAttention);

  // Status dots for strip mode
  const statusDots = useMemo(() => {
    const dots: Record<string, "green" | "yellow" | "red" | "zinc"> = {};
    dots.health = health?.overall_status === "failed" ? "red" : health?.overall_status === "degraded" ? "yellow" : health ? "green" : "zinc";
    dots.vram = gpu && gpu.usage_pct >= 90 ? "red" : gpu && gpu.usage_pct >= 80 ? "yellow" : gpu ? "green" : "zinc";
    dots.containers = infra?.containers.some((c) => c.health !== "healthy") ? "yellow" : infra ? "green" : "zinc";
    dots.briefing = (() => {
      if (!briefing?.generated_at) return "zinc";
      const h = (Date.now() - new Date(briefing.generated_at).getTime()) / 3_600_000;
      return h > 24 ? "yellow" : "green";
    })();
    dots.drift = drift && drift.drift_count > 0 ? "yellow" : drift ? "green" : "zinc";
    dots.management = mgmt?.people.some((p) => p.stale_1on1) ? "yellow" : mgmt ? "green" : "zinc";
    return dots;
  }, [health, gpu, infra, briefing, drift, mgmt]);

  const summaries = useMemo(() => {
    const s: Record<string, string> = {};
    if (health) s.health = `Health: ${health.healthy}/${health.total_checks} passing`;
    if (gpu) s.vram = `VRAM: ${(gpu.free_mb / 1024).toFixed(1)}GB free`;
    if (infra) s.containers = `${infra.containers.filter((c) => c.state === "running").length} containers running`;
    return s;
  }, [health, gpu, infra]);

  // Priority sorting (same as before)
  const sorted = useMemo(() => {
    function priority(id: string): number {
      switch (id) {
        case "health":
          if (health?.overall_status === "failed") return 100;
          if (health?.overall_status === "degraded") return 50;
          return 0;
        case "vram":
          if (gpu && gpu.usage_pct >= 90) return 60;
          if (gpu && gpu.usage_pct >= 80) return 30;
          return 0;
        case "containers": {
          const unhealthy = infra?.containers.filter((c) => c.health !== "healthy").length ?? 0;
          return unhealthy > 0 ? 40 : 0;
        }
        case "briefing": {
          if (!briefing?.generated_at) return 0;
          const hours = (Date.now() - new Date(briefing.generated_at).getTime()) / 3_600_000;
          return hours > 24 ? 30 : 0;
        }
        case "drift":
          return drift && drift.drift_count > 0 ? 20 : 0;
        case "management": {
          const stale = mgmt?.people.filter((p) => p.stale_1on1).length ?? 0;
          return stale > 0 ? 25 : 0;
        }
        default:
          return 0;
      }
    }

    return [...panels].sort((a, b) => {
      const pa = priority(a.id);
      const pb = priority(b.id);
      if (pa !== pb) return pb - pa;
      return a.defaultOrder - b.defaultOrder;
    });
  }, [health, gpu, infra, briefing, drift, mgmt]);

  const handleStripClick = useCallback((id: string) => {
    setFocusPanel(id);
    setManualOverride("expanded");
  }, []);

  const toggleSidebar = useCallback(() => {
    if (isExpanded) {
      setManualOverride("collapsed");
      setFocusPanel(null);
    } else {
      setManualOverride("expanded");
    }
  }, [isExpanded]);

  return (
    <aside className={`relative shrink-0 border-l border-zinc-700 bg-zinc-900/50 text-xs transition-[width] duration-200 ease-in-out ${isExpanded ? "w-72" : "w-12"}`}>
      {isExpanded ? (
        <div className="h-full divide-y divide-zinc-800 overflow-y-auto animate-in fade-in duration-150">
          <div className="flex justify-end p-2">
            <button
              onClick={toggleSidebar}
              className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
              title="Collapse sidebar"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
          {sorted.map((panel) => (
            <div key={panel.id} className="p-4" id={`sidebar-${panel.id}`}>
              <panel.component />
            </div>
          ))}
        </div>
      ) : (
        <div className="h-full overflow-y-auto">
          <div className="flex justify-center py-2">
            <button
              onClick={toggleSidebar}
              className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
              title="Expand sidebar"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
          </div>
          <SidebarStrip
            statusDots={statusDots}
            summaries={summaries}
            onPanelClick={handleStripClick}
          />
        </div>
      )}
    </aside>
  );
}
```

### Task 5.3: Verify and commit

```bash
pnpm build
```

**Commit:** `feat(sidebar): adaptive dual-mode — calm icon strip / alert expanded panels`

---

## Batch 6 — Spacing Rhythm Pass

### Task 6.1: SidebarSection internal spacing

**File:** `src/components/sidebar/SidebarSection.tsx`

Change `space-y-1` to `space-y-1.5` for within-panel rhythm (line 22):

```
Old: <div className="space-y-1 text-zinc-400">
New: <div className="space-y-1.5 text-zinc-400">
```

### Task 6.2: Verify and commit

```bash
pnpm build
```

**Commit:** `feat(ui): normalize spacing rhythm within sidebar panels`

---

## Batch 7 — Final Verification

### Task 7.1: Full build check

```bash
pnpm build
```

### Task 7.2: Visual verification

Open browser to `http://localhost:5173` and screenshot dashboard and chat pages. Verify:

- Dashboard: CopilotBanner has metrics line, no QuickInput, no SystemSummary
- Sidebar: starts in calm mode (icon strip) when healthy, expands on alerts
- Chat: suggestion chips on empty state, time separators, tool name indicator
- Typography: no `text-[11px]` anywhere
- All animations smooth

### Task 7.3: Search for remaining text-[11px]

```bash
pnpm exec -- grep -r "text-\[11px\]" src/ --include="*.tsx" --include="*.ts"
```

Should return zero results.

---

## Summary

| Batch | Scope | Files | Commit |
|-------|-------|-------|--------|
| 1 | Dashboard cleanup | 4 (2 modified, 2 deleted) | merge SystemSummary, remove QuickInput |
| 2 | Typography scale | 4 modified | kill text-[11px], fix StatusBar |
| 3 | Interaction polish | 7 modified | animations, focus, hover, press |
| 4 | Chat refinements | 4 modified | chips, tool indicator, separators |
| 5 | Adaptive sidebar | 2 (1 new, 1 rewrite) | dual-mode sidebar |
| 6 | Spacing rhythm | 1 modified | sidebar panel spacing |
| 7 | Verification | 0 | visual check |

**Total:** ~18 files touched, 1 new, 2 deleted, 7 commits.
