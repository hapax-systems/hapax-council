"""Materialize the world-language Layer-2 registry from the deployed SSOTs.

A GENERATED artifact (Ashby–Conant homomorphic projection): iterate the world
capability surface (and, as a follow-on, hardm_signal_map / density SOURCE_REGISTRY
/ OSC aliases) and emit ``WorldLanguageNode``s — each stamped with a
``GeneratedFromRecord`` backpointer — written to
``/dev/shm/hapax-world-language/layer2-manifest.json`` at service load.

No static symbol→referent table (meaning is bound at use-time by the affordance
pipeline; split 3). The Direction→PhysicalDirection map below is a *structural
projection* (the homomorphism), not a referent lookup.

Boot-safe: every source loop is guarded, and a coverage shortfall is surfaced as a
sheaf H¹ obstruction (information, not error). Materialization NEVER raises at
service load. See REQ-20260607-world-language-materializer + super-spec §2.2/§4.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from shared.direction import Direction, PhysicalDirection
from shared.sheaf_health import compute_consistency_radius
from shared.world_language import (
    SOSA_FOR_PHYSICAL_DIRECTION,
    DataSchema,
    Form,
    GeneratedFromRecord,
    ImageSchema,
    SosaClass,
    TdKind,
    WorldLanguageNode,
)

log = logging.getLogger(__name__)

MANIFEST_PATH = Path("/dev/shm/hapax-world-language/layer2-manifest.json")
_COVERAGE_SHORTFALL_THRESHOLD = 0.1  # matches sheaf_health's H¹ edge threshold

# Structural projection (the Ashby homomorphism), NOT a symbol→referent table:
# every capability Direction has a transport polarity. Used only when a WCS record
# does not already carry an explicit physical_direction.
_PHYSICAL_FOR_DIRECTION: dict[Direction, PhysicalDirection] = {
    Direction.OBSERVE: PhysicalDirection.AFFERENT,
    Direction.RECALL: PhysicalDirection.AFFERENT,
    Direction.EXPRESS: PhysicalDirection.EFFERENT,
    Direction.ACT: PhysicalDirection.EFFERENT,
    Direction.REGULATE: PhysicalDirection.EFFERENT,
    Direction.COMMUNICATE: PhysicalDirection.STIGMERGIC,
    Direction.ROUTE: PhysicalDirection.STIGMERGIC,
}
_TD_KIND_FOR_SOSA: dict[SosaClass, TdKind] = {
    SosaClass.OBSERVATION: TdKind.PROPERTY,
    SosaClass.ACTUATION: TdKind.ACTION,
    SosaClass.SAMPLING: TdKind.EVENT,
}
_OP_FOR_SOSA: dict[SosaClass, str] = {
    SosaClass.OBSERVATION: "readproperty",
    SosaClass.ACTUATION: "invokeaction",
    SosaClass.SAMPLING: "subscribeevent",
}


def _content_hash(payload: Any) -> str:
    """Deterministic short content hash of a JSON-serializable payload."""
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _project_wcs_record(record: Any) -> WorldLanguageNode:
    """Project one WorldCapabilityRecord into a WorldLanguageNode (homomorphism)."""
    physical = record.physical_direction or _PHYSICAL_FOR_DIRECTION[record.direction]
    sosa = SOSA_FOR_PHYSICAL_DIRECTION[physical]
    forms = tuple(Form(op=_OP_FOR_SOSA[sosa], href=ref) for ref in list(record.surface_refs)[:1])
    cadence_hz: float | None = None
    ttl = getattr(record, "freshness_ttl_s", None)
    if ttl:
        cadence_hz = round(1.0 / ttl, 4)
    return WorldLanguageNode(
        node_id=record.capability_id,
        td_kind=_TD_KIND_FOR_SOSA[sosa],
        sosa_class=sosa,
        physical_direction=physical,
        capability_direction=record.direction,
        image_schema=ImageSchema.SCALE,  # default magnitude; FORCE/CYCLE refinement is follow-on
        l1_relatum_id=record.domain,
        data_schema=DataSchema(type="object"),
        forms=forms,
        cadence_hz=cadence_hz,
        authority_ceiling=str(record.authority_ceiling),
        generated_from=GeneratedFromRecord(
            ssot="world_capability_surface",
            key=record.capability_id,
            content_hash=_content_hash(record.model_dump(mode="json")),
        ),
    )


def _materialize_wcs(nodes: list[WorldLanguageNode], residuals: list[float]) -> None:
    """Project the world capability surface into nodes; record per-row residuals."""
    try:
        from shared.world_capability_surface import load_world_capability_registry

        registry = load_world_capability_registry()
    except Exception as exc:  # noqa: BLE001 — boot-safety: a missing source degrades, never raises
        log.warning("world_language: WCS source unavailable, skipping: %s", exc)
        residuals.append(1.0)
        return
    for record in registry.records:
        try:
            node = _project_wcs_record(record)
        except Exception as exc:  # noqa: BLE001 — one bad row degrades coverage, never raises
            log.warning("world_language: failed to project WCS %r: %s", record.capability_id, exc)
            residuals.append(1.0)
            continue
        # Consent fail-closed: afferent non-operator FeatureOfInterest is withheld
        # until the consent-provenance REQ lands. (WCS rows are operator-scoped.)
        if node.physical_direction is PhysicalDirection.AFFERENT and (
            node.feature_of_interest.value != "operator"
        ):
            log.info(
                "world_language: withholding non-operator afferent node %s (consent)", node.node_id
            )
            continue
        nodes.append(node)
        residuals.append(0.0)


def materialize(*, write: bool = True) -> dict[str, Any]:
    """Build the Layer-2 manifest from the SSOTs. Boot-safe — never raises."""
    nodes: list[WorldLanguageNode] = []
    residuals: list[float] = []
    try:
        _materialize_wcs(nodes, residuals)
        # follow-on sources (hardm_signal_map / SOURCE_REGISTRY / OSC) project here.
    except Exception as exc:  # noqa: BLE001 — last-resort boot guard
        log.warning("world_language: materialization error, emitting partial manifest: %s", exc)

    # Drift gate — REUSE the sheaf consistency radius (no fork). A coverage shortfall
    # is a sheaf H¹ obstruction: surfaced as information (degraded manifest), not raised.
    radius = compute_consistency_radius(residuals)
    coverage_shortfall = radius > _COVERAGE_SHORTFALL_THRESHOLD
    if coverage_shortfall:
        log.warning(
            "world_language: H¹ obstruction — coverage shortfall (drift_radius=%.3f)", radius
        )

    node_payloads = sorted((n.model_dump(mode="json") for n in nodes), key=lambda d: d["node_id"])
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "nodes": node_payloads,
        "node_count": len(node_payloads),
        "drift_radius": round(radius, 4),
        "coverage_shortfall": coverage_shortfall,
    }
    manifest["content_hash"] = _content_hash(node_payloads)

    if write:
        try:
            MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
            MANIFEST_PATH.write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError as exc:
            log.warning("world_language: manifest write failed: %s", exc)

    return manifest


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    result = materialize()
    print(f"materialized {result['node_count']} nodes; drift_radius={result['drift_radius']}")
