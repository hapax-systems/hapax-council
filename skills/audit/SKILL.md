---
name: audit
description: Parallel Agent fan-out for deep subsystem research. Use when investigating an unfamiliar subsystem, debugging cross-cutting concerns, or user asks for a deep audit. Takes subsystem name as argument (e.g., /audit reactive-engine, /audit profiler, /audit voice). Manual invocation only — too open-ended for auto-trigger.
---

Deep audit of a Logos subsystem using parallel Agent fan-out. Argument: subsystem name.

**Known subsystem mappings:**

| Argument | Paths to explore |
|----------|-----------------|
| `voice` or `hapax-voice` | `agents/hapax_voice/`, `shared/voice*.py` |
| `reactive-engine` or `engine` | `logos/engine/`, `logos/rules/` |
| `api` or `logos-api` | `logos/api/`, `logos/routes/` |
| `profiler` or `profile` | `agents/profiler/`, `profiles/`, `shared/dimensions.py` |
| `axioms` or `governance` | `axioms/`, `shared/axiom_*.py`, `shared/consent.py` |
| `visual` or `perception` | `agents/visual_*/`, `shared/perception*.py` |
| `frontend` or `logos-ui` | `hapax-logos/src/` |
| `agents` | `agents/*/`, `shared/agent_registry.py` |

For the given subsystem:

1. Launch 2-3 parallel Agent calls (subagent_type: Explore), each focused on a different facet:
   - **Agent 1:** Code structure, module boundaries, and dependencies
   - **Agent 2:** Test coverage, edge cases, and error handling
   - **Agent 3:** Integration points with other subsystems

2. Synthesize findings into a structured report:
   - Architecture overview
   - Quality assessment (test coverage, error handling, code smells)
   - Integration risks
   - Recommended improvements (prioritized)
