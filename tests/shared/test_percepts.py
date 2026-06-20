"""Percept envelope — one schema across audio and visual perception."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.percepts import GeometryClass, Percept


def test_percept_is_frozen_and_forbids_extras() -> None:
    cfg = Percept.model_config
    assert cfg.get("frozen") is True
    assert cfg.get("extra") == "forbid"
    with pytest.raises(ValidationError):
        Percept(
            timestamp=1.0,
            source_point="rode",
            geometry_class=GeometryClass.PERSON_ATTACHED,
            confidence=1.0,
            unknown_extra="x",
        )


def test_confidence_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        Percept(
            timestamp=1.0,
            source_point="rode",
            geometry_class=GeometryClass.PERSON_ATTACHED,
            confidence=1.5,
        )
    with pytest.raises(ValidationError):
        Percept(
            timestamp=1.0,
            source_point="rode",
            geometry_class=GeometryClass.PERSON_ATTACHED,
            confidence=-0.1,
        )


def test_audio_and_visual_percepts_share_envelope() -> None:
    """§5d: one schema so CLAP/Essentia ↔ YOLO correlation composes."""
    doa = Percept(
        timestamp=1749600000.0,
        source_point="respeaker",
        geometry_class=GeometryClass.SPATIAL_ARRAY,
        confidence=0.92,
        payload={"kind": "doa", "bearing_deg": 135.0},
    )
    person = Percept(
        timestamp=1749600000.1,
        source_point="camera-mic-brio-operator",
        geometry_class=GeometryClass.AV_PAIRED,
        confidence=0.81,
        payload={"kind": "person", "bbox": [0.1, 0.2, 0.4, 0.9]},
    )
    assert doa.source_point != person.source_point
    assert abs(person.timestamp - doa.timestamp) < 0.5  # shared time base


def test_ir_edge_percepts_share_envelope() -> None:
    p = Percept(
        timestamp=1749600000.2,
        source_point="ir-desk",
        geometry_class=GeometryClass.IR_EDGE,
        confidence=0.74,
        payload={"kind": "person", "rppg_quality": 0.32},
    )
    assert p.geometry_class == GeometryClass.IR_EDGE
    assert p.payload["kind"] == "person"


def test_roundtrip() -> None:
    p = Percept(
        timestamp=1.5,
        source_point="yeti",
        geometry_class=GeometryClass.AMBIENT,
        confidence=0.5,
        payload={"kind": "vad", "prob": 0.5},
    )
    assert Percept.model_validate(p.model_dump(mode="json")) == p


def test_geometry_classes_complete() -> None:
    assert {g.value for g in GeometryClass} == {
        "person_attached",
        "spatial_array",
        "av_paired",
        "contact",
        "ambient",
        "instrument",
        "ir_edge",
    }
