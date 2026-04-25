"""Operator review + whitelist CLI for monetization-flagged payloads.

Tier-3 deterministic agent (no LLM). Plan §Phase 10 of
``docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md``.

Surfaces blocks emitted by ``MonetizationRiskGate`` so the operator can
accept (acknowledge), reject (confirm block), or whitelist (add to the
narrow-Ring-2 allowlist). Whitelist NEVER bypasses Ring 1 high-risk —
that invariant is pinned in tests.
"""
