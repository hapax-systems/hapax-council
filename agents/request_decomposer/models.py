"""Pydantic models for request decomposition output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QualityFloorValue = Literal[
    "frontier_required",
    "frontier_review_required",
    "deterministic_ok",
]
MutationSurfaceValue = Literal[
    "none",
    "vault_docs",
    "source",
    "runtime",
    "public",
    "provider_spend",
]
AuthorityLevelValue = Literal[
    "authoritative",
    "support_non_authoritative",
    "evidence_receipt",
    "relay_only",
]


class TaskSpec(BaseModel):
    """Single task in a request decomposition."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    title: str
    kind: Literal[
        "build",
        "operator_action",
        "recovery_triage",
        "watcher",
        "research_packet",
        "verification",
    ] = "build"
    status: Literal["offered", "ready", "blocked"] = "offered"
    priority: str = "p2"
    wsjf: float = 5.0
    depends_on: list[str] = Field(default_factory=list)
    phase_index: int = 0
    parent_request: str = ""
    authority_case: str = ""
    parent_spec: str | None = None
    blocked_reason: str | None = None

    quality_floor: QualityFloorValue = "deterministic_ok"
    mutation_surface: MutationSurfaceValue = "source"
    authority_level: AuthorityLevelValue = "authoritative"
    effort_class: str = "standard"

    intent: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)

    @field_validator("mutation_surface", mode="before")
    @classmethod
    def _normalize_mutation_surface(cls, value: object) -> object:
        if value in {"docs", "planning", "vault"}:
            return "vault_docs"
        if isinstance(value, str):
            text = value.strip()
            if "/" in text or text.startswith(("agents", "hooks", "logos", "scripts", "shared")):
                return "source"
        return value

    @field_validator("authority_level", mode="before")
    @classmethod
    def _normalize_authority_level(cls, value: object) -> object:
        if value in {"delegated", "session"}:
            return "authoritative"
        return value

    @field_validator("quality_floor", mode="before")
    @classmethod
    def _normalize_quality_floor(cls, value: object) -> object:
        if value == "production":
            return "frontier_required"
        return value

    @model_validator(mode="after")
    def _normalize_route_metadata(self) -> TaskSpec:
        if (
            self.quality_floor == "frontier_review_required"
            and self.authority_level == "authoritative"
        ):
            self.quality_floor = "frontier_required"
        return self

    @model_validator(mode="after")
    def _blocked_needs_reason(self) -> TaskSpec:
        if self.status == "blocked" and not self.blocked_reason:
            msg = "blocked task must have blocked_reason"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _needs_authority_case(self) -> TaskSpec:
        import re

        if self.kind in {"research_packet", "operator_action"}:
            return self
        if not re.match(r"^CASE-[A-Z0-9-]+$", self.authority_case):
            msg = (
                f"task {self.task_id} has invalid authority_case "
                f"'{self.authority_case}' — must match CASE-[A-Z0-9-]+"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _needs_parent_lineage(self) -> TaskSpec:
        if self.kind in {"research_packet", "operator_action"}:
            return self
        if not (self.parent_spec or self.parent_request):
            msg = f"task {self.task_id} has no parent_spec or parent_request"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _needs_acceptance_criteria(self) -> TaskSpec:
        if not self.acceptance_criteria:
            msg = f"task {self.task_id} has no acceptance criteria"
            raise ValueError(msg)
        return self


class RequestDecomposition(BaseModel):
    """Full decomposition of a request into tasks."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    request_path: str
    decomposition_model: str = "balanced"
    tasks: list[TaskSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_dag(self) -> RequestDecomposition:
        ids = {t.task_id for t in self.tasks}
        for task in self.tasks:
            for dep in task.depends_on:
                if dep not in ids:
                    msg = f"{task.task_id} depends_on unknown task {dep}"
                    raise ValueError(msg)
        visited: set[str] = set()
        path: set[str] = set()
        adj = {t.task_id: t.depends_on for t in self.tasks}

        def _has_cycle(node: str) -> bool:
            if node in path:
                return True
            if node in visited:
                return False
            visited.add(node)
            path.add(node)
            for dep in adj.get(node, []):
                if _has_cycle(dep):
                    return True
            path.discard(node)
            return False

        for t in self.tasks:
            if _has_cycle(t.task_id):
                msg = f"dependency cycle detected involving {t.task_id}"
                raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> RequestDecomposition:
        ids = [t.task_id for t in self.tasks]
        if len(ids) != len(set(ids)):
            dupes = [x for x in ids if ids.count(x) > 1]
            msg = f"duplicate task_ids: {dupes}"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _validate_parent_request(self) -> RequestDecomposition:
        for task in self.tasks:
            if not task.parent_request:
                msg = f"{task.task_id} missing parent_request"
                raise ValueError(msg)
        return self
