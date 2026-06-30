"""Admission gate for autonomous background model/tool capability use.

Background services do not launch SDLC lanes, but they still consume model,
tool, quota, and runtime-mutation capability. This module gives those call
sites a small fail-closed wrapper around the existing dispatch policy read
path: load task authority, build a normal DispatchRequest, evaluate policy,
and only admit when the policy returns LAUNCH.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from shared.dispatcher_policy import (
    DispatchAction,
    RouteDecision,
    build_dispatch_request,
    evaluate_dispatch_policy,
    load_dispatch_policy_sources,
    write_route_decision_receipt,
)
from shared.frontmatter import parse_frontmatter
from shared.platform_capability_registry import normalize_route_id

BACKGROUND_CAPABILITY_TASK_NOTE_ENV = "HAPAX_BACKGROUND_CAPABILITY_TASK_NOTE"
BACKGROUND_CAPABILITY_LANE_ENV = "HAPAX_BACKGROUND_CAPABILITY_LANE"
BACKGROUND_CAPABILITY_RECEIPTS_ENV = "HAPAX_BACKGROUND_CAPABILITY_RECEIPTS"


@dataclass(frozen=True)
class BackgroundCapabilityAdmission:
    """Result of one background capability admission check."""

    capability_name: str
    route_id: str
    model_alias: str | None = None
    admitted: bool = False
    denied_reason: str | None = None
    reason_codes: tuple[str, ...] = ()
    policy_outcome: str | None = None
    route_decision_id: str | None = None
    task_id: str | None = None
    authority_case: str | None = None
    parent_spec: str | None = None
    mutation_surface: str | None = None
    quality_floor: str | None = None
    authority_level: str | None = None
    model_descriptor: dict[str, object] = field(default_factory=dict)
    quota_evidence_refs: tuple[str, ...] = ()
    resource_state_refs: tuple[str, ...] = ()
    receipt_path: str | None = None

    def denial_summary(self) -> str:
        if self.reason_codes:
            return ",".join(self.reason_codes)
        return self.denied_reason or "background_capability_admission_denied"

    def metadata(self) -> dict[str, object]:
        """Compact JSON-safe metadata for downstream receipts/logs."""

        data: dict[str, object] = {
            "capability_name": self.capability_name,
            "route_id": self.route_id,
            "admitted": self.admitted,
        }
        optional: dict[str, object | None] = {
            "model_alias": self.model_alias,
            "denied_reason": self.denied_reason,
            "policy_outcome": self.policy_outcome,
            "route_decision_id": self.route_decision_id,
            "task_id": self.task_id,
            "authority_case": self.authority_case,
            "parent_spec": self.parent_spec,
            "mutation_surface": self.mutation_surface,
            "quality_floor": self.quality_floor,
            "authority_level": self.authority_level,
            "receipt_path": self.receipt_path,
        }
        for key, value in optional.items():
            if value is not None:
                data[key] = value
        if self.reason_codes:
            data["reason_codes"] = list(self.reason_codes)
        if self.model_descriptor:
            data["model_descriptor"] = self.model_descriptor
        if self.quota_evidence_refs:
            data["quota_evidence_refs"] = list(self.quota_evidence_refs)
        if self.resource_state_refs:
            data["resource_state_refs"] = list(self.resource_state_refs)
        return data


def admit_background_capability(
    *,
    capability_name: str,
    route_id: str,
    model_alias: str | None = None,
    task_note_path: Path | str | None = None,
    task_fields: Mapping[str, Any] | None = None,
    lane: str | None = None,
    mutation_surface: str = "none",
    quality_floor: str | None = None,
    authority_level: str | None = None,
    registry_path: Path | None = None,
    quota_ledger_path: Path | None = None,
    receipt_dir: Path | None = None,
    now: datetime | None = None,
    write_receipt: bool | None = None,
) -> BackgroundCapabilityAdmission:
    """Return a fail-closed background capability admission decision.

    ``task_fields`` is primarily a test seam. Production call sites should pass
    ``task_note_path`` or set ``HAPAX_BACKGROUND_CAPABILITY_TASK_NOTE`` so the
    admission is tied to an explicit task/authority context.
    """

    normalized_route_id = normalize_route_id(route_id)
    try:
        platform, mode, profile = _split_route_id(normalized_route_id)
    except ValueError as exc:
        return _denied(
            capability_name=capability_name,
            route_id=normalized_route_id,
            model_alias=model_alias,
            denied_reason=str(exc),
            mutation_surface=mutation_surface,
            quality_floor=quality_floor,
            authority_level=authority_level,
        )

    resolved_task_path = _resolve_task_note_path(task_note_path)
    fields = dict(task_fields or {})
    if not fields:
        if resolved_task_path is None:
            return _denied(
                capability_name=capability_name,
                route_id=normalized_route_id,
                model_alias=model_alias,
                denied_reason=(f"task_note_absent:{BACKGROUND_CAPABILITY_TASK_NOTE_ENV} not set"),
                mutation_surface=mutation_surface,
                quality_floor=quality_floor,
                authority_level=authority_level,
            )
        try:
            fields, _body = parse_frontmatter(resolved_task_path)
        except Exception as exc:
            return _denied(
                capability_name=capability_name,
                route_id=normalized_route_id,
                model_alias=model_alias,
                denied_reason=f"task_note_unreadable:{resolved_task_path}:{exc}",
                mutation_surface=mutation_surface,
                quality_floor=quality_floor,
                authority_level=authority_level,
            )
        if not fields:
            return _denied(
                capability_name=capability_name,
                route_id=normalized_route_id,
                model_alias=model_alias,
                denied_reason=f"task_note_unreadable:{resolved_task_path}",
                mutation_surface=mutation_surface,
                quality_floor=quality_floor,
                authority_level=authority_level,
            )
        fields["__task_note_path"] = str(resolved_task_path)

    task_id = _string_field(fields, "task_id")
    authority_case = _string_field(fields, "authority_case")
    if not task_id:
        return _denied(
            capability_name=capability_name,
            route_id=normalized_route_id,
            model_alias=model_alias,
            denied_reason="task_id_absent",
            mutation_surface=mutation_surface,
            quality_floor=quality_floor,
            authority_level=authority_level,
        )
    if not authority_case:
        return _denied(
            capability_name=capability_name,
            route_id=normalized_route_id,
            model_alias=model_alias,
            denied_reason="authority_case_absent",
            task_id=task_id,
            mutation_surface=mutation_surface,
            quality_floor=quality_floor,
            authority_level=authority_level,
        )

    invocation_fields = dict(fields)
    invocation_fields["mutation_surface"] = mutation_surface
    if quality_floor is not None:
        invocation_fields["quality_floor"] = quality_floor
    if authority_level is not None:
        invocation_fields["authority_level"] = authority_level

    try:
        sources = load_dispatch_policy_sources(
            registry_path=registry_path,
            quota_ledger_path=quota_ledger_path,
            receipt_dir=receipt_dir,
            now=now,
        )
        request = build_dispatch_request(
            task_id=task_id,
            lane=lane or os.environ.get(BACKGROUND_CAPABILITY_LANE_ENV, "background"),
            platform=platform,
            mode=mode,
            profile=profile,
            task_fields=invocation_fields,
            registry=sources.registry,
            registry_error=sources.registry_error,
            quota_ledger=sources.quota_ledger,
            quota_error=sources.quota_error,
            route_authority_receipts=sources.route_authority_receipts,
            now=now,
        )
        decision = evaluate_dispatch_policy(request, now=now)
    except Exception as exc:
        return _denied(
            capability_name=capability_name,
            route_id=normalized_route_id,
            model_alias=model_alias,
            denied_reason=f"admission_error:{exc}",
            task_id=task_id,
            authority_case=authority_case,
            parent_spec=_string_field(invocation_fields, "parent_spec"),
            mutation_surface=mutation_surface,
            quality_floor=quality_floor or _string_field(invocation_fields, "quality_floor"),
            authority_level=authority_level or _string_field(invocation_fields, "authority_level"),
        )

    receipt_path = _write_decision_receipt(decision, enabled=write_receipt)
    descriptor = _model_descriptor(sources.registry, normalized_route_id)
    return BackgroundCapabilityAdmission(
        capability_name=capability_name,
        route_id=normalized_route_id,
        model_alias=model_alias,
        admitted=decision.action is DispatchAction.LAUNCH and decision.launch_allowed,
        denied_reason=None
        if decision.action is DispatchAction.LAUNCH and decision.launch_allowed
        else "route_policy_denied",
        reason_codes=tuple(decision.reason_codes),
        policy_outcome=decision.policy_outcome,
        route_decision_id=decision.decision_id,
        task_id=task_id,
        authority_case=authority_case,
        parent_spec=_string_field(invocation_fields, "parent_spec"),
        mutation_surface=request.mutation_surface,
        quality_floor=request.quality_floor,
        authority_level=request.authority_level,
        model_descriptor=descriptor,
        quota_evidence_refs=tuple(decision.quota_evidence_refs),
        resource_state_refs=tuple(decision.resource_state_refs),
        receipt_path=str(receipt_path) if receipt_path is not None else None,
    )


def _denied(
    *,
    capability_name: str,
    route_id: str,
    model_alias: str | None,
    denied_reason: str,
    task_id: str | None = None,
    authority_case: str | None = None,
    parent_spec: str | None = None,
    mutation_surface: str | None = None,
    quality_floor: str | None = None,
    authority_level: str | None = None,
) -> BackgroundCapabilityAdmission:
    return BackgroundCapabilityAdmission(
        capability_name=capability_name,
        route_id=route_id,
        model_alias=model_alias,
        admitted=False,
        denied_reason=denied_reason,
        task_id=task_id,
        authority_case=authority_case,
        parent_spec=parent_spec,
        mutation_surface=mutation_surface,
        quality_floor=quality_floor,
        authority_level=authority_level,
    )


def _resolve_task_note_path(path: Path | str | None) -> Path | None:
    configured = str(path or os.environ.get(BACKGROUND_CAPABILITY_TASK_NOTE_ENV, "")).strip()
    if not configured:
        return None
    return Path(configured).expanduser()


def _split_route_id(route_id: str) -> tuple[str, str, str]:
    parts = route_id.split(".")
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"invalid_route_id:{route_id}")
    return parts[0], parts[1], parts[2]


def _string_field(fields: Mapping[str, Any], key: str) -> str | None:
    value = fields.get(key)
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"null", "None"}:
        return None
    return text


def _write_decision_receipt(
    decision: RouteDecision,
    *,
    enabled: bool | None,
) -> Path | None:
    if enabled is None:
        configured = os.environ.get(BACKGROUND_CAPABILITY_RECEIPTS_ENV, "1").strip().lower()
        enabled = configured not in {"0", "false", "off", "no"}
    if not enabled:
        return None
    return write_route_decision_receipt(decision)


def _model_descriptor(registry: Any, route_id: str) -> dict[str, object]:
    if registry is None:
        return {}
    route = registry.route_map().get(normalize_route_id(route_id))
    if route is None:
        return {}
    descriptor = route.execution_descriptor.model_dump(mode="json")
    return {
        "route_model_or_engine": route.model_or_engine,
        "execution_descriptor": descriptor,
        "selected_descriptor_leaf": route_id,
    }


__all__ = [
    "BACKGROUND_CAPABILITY_LANE_ENV",
    "BACKGROUND_CAPABILITY_RECEIPTS_ENV",
    "BACKGROUND_CAPABILITY_TASK_NOTE_ENV",
    "BackgroundCapabilityAdmission",
    "admit_background_capability",
]
