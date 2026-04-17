"""LRR Phase 8 item 8 — attention bids system.

Content-programming layer where subsystems (briefing, nudges, goals,
code-narration) submit bids for operator attention. The selector ranks
them against current stimmung state, active objectives, and stream-mode
constraints, and returns a single winner — or None, indicating no
bid cleared the bar.

Scope of this module: pure bidding + scoring primitives. Integration
with the bid-emitting subsystems is follow-up.
"""
