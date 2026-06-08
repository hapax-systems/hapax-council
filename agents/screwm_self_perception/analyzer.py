"""Drift self-perception — the re-perceivable (``get``) surface of the drift chiasmic entity.

Per the Chiasm Contract (``docs/superpowers/specs/2026-06-07-cns-chiasm-contract-design.md``), a
chiasmic entity is a lawful bidirectional optic: ``put`` modulates it (recruited expression) and
``get`` reports its realized state back into the recruitment loop, in the SAME 9-dimensional basis.
This module is drift's ``get``: it reads the per-zone drift currency the engine consumes
(``/dev/shm/hapax-compositor/quake-drift-currency.bgra``, 256x256 BGRA8) and projects the realized
field onto the 9 expressive dimensions.

AUDIT-ONLY: this computes + records the projection. Minting it onto the impingement bus and wiring it
into ``select()`` (closing the chiasm) is the gated loop-closure (see the spec, PR-E), which must
follow a feedback-gain measurement first.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# The canonical 9 expressive dimensions (shared/director_intent.py CompositionalImpingement.dimensions).
EXPRESSIVE_DIMS: tuple[str, ...] = (
    "intensity",
    "tension",
    "depth",
    "coherence",
    "spectral_color",
    "temporal_distortion",
    "degradation",
    "pitch_displacement",
    "diffusion",
)


@dataclass(frozen=True)
class DriftSelfPerception:
    """One snapshot of the drift entity's realized state, projected onto the 9 dims."""

    dims: dict[str, float]  # realized state in the 9-dim basis (the get projection)
    zone_energy: list[list[float]]  # per-zone mean currency, [zones_y][zones_x]
    mean_energy: float
    field_size: int
    zones: tuple[int, int]  # (zones_y, zones_x)

    def to_dict(self) -> dict:
        return {
            "dims": {k: round(v, 4) for k, v in self.dims.items()},
            "zone_energy": [[round(v, 4) for v in row] for row in self.zone_energy],
            "mean_energy": round(self.mean_energy, 4),
            "field_size": self.field_size,
            "zones": list(self.zones),
        }


def _zero_dims() -> dict[str, float]:
    return {d: 0.0 for d in EXPRESSIVE_DIMS}


def analyze(currency_bgra: np.ndarray, zones_y: int = 4, zones_x: int = 4) -> DriftSelfPerception:
    """Project a currency BGRA frame onto the 9 expressive dimensions.

    ``currency_bgra``: an ``(H, W, 4)`` uint8 array in BGRA byte order (the engine's ``Bgra8Unorm``
    readback). The currency value is the R channel (index 2); today it is greyscale (B==G==R), so any
    channel is equivalent. Values are in [0, 1] after /255 (the producer clamps live currency to
    [0.2, 1.0]). Greyscale today encodes only intensity-family observables; the dimensional wire
    (spec PR-B) and temporal analysis populate the rest — we report what is honestly observable from a
    single greyscale frame and leave the unobservable dims at 0.0.
    """
    if currency_bgra.ndim != 3 or currency_bgra.shape[2] != 4 or currency_bgra.size == 0:
        return DriftSelfPerception(
            dims=_zero_dims(),
            zone_energy=[],
            mean_energy=0.0,
            field_size=0,
            zones=(zones_y, zones_x),
        )

    h, w = int(currency_bgra.shape[0]), int(currency_bgra.shape[1])
    currency = currency_bgra[:, :, 2].astype(np.float64) / 255.0  # R channel == the engine's .r

    # Per-zone mean: split into a zones_y x zones_x grid (truncating any ragged remainder).
    zy, zx = max(1, zones_y), max(1, zones_x)
    bh, bw = max(1, h // zy), max(1, w // zx)
    zone_energy: list[list[float]] = []
    zone_means: list[float] = []
    for j in range(zy):
        row: list[float] = []
        for i in range(zx):
            block = currency[j * bh : (j + 1) * bh, i * bw : (i + 1) * bw]
            m = float(np.mean(block)) if block.size else 0.0
            row.append(m)
            zone_means.append(m)
        zone_energy.append(row)

    zarr = np.asarray(zone_means, dtype=np.float64)
    mean_energy = float(np.mean(zarr))
    std = float(np.std(zarr))
    z_range = float(zarr.max() - zarr.min()) if zarr.size else 0.0
    above = float(np.count_nonzero(zarr > mean_energy)) / zarr.size if zarr.size else 0.0

    dims = _zero_dims()
    # intensity: overall drift energy (the field's mean amplitude).
    dims["intensity"] = float(np.clip(mean_energy, 0.0, 1.0))
    # tension: spatial unevenness (std across zones), scaled so a strongly-split field saturates.
    dims["tension"] = float(np.clip(std * 2.0, 0.0, 1.0))
    # coherence: uniformity (inverse of normalized spread).
    dims["coherence"] = float(np.clip(1.0 - std * 3.0, 0.0, 1.0))
    # depth: dynamic range across zones (foreground/background separation the field carries).
    dims["depth"] = float(np.clip(z_range, 0.0, 1.0))
    # diffusion: spatial spread of above-mean activity (~0.5 above-fraction => evenly spread => high).
    dims["diffusion"] = float(np.clip(1.0 - abs(above - 0.5) * 2.0, 0.0, 1.0))

    return DriftSelfPerception(
        dims=dims,
        zone_energy=zone_energy,
        mean_energy=mean_energy,
        field_size=h,
        zones=(zy, zx),
    )


__all__ = ["DriftSelfPerception", "analyze", "EXPRESSIVE_DIMS"]
