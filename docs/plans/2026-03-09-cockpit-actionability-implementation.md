# Cockpit Actionability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make cockpit data panels actionable by connecting them to the agent execution system and adding a scout decision workflow.

**Architecture:** A shared React context (`AgentRunContext`) lets any panel trigger an agent run by setting `pendingAgentRun` state, which navigates to the dashboard and auto-opens the agent config modal with pre-filled flags. Scout decisions get a new backend endpoint and JSONL persistence. A `parseAgentCommand()` utility extracts agent name + flags from command strings.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, React Router, TanStack Query, FastAPI, Pydantic

---

### Task 1: Command Parsing Utility

**Files:**
- Create: `~/projects/hapax-logos/src/utils/parseAgentCommand.ts`

This is a pure function with no dependencies — build it first.

**Step 1: Create the utility**

Create `~/projects/hapax-logos/src/utils/parseAgentCommand.ts`:

```typescript
/**
 * Parse a command string like "uv run python -m agents.health_monitor --fix --hours 24"
 * into { agent, flags } for pre-filling the agent config modal.
 * Returns null if command doesn't match the agents.<name> pattern.
 */
export function parseAgentCommand(
  cmd: string,
): { agent: string; flags: Record<string, string> } | null {
  const match = cmd.match(/agents\.(\w+)/);
  if (!match) return null;

  const agent = match[1];
  const flags: Record<string, string> = {};

  // Extract everything after the agent module name
  const afterAgent = cmd.slice(cmd.indexOf(match[0]) + match[0].length).trim();
  const tokens = afterAgent.split(/\s+/).filter(Boolean);

  let i = 0;
  while (i < tokens.length) {
    const token = tokens[i];
    if (token.startsWith("--")) {
      // Check if next token is a value (not another flag)
      if (i + 1 < tokens.length && !tokens[i + 1].startsWith("--")) {
        flags[token] = tokens[i + 1];
        i += 2;
      } else {
        flags[token] = "";
        i += 1;
      }
    } else {
      i += 1;
    }
  }

  return { agent, flags };
}
```

**Step 2: Verify it builds**

Run: `cd ~/projects/hapax-logos && pnpm build 2>&1 | tail -5`
Expected: Build succeeds.

**Step 3: Commit**

```bash
cd ~/projects/hapax-logos
git add src/utils/parseAgentCommand.ts
git commit -m "feat: add parseAgentCommand utility for command string parsing"
```

---

### Task 2: AgentRunContext (Pre-fill Mechanism)

**Files:**
- Create: `~/projects/hapax-logos/src/contexts/AgentRunContext.tsx`
- Modify: `~/projects/hapax-logos/src/App.tsx`
- Modify: `~/projects/hapax-logos/src/components/MainPanel.tsx`
- Modify: `~/projects/hapax-logos/src/components/dashboard/AgentGrid.tsx`

**Step 1: Create the context**

Create `~/projects/hapax-logos/src/contexts/AgentRunContext.tsx`:

```typescript
import { createContext, useContext, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";

export interface PendingAgentRun {
  agent: string;
  flags: Record<string, string>;
}

interface AgentRunContextValue {
  pendingRun: PendingAgentRun | null;
  requestAgentRun: (run: PendingAgentRun) => void;
  clearPendingRun: () => void;
}

const AgentRunContext = createContext<AgentRunContextValue | null>(null);

export function AgentRunProvider({ children }: { children: React.ReactNode }) {
  const [pendingRun, setPendingRun] = useState<PendingAgentRun | null>(null);
  const navigate = useNavigate();

  const requestAgentRun = useCallback(
    (run: PendingAgentRun) => {
      setPendingRun(run);
      navigate("/");
    },
    [navigate],
  );

  const clearPendingRun = useCallback(() => setPendingRun(null), []);

  return (
    <AgentRunContext.Provider value={{ pendingRun, requestAgentRun, clearPendingRun }}>
      {children}
    </AgentRunContext.Provider>
  );
}

export function useAgentRun() {
  const ctx = useContext(AgentRunContext);
  if (!ctx) throw new Error("useAgentRun must be used within AgentRunProvider");
  return ctx;
}
```

**Step 2: Wrap app in provider**

Modify `~/projects/hapax-logos/src/components/layout/Layout.tsx`. Add import and wrap the content:

```typescript
import { AgentRunProvider } from "../../contexts/AgentRunContext";
```

Wrap the outer `<div>` content inside the `<ToastProvider>`:

```tsx
<ToastProvider>
  <AgentRunProvider>
    <div className="flex h-screen flex-col bg-zinc-950 text-zinc-100">
      {/* ... existing content unchanged ... */}
    </div>
  </AgentRunProvider>
</ToastProvider>
```

**Step 3: Make AgentGrid consume pending runs**

Modify `~/projects/hapax-logos/src/components/dashboard/AgentGrid.tsx`:

Add import:
```typescript
import { useEffect } from "react";
import { useAgentRun } from "../../contexts/AgentRunContext";
```

Inside `AgentGrid` component, after the existing `const [configAgent, setConfigAgent]` line, add:

```typescript
const { pendingRun, clearPendingRun } = useAgentRun();

useEffect(() => {
  if (pendingRun && agents) {
    const match = agents.find((a) => a.name === pendingRun.agent);
    if (match) {
      setConfigAgent(match);
      // Pre-fill flags handled in AgentConfigModal via initialFlags prop
    }
    clearPendingRun();
  }
}, [pendingRun, agents, clearPendingRun]);
```

Update the `AgentConfigModal` usage to pass initial flags:

```tsx
{configAgent && (
  <AgentConfigModal
    agent={configAgent}
    initialFlags={pendingRun?.agent === configAgent.name ? pendingRun.flags : undefined}
    onRun={handleRun}
    onClose={() => setConfigAgent(null)}
  />
)}
```

Wait — the `pendingRun` will be cleared before the modal renders. We need to capture the flags before clearing. Adjust:

```typescript
const { pendingRun, clearPendingRun } = useAgentRun();
const [prefilledFlags, setPrefilledFlags] = useState<Record<string, string> | undefined>();

useEffect(() => {
  if (pendingRun && agents) {
    const match = agents.find((a) => a.name === pendingRun.agent);
    if (match) {
      setPrefilledFlags(pendingRun.flags);
      setConfigAgent(match);
    }
    clearPendingRun();
  }
}, [pendingRun, agents, clearPendingRun]);
```

And clear prefilled flags when modal closes:

```typescript
function handleCloseConfig() {
  setConfigAgent(null);
  setPrefilledFlags(undefined);
}
```

Update JSX:

```tsx
{configAgent && (
  <AgentConfigModal
    agent={configAgent}
    initialFlags={prefilledFlags}
    onRun={handleRun}
    onClose={handleCloseConfig}
  />
)}
```

**Step 4: Make AgentConfigModal accept initialFlags**

Modify `~/projects/hapax-logos/src/components/dashboard/AgentConfigModal.tsx`:

Add `initialFlags` to props:

```typescript
interface AgentConfigModalProps {
  agent: AgentInfo;
  initialFlags?: Record<string, string>;
  onRun: (agent: AgentInfo, flags: string[]) => void;
  onClose: () => void;
}
```

Update the component signature:

```typescript
export function AgentConfigModal({ agent, initialFlags, onRun, onClose }: AgentConfigModalProps) {
```

Update the `useState` initializer to use `initialFlags` when provided:

```typescript
const [flagState, setFlagState] = useState<Record<string, string | boolean>>(() => {
  const initial: Record<string, string | boolean> = {};
  for (const f of agent.flags) {
    if (initialFlags && f.flag in initialFlags) {
      // Pre-fill from requested run
      if (f.flag_type === "bool") {
        initial[f.flag] = true;
      } else {
        initial[f.flag] = initialFlags[f.flag] || f.default || "";
      }
    } else if (f.flag_type === "bool") {
      initial[f.flag] = false;
    } else if (f.flag_type === "value") {
      initial[f.flag] = f.default ?? "";
    } else {
      initial[f.flag] = "";
    }
  }
  return initial;
});
```

**Step 5: Verify it builds**

Run: `cd ~/projects/hapax-logos && pnpm build 2>&1 | tail -5`
Expected: Build succeeds.

**Step 6: Commit**

```bash
cd ~/projects/hapax-logos
git add src/contexts/AgentRunContext.tsx src/components/layout/Layout.tsx src/components/dashboard/AgentGrid.tsx src/components/dashboard/AgentConfigModal.tsx
git commit -m "feat: add AgentRunContext for pre-filling agent runs from data panels"
```

---

### Task 3: Health + Drift Action Buttons

**Files:**
- Modify: `~/projects/hapax-logos/src/components/sidebar/HealthPanel.tsx`
- Modify: `~/projects/hapax-logos/src/components/sidebar/DriftPanel.tsx`

**Step 1: Add Auto-fix button to HealthPanel**

Modify `~/projects/hapax-logos/src/components/sidebar/HealthPanel.tsx`:

Add import:
```typescript
import { useAgentRun } from "../../contexts/AgentRunContext";
import { Wrench } from "lucide-react";
```

Inside the component, add:
```typescript
const { requestAgentRun } = useAgentRun();
```

In the detail modal, after the "Failed Checks" list (after the closing `</div>` of the failed_checks section, around line 50), add:

```tsx
<button
  onClick={() => {
    setDetailOpen(false);
    requestAgentRun({ agent: "health_monitor", flags: { "--fix": "" } });
  }}
  className="flex items-center gap-1.5 rounded bg-green-600/20 px-3 py-1.5 text-green-400 hover:bg-green-600/30"
>
  <Wrench className="h-3 w-3" />
  Auto-fix
</button>
```

Wrap this button in a conditional so it only shows when there are failures:

```tsx
{health.failed > 0 && (
  <button ...>
    ...
  </button>
)}
```

**Step 2: Add Fix drift button to DriftPanel**

Modify `~/projects/hapax-logos/src/components/sidebar/DriftPanel.tsx`:

Add imports:
```typescript
import { useAgentRun } from "../../contexts/AgentRunContext";
import { Wrench } from "lucide-react";
```

Inside the component, add:
```typescript
const { requestAgentRun } = useAgentRun();
```

After the drift items list (after the `.map()` block), add inside the `<SidebarSection>`:

```tsx
<button
  onClick={() => requestAgentRun({ agent: "drift_detector", flags: { "--fix": "" } })}
  className="mt-1 flex items-center gap-1 text-yellow-400 hover:text-yellow-300"
>
  <Wrench className="h-3 w-3" />
  <span>Fix drift</span>
</button>
```

**Step 3: Verify it builds**

Run: `cd ~/projects/hapax-logos && pnpm build 2>&1 | tail -5`
Expected: Build succeeds.

**Step 4: Commit**

```bash
cd ~/projects/hapax-logos
git add src/components/sidebar/HealthPanel.tsx src/components/sidebar/DriftPanel.tsx
git commit -m "feat: add auto-fix and fix-drift action buttons to sidebar panels"
```

---

### Task 4: Briefing + Nudge Action Buttons

**Files:**
- Modify: `~/projects/hapax-logos/src/components/sidebar/BriefingPanel.tsx`
- Modify: `~/projects/hapax-logos/src/components/dashboard/NudgeList.tsx`

**Step 1: Add play buttons to briefing action items**

Modify `~/projects/hapax-logos/src/components/sidebar/BriefingPanel.tsx`:

Add imports:
```typescript
import { useAgentRun } from "../../contexts/AgentRunContext";
import { parseAgentCommand } from "../../utils/parseAgentCommand";
import { Play } from "lucide-react";
```

Inside the component, add:
```typescript
const { requestAgentRun } = useAgentRun();
```

Replace the action items `<li>` in the detail modal (around line 39-42) with:

```tsx
<li key={i} className="flex items-center justify-between text-zinc-400">
  <span>
    <span className="font-medium text-zinc-300">[{a.priority}]</span> {a.action}
    {a.command && <code className="ml-1 text-zinc-500">{a.command}</code>}
  </span>
  {a.command && parseAgentCommand(a.command) && (
    <button
      onClick={() => {
        const parsed = parseAgentCommand(a.command!);
        if (parsed) {
          setDetailOpen(false);
          requestAgentRun(parsed);
        }
      }}
      className="ml-2 shrink-0 rounded p-1 text-green-400 hover:bg-green-500/20"
      title="Run this command"
    >
      <Play className="h-3 w-3" />
    </button>
  )}
</li>
```

**Step 2: Connect nudge play button to agent run**

Modify `~/projects/hapax-logos/src/components/dashboard/NudgeList.tsx`:

Add imports:
```typescript
import { useAgentRun } from "../../contexts/AgentRunContext";
import { parseAgentCommand } from "../../utils/parseAgentCommand";
```

Inside the component, add:
```typescript
const { requestAgentRun } = useAgentRun();
```

Update the `handleAction` function to also trigger agent run when acting on a command nudge:

```typescript
function handleAction(nudge: Nudge, action: "act" | "dismiss") {
  setPendingId(nudge.source_id);
  nudgeAction.mutate(
    { sourceId: nudge.source_id, action },
    {
      onSuccess: () => {
        // If acting on a nudge with a command hint, navigate to agent run
        if (action === "act" && nudge.command_hint) {
          const parsed = parseAgentCommand(nudge.command_hint);
          if (parsed) {
            requestAgentRun(parsed);
          }
        }
      },
      onError: () => addToast(`Failed to ${action} nudge`, "error"),
      onSettled: () => setPendingId(null),
    },
  );
}
```

**Step 3: Verify it builds**

Run: `cd ~/projects/hapax-logos && pnpm build 2>&1 | tail -5`
Expected: Build succeeds.

**Step 4: Commit**

```bash
cd ~/projects/hapax-logos
git add src/components/sidebar/BriefingPanel.tsx src/components/dashboard/NudgeList.tsx
git commit -m "feat: connect briefing actions and nudge commands to agent runner"
```

---

### Task 5: Scout Decision Backend

**Files:**
- Create: `~/projects/hapax-council/logos/api/routes/scout.py`
- Modify: `~/projects/hapax-council/logos/api/app.py`
- Create: `~/projects/hapax-council/tests/test_scout_decisions.py`

**Step 1: Write the tests**

Create `~/projects/hapax-council/tests/test_scout_decisions.py`:

```python
"""Tests for scout decision API endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from logos.api.app import app


@pytest.fixture
def decisions_file(tmp_path):
    path = tmp_path / "scout-decisions.jsonl"
    return path


@pytest.mark.asyncio
async def test_record_decision(decisions_file):
    with patch("cockpit.api.routes.scout.DECISIONS_FILE", decisions_file):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scout/litellm-proxy/decide", json={
                "decision": "adopted",
                "notes": "Time to upgrade",
            })
    assert resp.status_code == 200
    data = resp.json()
    assert data["component"] == "litellm-proxy"
    assert data["decision"] == "adopted"
    # Verify persisted
    lines = decisions_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["component"] == "litellm-proxy"
    assert record["decision"] == "adopted"
    assert record["notes"] == "Time to upgrade"


@pytest.mark.asyncio
async def test_get_decisions(decisions_file):
    # Pre-populate with 2 decisions
    decisions_file.write_text(
        json.dumps({"component": "foo", "decision": "adopted", "timestamp": "2026-03-09T10:00:00Z", "notes": ""}) + "\n"
        + json.dumps({"component": "bar", "decision": "dismissed", "timestamp": "2026-03-09T11:00:00Z", "notes": ""}) + "\n"
    )
    with patch("cockpit.api.routes.scout.DECISIONS_FILE", decisions_file):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/scout/decisions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["decisions"]) == 2
    assert data["decisions"][0]["component"] == "foo"


@pytest.mark.asyncio
async def test_invalid_decision():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/scout/litellm-proxy/decide", json={
            "decision": "invalid_value",
        })
    assert resp.status_code == 422
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_scout_decisions.py -v`
Expected: FAIL (import error — `cockpit.api.routes.scout` doesn't exist)

**Step 3: Create scout routes**

Create `~/projects/hapax-council/logos/api/routes/scout.py`:

```python
"""Logos API routes for scout decision tracking."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

router = APIRouter(prefix="/api", tags=["scout"])

DECISIONS_FILE = Path(__file__).parent.parent.parent.parent / "profiles" / "scout-decisions.jsonl"


class ScoutDecisionRequest(BaseModel):
    decision: str
    notes: str = ""

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        if v not in ("adopted", "deferred", "dismissed"):
            raise ValueError("decision must be 'adopted', 'deferred', or 'dismissed'")
        return v


@router.post("/scout/{component}/decide")
async def record_decision(component: str, body: ScoutDecisionRequest):
    record = {
        "component": component,
        "decision": body.decision,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "notes": body.notes,
    }
    DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")
    return record


@router.get("/scout/decisions")
async def get_decisions():
    if not DECISIONS_FILE.is_file():
        return {"decisions": []}
    decisions = []
    for line in DECISIONS_FILE.read_text().strip().splitlines():
        if line.strip():
            decisions.append(json.loads(line))
    return {"decisions": decisions}
```

**Step 4: Register the router**

Modify `~/projects/hapax-council/logos/api/app.py`. Add import and registration:

```python
from logos.api.routes.scout import router as scout_router
```

Add after the existing router registrations:
```python
app.include_router(scout_router)
```

**Step 5: Run tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_scout_decisions.py -v`
Expected: 3 passed

**Step 6: Commit**

```bash
cd ~/projects/hapax-council
git add logos/api/routes/scout.py logos/api/app.py tests/test_scout_decisions.py
git commit -m "feat: add scout decision API endpoints (record + retrieve)"
```

---

### Task 6: Scout Decision Frontend

**Files:**
- Modify: `~/projects/hapax-logos/src/api/types.ts`
- Modify: `~/projects/hapax-logos/src/api/client.ts`
- Modify: `~/projects/hapax-logos/src/api/hooks.ts`
- Modify: `~/projects/hapax-logos/src/components/sidebar/ScoutPanel.tsx`

**Step 1: Add types**

In `~/projects/hapax-logos/src/api/types.ts`, after the `CycleModeResponse` interface, add:

```typescript
// --- Scout Decisions ---

export interface ScoutDecision {
  component: string;
  decision: "adopted" | "deferred" | "dismissed";
  timestamp: string;
  notes: string;
}

export interface ScoutDecisionsResponse {
  decisions: ScoutDecision[];
}
```

**Step 2: Add API methods**

In `~/projects/hapax-logos/src/api/client.ts`, add before the `demos` line:

```typescript
  scoutDecisions: () => get<import("./types").ScoutDecisionsResponse>("/scout/decisions"),
  scoutDecide: (component: string, decision: string, notes?: string) =>
    post<import("./types").ScoutDecision>(`/scout/${component}/decide`, { decision, notes: notes ?? "" }),
```

**Step 3: Add hooks**

In `~/projects/hapax-logos/src/api/hooks.ts`, add before the `// --- Demos ---` section:

```typescript
// --- Scout Decisions ---

export const useScoutDecisions = () =>
  useQuery({ queryKey: ["scoutDecisions"], queryFn: api.scoutDecisions, refetchInterval: SLOW });

export function useScoutDecide() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ component, decision, notes }: { component: string; decision: string; notes?: string }) =>
      api.scoutDecide(component, decision, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scoutDecisions"] });
    },
  });
}
```

**Step 4: Update ScoutPanel with decision buttons**

Replace the entire content of `~/projects/hapax-logos/src/components/sidebar/ScoutPanel.tsx` with:

```tsx
import { useState } from "react";
import { useScout, useScoutDecisions, useScoutDecide } from "../../api/hooks";
import { useAgentRun } from "../../contexts/AgentRunContext";
import { SidebarSection } from "./SidebarSection";
import { DetailModal } from "../shared/DetailModal";
import { StatusBadge } from "../shared/StatusBadge";
import { useToast } from "../shared/ToastProvider";
import { formatAge } from "../../utils";
import { Check, Clock, X, Loader2 } from "lucide-react";

export function ScoutPanel() {
  const { data: scout, dataUpdatedAt } = useScout();
  const { data: decisionsData } = useScoutDecisions();
  const scoutDecide = useScoutDecide();
  const { requestAgentRun } = useAgentRun();
  const { addToast } = useToast();
  const [detailOpen, setDetailOpen] = useState(false);
  const [pendingComponent, setPendingComponent] = useState<string | null>(null);

  if (!scout) return null;

  const decisions = decisionsData?.decisions ?? [];
  const decisionMap = new Map(decisions.map((d) => [d.component, d]));

  const actionable = scout.adopt_count + scout.evaluate_count;

  function handleDecision(component: string, decision: "adopted" | "deferred" | "dismissed") {
    setPendingComponent(component);
    scoutDecide.mutate(
      { component, decision },
      {
        onSuccess: () => {
          if (decision === "adopted") {
            setDetailOpen(false);
            requestAgentRun({
              agent: "research",
              flags: { "query": `Evaluate migrating to ${component}: benefits, risks, migration effort, and step-by-step plan` },
            });
          }
        },
        onError: () => addToast(`Failed to record decision for ${component}`, "error"),
        onSettled: () => setPendingComponent(null),
      },
    );
  }

  return (
    <>
      <SidebarSection title="Scout" clickable onClick={() => setDetailOpen(true)} age={formatAge(dataUpdatedAt)}>
        <p>
          {scout.components_scanned} scanned
          {actionable > 0 && (
            <span className="text-yellow-400"> · {actionable} actionable</span>
          )}
        </p>
        {scout.recommendations.filter(r => r.tier === "adopt").slice(0, 2).map((r) => (
          <p key={r.component} className="text-green-400 truncate">
            adopt: {r.component}
          </p>
        ))}
      </SidebarSection>

      <DetailModal title="Scout Report" open={detailOpen} onClose={() => setDetailOpen(false)}>
        <div className="space-y-3 text-xs">
          <p className="text-zinc-500">
            {scout.components_scanned} components scanned · {scout.generated_at}
          </p>
          {scout.recommendations.map((r) => {
            const existing = decisionMap.get(r.component);
            return (
              <div key={r.component} className={`rounded border p-2 ${existing ? "border-zinc-800 opacity-60" : "border-zinc-700"}`}>
                <div className="flex items-center gap-2">
                  <StatusBadge status={r.tier} />
                  <span className="font-medium text-zinc-200">{r.component}</span>
                  <span className="text-zinc-500">({r.current})</span>
                  {existing && (
                    <span className={`ml-auto text-[10px] ${
                      existing.decision === "adopted" ? "text-green-400" :
                      existing.decision === "deferred" ? "text-yellow-400" : "text-zinc-500"
                    }`}>
                      {existing.decision}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-zinc-400">{r.summary}</p>
                <p className="text-zinc-500">
                  confidence: {r.confidence} · effort: {r.migration_effort}
                </p>
                {!existing && (
                  <div className="mt-2 flex gap-1">
                    {pendingComponent === r.component ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400" />
                    ) : (
                      <>
                        <button
                          onClick={() => handleDecision(r.component, "adopted")}
                          className="flex items-center gap-1 rounded px-2 py-1 text-green-400 hover:bg-green-500/20"
                          title="Adopt — generate migration plan"
                        >
                          <Check className="h-3 w-3" /> Adopt
                        </button>
                        <button
                          onClick={() => handleDecision(r.component, "deferred")}
                          className="flex items-center gap-1 rounded px-2 py-1 text-yellow-400 hover:bg-yellow-500/20"
                          title="Defer — revisit later"
                        >
                          <Clock className="h-3 w-3" /> Defer
                        </button>
                        <button
                          onClick={() => handleDecision(r.component, "dismissed")}
                          className="rounded px-2 py-1 text-zinc-500 hover:bg-zinc-700"
                          title="Dismiss"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </DetailModal>
    </>
  );
}
```

**Step 5: Verify it builds**

Run: `cd ~/projects/hapax-logos && pnpm build 2>&1 | tail -5`
Expected: Build succeeds.

**Step 6: Commit**

```bash
cd ~/projects/hapax-logos
git add src/api/types.ts src/api/client.ts src/api/hooks.ts src/components/sidebar/ScoutPanel.tsx
git commit -m "feat: add scout decision workflow with adopt/defer/dismiss buttons"
```

---

### Task 7: Validate

**Step 1: Run ai-agents tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_scout_decisions.py -v`
Expected: 3 passed

**Step 2: Run hapax-logos build**

Run: `cd ~/projects/hapax-logos && pnpm build 2>&1 | tail -5`
Expected: Build succeeds, no TypeScript errors.

**Step 3: Manual validation checklist**

Start logos stack:
```bash
cd ~/projects/hapax-council && uv run python -m cockpit.api &
cd ~/projects/hapax-logos && pnpm dev &
```

Verify in browser at localhost:5173:
- [ ] Health panel: if any checks failed, "Auto-fix" button appears in detail modal
- [ ] Drift panel: "Fix drift" button appears when drift items exist
- [ ] Briefing panel: action items with commands show play button
- [ ] Nudge list: acting on a command-hint nudge navigates to agent grid
- [ ] Scout panel: recommendations show Adopt/Defer/Dismiss buttons
- [ ] Scout Adopt: records decision and navigates to research agent
- [ ] Agent grid: pre-filled modal opens with correct flags
- [ ] Cycle mode toggle: still works in header
