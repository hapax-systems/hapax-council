"""Schema contracts for the systems observability Phase 1 catalog."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class EntityKind(StrEnum):
    """Phase 1 system entity kinds."""

    AGENT = "agent"
    SERVICE = "service"
    CONTAINER = "container"
    TIMER = "timer"
    DATA_STORE = "data_store"
    ENDPOINT = "endpoint"
    DEVICE = "device"
    PIPELINE = "pipeline"
    DASHBOARD = "dashboard"
    REPOSITORY = "repository"
    AXIOM = "axiom"
    SPEC = "spec"


class EntityMaturity(StrEnum):
    """Lifecycle state for cataloged system entities."""

    EXPERIMENTAL = "experimental"
    BETA = "beta"
    PRODUCTION = "production"
    DEPRECATED = "deprecated"


ENTITY_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.@/+%=-]*$"
ENTITY_REF_PATTERN = (
    r"^(agent|service|container|timer|data_store|endpoint|device|pipeline|dashboard|"
    r"repository|axiom|spec):[A-Za-z0-9][A-Za-z0-9_.@/+%=-]*$"
)

CatalogTier = Annotated[int, Field(ge=0, le=3)]
EntityRef = Annotated[str, Field(pattern=ENTITY_REF_PATTERN)]


def entity_ref(kind: EntityKind | str, name: str) -> str:
    """Return the canonical ``kind:name`` reference for a catalog entity."""

    return f"{kind}:{name}"


class SystemEntity(BaseModel):
    """Base record shared by every systems observability catalog entity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: EntityKind
    name: str = Field(min_length=1, max_length=160, pattern=ENTITY_NAME_PATTERN)
    tier: CatalogTier
    maturity: EntityMaturity
    description: str = Field(min_length=1)
    depends_on: tuple[EntityRef, ...] = Field(default_factory=tuple)
    consumed_by: tuple[EntityRef, ...] = Field(default_factory=tuple)

    @property
    def ref(self) -> str:
        """Canonical reference for relationship fields and CLOG read paths."""

        return entity_ref(self.kind, self.name)

    @model_validator(mode="after")
    def _validate_relationship_refs(self) -> Self:
        for field_name, refs in (
            ("depends_on", self.depends_on),
            ("consumed_by", self.consumed_by),
        ):
            if self.ref in refs:
                raise ValueError(f"{self.ref} cannot include itself in {field_name}")
            duplicate_refs = sorted({ref for ref in refs if refs.count(ref) > 1})
            if duplicate_refs:
                formatted = ", ".join(duplicate_refs)
                raise ValueError(f"{self.ref} has duplicate {field_name} refs: {formatted}")
        return self


class AgentEntity(SystemEntity):
    kind: Literal[EntityKind.AGENT] = EntityKind.AGENT


class ServiceEntity(SystemEntity):
    kind: Literal[EntityKind.SERVICE] = EntityKind.SERVICE


class ContainerEntity(SystemEntity):
    kind: Literal[EntityKind.CONTAINER] = EntityKind.CONTAINER


class TimerEntity(SystemEntity):
    kind: Literal[EntityKind.TIMER] = EntityKind.TIMER


class DataStoreEntity(SystemEntity):
    kind: Literal[EntityKind.DATA_STORE] = EntityKind.DATA_STORE


class EndpointEntity(SystemEntity):
    kind: Literal[EntityKind.ENDPOINT] = EntityKind.ENDPOINT


class DeviceEntity(SystemEntity):
    kind: Literal[EntityKind.DEVICE] = EntityKind.DEVICE


class PipelineEntity(SystemEntity):
    kind: Literal[EntityKind.PIPELINE] = EntityKind.PIPELINE


class DashboardEntity(SystemEntity):
    kind: Literal[EntityKind.DASHBOARD] = EntityKind.DASHBOARD


class RepositoryEntity(SystemEntity):
    kind: Literal[EntityKind.REPOSITORY] = EntityKind.REPOSITORY


class AxiomEntity(SystemEntity):
    kind: Literal[EntityKind.AXIOM] = EntityKind.AXIOM


class SpecEntity(SystemEntity):
    kind: Literal[EntityKind.SPEC] = EntityKind.SPEC


CatalogEntity = Annotated[
    AgentEntity
    | ServiceEntity
    | ContainerEntity
    | TimerEntity
    | DataStoreEntity
    | EndpointEntity
    | DeviceEntity
    | PipelineEntity
    | DashboardEntity
    | RepositoryEntity
    | AxiomEntity
    | SpecEntity,
    Field(discriminator="kind"),
]

ENTITY_MODEL_BY_KIND: Mapping[EntityKind, type[SystemEntity]] = {
    EntityKind.AGENT: AgentEntity,
    EntityKind.SERVICE: ServiceEntity,
    EntityKind.CONTAINER: ContainerEntity,
    EntityKind.TIMER: TimerEntity,
    EntityKind.DATA_STORE: DataStoreEntity,
    EntityKind.ENDPOINT: EndpointEntity,
    EntityKind.DEVICE: DeviceEntity,
    EntityKind.PIPELINE: PipelineEntity,
    EntityKind.DASHBOARD: DashboardEntity,
    EntityKind.REPOSITORY: RepositoryEntity,
    EntityKind.AXIOM: AxiomEntity,
    EntityKind.SPEC: SpecEntity,
}

_CATALOG_ENTITY_ADAPTER = TypeAdapter(CatalogEntity)


def entity_from_mapping(payload: Mapping[str, Any]) -> SystemEntity:
    """Validate one mapping and return the matching concrete entity subclass."""

    return _CATALOG_ENTITY_ADAPTER.validate_python(payload)


class SystemCatalog(BaseModel):
    """Validated entity graph for systems observability read paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    entities: tuple[CatalogEntity, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_entity_graph(self) -> Self:
        by_ref: dict[str, SystemEntity] = {}
        for entity in self.entities:
            if entity.ref in by_ref:
                raise ValueError(f"duplicate entity ref: {entity.ref}")
            by_ref[entity.ref] = entity

        missing_refs: list[str] = []
        for entity in self.entities:
            for relation_name, refs in (
                ("depends_on", entity.depends_on),
                ("consumed_by", entity.consumed_by),
            ):
                for ref in refs:
                    if ref not in by_ref:
                        missing_refs.append(f"{entity.ref}.{relation_name}->{ref}")

        if missing_refs:
            formatted = ", ".join(sorted(missing_refs))
            raise ValueError(f"unknown catalog relationship refs: {formatted}")
        return self

    def by_ref(self) -> dict[str, SystemEntity]:
        """Return entities keyed by canonical ``kind:name`` reference."""

        return {entity.ref: entity for entity in self.entities}

    def require_ref(self, ref: str) -> SystemEntity:
        """Return one entity or raise a KeyError with the missing reference."""

        return self.by_ref()[ref]

    def by_kind(self, kind: EntityKind) -> tuple[SystemEntity, ...]:
        """Return all entities of one kind in catalog order."""

        return tuple(entity for entity in self.entities if entity.kind == kind)


# Pydantic invokes validators by reflection and SBCL/CLOG consumers call read
# helpers dynamically; the diff-aware vulture gate needs a static reference.
_DYNAMIC_ENTRYPOINTS = (
    SystemEntity._validate_relationship_refs,
    SystemCatalog._validate_entity_graph,
    SystemCatalog.require_ref,
)


__all__ = [
    "AgentEntity",
    "AxiomEntity",
    "CatalogEntity",
    "CatalogTier",
    "ContainerEntity",
    "DashboardEntity",
    "DataStoreEntity",
    "DeviceEntity",
    "EndpointEntity",
    "EntityKind",
    "EntityMaturity",
    "EntityRef",
    "ENTITY_MODEL_BY_KIND",
    "PipelineEntity",
    "RepositoryEntity",
    "ServiceEntity",
    "SpecEntity",
    "SystemCatalog",
    "SystemEntity",
    "TimerEntity",
    "entity_from_mapping",
    "entity_ref",
]
