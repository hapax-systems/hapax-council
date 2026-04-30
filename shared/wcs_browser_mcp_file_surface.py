"""Browser, MCP, file, vault, command, and public-source WCS read surface contract.

This slice turns source-read surfaces into explicit evidence records.  It does
not execute tools, reread files, or grant public/truth authority from a URL,
path, command name, or tool name alone.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.capability_classification_inventory import (
    CapabilityClassificationInventory,
    SurfaceFamily,
    load_capability_classification_inventory,
)
from shared.capability_classification_inventory import (
    PublicClaimPolicy as ClassificationPublicClaimPolicy,
)
from shared.semantic_recruitment import PrivacyLabel, RightsLabel

REPO_ROOT = Path(__file__).resolve().parents[1]
WCS_BROWSER_MCP_FILE_SURFACE_FIXTURES = (
    REPO_ROOT / "config" / "wcs-browser-mcp-file-surface-fixtures.json"
)

REQUIRED_SURFACE_KINDS = frozenset(
    {
        "browser_state",
        "mcp_tool",
        "tool_schema",
        "local_file",
        "obsidian_vault",
        "command_output",
        "public_source",
    }
)
REQUIRED_AVAILABILITY_STATES = frozenset(
    {
        "available",
        "missing",
        "stale",
        "permission_blocked",
        "private_only",
        "tool_unavailable",
    }
)
REQUIRED_WITNESS_KINDS = frozenset(
    {
        "source_read_happened",
        "source_fresh_enough",
        "tool_unavailable",
        "file_path_not_found",
    }
)
FAIL_CLOSED_POLICY = {
    "path_or_url_name_grants_public_claim": False,
    "missing_source_read_allows_claim": False,
    "stale_source_allows_claim": False,
    "private_vault_surface_public_by_default": False,
    "tool_success_is_truth": False,
}


class WCSBrowserMCPFileSurfaceError(ValueError):
    """Raised when WCS browser/MCP/file surface fixtures fail closed."""


class SourceSurfaceKind(StrEnum):
    BROWSER_STATE = "browser_state"
    MCP_TOOL = "mcp_tool"
    TOOL_SCHEMA = "tool_schema"
    LOCAL_FILE = "local_file"
    OBSIDIAN_VAULT = "obsidian_vault"
    COMMAND_OUTPUT = "command_output"
    PUBLIC_SOURCE = "public_source"


class SourceAvailabilityState(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    STALE = "stale"
    PERMISSION_BLOCKED = "permission_blocked"
    PRIVATE_ONLY = "private_only"
    TOOL_UNAVAILABLE = "tool_unavailable"
    MALFORMED = "malformed"
    BLOCKED = "blocked"


class PublicScope(StrEnum):
    PUBLIC_SAFE = "public_safe"
    PUBLIC_FORBIDDEN = "public_forbidden"
    PRIVATE = "private"


class SourceWitnessKind(StrEnum):
    SOURCE_READ_HAPPENED = "source_read_happened"
    SOURCE_FRESH_ENOUGH = "source_fresh_enough"
    TOOL_UNAVAILABLE = "tool_unavailable"
    FILE_PATH_NOT_FOUND = "file_path_not_found"
    PERMISSION_BLOCKED = "permission_blocked"


class SourceWitnessResult(StrEnum):
    SATISFIED = "satisfied"
    BLOCKED = "blocked"


class SourceEvidenceKind(StrEnum):
    SOURCE_READ = "source_read"
    FRESHNESS = "freshness"
    TOOL_RESPONSE = "tool_response"
    TOOL_ERROR = "tool_error"
    CITATION = "citation"
    PUBLIC_URL = "public_url"
    PATH_HASH_MTIME = "path_hash_mtime"
    COMMAND_EXIT_STATUS = "command_exit_status"
    PERMISSION_WITNESS = "permission_witness"


class SourceWitnessProbe(BaseModel):
    """Evidence that a source-read obligation was satisfied or failed."""

    model_config = ConfigDict(extra="forbid")

    probe_id: str = Field(pattern=r"^probe\.[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    surface_id: str = Field(min_length=1)
    witness_kind: SourceWitnessKind
    result: SourceWitnessResult
    observed_at: str
    evidence_ref: str = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    freshness_ttl_s: int | None = Field(default=None, ge=0)
    blocked_reason: str | None = None

    @model_validator(mode="after")
    def _validate_witness_result(self) -> Self:
        if self.result is SourceWitnessResult.BLOCKED and not self.blocked_reason:
            raise ValueError("blocked source witnesses require blocked_reason")
        if self.result is SourceWitnessResult.SATISFIED and self.blocked_reason is not None:
            raise ValueError("satisfied source witnesses cannot carry blocked_reason")
        if (
            self.witness_kind is SourceWitnessKind.SOURCE_FRESH_ENOUGH
            and self.result is SourceWitnessResult.SATISFIED
            and self.freshness_ttl_s is None
        ):
            raise ValueError("fresh source witnesses require freshness_ttl_s")
        return self


class SourceSurfaceRecord(BaseModel):
    """One browser/MCP/file read surface and its claim ceiling."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    surface_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    surface_kind: SourceSurfaceKind
    classification_row_id: str = Field(min_length=1)
    wcs_capability_id: str | None = None
    producer: str = Field(min_length=1)
    concrete_interface: str = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    evidence_kinds: list[SourceEvidenceKind] = Field(min_length=1)
    witness_probe_ids: list[str] = Field(min_length=1)
    availability_state: SourceAvailabilityState
    public_scope: PublicScope
    privacy_label: PrivacyLabel
    rights_label: RightsLabel
    public_claim_requested: bool = False
    grounding_gate_ref: str | None = None
    citation_refs: list[str] = Field(default_factory=list)
    raw_hash_ref: str | None = None
    replay_ref: str | None = None
    blocked_reasons: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _validate_surface_contract(self) -> Self:
        blocked_states = {
            SourceAvailabilityState.MISSING,
            SourceAvailabilityState.STALE,
            SourceAvailabilityState.PERMISSION_BLOCKED,
            SourceAvailabilityState.TOOL_UNAVAILABLE,
            SourceAvailabilityState.MALFORMED,
            SourceAvailabilityState.BLOCKED,
        }
        if self.availability_state in blocked_states and not self.blocked_reasons:
            raise ValueError("blocked source surface states require blocked_reasons")
        if self.surface_kind in {SourceSurfaceKind.LOCAL_FILE, SourceSurfaceKind.OBSIDIAN_VAULT}:
            if SourceEvidenceKind.PATH_HASH_MTIME not in self.evidence_kinds:
                raise ValueError("file and vault surfaces require path_hash_mtime evidence")
        if self.surface_kind is SourceSurfaceKind.COMMAND_OUTPUT:
            if SourceEvidenceKind.COMMAND_EXIT_STATUS not in self.evidence_kinds:
                raise ValueError("command output surfaces require command_exit_status evidence")
        if self.public_claim_requested and self.public_scope is not PublicScope.PUBLIC_SAFE:
            if not self.blocked_reasons:
                raise ValueError("unsafe public-claim requests require blocked_reasons")
        return self


class SourceSurfaceEvaluation(BaseModel):
    """Fail-closed evaluation for one read surface."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    surface_id: str
    surface_kind: SourceSurfaceKind
    classification_row_id: str
    availability_state: SourceAvailabilityState
    can_support_private_evidence: bool
    can_support_public_claim: bool
    classification_public_claim_policy: str | None
    authority_ceiling: str | None
    blocked_reasons: list[str]
    source_refs: list[str]
    witness_probe_ids: list[str]


class WCSBrowserMCPFileSurfaceFixtureSet(BaseModel):
    """Canonical fixture packet for browser/MCP/file WCS read surfaces."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_ref: str | None = Field(default=None, alias="$schema")
    schema_version: Literal[1] = 1
    fixture_set_id: str
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    witness_probes: list[SourceWitnessProbe] = Field(min_length=1)
    surfaces: list[SourceSurfaceRecord] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]

    @model_validator(mode="after")
    def _validate_fixture_set_contract(self) -> Self:
        surface_ids = [surface.surface_id for surface in self.surfaces]
        duplicate_surfaces = sorted({item for item in surface_ids if surface_ids.count(item) > 1})
        if duplicate_surfaces:
            raise ValueError("duplicate source surface ids: " + ", ".join(duplicate_surfaces))

        probe_ids = [probe.probe_id for probe in self.witness_probes]
        duplicate_probes = sorted({item for item in probe_ids if probe_ids.count(item) > 1})
        if duplicate_probes:
            raise ValueError("duplicate source witness probes: " + ", ".join(duplicate_probes))

        probes_by_id = {probe.probe_id: probe for probe in self.witness_probes}
        for surface in self.surfaces:
            for probe_id in surface.witness_probe_ids:
                probe = probes_by_id.get(probe_id)
                if probe is None:
                    raise ValueError(f"surface {surface.surface_id} cites unknown probe {probe_id}")
                if probe.surface_id != surface.surface_id:
                    raise ValueError(
                        f"surface {surface.surface_id} cites probe {probe_id} for {probe.surface_id}"
                    )

        missing_kinds = REQUIRED_SURFACE_KINDS - {
            surface.surface_kind.value for surface in self.surfaces
        }
        if missing_kinds:
            raise ValueError("missing source surface kinds: " + ", ".join(sorted(missing_kinds)))

        missing_states = REQUIRED_AVAILABILITY_STATES - {
            surface.availability_state.value for surface in self.surfaces
        }
        if missing_states:
            raise ValueError("missing source states: " + ", ".join(sorted(missing_states)))

        missing_witnesses = REQUIRED_WITNESS_KINDS - {
            probe.witness_kind.value for probe in self.witness_probes
        }
        if missing_witnesses:
            raise ValueError(
                "missing source witness kinds: " + ", ".join(sorted(missing_witnesses))
            )

        if self.fail_closed_policy != FAIL_CLOSED_POLICY:
            raise ValueError("fail_closed_policy must pin source names and stale reads closed")

        return self

    def witness_probes_by_id(self) -> dict[str, SourceWitnessProbe]:
        return {probe.probe_id: probe for probe in self.witness_probes}

    def require_surface(self, surface_id: str) -> SourceSurfaceRecord:
        for surface in self.surfaces:
            if surface.surface_id == surface_id:
                return surface
        raise KeyError(f"unknown WCS browser/MCP/file surface: {surface_id}")

    def evaluate_all(
        self,
        inventory: CapabilityClassificationInventory | None = None,
    ) -> dict[str, SourceSurfaceEvaluation]:
        return {
            surface.surface_id: evaluate_surface(surface, self.witness_probes_by_id(), inventory)
            for surface in self.surfaces
        }


SURFACE_KIND_TO_CLASSIFICATION_FAMILY: Mapping[SourceSurfaceKind, SurfaceFamily] = {
    SourceSurfaceKind.BROWSER_STATE: SurfaceFamily.BROWSER_SURFACE,
    SourceSurfaceKind.MCP_TOOL: SurfaceFamily.MCP_TOOL,
    SourceSurfaceKind.TOOL_SCHEMA: SurfaceFamily.TOOL_SCHEMA,
    SourceSurfaceKind.LOCAL_FILE: SurfaceFamily.FILE,
    SourceSurfaceKind.OBSIDIAN_VAULT: SurfaceFamily.OBSIDIAN_NOTE,
    SourceSurfaceKind.COMMAND_OUTPUT: SurfaceFamily.COMMAND_OUTPUT,
    SourceSurfaceKind.PUBLIC_SOURCE: SurfaceFamily.SEARCH_PROVIDER,
}

STATE_BLOCK_REASON: Mapping[SourceAvailabilityState, str] = {
    SourceAvailabilityState.MISSING: "source_not_found",
    SourceAvailabilityState.STALE: "source_stale",
    SourceAvailabilityState.PERMISSION_BLOCKED: "source_permission_blocked",
    SourceAvailabilityState.TOOL_UNAVAILABLE: "tool_unavailable",
    SourceAvailabilityState.MALFORMED: "source_malformed",
    SourceAvailabilityState.BLOCKED: "source_blocked",
}


def evaluate_surface(
    surface: SourceSurfaceRecord,
    witness_probes_by_id: Mapping[str, SourceWitnessProbe],
    inventory: CapabilityClassificationInventory | None = None,
) -> SourceSurfaceEvaluation:
    """Evaluate one source-read surface without deriving authority from its name."""

    checked_inventory = inventory or load_capability_classification_inventory()
    blocked_reasons = list(surface.blocked_reasons)
    classification_policy: str | None = None
    authority_ceiling: str | None = None

    try:
        classification_row = checked_inventory.require_row(surface.classification_row_id)
    except KeyError:
        classification_row = None
        blocked_reasons.append("classification_row_unknown")

    if classification_row is not None:
        classification_policy = classification_row.public_claim_policy.value
        authority_ceiling = classification_row.authority_ceiling.value
        expected_family = SURFACE_KIND_TO_CLASSIFICATION_FAMILY[surface.surface_kind]
        if classification_row.surface_family is not expected_family:
            blocked_reasons.append("classification_family_mismatch")

    surface_witnesses = _surface_witnesses(surface, witness_probes_by_id)
    blocked_reasons.extend(_blocked_witness_reasons(surface_witnesses))

    if not _has_satisfied_witness(surface_witnesses, SourceWitnessKind.SOURCE_READ_HAPPENED):
        blocked_reasons.append("source_read_missing")
    if not _has_satisfied_witness(surface_witnesses, SourceWitnessKind.SOURCE_FRESH_ENOUGH):
        blocked_reasons.append("source_not_fresh")

    state_reason = STATE_BLOCK_REASON.get(surface.availability_state)
    if state_reason is not None:
        blocked_reasons.append(state_reason)

    private_evidence_allowed = not _has_private_evidence_blocker(blocked_reasons)
    public_claim_allowed = False

    if surface.public_claim_requested:
        if not private_evidence_allowed:
            blocked_reasons.append("public_claim_requires_private_evidence")
        if surface.public_scope is PublicScope.PRIVATE:
            blocked_reasons.append("public_scope_private")
        elif surface.public_scope is PublicScope.PUBLIC_FORBIDDEN:
            blocked_reasons.append("public_scope_forbidden")
        if classification_row is None or (
            classification_row.public_claim_policy
            is not ClassificationPublicClaimPolicy.PUBLIC_GATE_REQUIRED
        ):
            blocked_reasons.append("classification_not_public_claim_authority")
        if surface.grounding_gate_ref is None:
            blocked_reasons.append("public_claim_requires_grounding_gate")
        if _surface_needs_citations(surface.surface_kind) and not surface.citation_refs:
            blocked_reasons.append("public_claim_requires_citation_refs")
        if surface.rights_label in {
            RightsLabel.UNKNOWN,
            RightsLabel.THIRD_PARTY_UNCLEAR,
            RightsLabel.BLOCKED,
        }:
            blocked_reasons.append("rights_not_public_safe")
        if surface.privacy_label not in {PrivacyLabel.PUBLIC_SAFE, PrivacyLabel.PUBLIC_BROADCAST}:
            blocked_reasons.append("privacy_not_public_safe")
        if surface.availability_state is SourceAvailabilityState.PRIVATE_ONLY:
            blocked_reasons.append("source_private_only")

        public_claim_allowed = not _has_public_claim_blocker(blocked_reasons)
    else:
        blocked_reasons.append("public_claim_not_requested")

    blocked_reasons = _dedupe(blocked_reasons)
    return SourceSurfaceEvaluation(
        surface_id=surface.surface_id,
        surface_kind=surface.surface_kind,
        classification_row_id=surface.classification_row_id,
        availability_state=surface.availability_state,
        can_support_private_evidence=private_evidence_allowed,
        can_support_public_claim=public_claim_allowed,
        classification_public_claim_policy=classification_policy,
        authority_ceiling=authority_ceiling,
        blocked_reasons=blocked_reasons,
        source_refs=list(surface.source_refs),
        witness_probe_ids=list(surface.witness_probe_ids),
    )


def load_wcs_browser_mcp_file_surface_fixtures(
    path: Path = WCS_BROWSER_MCP_FILE_SURFACE_FIXTURES,
) -> WCSBrowserMCPFileSurfaceFixtureSet:
    """Load the fixture-backed browser/MCP/file read surface packet."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise WCSBrowserMCPFileSurfaceError(f"{path} did not contain a JSON object")
        return WCSBrowserMCPFileSurfaceFixtureSet.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise WCSBrowserMCPFileSurfaceError(
            f"failed to load WCS browser/MCP/file surface fixtures: {path}"
        ) from exc


def _surface_witnesses(
    surface: SourceSurfaceRecord,
    witness_probes_by_id: Mapping[str, SourceWitnessProbe],
) -> list[SourceWitnessProbe]:
    witnesses: list[SourceWitnessProbe] = []
    for probe_id in surface.witness_probe_ids:
        probe = witness_probes_by_id.get(probe_id)
        if probe is None:
            continue
        witnesses.append(probe)
    return witnesses


def _blocked_witness_reasons(witnesses: Sequence[SourceWitnessProbe]) -> list[str]:
    reasons: list[str] = []
    for witness in witnesses:
        if witness.result is SourceWitnessResult.BLOCKED:
            reasons.append(
                witness.blocked_reason or f"blocked_witness:{witness.witness_kind.value}"
            )
    return reasons


def _has_satisfied_witness(
    witnesses: Sequence[SourceWitnessProbe],
    witness_kind: SourceWitnessKind,
) -> bool:
    return any(
        witness.witness_kind is witness_kind and witness.result is SourceWitnessResult.SATISFIED
        for witness in witnesses
    )


def _has_private_evidence_blocker(blocked_reasons: Sequence[str]) -> bool:
    private_blockers = {
        "classification_row_unknown",
        "classification_family_mismatch",
        "source_read_missing",
        "source_not_fresh",
        "source_not_found",
        "source_permission_blocked",
        "tool_unavailable",
        "source_malformed",
        "source_blocked",
    }
    return any(reason in private_blockers for reason in blocked_reasons)


def _has_public_claim_blocker(blocked_reasons: Sequence[str]) -> bool:
    ignored = {"public_claim_not_requested"}
    return any(reason not in ignored for reason in blocked_reasons)


def _surface_needs_citations(surface_kind: SourceSurfaceKind) -> bool:
    return surface_kind in {
        SourceSurfaceKind.BROWSER_STATE,
        SourceSurfaceKind.MCP_TOOL,
        SourceSurfaceKind.PUBLIC_SOURCE,
    }


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def schema() -> dict[str, Any]:
    """Return the JSON schema for the fixture packet."""

    schema_payload = WCSBrowserMCPFileSurfaceFixtureSet.model_json_schema()
    schema_payload["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema_payload["title"] = "WCSBrowserMCPFileSurface"
    schema_payload["x-required_surface_kinds"] = sorted(REQUIRED_SURFACE_KINDS)
    schema_payload["x-required_availability_states"] = sorted(REQUIRED_AVAILABILITY_STATES)
    schema_payload["x-required_witness_kinds"] = sorted(REQUIRED_WITNESS_KINDS)
    return schema_payload


__all__ = [
    "FAIL_CLOSED_POLICY",
    "REQUIRED_AVAILABILITY_STATES",
    "REQUIRED_SURFACE_KINDS",
    "REQUIRED_WITNESS_KINDS",
    "SourceAvailabilityState",
    "SourceEvidenceKind",
    "SourceSurfaceEvaluation",
    "SourceSurfaceKind",
    "SourceSurfaceRecord",
    "SourceWitnessKind",
    "SourceWitnessProbe",
    "SourceWitnessResult",
    "PublicScope",
    "WCSBrowserMCPFileSurfaceError",
    "WCSBrowserMCPFileSurfaceFixtureSet",
    "WCS_BROWSER_MCP_FILE_SURFACE_FIXTURES",
    "evaluate_surface",
    "load_wcs_browser_mcp_file_surface_fixtures",
    "schema",
]
