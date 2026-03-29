# Hapax Obsidian Plugin v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the v1 management chat sidebar with a context-first system companion that surfaces sprint state, stimmung, posterior tracking, and research context alongside whatever note the operator is viewing in the Personal vault.

**Architecture:** Two subsystems — (1) 7 new FastAPI endpoints on logos-api (:8051) serving sprint/stimmung/nudge data from /dev/shm and vault notes, (2) an Obsidian plugin with a ContextResolver that classifies the active note and renders a contextual sidebar from API data. Single API dependency, no LLM calls, no direct filesystem access from the plugin.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic (API), TypeScript / Obsidian API / esbuild (plugin)

---

## File Structure

### Logos API (Python)

- **Create:** `logos/api/routes/sprint.py` — 6 endpoints (4 GET, 2 POST) for sprint state, measures, gates, transitions, acknowledgments
- **Create:** `logos/api/routes/stimmung.py` — 1 GET endpoint reading /dev/shm/hapax-stimmung/state.json
- **Modify:** `logos/api/app.py:128-166` — Register 2 new routers
- **Create:** `tests/api/test_sprint_routes.py` — Tests for sprint endpoints
- **Create:** `tests/api/test_stimmung_route.py` — Tests for stimmung endpoint

### Obsidian Plugin (TypeScript)

- **Create:** `obsidian-hapax/package.json`
- **Create:** `obsidian-hapax/tsconfig.json`
- **Create:** `obsidian-hapax/esbuild.config.mjs`
- **Create:** `obsidian-hapax/manifest.json`
- **Create:** `obsidian-hapax/src/main.ts` — Plugin lifecycle, view + settings registration
- **Create:** `obsidian-hapax/src/context-resolver.ts` — NoteKind classification
- **Create:** `obsidian-hapax/src/logos-client.ts` — HTTP client with TTL cache
- **Create:** `obsidian-hapax/src/context-panel.ts` — ItemView sidebar rendering
- **Create:** `obsidian-hapax/src/sections.ts` — All section renderers
- **Create:** `obsidian-hapax/src/settings.ts` — PluginSettingTab
- **Create:** `obsidian-hapax/src/types.ts` — Shared interfaces
- **Create:** `obsidian-hapax/styles.css` — Status badges, stimmung dot, action buttons

---

**Plan is 12 tasks. See spec at `docs/superpowers/specs/2026-03-29-hapax-obsidian-v2-design.md` for full design context. Plugin source lives at `obsidian-hapax/` (new directory, sibling to docs/).**

**Tasks 1-5:** Logos API endpoints (Python/FastAPI)
**Tasks 6-11:** Obsidian plugin (TypeScript)
**Task 12:** Integration test
