# Cockpit Insight Section — Design Spec

## Goal

Add a new "Insight" section to the logos web dashboard for natural language system introspection queries. The first query agent is dev-story (development archaeology); the architecture supports adding future query agents (health, infrastructure, etc.) without frontend changes.

## Architecture

### Frontend (hapax-logos)

New top-level route `/insight` with three zones:

1. **QueryInput** — Natural language textarea. Submit sends `POST /api/query/run`. "auto-detect" badge indicates agent classification is automatic.
2. **QueryResultList** — Scrollable history of results. Each result is streamed markdown rendered with react-markdown. Mermaid fenced code blocks render as inline SVG diagrams via lazy-loaded mermaid.js.
3. **RefinementInput** — Appears after result completes. Sends `POST /api/query/refine` with prior result as context.

**New files:**

```
src/pages/InsightPage.tsx
src/components/insight/QueryInput.tsx
src/components/insight/QueryResult.tsx
src/components/insight/QueryResultList.tsx
src/components/insight/RefinementInput.tsx
src/components/insight/MermaidBlock.tsx
```

**Routing:** Add `<Route path="insight" element={<InsightPage />} />` to App.tsx. Add "Insight" NavLink to Header. Add `i` keyboard shortcut.

**Dependencies:** Add `mermaid` (lazy-loaded, ~2.8MB ESM, zero impact on other pages).

### Backend (logos API)

Three endpoints in a new `routes/query.py` router:

```
POST /api/query/run     { query: string }
POST /api/query/refine  { query: string, prior_result: string, agent_type: string }
GET  /api/query/agents  → [{ type, name, description }]
```

**SSE event types:**

| Event | Data | Purpose |
|-------|------|---------|
| `status` | `{ phase, agent }` | Classification result, query start |
| `text_delta` | `{ content }` | Incremental markdown |
| `done` | `{ tokens_in, tokens_out, agent_used, elapsed_ms }` | Completion metadata |
| `error` | `{ message }` | Failure |

**New files:**

```
logos/api/routes/query.py       — FastAPI route handlers + SSE streaming
cockpit/query_dispatch.py         — Agent registry, classification, dispatch
```

### Agent Registry

Simple dict mapping agent type strings to metadata + factory functions:

```python
QUERY_AGENTS = {
    "dev_story": {
        "name": "Development Archaeology",
        "description": "Query development history, sessions, commits, and patterns",
        "keywords": ["story", "development", "commit", "session", "feature", "arc"],
        "create": lambda: dev_story_query.create_agent(),
        "deps_factory": lambda: dev_story_query.QueryDeps(db_path=...),
    },
}
```

**Classification:** With one agent, always routes to dev_story. When more agents are added, classification uses keyword matching first (check if query terms overlap with agent keywords), falling back to a fast LLM call if ambiguous.

### Query Agent Enhancement

The existing `agents/dev_story/query.py` gets a system prompt addition instructing it to produce Mermaid diagrams in fenced code blocks for relationships, flows, timelines, and architecture. Max 15-20 nodes per diagram.

The `extract_full_output()` function (already exists) is used by the SSE handler to collect all text parts from the agent's interleaved tool-call responses.

## SSE Streaming Flow

1. Frontend sends `POST /api/query/run` with query string
2. Backend classifies query → selects agent
3. Emits `status` event: `{ phase: "classifying", agent: "dev_story" }`
4. Runs agent with `agent.run()` (not `run_stream` — agent interleaves text with tool calls)
5. Collects full output via `extract_full_output(result)`
6. Emits `text_delta` with full markdown content
7. Emits `done` with token counts and metadata

Note: The dev-story agent makes 30-50 tool calls internally and produces output across multiple intermediate text parts. The SSE handler runs the agent to completion, then streams the collected output. This is simpler than trying to stream intermediate parts (which mix narrative with in-progress reasoning).

## Refinement Flow

1. User types follow-up in RefinementInput
2. Frontend sends `POST /api/query/refine` with `{ query, prior_result, agent_type }`
3. Backend constructs augmented prompt: "Previously asked: {original}. Result: {prior_result summary}. Now: {refinement query}"
4. Dispatches to same agent type, streams result
5. Frontend appends new result below the previous one in QueryResultList

No persistent server-side session state. Context is passed forward in the request.

## Mermaid Rendering

1. react-markdown encounters `` ```mermaid `` fenced code block
2. Custom `code` component checks `className === 'language-mermaid'`
3. Renders `<MermaidBlock source={children} />` instead of `<pre><code>`
4. MermaidBlock is `React.lazy(() => import('./MermaidBlock'))`
5. On mount: `mermaid.initialize()` with Gruvbox dark theme variables, then `mermaid.render(id, source)` → SVG
6. Wrapper div with "Copy source" button and diagram label
7. Error fallback: if mermaid parse fails, show raw source in code block with warning

**Theme variables** for Gruvbox compatibility:

```javascript
{
  theme: 'dark',
  themeVariables: {
    primaryColor: '#3c3836',
    primaryTextColor: '#ebdbb2',
    primaryBorderColor: '#b8bb26',
    lineColor: '#665c54',
    secondaryColor: '#282828',
    tertiaryColor: '#504945',
  }
}
```

## Component Details

**InsightPage** — Top-level route component. Manages state:
- `results: Array<{ id, query, markdown, metadata, isStreaming }>`
- Wires QueryInput → SSE → result accumulation → QueryResult rendering
- On refinement, appends to results array

**QueryInput** — Textarea with auto-resize (max 200px), search icon, submit button. Enter to submit, Shift+Enter for newline. Disabled during streaming.

**QueryResult** — Renders single result: status bar (agent name, elapsed time, token count) + MarkdownContent with mermaid-aware code renderer. Uses existing `MarkdownContent` shared component with extended code block handling.

**QueryResultList** — Flex column of QueryResult components with dividers. Auto-scrolls to bottom on new result.

**RefinementInput** — Smaller input with refresh icon. Appears only after result completes. Visually distinct (muted border, smaller text).

**MermaidBlock** — Lazy-loaded. Manages mermaid instance lifecycle. Unique IDs per render. Re-renders on source change. Suspense fallback shows loading skeleton.

## Conventions

- All styling via Tailwind utility classes (matching hapax-logos patterns)
- TypeScript strict mode, no `any`
- React Query for `/agents` endpoint; SSE via existing `connectSSE()` pattern
- Lucide icons consistent with existing cockpit
- Feature-based folder: `src/components/insight/`
