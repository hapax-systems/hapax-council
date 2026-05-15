"""LayoutIdentityContract -- binds 6 identity layers into a single
verifiable truth surface.

Incident: 2026-05-11 triple-surface-contradiction. Three layout
surfaces (runtime SHM, director receipt, Prometheus gauge) disagreed
on which layout was active. This contract formalizes what "layout
identity" means and provides a deterministic validator that returns
per-layer disagreements.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RenderedReadback(BaseModel):
    model_config = ConfigDict(frozen=True)

    active_layout: str | None = None
    visible_wards: tuple[str, ...] = ()
    source_placements: tuple[str, ...] = ()
    readback_ref: str | None = None
    observed_at: float | None = None


class ActiveMetricsSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    gauge_layout: str | None = None
    gauge_value: float | None = None
    scraped_at: float | None = None


class PersistenceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    autosaver_path: str | None = None
    autosaver_layout_name: str | None = None
    last_write_age_s: float | None = None
    write_skipped: bool = False
    skip_reason: str | None = None


class LayoutIdentitySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    filename: str | None = Field(None)
    internal_name: str | None = Field(None)
    selected_layout: str | None = Field(None)
    rendered_readback: RenderedReadback = Field(default_factory=RenderedReadback)
    active_metrics: ActiveMetricsSnapshot = Field(default_factory=ActiveMetricsSnapshot)
    persistence_state: PersistenceSnapshot = Field(default_factory=PersistenceSnapshot)
    captured_at: float = Field(default_factory=time.monotonic)
    capture_source: str = "unknown"


LayerName = Literal[
    "filename",
    "internal_name",
    "selected_layout",
    "rendered_readback",
    "active_metrics",
    "persistence_state",
]


class LayerDisagreement(BaseModel):
    model_config = ConfigDict(frozen=True)

    layer_a: LayerName
    layer_a_value: str | None
    layer_b: LayerName
    layer_b_value: str | None
    severity: Literal["error", "warning"] = "error"
    detail: str = ""


class LayoutIdentityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_captured_at: float
    canonical_name: str | None = None
    unanimous: bool = False
    disagreements: tuple[LayerDisagreement, ...] = ()
    layer_values: dict[str, str | None] = Field(default_factory=dict)
    absent_layers: tuple[LayerName, ...] = ()

    @property
    def agreement_count(self) -> int:
        if self.canonical_name is None:
            return 0
        return sum(1 for v in self.layer_values.values() if v == self.canonical_name)

    @property
    def participating_count(self) -> int:
        return sum(1 for v in self.layer_values.values() if v is not None)


def _extract_layer_values(
    snapshot: LayoutIdentitySnapshot,
) -> dict[LayerName, str | None]:
    return {
        "filename": snapshot.filename,
        "internal_name": snapshot.internal_name,
        "selected_layout": snapshot.selected_layout,
        "rendered_readback": snapshot.rendered_readback.active_layout,
        "active_metrics": snapshot.active_metrics.gauge_layout,
        "persistence_state": snapshot.persistence_state.autosaver_layout_name,
    }


_PRIORITY_ORDER: list[LayerName] = [
    "rendered_readback",
    "selected_layout",
    "internal_name",
    "filename",
    "active_metrics",
    "persistence_state",
]

_ERROR_PAIRS: set[frozenset[LayerName]] = {
    frozenset({"filename", "internal_name"}),
    frozenset({"selected_layout", "rendered_readback"}),
}
_ERROR_LAYERS: set[LayerName] = {"active_metrics"}


def validate_layout_identity(
    snapshot: LayoutIdentitySnapshot,
) -> LayoutIdentityReport:
    layer_values = _extract_layer_values(snapshot)

    absent: list[LayerName] = [n for n, v in layer_values.items() if v is None]
    participating: dict[LayerName, str] = {n: v for n, v in layer_values.items() if v is not None}

    if not participating:
        return LayoutIdentityReport(
            snapshot_captured_at=snapshot.captured_at,
            canonical_name=None,
            unanimous=True,
            disagreements=(),
            layer_values=dict(layer_values),
            absent_layers=tuple(absent),
        )

    value_counts: dict[str, int] = {}
    for v in participating.values():
        value_counts[v] = value_counts.get(v, 0) + 1

    max_count = max(value_counts.values())
    candidates = [v for v, c in value_counts.items() if c == max_count]

    if len(candidates) == 1:
        canonical = candidates[0]
    else:
        canonical = None
        for layer in _PRIORITY_ORDER:
            if layer in participating and participating[layer] in candidates:
                canonical = participating[layer]
                break
        if canonical is None:
            canonical = candidates[0]

    disagreements: list[LayerDisagreement] = []
    participating_names = list(participating.keys())
    for i, name_a in enumerate(participating_names):
        for name_b in participating_names[i + 1 :]:
            val_a = participating[name_a]
            val_b = participating[name_b]
            if val_a != val_b:
                pair = frozenset({name_a, name_b})
                if pair in _ERROR_PAIRS or name_a in _ERROR_LAYERS or name_b in _ERROR_LAYERS:
                    severity: Literal["error", "warning"] = "error"
                else:
                    severity = "warning"

                disagreements.append(
                    LayerDisagreement(
                        layer_a=name_a,
                        layer_a_value=val_a,
                        layer_b=name_b,
                        layer_b_value=val_b,
                        severity=severity,
                        detail=_disagreement_detail(name_a, val_a, name_b, val_b),
                    )
                )

    return LayoutIdentityReport(
        snapshot_captured_at=snapshot.captured_at,
        canonical_name=canonical,
        unanimous=len(disagreements) == 0,
        disagreements=tuple(disagreements),
        layer_values=dict(layer_values),
        absent_layers=tuple(absent),
    )


def _disagreement_detail(layer_a: str, val_a: str, layer_b: str, val_b: str) -> str:
    key = frozenset({layer_a, layer_b})

    if key == frozenset({"filename", "internal_name"}):
        return (
            f"Layout file stem is '{val_a}' but Layout.name field is '{val_b}'. "
            f"LayoutStore keys by filename stem, so consumers see '{val_a}' "
            f"but the model self-identifies as '{val_b}'."
        )

    if key == frozenset({"selected_layout", "rendered_readback"}):
        return (
            f"Segment control selected '{val_a}' but RuntimeLayoutReadback "
            f"observed '{val_b}'. LayoutState.mutate() succeeded but the "
            f"compositor rendered from a stale frame or the readback was "
            f"taken before the mutation propagated."
        )

    if "active_metrics" in key:
        other = layer_a if layer_b == "active_metrics" else layer_b
        other_val = val_a if layer_b == "active_metrics" else val_b
        gauge_val = val_b if layer_b == "active_metrics" else val_a
        return (
            f"Prometheus gauge says layout='{gauge_val}' but {other} says "
            f"'{other_val}'. The gauge is updated by LayoutStore.set_active() "
            f"but LayoutState.mutate() is a separate path."
        )

    if key == frozenset({"persistence_state", "internal_name"}):
        return (
            f"LayoutAutoSaver targets '{val_a}' but Layout.name is '{val_b}'. "
            f"The autosaver logs this and skips the write."
        )

    return f"{layer_a}='{val_a}' vs {layer_b}='{val_b}'"
