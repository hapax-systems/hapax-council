"""LiteLLM-backed cc-task annotation for coordination routing."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.frontmatter import parse_frontmatter
from shared.route_metadata_schema import (
    AuthorityLevel,
    MutationSurface,
    QualityFloor,
    RouteMetadata,
)

DEFAULT_TASK_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"
DEFAULT_STATE_PATH = Path("/dev/shm/hapax-triage/officer-state.json")
DEFAULT_MODEL = "balanced"
DEFAULT_LIMIT = 5
TASK_FRONTMATTER_DEFAULTS: dict[str, Any] = {
    "type": "cc-task",
    "priority": "p2",
    "depends_on": [],
    "blocks": [],
    "branch": None,
    "pr": None,
    "claimed_at": None,
    "completed_at": None,
    "tags": [],
}

AnnotationSource = Literal["deterministic_fallback", "frontier_triage", "operator_override"]
EffortClass = Literal["standard", "high", "max"]
Platform = Literal["claude", "codex", "gemini", "any"]

SOURCE_RANK = {
    "deterministic_fallback": 1,
    "frontier_triage": 2,
    "operator_override": 3,
}


class TaskTriageAnnotation(BaseModel):
    """Structured model output for a single cc-task annotation."""

    model_config = ConfigDict(extra="ignore")

    quality_floor: QualityFloor
    mutation_surface: MutationSurface
    authority_level: AuthorityLevel
    effort_class: EffortClass
    platform_suitability: list[Platform] = Field(min_length=1, max_length=3)
    annotation_confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    reasoning: str = Field(default="Frontier triage completed.", min_length=1, max_length=1200)

    @field_validator("quality_floor", mode="before")
    @classmethod
    def _coerce_quality_floor(cls, value: object) -> object:
        text = _norm(value)
        aliases = {
            "frontier": "frontier_required",
            "frontier_required": "frontier_required",
            "frontier review": "frontier_review_required",
            "frontier_review": "frontier_review_required",
            "frontier_review_required": "frontier_review_required",
            "deterministic": "deterministic_ok",
            "deterministic_ok": "deterministic_ok",
        }
        return aliases.get(text, value)

    @field_validator("mutation_surface", mode="before")
    @classmethod
    def _coerce_mutation_surface(cls, value: object) -> object:
        text = _norm(value)
        aliases = {
            "config": "source",
            "code": "source",
            "docs": "vault_docs",
            "documentation": "vault_docs",
            "vault": "vault_docs",
            "vault_docs": "vault_docs",
            "provider_spend": "provider_spend",
            "provider_billing": "provider_spend",
        }
        return aliases.get(text, value)

    @field_validator("authority_level", mode="before")
    @classmethod
    def _coerce_authority_level(cls, value: object) -> object:
        text = _norm(value)
        aliases = {
            "support": "support_non_authoritative",
            "non_authoritative": "support_non_authoritative",
            "support_non_authoritative": "support_non_authoritative",
            "evidence": "evidence_receipt",
            "receipt": "evidence_receipt",
            "relay": "relay_only",
            "relay_only": "relay_only",
        }
        return aliases.get(text, value)

    @field_validator("effort_class", mode="before")
    @classmethod
    def _coerce_effort_class(cls, value: object) -> object:
        text = _norm(value)
        aliases = {"medium": "standard", "normal": "standard", "low": "standard"}
        return aliases.get(text, value)

    @field_validator("platform_suitability", mode="before")
    @classmethod
    def _coerce_platforms(cls, value: object) -> list[str] | object:
        if isinstance(value, str):
            raw = value.replace("/", ",").split(",")
            return [_platform_alias(item) for item in raw if item.strip()]
        if isinstance(value, (list, tuple, set, frozenset)):
            return [_platform_alias(item) for item in value if str(item).strip()]
        return value

    @field_validator("platform_suitability")
    @classmethod
    def _platforms_are_unique(cls, value: list[Platform]) -> list[Platform]:
        deduped = list(dict.fromkeys(value))
        if "any" in deduped and len(deduped) > 1:
            return ["any"]
        return deduped

    @model_validator(mode="after")
    def _support_artifacts_are_non_authoritative(self) -> TaskTriageAnnotation:
        if (
            self.quality_floor == QualityFloor.FRONTIER_REVIEW_REQUIRED
            and self.authority_level == AuthorityLevel.AUTHORITATIVE
        ):
            self.authority_level = AuthorityLevel.SUPPORT_NON_AUTHORITATIVE
        return self


@dataclass(frozen=True)
class TriageCandidate:
    task_id: str
    path: Path
    title: str
    status: str
    annotation_source: str | None


@dataclass(frozen=True)
class TriageReceipt:
    task_id: str
    path: str
    action: Literal["updated", "would_update", "skipped", "failed"]
    reason: str
    annotation_source: str | None = None


@dataclass
class TriageRun:
    generated_at: str
    model: str
    write: bool
    scanned: int = 0
    candidates: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    receipts: list[TriageReceipt] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["receipts"] = [asdict(receipt) for receipt in self.receipts]
        return data


def run_triage_pass(
    *,
    task_root: Path = DEFAULT_TASK_ROOT,
    state_path: Path = DEFAULT_STATE_PATH,
    model_name: str | None = None,
    write: bool = False,
    limit: int = DEFAULT_LIMIT,
    include_missing: bool = False,
    force: bool = False,
    agent_factory: Any | None = None,
) -> TriageRun:
    """Run a bounded triage pass over active cc-task notes."""
    model = _configured_model(model_name)
    run = TriageRun(generated_at=_now(), model=model, write=write)
    candidates = list(
        iter_candidates(
            task_root=task_root,
            include_missing=include_missing,
            force=force,
        )
    )
    run.scanned = len(list(_iter_task_notes(task_root)))
    run.candidates = len(candidates)

    for candidate in candidates[: max(0, limit)]:
        try:
            if not _can_update(candidate.annotation_source, force=force):
                run.skipped += 1
                run.receipts.append(
                    TriageReceipt(
                        task_id=candidate.task_id,
                        path=str(candidate.path),
                        action="skipped",
                        reason="protected_higher_tier_annotation",
                        annotation_source=candidate.annotation_source,
                    )
                )
                continue

            annotation = annotate_task(
                candidate.path, model_name=model, agent_factory=agent_factory
            )
            if write:
                apply_annotation(candidate.path, annotation, model_name=model)
                action: Literal["updated", "would_update"] = "updated"
                run.updated += 1
            else:
                action = "would_update"
                run.skipped += 1
            run.receipts.append(
                TriageReceipt(
                    task_id=candidate.task_id,
                    path=str(candidate.path),
                    action=action,
                    reason=annotation.reasoning,
                    annotation_source="frontier_triage",
                )
            )
        except Exception as exc:
            run.failed += 1
            run.receipts.append(
                TriageReceipt(
                    task_id=candidate.task_id,
                    path=str(candidate.path),
                    action="failed",
                    reason=f"{type(exc).__name__}: {exc}",
                    annotation_source=candidate.annotation_source,
                )
            )

    write_state(run, state_path)
    return run


def iter_candidates(
    *,
    task_root: Path = DEFAULT_TASK_ROOT,
    include_missing: bool = False,
    force: bool = False,
) -> list[TriageCandidate]:
    candidates: list[TriageCandidate] = []
    for path in _iter_task_notes(task_root):
        frontmatter, _body = parse_frontmatter(path)
        if not frontmatter:
            continue
        status = str(frontmatter.get("status", "")).strip()
        if status in {"done", "closed", "withdrawn", "superseded"}:
            continue
        source = _annotation_source(frontmatter)
        if force or source == "deterministic_fallback" or (include_missing and source is None):
            candidates.append(
                TriageCandidate(
                    task_id=str(frontmatter.get("task_id") or path.stem),
                    path=path,
                    title=str(frontmatter.get("title") or path.stem),
                    status=status,
                    annotation_source=source,
                )
            )
    return candidates


def annotate_task(
    path: Path,
    *,
    model_name: str | None = None,
    agent_factory: Any | None = None,
) -> TaskTriageAnnotation:
    frontmatter, body = parse_frontmatter(path)
    if not frontmatter:
        raise ValueError("task note has no valid frontmatter")
    model = _configured_model(model_name)
    agent = agent_factory(model) if agent_factory else _build_agent(model)
    result = agent.run_sync(_build_prompt(path, frontmatter, body))
    output = result.output
    if isinstance(output, TaskTriageAnnotation):
        return output
    return TaskTriageAnnotation.model_validate(output)


def apply_annotation(
    path: Path,
    annotation: TaskTriageAnnotation,
    *,
    model_name: str | None = None,
    now: datetime | None = None,
) -> None:
    frontmatter, body = parse_frontmatter(path)
    if not frontmatter:
        raise ValueError("task note has no valid frontmatter")

    source = _annotation_source(frontmatter)
    if not _can_update(source, force=False):
        raise ValueError(f"refusing to override higher-tier annotation_source={source!r}")

    timestamp = _iso(now or datetime.now(UTC))
    _ensure_required_task_frontmatter(frontmatter, path)
    route = _route_metadata(annotation)
    updates: dict[str, Any] = {
        "route_metadata_schema": 1,
        "quality_floor": annotation.quality_floor.value,
        "mutation_surface": annotation.mutation_surface.value,
        "authority_level": annotation.authority_level.value,
        "effort_class": annotation.effort_class,
        "platform_suitability": annotation.platform_suitability,
        "route_metadata": route.model_dump(mode="json"),
        "annotation_source": "frontier_triage",
        "annotation_model": _configured_model(model_name),
        "annotation_timestamp": timestamp,
        "annotation_confidence": annotation.annotation_confidence,
        "annotation_reasoning": annotation.reasoning,
        "updated_at": timestamp,
    }
    frontmatter.update(updates)
    path.write_text(_render_note(frontmatter, body), encoding="utf-8")


def write_state(run: TriageRun, state_path: Path = DEFAULT_STATE_PATH) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp.write_text(json.dumps(run.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(state_path)


def repair_required_frontmatter(path: Path) -> None:
    """Add missing required cc-task housekeeping keys without model calls."""
    frontmatter, body = parse_frontmatter(path)
    if not frontmatter:
        raise ValueError("task note has no valid frontmatter")
    _ensure_required_task_frontmatter(frontmatter, path)
    path.write_text(_render_note(frontmatter, body), encoding="utf-8")


def _build_agent(model_name: str):
    from pydantic_ai import Agent

    from shared.config import get_model

    return Agent(get_model(model_name), output_type=TaskTriageAnnotation, output_retries=3)


def _build_prompt(path: Path, frontmatter: dict[str, Any], body: str) -> str:
    fm = yaml.safe_dump(frontmatter, sort_keys=False)
    clipped_body = body[:6000]
    return f"""\
You are the Hapax frontier triage officer. Annotate this cc-task for routing.

Use only these enum values:
- quality_floor: frontier_required, frontier_review_required, deterministic_ok
- mutation_surface: none, vault_docs, source, runtime, public, provider_spend
- authority_level: authoritative, support_non_authoritative, evidence_receipt, relay_only
- effort_class: standard, high, max
- platform_suitability: claude, codex, gemini, any

Rules:
- operator_override outranks frontier_triage; never weaken an operator directive.
- Tasks touching governance, coordination guarantees, cross-runtime dispatch, route policy,
  provider spend, public claims, live egress, or user-facing control surfaces should not be
  downgraded to deterministic_ok.
- frontier_review_required artifacts must be support_non_authoritative and require later
  independent review.
- Prefer codex for bounded implementation/config work, claude for governance or max-effort
  source changes, gemini for research-only tasks.

Task path: {path}

Frontmatter:
---
{fm}---

Body:
{clipped_body}
"""


def _route_metadata(annotation: TaskTriageAnnotation) -> RouteMetadata:
    review_requirement: dict[str, object] = {}
    authority = annotation.authority_level
    if annotation.quality_floor == QualityFloor.FRONTIER_REVIEW_REQUIRED:
        authority = AuthorityLevel.SUPPORT_NON_AUTHORITATIVE
        review_requirement = {
            "support_artifact_allowed": True,
            "independent_review_required": True,
            "authoritative_acceptor_profile": "frontier_full",
        }
    return RouteMetadata.model_validate(
        {
            "route_metadata_schema": 1,
            "quality_floor": annotation.quality_floor.value,
            "authority_level": authority.value,
            "mutation_surface": annotation.mutation_surface.value,
            "route_constraints": {
                "preferred_platforms": annotation.platform_suitability,
                "allowed_platforms": annotation.platform_suitability,
                "prohibited_platforms": [],
            },
            "review_requirement": review_requirement,
        }
    )


def _render_note(frontmatter: dict[str, Any], body: str) -> str:
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False)
    return f"---\n{yaml_text}---\n\n{body.lstrip()}"


def _ensure_required_task_frontmatter(frontmatter: dict[str, Any], path: Path) -> None:
    for key, value in TASK_FRONTMATTER_DEFAULTS.items():
        default = list(value) if isinstance(value, list) else value
        frontmatter.setdefault(key, default)
    frontmatter.setdefault("task_id", path.stem)


def _iter_task_notes(task_root: Path) -> list[Path]:
    active = task_root.expanduser() / "active"
    if not active.is_dir():
        return []
    return sorted(active.glob("*.md"))


def _annotation_source(frontmatter: dict[str, Any]) -> str | None:
    value = frontmatter.get("annotation_source")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _can_update(source: str | None, *, force: bool) -> bool:
    if force:
        return source != "operator_override"
    return SOURCE_RANK.get(source or "", 0) < SOURCE_RANK["frontier_triage"]


def _configured_model(model_name: str | None = None) -> str:
    raw = (
        model_name
        or os.environ.get("HAPAX_TRIAGE_MODEL")
        or os.environ.get("SDLC_TRIAGE_MODEL", DEFAULT_MODEL)
    )
    raw = raw.strip()
    for prefix in ("anthropic:", "anthropic/"):
        if raw.startswith(prefix):
            return raw.removeprefix(prefix)
    return raw


def _norm(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _platform_alias(value: object) -> str:
    text = _norm(value)
    aliases = {
        "claude_code": "claude",
        "anthropic": "claude",
        "codex_cli": "codex",
        "openai": "codex",
        "gemini_cli": "gemini",
        "google": "gemini",
        "all": "any",
        "either": "any",
    }
    return aliases.get(text, text)


def _now() -> str:
    return _iso(datetime.now(UTC))


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def run_forever(
    *,
    task_root: Path = DEFAULT_TASK_ROOT,
    state_path: Path = DEFAULT_STATE_PATH,
    model_name: str | None = None,
    write: bool = False,
    limit: int = DEFAULT_LIMIT,
    include_missing: bool = False,
    interval_s: float = 900.0,
) -> None:
    while True:
        run_triage_pass(
            task_root=task_root,
            state_path=state_path,
            model_name=model_name,
            write=write,
            limit=limit,
            include_missing=include_missing,
        )
        time.sleep(max(1.0, interval_s))
