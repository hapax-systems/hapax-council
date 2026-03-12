"""Tests for shared.operator_schema — query interface + staleness model."""

from __future__ import annotations

import time

from shared.dimensions import DimensionDef
from shared.operator_schema import (
    OperatorSchema,
    SchemaQuery,
    SchemaResponse,
    StalenessConfig,
    StalenessModel,
)

# ------------------------------------------------------------------
# StalenessModel
# ------------------------------------------------------------------


class TestStalenessModel:
    def _trait_dim(self) -> DimensionDef:
        return DimensionDef(
            name="identity",
            kind="trait",
            description="test",
            consumers=(),
            primary_sources=(),
        )

    def _behavioral_dim(self) -> DimensionDef:
        return DimensionDef(
            name="energy_and_attention",
            kind="behavioral",
            description="test",
            consumers=(),
            primary_sources=(),
        )

    def test_trait_fresh(self):
        model = StalenessModel()
        conf = model.confidence(self._trait_dim(), age_seconds=86400)  # 1 day
        assert conf == 1.0

    def test_trait_stale(self):
        model = StalenessModel()
        conf = model.confidence(self._trait_dim(), age_seconds=91 * 86400)  # 91 days
        assert conf == 0.5  # default floor

    def test_trait_exact_threshold(self):
        model = StalenessModel(StalenessConfig(trait_fresh_threshold_days=90.0))
        conf = model.confidence(self._trait_dim(), age_seconds=90 * 86400)
        assert conf == 1.0  # at threshold, still fresh

    def test_behavioral_fresh(self):
        model = StalenessModel()
        conf = model.confidence(self._behavioral_dim(), age_seconds=0)
        assert conf == 1.0

    def test_behavioral_half_life(self):
        model = StalenessModel(StalenessConfig(behavioral_half_life_hours=24.0))
        conf = model.confidence(self._behavioral_dim(), age_seconds=24 * 3600)
        assert conf == 0.5

    def test_behavioral_decays_to_floor(self):
        model = StalenessModel(
            StalenessConfig(behavioral_half_life_hours=1.0, behavioral_floor=0.1)
        )
        conf = model.confidence(self._behavioral_dim(), age_seconds=100 * 3600)
        assert conf == 0.1

    def test_negative_age_returns_full_confidence(self):
        model = StalenessModel()
        assert model.confidence(self._trait_dim(), age_seconds=-1) == 1.0
        assert model.confidence(self._behavioral_dim(), age_seconds=-1) == 1.0

    def test_custom_config(self):
        config = StalenessConfig(
            trait_fresh_threshold_days=30.0,
            trait_floor=0.3,
            behavioral_half_life_hours=12.0,
            behavioral_floor=0.05,
        )
        model = StalenessModel(config)
        # Trait: stale after 30 days
        assert model.confidence(self._trait_dim(), 31 * 86400) == 0.3
        # Behavioral: at half-life
        assert model.confidence(self._behavioral_dim(), 12 * 3600) == 0.5


# ------------------------------------------------------------------
# OperatorSchema
# ------------------------------------------------------------------


class TestOperatorSchema:
    def test_query_all_dimensions(self):
        schema = OperatorSchema()
        response = schema.query(SchemaQuery())
        assert isinstance(response, SchemaResponse)
        assert response.total_dimensions == 11
        assert len(response.entries) == 11

    def test_query_specific_dimensions(self):
        schema = OperatorSchema()
        response = schema.query(SchemaQuery(dimensions=["identity", "values"]))
        assert len(response.entries) == 2
        names = {e.dimension for e in response.entries}
        assert names == {"identity", "values"}

    def test_query_by_kind(self):
        schema = OperatorSchema()
        response = schema.query(SchemaQuery(kind_filter="trait"))
        assert all(e.kind == "trait" for e in response.entries)
        assert len(response.entries) == 5

    def test_query_behavioral_kind(self):
        schema = OperatorSchema()
        response = schema.query(SchemaQuery(kind_filter="behavioral"))
        assert all(e.kind == "behavioral" for e in response.entries)
        assert len(response.entries) == 6

    def test_confidence_with_timestamps(self):
        now = time.monotonic()
        schema = OperatorSchema(
            dimension_timestamps={
                "identity": now - 3600,  # 1 hour ago (trait, should be fresh)
                "energy_and_attention": now - 3600,  # 1 hour ago (behavioral)
            }
        )
        response = schema.query(SchemaQuery(dimensions=["identity", "energy_and_attention"]))
        identity_entry = next(e for e in response.entries if e.dimension == "identity")
        energy_entry = next(e for e in response.entries if e.dimension == "energy_and_attention")
        assert identity_entry.confidence == 1.0
        assert energy_entry.confidence > 0.9  # recently updated behavioral

    def test_min_confidence_filter(self):
        schema = OperatorSchema()  # no timestamps → all inf age → all stale
        response = schema.query(SchemaQuery(min_confidence=0.9))
        # With no timestamps, behavioral dims have floor confidence
        # Trait dims also have floor confidence with infinite age
        assert all(e.confidence >= 0.9 for e in response.entries)

    def test_update_timestamp(self):
        schema = OperatorSchema()
        now = time.monotonic()
        schema.update_timestamp("identity", now)
        response = schema.query(SchemaQuery(dimensions=["identity"]))
        assert response.entries[0].confidence == 1.0

    def test_access_log(self):
        schema = OperatorSchema()
        schema.query(SchemaQuery(dimensions=["identity"]))
        schema.query(SchemaQuery(dimensions=["values"]))
        assert len(schema.access_log) == 2

    def test_stale_flag(self):
        schema = OperatorSchema()  # no timestamps
        response = schema.query(SchemaQuery(dimensions=["energy_and_attention"]))
        # Infinite age → floor confidence → stale
        entry = response.entries[0]
        assert entry.stale is True

    def test_nonexistent_dimension_ignored(self):
        schema = OperatorSchema()
        response = schema.query(SchemaQuery(dimensions=["nonexistent"]))
        assert len(response.entries) == 0

    def test_access_log_truncation(self):
        schema = OperatorSchema()
        for _ in range(1100):
            schema.query(SchemaQuery(dimensions=["identity"]))
        assert len(schema.access_log) <= 1000
