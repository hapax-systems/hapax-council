---
name: logos-review
description: Parallel Agent fan-out for Logos code quality review. Auto-run when: preparing a release, before a demo, after large refactors across Logos, or user asks for a code quality review. Invoke proactively without asking.
---

Full Logos code quality review using parallel Agent fan-out. Covers all three layers.

Launch 3 parallel Agent calls (subagent_type: Explore, thoroughness: very thorough):

**Agent 1 — API layer** (`logos/api/`, `logos/routes/`):
- Endpoint coverage and consistency
- Error handling and response schemas
- Input validation
- Performance concerns (N+1 queries, blocking calls)

**Agent 2 — Engine layer** (`logos/engine/`, `logos/rules/`):
- Rule correctness and phase ordering
- Error recovery and edge cases
- Reactive cascade behavior
- Resource cleanup

**Agent 3 — Frontend** (`hapax-logos/src/`):
- Component quality and prop interfaces
- Accessibility
- Performance (re-renders, bundle size)
- Design language compliance (check against `docs/logos-design-language.md`)

Synthesize into a go/no-go report with:
- Critical issues (must fix)
- Warnings (should fix)
- Observations (nice to fix)
- Overall quality assessment
