"""Tests for the world-language Layer-1/2 type system (keystone split 1/3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.direction import Direction as CanonicalDirection
from shared.direction import PhysicalDirection as CanonicalPhysicalDirection
from shared.world_language import (
    DataSchema,
    Direction,
    Form,
    GeneratedFromRecord,
    ImageSchema,
    ImageSchemaNode,
    PhysicalDirection,
    SosaClass,
    TdKind,
    WorldLanguageNode,
)


def _gen() -> GeneratedFromRecord:
    return GeneratedFromRecord(
        ssot="world_capability_surface", key="audio.broadcast_rms", content_hash="abc123"
    )


def _node(**kw) -> WorldLanguageNode:
    base = dict(
        node_id="n1",
        td_kind=TdKind.PROPERTY,
        sosa_class=SosaClass.OBSERVATION,
        physical_direction=PhysicalDirection.AFFERENT,
        capability_direction=Direction.OBSERVE,
        image_schema=ImageSchema.SCALE,
        l1_relatum_id="l1",
        data_schema=DataSchema(type="number"),
        authority_ceiling="internal_only",
        generated_from=_gen(),
    )
    base.update(kw)
    return WorldLanguageNode(**base)


class TestImageSchema:
    def test_exactly_seven_members(self):
        assert [s.value for s in ImageSchema] == [
            "scale",
            "cycle",
            "container",
            "force",
            "path",
            "link",
            "support",
        ]


class TestImageSchemaNode:
    def test_force_requires_efferent_terminus(self):
        with pytest.raises(ValidationError):
            ImageSchemaNode(image_schema=ImageSchema.FORCE, relatum_id="r")
        # FORCE with a terminus is fine; non-FORCE never requires one
        ImageSchemaNode(image_schema=ImageSchema.FORCE, relatum_id="r", efferent_terminus="hue")
        ImageSchemaNode(image_schema=ImageSchema.SCALE, relatum_id="r")

    def test_bounds_is_a_range(self):
        ImageSchemaNode(image_schema=ImageSchema.SCALE, relatum_id="r", bounds=(0.0, 1.0))
        with pytest.raises(ValidationError):
            ImageSchemaNode(image_schema=ImageSchema.SCALE, relatum_id="r", bounds=(1.0, 0.0))


class TestGeneratedFromRecord:
    def test_carries_ssot_key_content_hash(self):
        g = _gen()
        assert g.ssot and g.key and g.content_hash  # three named fields, not a Literal


class TestWorldLanguageNode:
    def test_uses_canonical_direction_enums_no_parallel(self):
        f = WorldLanguageNode.model_fields
        assert f["physical_direction"].annotation is CanonicalPhysicalDirection
        assert f["capability_direction"].annotation is CanonicalDirection
        assert PhysicalDirection is CanonicalPhysicalDirection
        assert Direction is CanonicalDirection

    def test_valid_afferent_observation_node(self):
        n = _node()
        assert n.sosa_class is SosaClass.OBSERVATION
        assert n.generated_from.content_hash == "abc123"

    def test_sosa_class_must_match_physical_direction(self):
        # afferent node mislabeled as Actuation → invalid
        with pytest.raises(ValidationError):
            _node(physical_direction=PhysicalDirection.AFFERENT, sosa_class=SosaClass.ACTUATION)

    def test_stigmergic_is_sampling(self):
        n = _node(
            physical_direction=PhysicalDirection.STIGMERGIC,
            sosa_class=SosaClass.SAMPLING,
            capability_direction=Direction.ROUTE,
        )
        assert n.sosa_class is SosaClass.SAMPLING

    def test_force_node_requires_efferent_and_form(self):
        # FORCE + afferent → invalid
        with pytest.raises(ValidationError):
            _node(image_schema=ImageSchema.FORCE)
        # FORCE + efferent but no form → invalid (no efferent terminus)
        with pytest.raises(ValidationError):
            _node(
                image_schema=ImageSchema.FORCE,
                physical_direction=PhysicalDirection.EFFERENT,
                sosa_class=SosaClass.ACTUATION,
                capability_direction=Direction.ACT,
                td_kind=TdKind.ACTION,
            )
        # FORCE + efferent + a Form → valid
        n = _node(
            image_schema=ImageSchema.FORCE,
            physical_direction=PhysicalDirection.EFFERENT,
            sosa_class=SosaClass.ACTUATION,
            capability_direction=Direction.ACT,
            td_kind=TdKind.ACTION,
            forms=(Form(op="invokeaction", href="hue://office/brightness"),),
        )
        assert n.image_schema is ImageSchema.FORCE

    def test_authority_ceiling_required(self):
        # missing authority_ceiling → build error (no default)
        with pytest.raises(ValidationError):
            WorldLanguageNode(
                node_id="n",
                td_kind=TdKind.PROPERTY,
                sosa_class=SosaClass.OBSERVATION,
                physical_direction=PhysicalDirection.AFFERENT,
                capability_direction=Direction.OBSERVE,
                image_schema=ImageSchema.SCALE,
                l1_relatum_id="l1",
                data_schema=DataSchema(type="number"),
                generated_from=_gen(),
            )
