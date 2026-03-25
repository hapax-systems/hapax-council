---
id: DEVIATION-014
date: 2026-03-25
phase: baseline
paths:
  - agents/hapax_voice/conversation_pipeline.py
justification: |
  Adding 3 new VOLATILE band sections (goals, health, nudges) to the
  per-turn system context. These are in the VOLATILE band, which is
  already frozen under volatile_lockdown. The new sections follow the
  existing pattern (callback → try/except → string injection) and are
  automatically frozen when volatile_lockdown is active.
  No changes to experiment variables, grounding logic, acceptance
  scoring, or model routing.
risk: none — new sections are omitted under volatile_lockdown
approved_by: operator
---
