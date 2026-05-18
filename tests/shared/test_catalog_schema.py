"""Tests for systems observability catalog schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.catalog_schema import (
    ENTITY_MODEL_BY_KIND,
    AgentEntity,
    AxiomEntity,
    ContainerEntity,
    DashboardEntity,
    DataStoreEntity,
    DeviceEntity,
    EndpointEntity,
    EntityKind,
    EntityMaturity,
    PipelineEntity,
    RepositoryEntity,
    ServiceEntity,
    SpecEntity,
    SystemCatalog,
    TimerEntity,
    entity_from_mapping,
    entity_ref,
)


def _entity_kwargs(**overrides):
    payload = {
        "name": "health_monitor",
        "tier": 1,
        "maturity": "production",
        "description": "Deterministic stack health check suite.",
    }
    payload.update(overrides)
    return payload


def test_all_phase1_entity_kinds_have_concrete_models() -> None:
    assert set(ENTITY_MODEL_BY_KIND) == set(EntityKind)

    expected_models = {
        AgentEntity,
        ServiceEntity,
        ContainerEntity,
        TimerEntity,
        DataStoreEntity,
        EndpointEntity,
        DeviceEntity,
        PipelineEntity,
        DashboardEntity,
        RepositoryEntity,
        AxiomEntity,
        SpecEntity,
    }
    assert set(ENTITY_MODEL_BY_KIND.values()) == expected_models

    for kind, model in ENTITY_MODEL_BY_KIND.items():
        entity = model(
            name=f"{kind.value}-example",
            tier=3,
            maturity=EntityMaturity.EXPERIMENTAL,
            description=f"Example {kind.value} entity.",
        )
        assert entity.kind == kind
        assert entity.ref == f"{kind.value}:{kind.value}-example"


def test_entity_validates_tier_maturity_and_extra_fields() -> None:
    entity = AgentEntity(**_entity_kwargs())

    assert entity.kind is EntityKind.AGENT
    assert entity.tier == 1
    assert entity.maturity is EntityMaturity.PRODUCTION

    with pytest.raises(ValidationError):
        AgentEntity(**_entity_kwargs(tier=4))

    with pytest.raises(ValidationError):
        AgentEntity(**_entity_kwargs(maturity="alpha"))

    with pytest.raises(ValidationError):
        AgentEntity(**_entity_kwargs(unexpected=True))


def test_concrete_entity_rejects_wrong_kind() -> None:
    with pytest.raises(ValidationError):
        AgentEntity(**_entity_kwargs(kind="service"))


def test_relationship_refs_are_canonical_and_non_self_referential() -> None:
    entity = AgentEntity(
        **_entity_kwargs(
            depends_on=("service:logos-api", "data_store:qdrant"),
            consumed_by=("dashboard:systems-observability",),
        )
    )

    assert entity.ref == entity_ref(EntityKind.AGENT, "health_monitor")
    assert entity.depends_on == ("service:logos-api", "data_store:qdrant")
    assert entity.consumed_by == ("dashboard:systems-observability",)

    with pytest.raises(ValidationError, match="cannot include itself"):
        AgentEntity(**_entity_kwargs(depends_on=("agent:health_monitor",)))

    with pytest.raises(ValidationError, match="duplicate depends_on refs"):
        AgentEntity(**_entity_kwargs(depends_on=("service:logos-api", "service:logos-api")))

    with pytest.raises(ValidationError):
        AgentEntity(**_entity_kwargs(depends_on=("badkind:logos-api",)))


def test_entity_from_mapping_uses_kind_discriminator() -> None:
    entity = entity_from_mapping(
        {
            "kind": "timer",
            "name": "hapax-cc-hygiene.timer",
            "tier": 2,
            "maturity": "beta",
            "description": "Periodic CC hygiene timer.",
            "depends_on": ["service:hapax-cc-hygiene.service"],
        }
    )

    assert isinstance(entity, TimerEntity)
    assert entity.kind is EntityKind.TIMER
    assert entity.depends_on == ("service:hapax-cc-hygiene.service",)


def test_system_catalog_validates_unique_entities_and_known_relationship_targets() -> None:
    catalog = SystemCatalog(
        entities=(
            ServiceEntity(
                name="logos-api",
                tier=1,
                maturity="production",
                description="Council FastAPI service.",
            ),
            AgentEntity(
                name="health_monitor",
                tier=1,
                maturity="production",
                description="Deterministic stack health checks.",
                depends_on=("service:logos-api",),
            ),
            DashboardEntity(
                name="systems-observability",
                tier=2,
                maturity="experimental",
                description="Phase 1 systems observability dashboard.",
                depends_on=("agent:health_monitor", "service:logos-api"),
            ),
        )
    )

    assert catalog.require_ref("agent:health_monitor").name == "health_monitor"
    assert [entity.name for entity in catalog.by_kind(EntityKind.SERVICE)] == ["logos-api"]
    assert set(catalog.by_ref()) == {
        "service:logos-api",
        "agent:health_monitor",
        "dashboard:systems-observability",
    }

    with pytest.raises(ValidationError, match="duplicate entity ref"):
        SystemCatalog(
            entities=(
                ServiceEntity(
                    name="logos-api",
                    tier=1,
                    maturity="production",
                    description="Council FastAPI service.",
                ),
                ServiceEntity(
                    name="logos-api",
                    tier=1,
                    maturity="production",
                    description="Duplicate service.",
                ),
            )
        )

    with pytest.raises(ValidationError, match="unknown catalog relationship refs"):
        SystemCatalog(
            entities=(
                AgentEntity(
                    name="health_monitor",
                    tier=1,
                    maturity="production",
                    description="Deterministic stack health checks.",
                    depends_on=("service:missing",),
                ),
            )
        )


def test_catalog_json_schema_exposes_tier_and_maturity_contracts() -> None:
    schema = SystemCatalog.model_json_schema()

    assert "entities" in schema["properties"]
    assert schema["$defs"]["AgentEntity"]["properties"]["tier"]["maximum"] == 3
    assert schema["$defs"]["AgentEntity"]["properties"]["tier"]["minimum"] == 0
    assert set(schema["$defs"]["EntityMaturity"]["enum"]) == {
        "experimental",
        "beta",
        "production",
        "deprecated",
    }
