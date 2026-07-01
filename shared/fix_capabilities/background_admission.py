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

_SURFACE_AUTH_FLAGS: dict[str, str] = {
    "provider_spend": "provider_spend_authorized",
    "runtime": "runtime_mutation_authorized",
    "source": "source_mutation_authorized",
    "vault_docs": "docs_mutation_authorized",
    "docs": "docs_mutation_authorized",
    "public": "release_authorized",
}

_QUALITY_FLOOR_ORDER: dict[str, int] = {
    "deterministic_ok": 0,
    "capable_sufficient": 1,
    "frontier_preferred": 2,
    "frontier_required": 3,
    "frontier_review_required": 4,
}

_AUTHORITY_LEVEL_ORDER: dict[str, int] = {
    "support_only": 0,
    "support_non_authoritative": 1,
    "authoritative": 2,
}

_ACTIVE_TASK_STATUSES: frozenset[str] = frozenset({"claimed", "in_progress", "pr_open"})
_UNASSIGNED_VALUES: frozenset[str] = frozenset({"", "null", "none", "unassigned"})


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
    lifecycle_blocker = _task_lifecycle_blocker(fields)
    if lifecycle_blocker is not None:
        reason, code = lifecycle_blocker
        return _denied(
            capability_name=capability_name,
            route_id=normalized_route_id,
            model_alias=model_alias,
            denied_reason=reason,
            reason_codes=(code,),
            task_id=task_id,
            authority_case=authority_case,
            mutation_surface=mutation_surface,
            quality_floor=quality_floor or _string_field(fields, "quality_floor"),
            authority_level=authority_level or _string_field(fields, "authority_level"),
        )
    parent_spec = _string_field(fields, "parent_spec")
    if not parent_spec:
        return _denied(
            capability_name=capability_name,
            route_id=normalized_route_id,
            model_alias=model_alias,
            denied_reason="parent_spec_absent",
            reason_codes=("parent_spec_absent",),
            task_id=task_id,
            authority_case=authority_case,
            mutation_surface=mutation_surface,
            quality_floor=quality_floor or _string_field(fields, "quality_floor"),
            authority_level=authority_level or _string_field(fields, "authority_level"),
        )

    authority_blocker = _invocation_authority_blocker(
        fields,
        mutation_surface=mutation_surface,
        quality_floor=quality_floor,
        authority_level=authority_level,
    )
    if authority_blocker is not None:
        reason, code = authority_blocker
        return _denied(
            capability_name=capability_name,
            route_id=normalized_route_id,
            model_alias=model_alias,
            denied_reason=reason,
            reason_codes=(code,),
            task_id=task_id,
            authority_case=authority_case,
            parent_spec=_string_field(fields, "parent_spec"),
            mutation_surface=mutation_surface,
            quality_floor=quality_floor or _string_field(fields, "quality_floor"),
            authority_level=authority_level or _string_field(fields, "authority_level"),
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
        model_blocker = _model_binding_blocker(
            sources.registry,
            route_id=normalized_route_id,
            model_alias=model_alias,
            mutation_surface=mutation_surface,
        )
        if model_blocker is not None:
            reason, code = model_blocker
            return _denied(
                capability_name=capability_name,
                route_id=normalized_route_id,
                model_alias=model_alias,
                denied_reason=reason,
                reason_codes=(code,),
                task_id=task_id,
                authority_case=authority_case,
                parent_spec=_string_field(invocation_fields, "parent_spec"),
                mutation_surface=mutation_surface,
                quality_floor=quality_floor or _string_field(invocation_fields, "quality_floor"),
                authority_level=authority_level
                or _string_field(invocation_fields, "authority_level"),
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

    try:
        receipt_path = _write_decision_receipt(decision, enabled=write_receipt)
    except Exception as exc:
        return _denied(
            capability_name=capability_name,
            route_id=normalized_route_id,
            model_alias=model_alias,
            denied_reason=f"route_decision_receipt_write_failed:{exc}",
            reason_codes=("route_decision_receipt_write_failed",),
            task_id=task_id,
            authority_case=authority_case,
            parent_spec=_string_field(invocation_fields, "parent_spec"),
            mutation_surface=mutation_surface,
            quality_floor=quality_floor or _string_field(invocation_fields, "quality_floor"),
            authority_level=authority_level or _string_field(invocation_fields, "authority_level"),
        )
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
    reason_codes: tuple[str, ...] = (),
) -> BackgroundCapabilityAdmission:
    return BackgroundCapabilityAdmission(
        capability_name=capability_name,
        route_id=route_id,
        model_alias=model_alias,
        admitted=False,
        denied_reason=denied_reason,
        reason_codes=reason_codes,
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


def _task_lifecycle_blocker(fields: Mapping[str, Any]) -> tuple[str, str] | None:
    status = (_string_field(fields, "status") or "").lower()
    assigned_to = (_string_field(fields, "assigned_to") or "").lower()
    if status not in _ACTIVE_TASK_STATUSES:
        return (
            f"inactive_task_status:status={status or '<absent>'}",
            "inactive_task_status",
        )
    if assigned_to in _UNASSIGNED_VALUES:
        return (
            f"inactive_task_assignee:assigned_to={assigned_to or '<absent>'}",
            "inactive_task_assignee",
        )
    return None


def _invocation_authority_blocker(
    fields: Mapping[str, Any],
    *,
    mutation_surface: str,
    quality_floor: str | None,
    authority_level: str | None,
) -> tuple[str, str] | None:
    surface_blocker = _mutation_surface_blocker(fields, mutation_surface)
    if surface_blocker is not None:
        return surface_blocker
    if quality_floor is not None:
        quality_blocker = _ordered_field_blocker(
            fields,
            key="quality_floor",
            requested=quality_floor,
            order=_QUALITY_FLOOR_ORDER,
            code="task_quality_floor_not_authorized",
        )
        if quality_blocker is not None:
            return quality_blocker
    if authority_level is not None:
        return _ordered_field_blocker(
            fields,
            key="authority_level",
            requested=authority_level,
            order=_AUTHORITY_LEVEL_ORDER,
            code="task_authority_level_not_authorized",
        )
    return None


def _mutation_surface_blocker(
    fields: Mapping[str, Any],
    requested_surface: str,
) -> tuple[str, str] | None:
    requested = requested_surface.strip() or "none"
    if requested == "none":
        return None

    declared = _declared_mutation_surfaces(fields)
    flag_key = _SURFACE_AUTH_FLAGS.get(requested)
    if flag_key is not None and flag_key in fields and not _truthy_field(fields, flag_key):
        return (
            f"task_mutation_surface_not_authorized:requested={requested} "
            f"declared={_surface_summary(declared)} flag={flag_key}:false",
            "task_mutation_surface_not_authorized",
        )
    if requested in declared:
        return None
    if flag_key is not None and _truthy_field(fields, flag_key):
        return None
    return (
        f"task_mutation_surface_not_authorized:requested={requested} "
        f"declared={_surface_summary(declared)} flag={flag_key or 'none'}",
        "task_mutation_surface_not_authorized",
    )


def _declared_mutation_surfaces(fields: Mapping[str, Any]) -> frozenset[str]:
    surfaces: set[str] = set()
    for key in ("mutation_surface", "mutation_surfaces"):
        raw = fields.get(key)
        if raw is None:
            continue
        if isinstance(raw, str):
            values = raw.split(",")
        elif isinstance(raw, (list, tuple, set, frozenset)):
            values = raw
        else:
            values = (raw,)
        for value in values:
            text = str(value).strip()
            if text and text not in {"null", "None"}:
                surfaces.add(text)
    return frozenset(surfaces)


def _surface_summary(surfaces: frozenset[str]) -> str:
    return ",".join(sorted(surfaces)) if surfaces else "none"


def _truthy_field(fields: Mapping[str, Any], key: str) -> bool:
    value = fields.get(key)
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _ordered_field_blocker(
    fields: Mapping[str, Any],
    *,
    key: str,
    requested: str,
    order: Mapping[str, int],
    code: str,
) -> tuple[str, str] | None:
    declared = _string_field(fields, key)
    normalized_requested = requested.strip()
    if not declared:
        return (
            f"{code}:requested={normalized_requested} declared=absent",
            code,
        )
    declared_rank = order.get(declared)
    requested_rank = order.get(normalized_requested)
    if declared_rank is None or requested_rank is None:
        if declared == normalized_requested:
            return None
    elif requested_rank <= declared_rank:
        return None
    return (
        f"{code}:requested={normalized_requested} declared={declared}",
        code,
    )


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
        "provider_model_aliases": [
            alias.model_dump(mode="json") for alias in getattr(route, "provider_model_aliases", ())
        ],
        "selected_descriptor_leaf": route_id,
    }


def _model_binding_blocker(
    registry: Any,
    *,
    route_id: str,
    model_alias: str | None,
    mutation_surface: str,
) -> tuple[str, str] | None:
    if model_alias is None:
        return None
    requested = model_alias.strip()
    if not requested:
        return None
    if registry is None:
        return (
            f"provider_model_binding_unverifiable:route={route_id} model={requested}",
            "provider_model_binding_unverifiable",
        )
    route = registry.route_map().get(normalize_route_id(route_id))
    if route is None:
        return (
            f"model_route_unregistered:route={route_id} model={requested}",
            "model_route_unregistered",
        )
    descriptor = route.execution_descriptor
    allowed = {
        str(route.model_or_engine or "").strip(),
        str(descriptor.model_id).strip(),
    }
    model_fingerprint = getattr(descriptor, "model_fingerprint", None)
    if model_fingerprint is not None:
        allowed.add(str(model_fingerprint).strip())
    allowed.discard("")
    if requested in allowed:
        return None
    if mutation_surface != "provider_spend":
        return (
            "model_descriptor_mismatch:"
            f"route={route_id} requested_model={requested} "
            f"route_models={','.join(sorted(allowed)) or 'none'}",
            "model_descriptor_mismatch",
        )
    for alias in getattr(route, "provider_model_aliases", ()):
        alias_keys = {str(alias.alias).strip(), str(alias.model_id).strip()}
        if requested in alias_keys:
            route_provider = str(getattr(route, "paid_provider", "") or "").strip()
            alias_provider = str(alias.provider).strip()
            if route_provider and alias_provider and alias_provider != route_provider:
                return (
                    "provider_alias_paid_provider_mismatch:"
                    f"route={route_id} requested_model={requested} "
                    f"alias_provider={alias_provider} route_paid_provider={route_provider}",
                    "provider_alias_paid_provider_mismatch",
                )
            return None
    return (
        "provider_model_descriptor_mismatch:"
        f"route={route_id} requested_model={requested} "
        f"route_models={','.join(sorted(allowed)) or 'none'}",
        "provider_model_descriptor_mismatch",
    )


__all__ = [
    "BACKGROUND_CAPABILITY_LANE_ENV",
    "BACKGROUND_CAPABILITY_RECEIPTS_ENV",
    "BACKGROUND_CAPABILITY_TASK_NOTE_ENV",
    "BackgroundCapabilityAdmission",
    "admit_background_capability",
]
