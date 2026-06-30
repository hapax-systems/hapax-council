"""Manifest-backed MCP/app connector classification and receipt checks.

Read-only MCP tools are evidence sources. Side-effecting MCP/app connector tools
are capabilities: they require the normal task/authority gate plus fresh route,
quota, resource, and route-authority receipt evidence before execution.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

EFFECT_READ_ONLY = "read_only_evidence"
EFFECT_LOCAL = "local_mutation"
EFFECT_EXTERNAL = "external_mutation"
EFFECT_PUBLIC = "public_egress"
EFFECT_PROVIDER_SPEND = "money_resource_mutation"
EFFECT_GOVERNANCE = "governance_mutation"

MUTATING_EFFECTS = frozenset(
    {
        EFFECT_LOCAL,
        EFFECT_EXTERNAL,
        EFFECT_PUBLIC,
        EFFECT_PROVIDER_SPEND,
        EFFECT_GOVERNANCE,
    }
)
EFFECT_TO_SURFACE = {
    EFFECT_LOCAL: "local",
    EFFECT_EXTERNAL: "external",
    EFFECT_PUBLIC: "public",
    EFFECT_PROVIDER_SPEND: "provider_spend",
    EFFECT_GOVERNANCE: "governance",
}

DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "config" / ("mcp-connector-tool-manifest.json")
)
DEFAULT_ROUTE_DECISION_LEDGER = (
    Path.home() / ".cache" / "hapax" / "orchestration" / "route-decisions.jsonl"
)
DEFAULT_RECEIPT_DIR = Path.home() / ".cache" / "hapax" / "platform-capability-receipts"
RECEIPT_DIR_ENV = "HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR"
ROUTE_DECISION_LEDGER_ENV = "HAPAX_ROUTE_DECISION_LEDGER"
ROUTE_DECISION_MAX_AGE_SECONDS = 24 * 60 * 60

_SERVICE_ALIASES = {
    "codex_apps": "codex_apps",
    "google_calendar": "calendar",
    "calendar": "calendar",
    "google_drive": "drive",
    "drive": "drive",
    "hapax-mcp": "hapax",
    "hapax_mcp": "hapax",
    "hapax": "hapax",
}
_KNOWN_CONNECTOR_SERVICES = frozenset(
    {
        "calendar",
        "context7",
        "drive",
        "github",
        "gmail",
        "hapax",
        "tavily",
    }
)
_MUTATING_FUNCTION_RE = re.compile(
    r"^(?:"
    r"act|add|apply|archive|batch_modify|batch_update|bulk_label|bulk_update|close|confirm"
    r"|copy|correct|create|decide|delete|disable|dismiss|flush|forward|import|merge"
    r"|modify|move|nudge_act|enable|push|rename|remove|replace|reply|reopen|respond"
    r"|restore|send|set|share|trash|update|upload|write"
    r")(?:_|$)"
)
_READ_ONLY_FUNCTION_RE = re.compile(
    r"^(?:"
    r"batch_read|briefing|chronicle(?:_narrate)?|copilot|cost|daily_summary|drift"
    r"|fetch|get|goals|gpu|health|infrastructure|list|manual|profile(?:_|$)"
    r"|query|read|readiness|resolve|scout(?:_|$)|search|status|workspace"
    r"|working_mode$|cycle_mode$|nudges$|agents$|accommodations$"
    r")"
)


@dataclass(frozen=True)
class ConnectorToolClassification:
    """Normalized connector tool classification."""

    canonical_name: str
    effect_classes: tuple[str, ...]
    required_mutation_surfaces: tuple[str, ...]
    description: str = ""
    matched_by: str = "manifest"

    @property
    def side_effecting(self) -> bool:
        return bool(set(self.effect_classes) & MUTATING_EFFECTS)


@dataclass(frozen=True)
class ConnectorReceiptGateResult:
    """Decision returned by the connector receipt gate."""

    allowed: bool
    reason_code: str
    message: str
    classification: ConnectorToolClassification | None = None
    route_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    receipt_ref: str | None = None


def canonicalize_tool_name(tool_name: str) -> str:
    """Normalize Claude/Codex MCP and app connector spellings to service.tool."""

    name = (tool_name or "").strip()
    if not name:
        return ""
    name = name.replace("-", "_")
    if name.startswith("functions."):
        name = name.split(".", 1)[1]
    if name.startswith("mcp__"):
        parts = [part.strip("_") for part in name.split("__") if part.strip("_")]
        if len(parts) >= 3 and parts[0] == "mcp":
            if parts[1] == "codex_apps" and len(parts) >= 4:
                service = _SERVICE_ALIASES.get(parts[2], parts[2])
                function = "_".join(parts[3:]).lstrip("_")
                return f"{service}.{function}"
            service = _SERVICE_ALIASES.get(parts[1], parts[1])
            function = "_".join(parts[2:]).lstrip("_")
            return f"{service}.{function}"
    if "." in name:
        service, function = name.split(".", 1)
        service = _SERVICE_ALIASES.get(service, service)
        function = function.lstrip("_").replace("._", ".")
        return f"{service}.{function}"
    return name.lstrip("_")


def _surfaces_for_effects(effect_classes: tuple[str, ...]) -> tuple[str, ...]:
    surfaces = ["connector"]
    for effect in effect_classes:
        surface = EFFECT_TO_SURFACE.get(effect)
        if surface:
            surfaces.append(surface)
    return tuple(dict.fromkeys(surfaces))


def _classification_from_entry(
    entry: dict[str, Any], *, canonical_name: str, matched_by: str
) -> ConnectorToolClassification:
    effect_classes = tuple(entry.get("effect_classes") or ())
    required = tuple(
        entry.get("required_mutation_surfaces") or _surfaces_for_effects(effect_classes)
    )
    return ConnectorToolClassification(
        canonical_name=canonical_name,
        effect_classes=effect_classes,
        required_mutation_surfaces=required,
        description=str(entry.get("description") or ""),
        matched_by=matched_by,
    )


@lru_cache(maxsize=1)
def _manifest_index() -> dict[str, ConnectorToolClassification]:
    payload = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported MCP connector manifest schema")
    index: dict[str, ConnectorToolClassification] = {}
    for entry in payload.get("tools", []):
        canonical = canonicalize_tool_name(str(entry["canonical_name"]))
        classification = _classification_from_entry(
            entry, canonical_name=canonical, matched_by="manifest"
        )
        index[canonical] = classification
        for alias in entry.get("aliases", []):
            index[canonicalize_tool_name(str(alias))] = classification
    return index


def _heuristic_classification(canonical_name: str) -> ConnectorToolClassification | None:
    if "." not in canonical_name:
        return None
    service, function = canonical_name.split(".", 1)
    function = function.lstrip("_")
    if _READ_ONLY_FUNCTION_RE.match(function):
        return ConnectorToolClassification(
            canonical_name=canonical_name,
            effect_classes=(EFFECT_READ_ONLY,),
            required_mutation_surfaces=(),
            description="Heuristically classified read-only connector evidence tool.",
            matched_by="heuristic_read_only",
        )
    if not _MUTATING_FUNCTION_RE.match(function):
        return None
    if service not in _KNOWN_CONNECTOR_SERVICES:
        effects = [EFFECT_EXTERNAL]
        if function.startswith(("send", "share", "reply", "forward", "publish", "post")):
            effects.append(EFFECT_PUBLIC)
        effect_tuple = tuple(dict.fromkeys(effects))
        return ConnectorToolClassification(
            canonical_name=canonical_name,
            effect_classes=effect_tuple,
            required_mutation_surfaces=_surfaces_for_effects(effect_tuple),
            description="Heuristically classified side-effecting unknown connector tool.",
            matched_by="heuristic_unknown_mutating_verb",
        )
    effects: list[str]
    if service == "github":
        effects = [EFFECT_EXTERNAL, EFFECT_PUBLIC, EFFECT_GOVERNANCE]
    elif service in {"gmail", "calendar", "drive"}:
        effects = [EFFECT_EXTERNAL]
        if function.startswith(("send", "share", "create_event", "update_event", "respond")):
            effects.append(EFFECT_PUBLIC)
    elif service == "hapax":
        effects = [EFFECT_LOCAL, EFFECT_GOVERNANCE]
    elif service == "tavily":
        effects = [EFFECT_PROVIDER_SPEND]
    else:
        effects = [EFFECT_EXTERNAL]
    effect_tuple = tuple(dict.fromkeys(effects))
    return ConnectorToolClassification(
        canonical_name=canonical_name,
        effect_classes=effect_tuple,
        required_mutation_surfaces=_surfaces_for_effects(effect_tuple),
        description="Heuristically classified side-effecting connector tool.",
        matched_by="heuristic_mutating_verb",
    )


def classify_connector_tool(tool_name: str) -> ConnectorToolClassification | None:
    """Return connector classification, or None when the tool is outside this policy."""

    canonical = canonicalize_tool_name(tool_name)
    if not canonical:
        return None
    manifest_match = _manifest_index().get(canonical)
    if manifest_match is not None:
        return manifest_match
    return _heuristic_classification(canonical)


def is_side_effecting_connector_tool(tool_name: str) -> bool:
    classification = classify_connector_tool(tool_name)
    return bool(classification and classification.side_effecting)


def _ledger_path(path: str | Path | None) -> Path:
    if path:
        return Path(path)
    env_value = os.environ.get(ROUTE_DECISION_LEDGER_ENV)
    return Path(env_value) if env_value else DEFAULT_ROUTE_DECISION_LEDGER


def _receipt_root(path: str | Path | None) -> Path | None:
    if path:
        return Path(path)
    env_value = os.environ.get(RECEIPT_DIR_ENV)
    if env_value is not None and env_value.strip().lower() in {"", "0", "none", "false"}:
        return None
    return Path(env_value) if env_value else DEFAULT_RECEIPT_DIR


def _parse_dt(value: Any) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, UTC)
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.fromtimestamp(0, UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _latest_route_decision(
    *, task_id: str, role: str | None, ledger_path: Path
) -> dict[str, Any] | None:
    if not ledger_path.is_file():
        return None
    latest: dict[str, Any] | None = None
    latest_at = datetime.fromtimestamp(0, UTC)
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("task_id") != task_id:
            continue
        if role and row.get("lane") not in {role, None, ""}:
            continue
        created_at = _parse_dt(row.get("created_at") or row.get("ts"))
        if latest is None or created_at >= latest_at:
            latest = row
            latest_at = created_at
    return latest


def _sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value if str(item))
    return ()


def _route_decision_refusal(row: dict[str, Any] | None, *, now: datetime) -> str | None:
    if row is None:
        return "route_decision_absent"
    created_at = _parse_dt(row.get("created_at") or row.get("ts"))
    age_s = (now - created_at).total_seconds()
    if age_s < 0:
        return "route_decision_from_future"
    if age_s > ROUTE_DECISION_MAX_AGE_SECONDS:
        return "route_decision_stale"
    if row.get("route_id") in {None, ""}:
        return "route_id_absent"
    if row.get("action") != "launch" or row.get("launch_allowed") is not True:
        return "route_launch_not_allowed"
    if row.get("route_policy_green") is not True:
        return "route_policy_not_green"
    if row.get("authority_allowed") is not True:
        return "route_authority_not_allowed"
    if row.get("quota_freshness_green") is not True:
        return "quota_freshness_not_green"
    if not _sequence(row.get("quota_evidence_refs")):
        return "quota_evidence_refs_absent"
    if row.get("resource_freshness_green") is not True:
        return "resource_freshness_not_green"
    if not _sequence(row.get("resource_state_refs")):
        return "resource_state_refs_absent"
    return None


def _load_route_receipts(receipt_root: Path):
    from pydantic import ValidationError

    from shared.dispatcher_policy import RouteAuthorityReceipt

    receipt_dir = receipt_root / "route-authority"
    if not receipt_dir.is_dir():
        return ()
    receipts = []
    for path in sorted(receipt_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            receipts.append(RouteAuthorityReceipt.model_validate(payload))
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise ValueError(f"invalid route authority receipt at {path}: {exc}") from exc
    return tuple(receipts)


def _connector_receipt_match(
    *,
    route_id: str,
    task_id: str,
    required_surfaces: tuple[str, ...],
    receipt_root: Path,
    now: datetime,
) -> tuple[str | None, str | None]:
    from shared.dispatcher_policy import (
        _route_authority_receipt_is_fresh,
        route_authority_receipt_reference,
    )
    from shared.platform_capability_registry import normalize_route_id

    receipts = _load_route_receipts(receipt_root)
    connector_receipts = tuple(
        receipt for receipt in receipts if receipt.receipt_type == "connector_mutation"
    )
    if not connector_receipts:
        return "connector_mutation_receipt_absent", None

    route_matches = tuple(
        receipt
        for receipt in connector_receipts
        if normalize_route_id(receipt.route_id) == normalize_route_id(route_id)
    )
    if not route_matches:
        return "connector_mutation_route_mismatch", None

    task_matches = tuple(receipt for receipt in route_matches if task_id in receipt.task_ids)
    if not task_matches:
        return "connector_mutation_task_mismatch", None

    required = set(required_surfaces)
    surface_matches = tuple(
        receipt for receipt in task_matches if required.issubset(set(receipt.mutation_surfaces))
    )
    if not surface_matches:
        return "connector_mutation_surface_mismatch", None

    for receipt in surface_matches:
        if _route_authority_receipt_is_fresh(receipt, now=now):
            return None, route_authority_receipt_reference(receipt)
    return "connector_mutation_receipt_stale", None


def evaluate_connector_receipt_gate(
    tool_name: str,
    *,
    task_id: str | None,
    role: str | None,
    ledger_path: str | Path | None = None,
    receipt_root: str | Path | None = None,
    now: datetime | None = None,
) -> ConnectorReceiptGateResult:
    """Evaluate route/quota/resource/receipt evidence for a connector tool."""

    classification = classify_connector_tool(tool_name)
    if classification is None or not classification.side_effecting:
        return ConnectorReceiptGateResult(
            allowed=True,
            reason_code="read_only_or_unclassified",
            message="connector tool is read-only evidence or outside connector policy",
            classification=classification,
        )
    if not task_id:
        return ConnectorReceiptGateResult(
            allowed=False,
            reason_code="task_id_absent",
            message=(
                "side-effecting connector tool requires a claimed task. Next action: "
                "claim the dispatched task before retrying the connector mutation."
            ),
            classification=classification,
        )
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    ledger = _ledger_path(ledger_path)
    route_decision = _latest_route_decision(task_id=task_id, role=role, ledger_path=ledger)
    route_refusal = _route_decision_refusal(route_decision, now=checked_at)
    if route_refusal is not None:
        return ConnectorReceiptGateResult(
            allowed=False,
            reason_code=route_refusal,
            message=(
                "side-effecting connector tool requires a fresh green route decision "
                f"for task {task_id}. Next action: refresh the route through governed "
                "methodology dispatch so route, quota, and resource evidence are current."
            ),
            classification=classification,
        )
    assert route_decision is not None
    route_id = str(route_decision["route_id"])
    root = _receipt_root(receipt_root)
    if root is None:
        return ConnectorReceiptGateResult(
            allowed=False,
            reason_code="receipt_dir_disabled",
            message=(
                "route-authority receipt directory is disabled. Next action: restore "
                "HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR or the default receipt directory."
            ),
            classification=classification,
            route_id=route_id,
        )
    try:
        receipt_refusal, receipt_ref = _connector_receipt_match(
            route_id=route_id,
            task_id=task_id,
            required_surfaces=classification.required_mutation_surfaces,
            receipt_root=root,
            now=checked_at,
        )
    except ValueError as exc:
        return ConnectorReceiptGateResult(
            allowed=False,
            reason_code="route_authority_receipt_invalid",
            message=(
                f"{exc}. Next action: repair or remove malformed route-authority "
                "receipts, then mint a fresh connector_mutation receipt."
            ),
            classification=classification,
            route_id=route_id,
        )
    if receipt_refusal is not None:
        return ConnectorReceiptGateResult(
            allowed=False,
            reason_code=receipt_refusal,
            message=(
                "side-effecting connector tool requires a fresh connector_mutation "
                f"receipt for route {route_id}, task {task_id}, surfaces "
                f"{','.join(classification.required_mutation_surfaces)}. Next action: "
                "mint a task-bound connector_mutation route-authority receipt after "
                "refreshing route/quota/resource evidence."
            ),
            classification=classification,
            route_id=route_id,
            evidence_refs=(
                *_sequence(route_decision.get("quota_evidence_refs")),
                *_sequence(route_decision.get("resource_state_refs")),
            ),
        )
    return ConnectorReceiptGateResult(
        allowed=True,
        reason_code="connector_receipts_ok",
        message="connector route, quota, resource, and authority receipt evidence is fresh",
        classification=classification,
        route_id=route_id,
        evidence_refs=(
            *_sequence(route_decision.get("quota_evidence_refs")),
            *_sequence(route_decision.get("resource_state_refs")),
        ),
        receipt_ref=receipt_ref,
    )


def _classification_json(classification: ConnectorToolClassification | None) -> dict[str, Any]:
    if classification is None:
        return {"classified": False}
    return {
        "classified": True,
        "canonical_name": classification.canonical_name,
        "effect_classes": list(classification.effect_classes),
        "required_mutation_surfaces": list(classification.required_mutation_surfaces),
        "side_effecting": classification.side_effecting,
        "matched_by": classification.matched_by,
        "description": classification.description,
    }


def _gate_json(result: ConnectorReceiptGateResult) -> dict[str, Any]:
    return {
        "allowed": result.allowed,
        "reason_code": result.reason_code,
        "message": result.message,
        "route_id": result.route_id,
        "evidence_refs": list(result.evidence_refs),
        "receipt_ref": result.receipt_ref,
        "classification": _classification_json(result.classification),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcp_connector_policy")
    sub = parser.add_subparsers(dest="command", required=True)

    p_canon = sub.add_parser("canonicalize")
    p_canon.add_argument("tool_name")

    p_classify = sub.add_parser("classify")
    p_classify.add_argument("tool_name")

    p_side = sub.add_parser("is-side-effecting")
    p_side.add_argument("tool_name")

    p_gate = sub.add_parser("receipt-gate")
    p_gate.add_argument("tool_name")
    p_gate.add_argument("--task-id", default="")
    p_gate.add_argument("--role", default="")
    p_gate.add_argument("--ledger", default=None)
    p_gate.add_argument("--receipt-dir", default=None)
    p_gate.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "canonicalize":
            print(canonicalize_tool_name(args.tool_name))
            return 0
        if args.command == "classify":
            print(json.dumps(_classification_json(classify_connector_tool(args.tool_name))))
            return 0
        if args.command == "is-side-effecting":
            return 0 if is_side_effecting_connector_tool(args.tool_name) else 10

        result = evaluate_connector_receipt_gate(
            args.tool_name,
            task_id=args.task_id or None,
            role=args.role or None,
            ledger_path=args.ledger,
            receipt_root=args.receipt_dir,
        )
    except Exception as exc:
        print(f"mcp_connector_policy: classifier error: {exc}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(_gate_json(result), sort_keys=True))
    elif result.allowed:
        print(f"mcp-connector-mutator-gate: allowed — {result.message}")
    else:
        print(
            f"mcp-connector-mutator-gate: BLOCKED — {result.reason_code}: {result.message}",
            file=sys.stderr,
        )
    return 0 if result.allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
