"""Audio-safety detectors for broadcast.

Real-time monitors that read the L-12 multitrack capture and emit
impingements + ntfy alerts when broadcast-unsafe audio routing is
detected. Read-only — never modifies the broadcast graph.

Per `docs/governance/evil-pet-broadcast-source-policy.md`.
"""
