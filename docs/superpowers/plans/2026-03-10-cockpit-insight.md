# Cockpit Insight Section Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new "Insight" section to the cockpit for natural language system introspection queries with markdown + Mermaid diagram rendering.

**Architecture:** Backend query dispatch router classifies natural language queries and routes to registered agents (initially dev-story). Agents produce markdown with mermaid fences. Frontend streams results via SSE and renders with react-markdown + lazy-loaded mermaid.js. Refinement passes prior context forward.

**Tech Stack:** FastAPI + sse-starlette (backend), React 19 + TypeScript + Tailwind + react-markdown + mermaid.js (frontend), pydantic-ai (query agents)

---

## Chunk 1: Backend — Query Dispatch & SSE Endpoint

### Task 1: Query Dispatch Module

**Files:**
- Create: `cockpit/query_dispatch.py`
- Test: `tests/test_query_dispatch.py`

This module manages the agent registry, query classification, and agent execution. It does NOT handle HTTP — that's the route handler's job.

- [ ] **Step 1: Write tests for the agent registry and classification**

```python
# tests/test_query_dispatch.py
"""Tests for query dispatch — agent registry and classification."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cockpit.query_dispatch import (
    QueryAgentInfo,
    classify_query,
    get_agent_list,
    run_query,
)


class TestClassifyQuery:
    def test_single_agent_always_matches(self):
        """With only one registered agent, every query routes to it."""
        result = classify_query("tell me about the weather")
        assert result == "dev_story"

    def test_dev_story_keywords_match(self):
        """Queries mentioning development terms route to dev_story."""
        result = classify_query("show me commit history for voice pipeline")
        assert result == "dev_story"

    def test_empty_query_returns_default(self):
        result = classify_query("")
        assert result == "dev_story"


class TestGetAgentList:
    def test_returns_registered_agents(self):
        agents = get_agent_list()
        assert len(agents) >= 1
        assert agents[0].agent_type == "dev_story"
        assert agents[0].name == "Development Archaeology"
        assert agents[0].description != ""


class TestRunQuery:
    @patch("cockpit.query_dispatch._create_dev_story_agent")
    async def test_run_query_returns_markdown(self, mock_create):
        mock_result = MagicMock()
        mock_result.usage.return_value = MagicMock(
            input_tokens=1000, output_tokens=500
        )
        # Mock extract_full_output
        with patch("cockpit.query_dispatch.extract_full_output", return_value="## Test\nHello"):
            mock_agent = AsyncMock()
            mock_agent.run.return_value = mock_result
            mock_create.return_value = (mock_agent, MagicMock())

            result = await run_query("dev_story", "tell me about features")

        assert result.markdown == "## Test\nHello"
        assert result.agent_type == "dev_story"
        assert result.tokens_in == 1000
        assert result.tokens_out == 500

    async def test_run_query_unknown_agent_raises(self):
        with pytest.raises(ValueError, match="Unknown query agent"):
            await run_query("nonexistent", "hello")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_query_dispatch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cockpit.query_dispatch'`

- [ ] **Step 3: Implement query_dispatch.py**

```python
# cockpit/query_dispatch.py
"""Query dispatch — agent registry, classification, and execution."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from agents.dev_story.query import QueryDeps, create_agent, extract_full_output
from shared.config import PROFILES_DIR

log = logging.getLogger(__name__)


@dataclass
class QueryAgentInfo:
    """Public metadata about a registered query agent."""
    agent_type: str
    name: str
    description: str


@dataclass
class QueryResult:
    """Result of running a query agent."""
    markdown: str
    agent_type: str
    tokens_in: int
    tokens_out: int
    elapsed_ms: int


# ── Agent Registry ───────────────────────────────────────────────────────────

_AGENTS: dict[str, dict] = {
    "dev_story": {
        "name": "Development Archaeology",
        "description": "Query development history, sessions, commits, and patterns",
        "keywords": [
            "story", "development", "commit", "session", "feature", "arc",
            "history", "git", "churn", "token", "pattern", "code",
        ],
    },
}


def get_agent_list() -> list[QueryAgentInfo]:
    """Return metadata for all registered query agents."""
    return [
        QueryAgentInfo(agent_type=k, name=v["name"], description=v["description"])
        for k, v in _AGENTS.items()
    ]


def classify_query(query: str) -> str:
    """Classify a natural language query to select the best agent.

    With one agent registered, always returns that agent.
    When more are added, uses keyword overlap scoring with fallback
    to the agent with the broadest keyword set.
    """
    if len(_AGENTS) == 1:
        return next(iter(_AGENTS))

    query_lower = query.lower()
    best_agent = next(iter(_AGENTS))
    best_score = 0

    for agent_type, info in _AGENTS.items():
        score = sum(1 for kw in info["keywords"] if kw in query_lower)
        if score > best_score:
            best_score = score
            best_agent = agent_type

    return best_agent


# ── Agent Factories ──────────────────────────────────────────────────────────

def _create_dev_story_agent():
    """Create the dev-story query agent and its deps."""
    db_path = str(PROFILES_DIR / "dev_story.db")
    agent = create_agent()
    deps = QueryDeps(db_path=db_path)
    return agent, deps


_AGENT_FACTORIES = {
    "dev_story": _create_dev_story_agent,
}


async def run_query(agent_type: str, query: str, prior_context: str | None = None) -> QueryResult:
    """Run a query against the specified agent and return the result."""
    if agent_type not in _AGENT_FACTORIES:
        raise ValueError(f"Unknown query agent: {agent_type}")

    factory = _AGENT_FACTORIES[agent_type]
    agent, deps = factory()

    prompt = query
    if prior_context:
        prompt = (
            f"The user previously received this result:\n\n"
            f"---\n{prior_context[:4000]}\n---\n\n"
            f"Now they ask: {query}\n\n"
            f"Answer in the context of the prior result."
        )

    start = time.monotonic()
    result = await agent.run(prompt, deps=deps)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    markdown = extract_full_output(result)
    usage = result.usage()

    return QueryResult(
        markdown=markdown,
        agent_type=agent_type,
        tokens_in=usage.input_tokens,
        tokens_out=usage.output_tokens,
        elapsed_ms=elapsed_ms,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_query_dispatch.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add cockpit/query_dispatch.py tests/test_query_dispatch.py
git commit -m "feat: query dispatch module — agent registry, classification, execution"
```

---

### Task 2: Query API Route with SSE Streaming

**Files:**
- Create: `cockpit/api/routes/query.py`
- Modify: `cockpit/api/app.py:44-64` (add router import + include)
- Test: `tests/test_query_api.py`

- [ ] **Step 1: Write tests for the query API endpoints**

```python
# tests/test_query_api.py
"""Tests for query API route — SSE streaming, refinement, agent listing."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from cockpit.query_dispatch import QueryAgentInfo, QueryResult


@pytest.fixture
async def client():
    from cockpit.api.app import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestQueryAgentsList:
    @patch("cockpit.api.routes.query.get_agent_list")
    async def test_list_agents(self, mock_list, client):
        mock_list.return_value = [
            QueryAgentInfo(
                agent_type="dev_story",
                name="Development Archaeology",
                description="Query development history",
            )
        ]
        resp = await client.get("/api/query/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["agent_type"] == "dev_story"


class TestQueryRun:
    @patch("cockpit.api.routes.query.run_query")
    @patch("cockpit.api.routes.query.classify_query")
    async def test_run_returns_sse_stream(self, mock_classify, mock_run, client):
        mock_classify.return_value = "dev_story"
        mock_run.return_value = QueryResult(
            markdown="## Hello\nWorld",
            agent_type="dev_story",
            tokens_in=100,
            tokens_out=50,
            elapsed_ms=1234,
        )
        resp = await client.post(
            "/api/query/run",
            json={"query": "tell me the story"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    @patch("cockpit.api.routes.query.run_query")
    @patch("cockpit.api.routes.query.classify_query")
    async def test_run_empty_query_rejected(self, mock_classify, mock_run, client):
        resp = await client.post("/api/query/run", json={"query": ""})
        assert resp.status_code == 422 or resp.status_code == 400


class TestQueryRefine:
    @patch("cockpit.api.routes.query.run_query")
    async def test_refine_passes_context(self, mock_run, client):
        mock_run.return_value = QueryResult(
            markdown="## Refined\nResult",
            agent_type="dev_story",
            tokens_in=200,
            tokens_out=100,
            elapsed_ms=2000,
        )
        resp = await client.post(
            "/api/query/refine",
            json={
                "query": "zoom into voice pipeline",
                "prior_result": "## Previous result...",
                "agent_type": "dev_story",
            },
        )
        assert resp.status_code == 200
        # Verify prior_context was passed
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[1]["prior_context"] is not None or (
            len(call_args[0]) >= 3 and call_args[0][2] is not None
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_query_api.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Implement the query route**

```python
# cockpit/api/routes/query.py
"""Query endpoints — natural language system introspection with SSE streaming."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from sse_starlette.sse import EventSourceResponse

from cockpit.query_dispatch import classify_query, get_agent_list, run_query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/query", tags=["query"])


class QueryRunRequest(BaseModel):
    query: str

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Query must not be empty")
        return v.strip()


class QueryRefineRequest(BaseModel):
    query: str
    prior_result: str
    agent_type: str

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Query must not be empty")
        return v.strip()


@router.get("/agents")
async def list_query_agents():
    """List available query agent types."""
    agents = get_agent_list()
    return [
        {
            "agent_type": a.agent_type,
            "name": a.name,
            "description": a.description,
        }
        for a in agents
    ]


@router.post("/run")
async def run_query_endpoint(req: QueryRunRequest):
    """Run a natural language query with auto-classification.

    Returns an SSE stream with events: status, text_delta, done, error.
    """
    async def event_generator():
        try:
            agent_type = classify_query(req.query)
            yield {
                "event": "status",
                "data": json.dumps({"phase": "querying", "agent": agent_type}),
            }

            result = await run_query(agent_type, req.query)

            yield {
                "event": "text_delta",
                "data": json.dumps({"content": result.markdown}),
            }
            yield {
                "event": "done",
                "data": json.dumps({
                    "agent_used": result.agent_type,
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "elapsed_ms": result.elapsed_ms,
                }),
            }
        except Exception as e:
            log.exception("Query failed")
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}),
            }

    return EventSourceResponse(event_generator())


@router.post("/refine")
async def refine_query_endpoint(req: QueryRefineRequest):
    """Refine a prior query result with follow-up context.

    Returns an SSE stream with the same events as /run.
    """
    if req.agent_type not in {a.agent_type for a in get_agent_list()}:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {req.agent_type}")

    async def event_generator():
        try:
            yield {
                "event": "status",
                "data": json.dumps({"phase": "querying", "agent": req.agent_type}),
            }

            result = await run_query(
                req.agent_type,
                req.query,
                prior_context=req.prior_result,
            )

            yield {
                "event": "text_delta",
                "data": json.dumps({"content": result.markdown}),
            }
            yield {
                "event": "done",
                "data": json.dumps({
                    "agent_used": result.agent_type,
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "elapsed_ms": result.elapsed_ms,
                }),
            }
        except Exception as e:
            log.exception("Refine query failed")
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}),
            }

    return EventSourceResponse(event_generator())
```

- [ ] **Step 4: Register the router in app.py**

Add to `cockpit/api/app.py` after line 53 (the scout import):

```python
from cockpit.api.routes.query import router as query_router
```

Add after line 64 (the scout include):

```python
app.include_router(query_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_query_api.py tests/test_query_dispatch.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add cockpit/api/routes/query.py cockpit/api/app.py tests/test_query_api.py
git commit -m "feat: query API route — SSE streaming for natural language queries"
```

---

### Task 3: Add Mermaid Diagram Instructions to Dev-Story Agent

**Files:**
- Modify: `agents/dev_story/query.py:17-84` (system prompt)
- Test: `tests/dev_story/test_query_prompt.py` (new test file for prompt content)

- [ ] **Step 1: Write test that the system prompt mentions mermaid**

```python
# tests/dev_story/test_query_prompt.py
"""Tests for dev-story query agent prompt content."""
from __future__ import annotations

from agents.dev_story.query import build_system_prompt


def test_prompt_includes_mermaid_instructions():
    prompt = build_system_prompt()
    assert "mermaid" in prompt.lower()
    assert "```mermaid" in prompt


def test_prompt_includes_diagram_guidance():
    prompt = build_system_prompt()
    assert "graph" in prompt.lower() or "flowchart" in prompt.lower()
    assert "gantt" in prompt.lower() or "timeline" in prompt.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council && uv run pytest tests/dev_story/test_query_prompt.py -v`
Expected: FAIL — "mermaid" not in prompt

- [ ] **Step 3: Add mermaid section to the system prompt**

In `agents/dev_story/query.py`, add this section before the closing `"""` of `build_system_prompt()`, after the "Evidence standards" section:

```python
## Diagram generation
When your answer involves relationships, flows, timelines, or architecture,
include Mermaid diagrams using fenced code blocks:

    ```mermaid
    graph TD
      A[SharedConfig] --> B[HealthMonitor]
      A --> C[Profiler]
    ```

Useful diagram types:
- Feature dependency flows: graph TD (top-down directed)
- Architecture relationships: graph LR (left-right)
- Development timelines: gantt
- Session/commit correlations: flowchart

Keep diagrams focused — max 15-20 nodes. Split complex relationships into
multiple smaller diagrams rather than one massive graph. Use descriptive
node labels, not abbreviations.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/hapax-council && uv run pytest tests/dev_story/test_query_prompt.py tests/dev_story/ -v`
Expected: All tests PASS (new tests + existing 85 tests)

- [ ] **Step 5: Commit**

```bash
git add agents/dev_story/query.py tests/dev_story/test_query_prompt.py
git commit -m "feat: add mermaid diagram instructions to dev-story query prompt"
```

---

## Chunk 2: Frontend — Insight Page & Mermaid Rendering

### Task 4: MermaidBlock Component (Lazy-Loaded)

**Files:**
- Create: `cockpit-web/src/components/insight/MermaidBlock.tsx`

This is the foundation — the diagram renderer. Build it first so other components can use it.

- [ ] **Step 1: Install mermaid dependency**

```bash
cd ~/projects/cockpit-web && pnpm add mermaid dompurify && pnpm add -D @types/dompurify
```

- [ ] **Step 2: Create MermaidBlock component**

```typescript
// src/components/insight/MermaidBlock.tsx
import { useEffect, useRef, useState } from "react";
import DOMPurify from "dompurify";
import { Copy, AlertTriangle } from "lucide-react";

let mermaidInstance: typeof import("mermaid") | null = null;
let initPromise: Promise<void> | null = null;
let renderCounter = 0;

async function getMermaid() {
  if (mermaidInstance) return mermaidInstance;
  if (!initPromise) {
    initPromise = (async () => {
      const m = await import("mermaid");
      m.default.initialize({
        startOnLoad: false,
        theme: "dark",
        themeVariables: {
          primaryColor: "#3c3836",
          primaryTextColor: "#ebdbb2",
          primaryBorderColor: "#b8bb26",
          lineColor: "#665c54",
          secondaryColor: "#282828",
          tertiaryColor: "#504945",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: "12px",
        },
      });
      mermaidInstance = m;
    })();
  }
  await initPromise;
  return mermaidInstance!;
}

interface MermaidBlockProps {
  source: string;
}

export function MermaidBlock({ source }: MermaidBlockProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const id = `mermaid-${++renderCounter}`;

    (async () => {
      try {
        const mermaid = await getMermaid();
        const { svg } = await mermaid.default.render(id, source.trim());
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();

    return () => { cancelled = true; };
  }, [source]);

  const handleCopy = () => {
    navigator.clipboard.writeText(source.trim());
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (error) {
    return (
      <div className="my-3 rounded-lg border border-yellow-800 bg-yellow-950/30 p-4">
        <div className="mb-2 flex items-center gap-2 text-xs text-yellow-500">
          <AlertTriangle className="h-3.5 w-3.5" />
          <span>Diagram parse error</span>
        </div>
        <pre className="overflow-x-auto text-xs text-zinc-400">{source.trim()}</pre>
      </div>
    );
  }

  return (
    <div className="my-3 rounded-lg border border-zinc-700 bg-zinc-800 p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider text-zinc-500">
          Diagram
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 rounded border border-zinc-700 px-2 py-0.5 text-[10px] text-zinc-500 hover:bg-zinc-700 hover:text-zinc-300"
        >
          <Copy className="h-3 w-3" />
          {copied ? "Copied" : "Copy source"}
        </button>
      </div>
      <div ref={containerRef} className="flex justify-center [&>svg]:max-w-full" />
    </div>
  );
}
```

- [ ] **Step 3: Verify it builds**

```bash
cd ~/projects/cockpit-web && pnpm build
```
Expected: Build succeeds (component is tree-shaken unless imported)

- [ ] **Step 4: Commit**

```bash
cd ~/projects/cockpit-web
git add src/components/insight/MermaidBlock.tsx package.json pnpm-lock.yaml
git commit -m "feat: MermaidBlock component — lazy-loaded diagram renderer"
```

---

### Task 5: Insight Page Components

**Files:**
- Create: `cockpit-web/src/pages/InsightPage.tsx`
- Create: `cockpit-web/src/components/insight/QueryInput.tsx`
- Create: `cockpit-web/src/components/insight/QueryResult.tsx`
- Create: `cockpit-web/src/components/insight/QueryResultList.tsx`
- Create: `cockpit-web/src/components/insight/RefinementInput.tsx`

- [ ] **Step 1: Create QueryInput component**

```typescript
// src/components/insight/QueryInput.tsx
import { useState, useRef, useEffect } from "react";
import { Search, ArrowRight, Loader2 } from "lucide-react";

interface QueryInputProps {
  onSubmit: (query: string) => void;
  isLoading: boolean;
  placeholder?: string;
}

export function QueryInput({ onSubmit, isLoading, placeholder }: QueryInputProps) {
  const [query, setQuery] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!isLoading && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [isLoading]);

  const handleSubmit = () => {
    const trimmed = query.trim();
    if (!trimmed || isLoading) return;
    onSubmit(trimmed);
    setQuery("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex items-start gap-3 rounded-lg border border-zinc-700 bg-zinc-800 p-3">
      <Search className="mt-1 h-4 w-4 shrink-0 text-zinc-500" />
      <textarea
        ref={textareaRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder ?? "Ask about development history, system patterns, architecture..."}
        disabled={isLoading}
        rows={1}
        className="flex-1 resize-none bg-transparent text-sm text-zinc-200 placeholder-zinc-500 outline-none disabled:opacity-50"
        style={{ maxHeight: "120px" }}
      />
      <button
        onClick={handleSubmit}
        disabled={!query.trim() || isLoading}
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-green-700 text-zinc-100 transition-colors hover:bg-green-600 disabled:bg-zinc-700 disabled:text-zinc-500"
      >
        {isLoading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <ArrowRight className="h-3.5 w-3.5" />
        )}
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Create QueryResult component**

```typescript
// src/components/insight/QueryResult.tsx
import { lazy, Suspense } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Clock, Cpu, Loader2 } from "lucide-react";

const MermaidBlock = lazy(() =>
  import("./MermaidBlock").then((m) => ({ default: m.MermaidBlock }))
);

interface QueryResultProps {
  query: string;
  markdown: string;
  isStreaming: boolean;
  metadata?: {
    agent_used: string;
    tokens_in: number;
    tokens_out: number;
    elapsed_ms: number;
  };
}

export function QueryResult({ query, markdown, isStreaming, metadata }: QueryResultProps) {
  return (
    <div className="space-y-3">
      {/* Query echo */}
      <div className="flex items-start gap-2 text-sm">
        <span className="mt-0.5 shrink-0 text-zinc-500">Q:</span>
        <span className="text-zinc-300">{query}</span>
      </div>

      {/* Status bar */}
      <div className="flex items-center gap-2 rounded-md bg-zinc-800/50 px-3 py-1.5 text-[11px]">
        {isStreaming ? (
          <>
            <Loader2 className="h-3 w-3 animate-spin text-green-400" />
            <span className="text-green-400">Querying...</span>
          </>
        ) : metadata ? (
          <>
            <Cpu className="h-3 w-3 text-zinc-500" />
            <span className="text-zinc-400">{metadata.agent_used}</span>
            <span className="text-zinc-600">·</span>
            <Clock className="h-3 w-3 text-zinc-500" />
            <span className="text-zinc-400">{(metadata.elapsed_ms / 1000).toFixed(1)}s</span>
            <span className="text-zinc-600">·</span>
            <span className="text-zinc-500">
              {((metadata.tokens_in + metadata.tokens_out) / 1000).toFixed(0)}k tokens
            </span>
          </>
        ) : null}
      </div>

      {/* Markdown content */}
      {markdown && (
        <div className="max-w-none space-y-3">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code: ({ children, className, ...props }) => {
                if (className === "language-mermaid") {
                  return (
                    <Suspense
                      fallback={
                        <div className="my-3 flex items-center justify-center rounded-lg border border-zinc-700 bg-zinc-800 p-8">
                          <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
                        </div>
                      }
                    >
                      <MermaidBlock source={String(children)} />
                    </Suspense>
                  );
                }
                const isInline = !className;
                return isInline ? (
                  <code className="rounded bg-zinc-800 px-1 py-0.5 text-xs text-zinc-300" {...props}>
                    {children}
                  </code>
                ) : (
                  <code className={`${className ?? ""} text-xs`} {...props}>
                    {children}
                  </code>
                );
              },
              pre: ({ children }) => (
                <pre className="overflow-x-auto rounded bg-zinc-800 p-3 text-xs">{children}</pre>
              ),
              table: ({ children }) => (
                <table className="w-full border-collapse text-xs">{children}</table>
              ),
              th: ({ children }) => (
                <th className="border border-zinc-700 bg-zinc-800 px-2 py-1 text-left font-medium text-zinc-300">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="border border-zinc-700 px-2 py-1 text-zinc-400">{children}</td>
              ),
              a: ({ children, href }) => (
                <a href={href} className="text-blue-400 hover:text-blue-300 no-underline" target="_blank" rel="noopener noreferrer">
                  {children}
                </a>
              ),
              h1: ({ children }) => <h1 className="text-lg font-bold text-zinc-200">{children}</h1>,
              h2: ({ children }) => {
                const id = String(children).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
                return <h2 id={id} className="text-base font-semibold text-zinc-200 scroll-mt-4">{children}</h2>;
              },
              h3: ({ children }) => {
                const id = String(children).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
                return <h3 id={id} className="text-sm font-semibold text-zinc-300 scroll-mt-4">{children}</h3>;
              },
              p: ({ children }) => <p className="text-zinc-400 leading-relaxed">{children}</p>,
              ul: ({ children }) => <ul className="list-disc pl-5 space-y-1">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal pl-5 space-y-1">{children}</ol>,
              li: ({ children }) => <li className="text-zinc-400">{children}</li>,
              blockquote: ({ children }) => (
                <blockquote className="border-l-2 border-green-700 pl-3 text-zinc-400 italic bg-green-950/20 rounded-r py-1">
                  {children}
                </blockquote>
              ),
            }}
          >
            {markdown}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create RefinementInput component**

```typescript
// src/components/insight/RefinementInput.tsx
import { useState, useRef, useEffect } from "react";
import { RotateCcw, ArrowRight, Loader2 } from "lucide-react";

interface RefinementInputProps {
  onSubmit: (query: string) => void;
  isLoading: boolean;
}

export function RefinementInput({ onSubmit, isLoading }: RefinementInputProps) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isLoading && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isLoading]);

  const handleSubmit = () => {
    const trimmed = query.trim();
    if (!trimmed || isLoading) return;
    onSubmit(trimmed);
    setQuery("");
  };

  return (
    <div className="mt-4 flex items-center gap-2 border-t border-zinc-800 pt-4">
      <RotateCcw className="h-3.5 w-3.5 shrink-0 text-zinc-600" />
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
        placeholder="Refine: zoom in, change perspective, show as diagram..."
        disabled={isLoading}
        className="flex-1 bg-transparent text-xs text-zinc-300 placeholder-zinc-600 outline-none disabled:opacity-50"
      />
      <button
        onClick={handleSubmit}
        disabled={!query.trim() || isLoading}
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-zinc-700 text-zinc-400 hover:bg-zinc-600 hover:text-zinc-200 disabled:opacity-30"
      >
        {isLoading ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <ArrowRight className="h-3 w-3" />
        )}
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Create QueryResultList component**

```typescript
// src/components/insight/QueryResultList.tsx
import { useRef, useEffect } from "react";
import { QueryResult } from "./QueryResult";

export interface ResultEntry {
  id: string;
  query: string;
  markdown: string;
  isStreaming: boolean;
  metadata?: {
    agent_used: string;
    tokens_in: number;
    tokens_out: number;
    elapsed_ms: number;
  };
}

interface QueryResultListProps {
  results: ResultEntry[];
}

export function QueryResultList({ results }: QueryResultListProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [results.length]);

  if (results.length === 0) return null;

  return (
    <div className="space-y-6">
      {results.map((r, i) => (
        <div key={r.id}>
          {i > 0 && <div className="mb-6 border-t border-zinc-800" />}
          <QueryResult
            query={r.query}
            markdown={r.markdown}
            isStreaming={r.isStreaming}
            metadata={r.metadata}
          />
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
```

- [ ] **Step 5: Create InsightPage**

```typescript
// src/pages/InsightPage.tsx
import { useState, useCallback, useRef } from "react";
import { QueryInput } from "../components/insight/QueryInput";
import { QueryResultList, type ResultEntry } from "../components/insight/QueryResultList";
import { RefinementInput } from "../components/insight/RefinementInput";
import { connectSSE } from "../api/sse";
import { sseUrl } from "../api/client";
import { Sparkles } from "lucide-react";

export function InsightPage() {
  const [results, setResults] = useState<ResultEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  const runQuery = useCallback(
    (query: string, refine?: { prior_result: string; agent_type: string }) => {
      setIsLoading(true);

      const id = `q-${Date.now()}`;
      const entry: ResultEntry = {
        id,
        query,
        markdown: "",
        isStreaming: true,
      };

      setResults((prev) => [...prev, entry]);

      const url = refine ? sseUrl("/query/refine") : sseUrl("/query/run");
      const body = refine
        ? { query, prior_result: refine.prior_result, agent_type: refine.agent_type }
        : { query };

      controllerRef.current = connectSSE(url, {
        body,
        onEvent: (event) => {
          try {
            const data = JSON.parse(event.data);

            if (event.event === "text_delta") {
              setResults((prev) =>
                prev.map((r) =>
                  r.id === id ? { ...r, markdown: r.markdown + data.content } : r,
                ),
              );
            } else if (event.event === "done") {
              setResults((prev) =>
                prev.map((r) =>
                  r.id === id
                    ? { ...r, isStreaming: false, metadata: data }
                    : r,
                ),
              );
              setIsLoading(false);
            } else if (event.event === "error") {
              setResults((prev) =>
                prev.map((r) =>
                  r.id === id
                    ? {
                        ...r,
                        isStreaming: false,
                        markdown: r.markdown + `\n\n> **Error:** ${data.message}`,
                      }
                    : r,
                ),
              );
              setIsLoading(false);
            }
          } catch {
            // Ignore malformed events
          }
        },
        onDone: () => setIsLoading(false),
        onError: (err) => {
          setResults((prev) =>
            prev.map((r) =>
              r.id === id
                ? { ...r, isStreaming: false, markdown: `> **Error:** ${err.message}` }
                : r,
            ),
          );
          setIsLoading(false);
        },
      });
    },
    [],
  );

  const handleQuery = useCallback(
    (query: string) => runQuery(query),
    [runQuery],
  );

  const handleRefine = useCallback(
    (query: string) => {
      const lastDone = [...results].reverse().find((r) => !r.isStreaming && r.metadata);
      if (!lastDone) return;
      runQuery(query, {
        prior_result: lastDone.markdown,
        agent_type: lastDone.metadata!.agent_used,
      });
    },
    [results, runQuery],
  );

  const lastResult = results[results.length - 1];
  const showRefinement = lastResult && !lastResult.isStreaming && lastResult.metadata;

  return (
    <div className="flex flex-1 flex-col">
      <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-6">
        <QueryInput onSubmit={handleQuery} isLoading={isLoading} />

        {results.length === 0 && !isLoading && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-zinc-600">
            <Sparkles className="h-8 w-8" />
            <p className="text-sm">Ask about development history, system patterns, or architecture</p>
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          <QueryResultList results={results} />
          {showRefinement && (
            <RefinementInput onSubmit={handleRefine} isLoading={isLoading} />
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Verify it builds**

```bash
cd ~/projects/cockpit-web && pnpm build
```
Expected: Build succeeds

- [ ] **Step 7: Commit**

```bash
cd ~/projects/cockpit-web
git add src/pages/InsightPage.tsx src/components/insight/
git commit -m "feat: Insight page — query input, result list, refinement, mermaid rendering"
```

---

### Task 6: Wire Into App Shell (Routing, Nav, Keyboard)

**Files:**
- Modify: `cockpit-web/src/App.tsx:1-19`
- Modify: `cockpit-web/src/components/Header.tsx:39-49`
- Modify: `cockpit-web/src/hooks/useKeyboardShortcuts.ts:25-41`

- [ ] **Step 1: Add route to App.tsx**

In `src/App.tsx`, add import at top:
```typescript
import { InsightPage } from "./pages/InsightPage";
```

Add route after the chat route (after line 13):
```typescript
          <Route path="insight" element={<InsightPage />} />
```

- [ ] **Step 2: Add nav link to Header.tsx**

In `src/components/Header.tsx`, add after the Chat NavLink (after line 44):
```typescript
          <NavLink to="/insight" className={navLinkClass}>
            Insight
          </NavLink>
```

- [ ] **Step 3: Add keyboard shortcut**

In `src/hooks/useKeyboardShortcuts.ts`, add case after `"d"` (after line 37):
```typescript
        case "i":
          e.preventDefault();
          navigate("/insight");
          break;
```

- [ ] **Step 4: Build and verify**

```bash
cd ~/projects/cockpit-web && pnpm build
```
Expected: Build succeeds

- [ ] **Step 5: Manual smoke test**

Start both services and verify:
```bash
# Terminal 1: Backend
cd ~/projects/hapax-council && docker compose up -d cockpit-api

# Terminal 2: Frontend
cd ~/projects/cockpit-web && pnpm dev
```

Open `http://localhost:5173/insight`. Verify:
1. Page loads with query input and empty state
2. "Insight" nav link is active
3. Press `i` from dashboard → navigates to insight
4. Type a query and submit → SSE streams, result renders
5. Mermaid diagrams (if present) render as SVG
6. Refinement input appears after result completes

- [ ] **Step 6: Commit**

```bash
cd ~/projects/cockpit-web
git add src/App.tsx src/components/Header.tsx src/hooks/useKeyboardShortcuts.ts
git commit -m "feat: wire Insight page into app shell — routing, nav, keyboard shortcut"
```
