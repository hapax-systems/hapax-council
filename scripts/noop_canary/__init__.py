"""noop_canary — FIXING-CORRECT-CODE no-op canary machinery.

Taxonomy watch-list #2 probe (llm-agent-failure-taxonomy-2026-06-11 §5;
failure-ledger-sdlc-feedback-2026-06-11 "NO-OP CANARY (v3)"): a periodic
decoy cc-task whose target code is healthy and whose correct outcome is a
no-change verdict with justification. Any diff is a FIXING-CORRECT-CODE
ledger event; canary rot reads probe-error, never green.

SI canary doctrine: the minted note travels the SAME offer/claim/dispatch
path as every other cc-task — no special-case code in the dispatch plane
(regression-pinned by tests/scripts/test_noop_canary_no_special_case.py).
"""
