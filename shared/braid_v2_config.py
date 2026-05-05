"""Braid v2.0 default constants.

Per ``docs/superpowers/specs/2026-05-04-braid-v2-and-wsjf-expansion-design.md`` §3.

Operator-tunable. Defaults reproduce the design's central calibration
(ρ = -2.0 between Leontief and Cobb-Douglas, β = 1.3 superlinear polysemic
per Birkhoff-Bense / Barabási preferential-attachment empirical bounds).

Three CES limit cases are reachable from this module:
- ``BRAID_V2_RHO = float("-inf")`` reproduces ``min`` (Leontief, perfect complements)
- ``BRAID_V2_RHO = 0.0`` reproduces Cobb-Douglas (geometric mean)
- ``BRAID_V2_RHO = 1.0`` reproduces weighted average (perfect substitutes)

Backward-compatibility invariant: setting ρ = 1, β = 1.0,
``witness_freshness = 1.0`` on a vector with no axiomatic_strain and no
forcing-zero gate yields a score that differs from v1.1 only in the
rebalanced E/M/R weights and the multiplicative C/10 form (vs.
v1.1's additive +0.10·C). Per-task drift is tolerated via the existing
``BRAID_V1_STABILITY_CARVEOUT`` mechanism on a future v1.1 → v2.0
migration pass.
"""

from __future__ import annotations

# CES substitution-elasticity. Spec §3.2 default.
BRAID_V2_RHO: float = -2.0

# Polysemic compounding exponent. Spec §3.3 default. β = 1.0 reproduces v1.1 linear.
BRAID_V2_BETA: float = 1.3

# CES core weights for E, M, R. Sum to 1.0. Spec §3.2 v1.1 grounding-favored balance.
BRAID_V2_W_ENGAGEMENT: float = 0.40
BRAID_V2_W_MONETARY: float = 0.30
BRAID_V2_W_RESEARCH: float = 0.30

# Additive bonus weights. Spec §3.3 — preserves v1.1 base proportions.
BRAID_V2_W_TREE_EFFECT: float = 0.20
BRAID_V2_W_UNBLOCK: float = 0.10
BRAID_V2_W_POLYSEMIC: float = 0.10
BRAID_V2_W_FORCING: float = 0.05

# Mode-ceiling priority order. Spec §2.6.
# Lower index = stronger ceiling (more restrictive / private).
BRAID_V2_MODE_CEILING_ORDER: tuple[str, ...] = (
    "private",
    "dry_run",
    "public_archive",
    "public_live",
    "public_monetizable",
)

# max_public_claim ladder. Spec §2.6 — same ordering semantics.
BRAID_V2_MAX_PUBLIC_CLAIM_ORDER: tuple[str, ...] = (
    "none",
    "research-only",
    "public-archive",
    "public-live",
    "monetized",
)

# Strain hard-cut threshold. Spec §3.1 — strain >= 3 short-circuits to None.
BRAID_V2_STRAIN_GATE_THRESHOLD: float = 3.0

# Forcing-urgency hard-cut threshold. Spec §3.1 — deadline within 30 days
# (urgency 10) gates the score with cause "forcing_zero_deadline".
BRAID_V2_FORCING_GATE_THRESHOLD: float = 10.0
