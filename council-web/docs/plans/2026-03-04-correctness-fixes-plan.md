# Cockpit-Web Correctness & Robustness Fixes

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix P0/P1 correctness issues — unmount cleanup, dead navigation, keyboard accessibility, error states, and silent failures.

**Architecture:** Targeted fixes to existing components. No new files, no structural changes. Each batch is independently shippable.

**Tech Stack:** React 19, TypeScript, TanStack Query, Tailwind v4

**Working directory:** `~/projects/cockpit-web`
**Branch:** `feat/web-migration`
**Verify after each batch:** `pnpm build`

---

## Batch 1 — P0: ChatProvider unmount cleanup

The core issue: if the user navigates away from `/chat` while streaming, the SSE fetch continues and dispatches state updates to an unmounted reducer.

### Task 1.1: Add unmount abort to ChatProvider

**File:** `src/components/chat/ChatProvider.tsx`

Add a cleanup effect that aborts any active stream when the provider unmounts. Insert after `const controllerRef = useRef<AbortController | null>(null);` (line 183):

```tsx
  // Abort any active stream on unmount
  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
    };
  }, []);
```

### Task 1.2: Update ChatPage comment

**File:** `src/pages/ChatPage.tsx`

Fix the stale comment on line 25:

```
Old:   // Handle ?message= from QuickInput
New:   // Handle ?message= param (command palette, external deep links)
```

### Task 1.3: Verify and commit

```bash
pnpm build
```

**Commit:** `fix(chat): abort SSE stream on ChatProvider unmount`

---

## Batch 2 — P1: ManualDrawer error state + backdrop consistency

### Task 2.1: Add error handling to ManualDrawer

**File:** `src/components/layout/ManualDrawer.tsx`

The `useManual()` hook can fail but the drawer shows "Loading manual..." forever. Fix by destructuring `isError`:

Replace line 12:
```
Old:   const { data: manual } = useManual();
New:   const { data: manual, isError } = useManual();
```

Replace the content area (lines 49-52):
```
Old:         {manual?.content ? (
            <MarkdownContent content={manual.content} />
          ) : (
            <p className="text-xs text-zinc-500">Loading manual...</p>
          )}
New:         {manual?.content ? (
            <MarkdownContent content={manual.content} />
          ) : isError ? (
            <p className="text-xs text-red-400">Failed to load manual. Is the API running?</p>
          ) : (
            <p className="text-xs text-zinc-500">Loading manual...</p>
          )}
```

### Task 2.2: Fix ManualDrawer backdrop to match other overlays

**File:** `src/components/layout/ManualDrawer.tsx`

Update backdrop to match DetailModal and CommandPalette:

```
Old:       {open && <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />}
New:       {open && <div className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm" onClick={onClose} />}
```

### Task 2.3: Verify and commit

```bash
pnpm build
```

**Commit:** `fix(manual): add error state, match backdrop to other overlays`

---

## Batch 3 — P1: SidebarSection keyboard accessibility

### Task 3.1: Add keyboard support to clickable SidebarSection

**File:** `src/components/sidebar/SidebarSection.tsx`

The clickable variant uses `<div onClick>` without keyboard support. Fix:

Replace lines 14-16:
```
Old:     <div
      className={clickable ? "cursor-pointer rounded p-1 -m-1 hover:bg-zinc-800/50" : ""}
      onClick={clickable ? onClick : undefined}
    >
New:     <div
      className={clickable ? "cursor-pointer rounded p-1 -m-1 hover:bg-zinc-800/50 focus-visible:ring-1 focus-visible:ring-zinc-500 focus-visible:outline-none" : ""}
      onClick={clickable ? onClick : undefined}
      onKeyDown={clickable ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick?.(); } } : undefined}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
    >
```

### Task 3.2: Verify and commit

```bash
pnpm build
```

**Commit:** `fix(a11y): add keyboard support to clickable SidebarSection`

---

## Batch 4 — P1: Dead command palette navigation targets

### Task 4.1: Remove dead navigation params from CommandPalette

**File:** `src/components/shared/CommandPalette.tsx`

The palette navigates to `/?agent=${name}` and `/chat?action=export` but nothing reads these params. Fix by making them actually work — or removing them if they don't make sense.

The `?agent=` param: DashboardPage doesn't read this. Rather than adding param handling to DashboardPage (which would need to trigger MainPanel's agent run), simplify by just navigating to dashboard (the agent grid is visible, user can click run).

The `?action=export` param: ChatPage doesn't read this either. Remove — user can type `/export` in chat.

The `?new=1` param: ChatPage doesn't read this either. Remove — user can type `/new` in chat.

Replace lines 32-34:
```
Old:     { id: "new-chat", label: "New Chat Session", action: () => { navigate("/chat?new=1"); onClose(); } },
    { id: "health", label: "View Health Detail", action: () => { navigate("/"); onClose(); } },
    { id: "export", label: "Export Chat", action: () => { navigate("/chat?action=export"); onClose(); } },
New:     { id: "new-chat", label: "New Chat Session", action: () => { navigate("/chat"); onClose(); } },
    { id: "health", label: "View Health Detail", action: () => { navigate("/"); onClose(); } },
```

Remove the agent command navigation hack. Replace lines 37-41:
```
Old:   const agentCommands: Command[] = (agents ?? []).map((a) => ({
    id: `agent-${a.name}`,
    label: `Run ${a.name}`,
    action: () => { navigate(`/?agent=${a.name}`); onClose(); },
  }));
New:   const agentCommands: Command[] = (agents ?? []).map((a) => ({
    id: `agent-${a.name}`,
    label: `Run ${a.name}`,
    action: () => { navigate("/"); onClose(); },
  }));
```

### Task 4.2: Verify and commit

```bash
pnpm build
```

**Commit:** `fix(palette): remove dead navigation params`

---

## Batch 5 — P1: ChatInput unhandled promise rejections

### Task 5.1: Wrap interview command handlers

**File:** `src/components/chat/ChatInput.tsx`

The `handleInterviewCommand` function calls async methods without try/catch. Wrap them:

Replace the entire `handleInterviewCommand` function (lines 230-254):
```tsx
  async function handleInterviewCommand(args: string[]) {
    const sub = args[0]?.toLowerCase();
    try {
      switch (sub) {
        case "end":
          await endInterview();
          return;
        case "skip":
          await skipInterviewTopic();
          return;
        case "status": {
          const status = await getInterviewStatus();
          if (!status || !status.active) {
            addSystemMessage("No active interview.");
          } else {
            addSystemMessage(
              `Interview: ${status.topics_explored}/${status.total_topics} topics explored, ${status.facts_count} facts, ${status.insights_count} insights\n${status.status}`
            );
          }
          return;
        }
        default:
          startInterview();
          return;
      }
    } catch (err) {
      addSystemMessage(`Interview error: ${err}`);
    }
  }
```

### Task 5.2: Verify and commit

```bash
pnpm build
```

**Commit:** `fix(chat): handle interview command promise rejections`

---

## Batch 6 — P2: MarkdownContent list styling

### Task 6.1: Add list styling to MarkdownContent

**File:** `src/components/shared/MarkdownContent.tsx`

Lists render without bullets or numbers. Add `ul` and `ol` component overrides. Insert after the `li` component (line 55):

```
Old:           li: ({ children }) => <li className="text-zinc-400">{children}</li>,
New:           ul: ({ children }) => <ul className="list-disc pl-5 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="text-zinc-400">{children}</li>,
```

### Task 6.2: Verify and commit

```bash
pnpm build
```

**Commit:** `fix(markdown): add list bullet/number styling`

---

## Batch 7 — Final verification

### Task 7.1: Full build

```bash
pnpm build
```

### Task 7.2: Visual check

Start dev server, screenshot dashboard and chat pages to verify nothing regressed.

---

## Summary

| Batch | Priority | Issue | Files |
|-------|----------|-------|-------|
| 1 | P0 | SSE stream not aborted on unmount | ChatProvider, ChatPage |
| 2 | P1 | ManualDrawer stuck loading + backdrop | ManualDrawer |
| 3 | P1 | Clickable div without keyboard support | SidebarSection |
| 4 | P1 | Dead command palette navigation params | CommandPalette |
| 5 | P1 | Unhandled promise rejections | ChatInput |
| 6 | P2 | Lists render without bullets | MarkdownContent |
| 7 | — | Verification | — |

**Total:** 6 files modified, 7 commits.
