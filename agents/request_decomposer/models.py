"""Pydantic models for request decomposition output."""

from __future__ import annotations

import fnmatch
import functools
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.route_metadata_schema import RouteEnvelope

_GOVERNANCE_SUFFIXES = (".rs", ".wgsl")


@functools.lru_cache(maxsize=1)
def _codeowners_protected_patterns() -> tuple[str, ...]:
    """Path patterns from ``.github/CODEOWNERS`` — the governance-protected set.

    Sourced live from the repo's CODEOWNERS (never a hardcoded list, so the D8
    floor tracks governance changes). Returns the leading path token of each
    non-comment, non-blank line; empty if CODEOWNERS is absent.
    """
    codeowners = Path(__file__).resolve().parents[2] / ".github" / "CODEOWNERS"
    if not codeowners.is_file():
        return ()
    patterns: list[str] = []
    for raw in codeowners.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            patterns.append(line.split()[0])
    return tuple(patterns)


def _path_matches_codeowners(path: str, patterns: tuple[str, ...]) -> bool:
    # CODEOWNERS uses gitignore-style globs. Handle directory-prefix (``dir/``),
    # any-depth (``**/name``), fnmatch globs (``*.ext``, ``dir/*``), and exact /
    # basename matches. (Full gitignore semantics are broader; this covers the
    # governance CODEOWNERS patterns plus the common glob cases.)
    p = path.strip().lstrip("/")
    base = p.rsplit("/", 1)[-1]
    for pat in patterns:
        anchored = pat.startswith("/")  # leading "/" anchors to repo root
        q = pat.lstrip("/")
        if not q:
            continue
        if q.endswith("/"):
            prefix = q.rstrip("/")
            if p == prefix or p.startswith(prefix + "/"):
                return True
            continue
        any_depth = q.startswith("**/")
        if any_depth:
            q = q[3:]
        # Root-anchored patterns match only at root; non-anchored and **/ patterns
        # match at any depth (gitignore/CODEOWNERS basename semantics).
        if any(c in q for c in "*?["):
            if fnmatch.fnmatch(p, q):
                return True
            if (any_depth or not anchored) and fnmatch.fnmatch(base, q):
                return True
        else:
            if p == q:
                return True
            if (any_depth or not anchored) and p.endswith("/" + q):
                return True
    return False


def _is_governance_protected_path(path: str) -> bool:
    """A .rs/.wgsl file or a CODEOWNERS-protected path (the D8 frontier surfaces)."""
    return path.strip().lower().endswith(_GOVERNANCE_SUFFIXES) or _path_matches_codeowners(
        path, _codeowners_protected_patterns()
    )


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
RoutingClassValue = Literal[
    "unknown",
    "coordination",
    "research_support",
    "docs_planning",
    "source_python",
    "source_other",
    "source_governance",
    "runtime_ops",
    "public_surface",
    "provider_spend",
    "operator_action",
    "verification",
]
CompositionToleranceValue = Literal[
    "unknown",
    "atomic",
    "parallel_ok",
    "sequential_required",
    "decompose_required",
]
REQUIREMENT_VECTOR_DIMENSIONS = (
    "quality_floor",
    "information_scope",
    "context_length",
    "mutation_risk",
    "verification_demand",
    "ambiguity_novelty",
    "composition_coupling",
    "governance_sensitivity",
)
_REQUIREMENT_VECTOR_DIMENSION_SET = frozenset(REQUIREMENT_VECTOR_DIMENSIONS)
_REQUIREMENT_VECTOR_NEXT_ACTION = (
    "next action: provide one value for each taxonomy dimension: "
    + ", ".join(REQUIREMENT_VECTOR_DIMENSIONS)
)
_REQUIREMENT_SCORE_NEXT_ACTION = (
    "next action: set each requirement vector score to an integer from 0 through 5"
)
_VALIDITY_MASK_NEXT_ACTION = (
    "next action: set each requirement_vector_validity_mask value to true or false"
)
_REQUIREMENT_VECTOR_ALIASES = {
    "d1": "quality_floor",
    "quality": "quality_floor",
    "qualityfloor": "quality_floor",
    "d2": "information_scope",
    "scope": "information_scope",
    "info_scope": "information_scope",
    "information": "information_scope",
    "d3": "context_length",
    "context": "context_length",
    "context_budget": "context_length",
    "context_budget_class": "context_length",
    "token_budget": "context_length",
    "d4": "mutation_risk",
    "mutation": "mutation_risk",
    "surface_risk": "mutation_risk",
    "d5": "verification_demand",
    "verification": "verification_demand",
    "verifier": "verification_demand",
    "verification_surface": "verification_demand",
    "d6": "ambiguity_novelty",
    "ambiguity": "ambiguity_novelty",
    "novelty": "ambiguity_novelty",
    "d7": "composition_coupling",
    "composition": "composition_coupling",
    "coupling": "composition_coupling",
    "d8": "governance_sensitivity",
    "governance": "governance_sensitivity",
    "governance_risk": "governance_sensitivity",
}


def _normalize_requirement_dimension(value: object) -> str:
    key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return _REQUIREMENT_VECTOR_ALIASES.get(key, key)


def _coerce_requirement_score(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError(
            f"requirement vector scores must be integers 0..5; {_REQUIREMENT_SCORE_NEXT_ACTION}"
        )
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(
            f"requirement vector scores must be integers 0..5; {_REQUIREMENT_SCORE_NEXT_ACTION}"
        )
    try:
        score = int(str(value).strip() if isinstance(value, str) else value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"requirement vector scores must be integers 0..5; {_REQUIREMENT_SCORE_NEXT_ACTION}"
        ) from exc
    if score < 0 or score > 5:
        raise ValueError(
            f"requirement vector scores must be integers 0..5; {_REQUIREMENT_SCORE_NEXT_ACTION}"
        )
    return score


def _coerce_mask_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1"}:
        return True
    if text in {"false", "no", "n", "0"}:
        return False
    raise ValueError(
        f"requirement vector validity values must be booleans; {_VALIDITY_MASK_NEXT_ACTION}"
    )


def _ordered_dimension_mapping(value: object, *, mask: bool) -> dict[str, int] | dict[str, bool]:
    if value in (None, "", [], {}):
        return {}
    if isinstance(value, Mapping):
        items = list(value.items())
    elif isinstance(value, Sequence) and not isinstance(value, str):
        if len(value) != len(REQUIREMENT_VECTOR_DIMENSIONS):
            msg = (
                "requirement vector sequences must have exactly 8 values; "
                f"{_REQUIREMENT_VECTOR_NEXT_ACTION}"
            )
            raise ValueError(msg)
        items = list(zip(REQUIREMENT_VECTOR_DIMENSIONS, value, strict=True))
    else:
        msg = (
            "requirement vector must be an object keyed by the 8 taxonomy dimensions; "
            f"{_REQUIREMENT_VECTOR_NEXT_ACTION}"
        )
        raise ValueError(msg)

    out: dict[str, int] | dict[str, bool] = {}
    seen: set[str] = set()
    for raw_key, raw_value in items:
        key = _normalize_requirement_dimension(raw_key)
        if key not in _REQUIREMENT_VECTOR_DIMENSION_SET:
            msg = (
                f"unknown requirement vector dimension: {raw_key}; "
                f"{_REQUIREMENT_VECTOR_NEXT_ACTION}"
            )
            raise ValueError(msg)
        if key in seen:
            msg = (
                f"duplicate requirement vector dimension: {key}; {_REQUIREMENT_VECTOR_NEXT_ACTION}"
            )
            raise ValueError(msg)
        seen.add(key)
        out[key] = _coerce_mask_bool(raw_value) if mask else _coerce_requirement_score(raw_value)

    if seen != _REQUIREMENT_VECTOR_DIMENSION_SET:
        missing = sorted(_REQUIREMENT_VECTOR_DIMENSION_SET - seen)
        extra = sorted(seen - _REQUIREMENT_VECTOR_DIMENSION_SET)
        detail = f"missing={missing}"
        if extra:
            detail += f", extra={extra}"
        msg = (
            f"requirement vector must include exactly 8 dimensions ({detail}); "
            f"{_REQUIREMENT_VECTOR_NEXT_ACTION}"
        )
        raise ValueError(msg)
    return out


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
    routing_class: RoutingClassValue = "unknown"
    requirement_vector: dict[str, int] = Field(default_factory=dict)
    composition_tolerance: CompositionToleranceValue = "unknown"
    requirement_vector_validity_mask: dict[str, bool] = Field(default_factory=dict)
    route_envelope: RouteEnvelope | None = None
    task_demand: dict[str, Any] = Field(default_factory=dict)

    intent: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    # File touch-set (paths this task will mutate). Drives the D8 governance floor.
    # Populated by the decomposer (Phase 1 wiring); default empty is additive.
    target_paths: list[str] = Field(default_factory=list)

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

    @field_validator("routing_class", mode="before")
    @classmethod
    def _normalize_routing_class(cls, value: object) -> object:
        if value in (None, ""):
            return "unknown"
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "docs": "docs_planning",
            "planning": "docs_planning",
            "research": "research_support",
            "support": "research_support",
            "source": "source_other",
            "python": "source_python",
            "source_patch": "source_other",
            "source_mutation": "source_other",
            "governance": "source_governance",
            "runtime": "runtime_ops",
            "public": "public_surface",
            "public_claim": "public_surface",
            "spend": "provider_spend",
            "operator": "operator_action",
            "verify": "verification",
            "test": "verification",
            "tests": "verification",
            "relay": "coordination",
        }
        return aliases.get(text, text)

    @field_validator("composition_tolerance", mode="before")
    @classmethod
    def _normalize_composition_tolerance(cls, value: object) -> object:
        if value in (None, ""):
            return "unknown"
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "single": "atomic",
            "single_task": "atomic",
            "independent": "parallel_ok",
            "parallel": "parallel_ok",
            "sequential": "sequential_required",
            "depends": "sequential_required",
            "blocked": "sequential_required",
            "split": "decompose_required",
            "too_large": "decompose_required",
        }
        return aliases.get(text, text)

    @field_validator("requirement_vector", mode="before")
    @classmethod
    def _normalize_requirement_vector(cls, value: object) -> dict[str, int]:
        return dict(_ordered_dimension_mapping(value, mask=False))

    @field_validator("requirement_vector_validity_mask", mode="before")
    @classmethod
    def _normalize_requirement_vector_validity_mask(cls, value: object) -> dict[str, bool]:
        return dict(_ordered_dimension_mapping(value, mask=True))

    @model_validator(mode="after")
    def _normalize_route_metadata(self) -> TaskSpec:
        if (
            self.quality_floor == "frontier_review_required"
            and self.authority_level == "authoritative"
        ):
            self.quality_floor = "frontier_required"
        return self

    @model_validator(mode="after")
    def _taxonomy_payload_is_complete(self) -> TaskSpec:
        has_taxonomy = (
            self.routing_class != "unknown"
            or bool(self.requirement_vector)
            or self.composition_tolerance != "unknown"
            or bool(self.requirement_vector_validity_mask)
        )
        if not has_taxonomy:
            return self
        if not self.requirement_vector:
            raise ValueError(
                "routing taxonomy requires requirement_vector; next action: add one "
                "0-5 score for each taxonomy dimension or omit all taxonomy fields"
            )
        if not self.requirement_vector_validity_mask:
            raise ValueError(
                "routing taxonomy requires requirement_vector_validity_mask; next "
                "action: add true/false validity for each taxonomy dimension or omit "
                "all taxonomy fields"
            )
        return self

    @model_validator(mode="after")
    def _enforce_d8_governance_floor(self) -> TaskSpec:
        # D8: a SOURCE mutation touching a .rs/.wgsl file or a CODEOWNERS-protected
        # path stays frontier — enforced in code here, not in MATRIX prose.
        # (Activation: the decomposer must populate target_paths — Phase 1 wiring.)
        if self.mutation_surface == "source" and any(
            _is_governance_protected_path(p) for p in self.target_paths
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
