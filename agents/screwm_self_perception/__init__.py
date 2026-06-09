"""Drift self-perception — drift's re-perceivable (``get``) surface in the Chiasm Contract.

Reads the per-zone drift currency the engine consumes and projects the realized field onto the 9
expressive dimensions, so the drift the CNS expresses can re-enter the recruitment loop as impingement
(closing the chiasm). Audit-only today; the gated loop-closure is spec PR-E. See
``docs/superpowers/specs/2026-06-07-cns-chiasm-contract-design.md``.
"""

from agents.screwm_self_perception.analyzer import DriftSelfPerception, analyze

__all__ = ["DriftSelfPerception", "analyze"]
