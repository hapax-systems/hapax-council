"""HKP bundle schema and validator.

HKP bundles are derived support projections. This module validates their local
shape and authority ceilings; it does not grant authority to any bundle.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from shared.frontmatter import parse_frontmatter_with_diagnostics

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UID_RE = re.compile(r"^hkp:[A-Za-z0-9_.:-]+$")
EDGE_ID_RE = re.compile(r"^hkp-edge:[A-Za-z0-9_.:-]+$")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
MARKDOWN_REFERENCE_LINK_RE = re.compile(r"(?m)^\s{0,3}\[[^\]]+\]:\s*(\S+)")
LOCAL_PATH_RE = re.compile(r"^(?:/|~(?:/|$)|file://|[A-Za-z]:[\\/])")
RESERVED_BUNDLE_NAMES = {
    ".env",
    ".env.local",
    ".git",
    ".hg",
    ".ssh",
    ".svn",
    "id_ed25519",
    "id_rsa",
    "secret.yaml",
    "secret.yml",
    "secrets.yaml",
    "secrets.yml",
}
VALIDATOR_VERSION = "0.2.0"
TREE_HASH_EXCLUDED_PATHS = {"_hkp/checksums.json", "_hkp/manifest.yaml"}
ALLOWED_HKP_FILES = {
    "_hkp/manifest.yaml",
    "_hkp/consumer_policy.yaml",
    "_hkp/edges.jsonl",
    "_hkp/events.jsonl",
    "_hkp/snapshot.json",
    "_hkp/checksums.json",
}

AUTHORITY_SOURCE_ROLES = {"authority_source", "raw_evidence", "public_event_move"}
AUTHORITY_SOURCE_CLASSES = {
    "planning",
    "authoritative_docs",
    "source_mutation",
    "runtime_mutation",
    "public_claim",
    "provider_spend",
}
STALE_SOURCE_STATES = {"stale", "missing", "contradictory", "unparseable", "unknown"}
CONCEPT_TYPES = {
    "cc-task",
    "authority-case",
    "spec",
    "route",
    "source-module",
    "service",
    "api",
    "runbook",
    "receipt",
    "reference",
    "concept",
    "Tombstone",
}
ALLOWED_CONSUMERS = {
    "research_viewer",
    "local_prompt_context",
    "dashboard",
    "qdrant_rag",
    "public_export",
    "release_gate",
    "dispatcher",
    "close_gate",
    "runtime_loader",
    "provider_spend_gate",
    "unknown",
}
FORBIDDEN_CONSUMERS = {
    "dispatcher",
    "close_gate",
    "release_gate",
    "runtime_loader",
    "provider_spend_gate",
}
VALIDATOR_FIRST_DENY_CONSUMERS = FORBIDDEN_CONSUMERS | {"qdrant_rag", "public_export"}
RELATIONS = {
    "governs",
    "implements",
    "cites",
    "references",
    "derived_from",
    "blocks",
    "supersedes",
    "contradicts",
    "depends_on",
    "consumes",
    "produces",
    "same_as",
    "part_of",
    "required_by",
    "obsoletes",
    "is_obsoleted_by",
    "version_of",
    "has_version",
    "evidenced_by",
    "observed_in",
    "generated_by",
    "invalidates",
    "has_manifest",
}
ALLOWED_TOP_LEVEL_CONCEPT_KEYS = {
    "hkp_schema",
    "type",
    "concept_uid",
    "concept_path",
    "title",
    "description",
    "resource",
    "tags",
    "source_refs",
    "posture",
    "authority",
    "freshness",
    "projection_provenance",
    "summary_invariants",
    "tombstone",
    "extensions",
    "x_hkp",
}


class ValidationMode(StrEnum):
    GOVERNED = "governed"
    RESEARCH = "research"


class FindingSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class HkpFinding:
    severity: FindingSeverity
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class HkpValidationResult:
    bundle_path: Path
    mode: ValidationMode
    findings: tuple[HkpFinding, ...]

    @property
    def ok(self) -> bool:
        return not any(finding.severity == FindingSeverity.ERROR for finding in self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode.value,
            "validator_version": VALIDATOR_VERSION,
            "bundle_path": str(self.bundle_path),
            "findings": [finding.as_dict() for finding in self.findings],
        }


class _HkpModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HkpFreshness(_HkpModel):
    state: Literal["fresh", "stale", "missing", "contradictory", "unparseable", "unknown"]
    valid_from: str | None = None
    valid_until: str | None = None
    checked_at: str | None = None


class HkpSourceRef(_HkpModel):
    ref_id: str
    data_role: Literal[
        "authority_source",
        "raw_evidence",
        "derived_index",
        "projection",
        "read_model",
        "dashboard_snapshot",
        "support_artifact",
        "egress_manifest",
        "public_event_move",
    ]
    source_authority_class: Literal[
        "planning",
        "authoritative_docs",
        "source_mutation",
        "runtime_mutation",
        "public_claim",
        "provider_spend",
        "none",
    ]
    uri: str
    content_hash: str | None = None
    hash_scope: (
        Literal["full_content", "frontmatter", "body", "selected_fields", "external_pointer"] | None
    ) = None
    hash_algorithm: Literal["sha256"] | None = None
    observed_at: str | None = None
    checked_at: str | None = None
    stale_after: str | None = None
    freshness_state: Literal[
        "fresh",
        "stale",
        "missing",
        "contradictory",
        "unparseable",
        "manual_assertion",
        "unknown",
    ]

    @field_validator("uri")
    @classmethod
    def _uri_is_not_local_path_leak(cls, value: str) -> str:
        if LOCAL_PATH_RE.match(value) or ".." in Path(value).parts:
            raise ValueError(
                "source ref uri must not expose a local path or ..; use a logical repo: or https: id"
            )
        return value

    @field_validator("content_hash")
    @classmethod
    def _hash_is_sha256(cls, value: str | None) -> str | None:
        if value is not None and not SHA256_RE.match(value):
            raise ValueError("content_hash must be sha256:<64 lowercase hex>")
        return value

    @model_validator(mode="after")
    def _authority_refs_are_hashed(self) -> HkpSourceRef:
        requires_hash = (
            self.data_role in AUTHORITY_SOURCE_ROLES
            or self.source_authority_class in AUTHORITY_SOURCE_CLASSES
        )
        if not requires_hash:
            return self
        missing = [
            name
            for name in (
                "content_hash",
                "hash_scope",
                "hash_algorithm",
                "observed_at",
                "checked_at",
                "stale_after",
            )
            if getattr(self, name) in (None, "")
        ]
        if missing:
            raise ValueError(f"authority/evidence source ref requires {', '.join(missing)}")
        if self.freshness_state in STALE_SOURCE_STATES:
            raise ValueError(f"authority/evidence source ref cannot be {self.freshness_state}")
        return self


class HkpPosture(_HkpModel):
    privacy_class: Literal["public", "internal", "private", "secret", "unknown"]
    consent_label_ref: str | None = None
    provenance_expr: str | None = None
    rights_state: Literal["operator_controlled", "third_party", "mixed", "unknown"]
    egress_state: Literal[
        "private", "anonymized", "hash_only", "aggregate_only", "public", "forbidden", "unknown"
    ]
    public_export_allowed: bool = False
    redaction_policy: str
    allowed_consumers: list[str] = Field(default_factory=list)
    forbidden_consumers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fail_closed_on_ambiguity(self) -> HkpPosture:
        if self.privacy_class == "unknown":
            raise ValueError("privacy_class cannot be unknown in producer-strict HKP")
        if self.rights_state == "unknown":
            raise ValueError("rights_state cannot be unknown in producer-strict HKP")
        if self.egress_state == "unknown":
            raise ValueError("egress_state cannot be unknown in producer-strict HKP")
        missing = sorted(FORBIDDEN_CONSUMERS - set(self.forbidden_consumers))
        if missing:
            raise ValueError(
                f"forbidden_consumers missing fail-closed consumers: {', '.join(missing)}"
            )
        if self.public_export_allowed:
            raise ValueError("validator-first HKP cannot allow public export")
        unknown_allowed = sorted(set(self.allowed_consumers) - (ALLOWED_CONSUMERS - {"unknown"}))
        if unknown_allowed:
            raise ValueError(
                "validator-first posture cannot allow unknown consumers: "
                + ", ".join(unknown_allowed)
            )
        unknown_forbidden = sorted(set(self.forbidden_consumers) - ALLOWED_CONSUMERS)
        if unknown_forbidden:
            raise ValueError(
                "validator-first posture names unsupported forbidden consumers: "
                + ", ".join(unknown_forbidden)
            )
        blocked_allowed = sorted(VALIDATOR_FIRST_DENY_CONSUMERS & set(self.allowed_consumers))
        if blocked_allowed:
            raise ValueError(
                "validator-first posture cannot allow blocked consumers: "
                + ", ".join(blocked_allowed)
            )
        return self


class HkpAuthority(_HkpModel):
    level: Literal["support_non_authoritative"]
    may_authorize: bool = False
    ceiling_family: Literal["route", "claim", "task", "publication", "storage", "evidence"]
    ceiling: Literal[
        "read_only",
        "support_only",
        "internal_only",
        "evidence_bound",
        "public_gate_required",
        "no_claim",
    ]
    promotion_required: str

    @model_validator(mode="after")
    def _never_authorizes(self) -> HkpAuthority:
        if self.may_authorize:
            raise ValueError("HKP records may not authorize")
        return self


class HkpProjectionProvenance(_HkpModel):
    producer: str
    generated_at: str
    projection_event_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    citation_refs: list[str] = Field(default_factory=list)


class HkpSummaryInvariants(_HkpModel):
    preserve_authority_ceiling: bool = True
    preserve_cannot_prove: bool = True
    preserve_source_refs: bool = True
    preserve_public_private_posture: bool = True


class HkpTombstone(_HkpModel):
    commitment: str
    commitment_kind: Literal["hmac_sha256", "keyed_commitment"]
    erasure_ref: str | None = None
    purge_receipt_refs: list[str] = Field(default_factory=list)

    @field_validator("commitment")
    @classmethod
    def _commitment_is_not_bare_hash(cls, value: str) -> str:
        if value.startswith("sha256:"):
            raise ValueError("tombstone commitment must be keyed; bare hashes are not allowed")
        if not (value.startswith("hmac-sha256:") or value.startswith("keyed:")):
            raise ValueError("tombstone commitment must start with hmac-sha256: or keyed:")
        return value


class HkpConceptFrontmatter(_HkpModel):
    hkp_schema: Literal[1]
    type: str
    concept_uid: str
    concept_path: str
    title: str
    description: str
    resource: Literal["file", "git", "https", "qdrant", "systemd", "github-pr"]
    tags: list[str] = Field(default_factory=list)
    source_refs: list[HkpSourceRef]
    posture: HkpPosture
    authority: HkpAuthority
    freshness: HkpFreshness
    projection_provenance: HkpProjectionProvenance
    summary_invariants: HkpSummaryInvariants = Field(default_factory=HkpSummaryInvariants)
    tombstone: HkpTombstone | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)
    x_hkp: dict[str, Any] = Field(default_factory=dict)

    @field_validator("concept_uid")
    @classmethod
    def _concept_uid_shape(cls, value: str) -> str:
        if not UID_RE.match(value):
            raise ValueError(
                "concept_uid must start with hkp: and use stable identifier characters"
            )
        return value

    @field_validator("concept_path")
    @classmethod
    def _concept_path_is_bundle_local(cls, value: str) -> str:
        if LOCAL_PATH_RE.match(value) or ".." in Path(value).parts:
            raise ValueError("concept_path must be bundle-local and must not contain ..")
        return value

    @model_validator(mode="after")
    def _tombstone_shape(self) -> HkpConceptFrontmatter:
        if self.resource == "qdrant":
            raise ValueError("validator-first HKP cannot reference qdrant resources")
        if self.type == "Tombstone":
            if self.tombstone is None:
                raise ValueError("Tombstone concepts require tombstone metadata")
            if self.title.lower() not in {"tombstone", "erased concept", "removed concept"}:
                raise ValueError("Tombstone title must be generic and non-disclosing")
            if self.resource != "file":
                raise ValueError("Tombstone concepts must use resource: file")
        return self


class HkpEdgeFreshness(_HkpModel):
    state: Literal["fresh", "stale", "missing", "contradictory", "unparseable", "unknown"]


class HkpGeneratedFrom(_HkpModel):
    projection_event_id: str
    generator_id: str


class HkpEdge(_HkpModel):
    hkp_schema: Literal[1]
    edge_id: str
    from_uid: str
    rel_family: Literal[
        "dependency",
        "evidence",
        "identity",
        "hierarchy",
        "versioning",
        "invalidation",
        "generation",
        "governance",
    ]
    rel: str
    direction: Literal["outbound", "inbound"]
    to_uid: str | None = None
    target_ref: str | None = None
    target_path: str | None = None
    source_refs: list[str]
    authority_ceiling: str
    freshness: HkpEdgeFreshness
    generated_from: HkpGeneratedFrom

    @field_validator("target_path")
    @classmethod
    def _target_path_is_bundle_local(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if LOCAL_PATH_RE.match(value) or ".." in Path(value).parts:
            raise ValueError("target_path must be bundle-local and non-leaking; remove ..")
        return value

    @model_validator(mode="after")
    def _edge_shape(self) -> HkpEdge:
        if not EDGE_ID_RE.match(self.edge_id):
            raise ValueError("edge_id must start with hkp-edge:")
        if not UID_RE.match(self.from_uid):
            raise ValueError("from_uid must be an hkp uid")
        if self.rel not in RELATIONS:
            raise ValueError(f"rel is not in HKP relation vocabulary: {self.rel}")
        targets = [self.to_uid, self.target_ref, self.target_path]
        if sum(1 for target in targets if target) != 1:
            raise ValueError("edge must name exactly one target form")
        if self.to_uid and not UID_RE.match(self.to_uid):
            raise ValueError("to_uid must be an hkp uid")
        return self


class HkpManifest(_HkpModel):
    bundle_uid: str
    hkp_schema: Literal[1]
    profile_version: str
    generator_id: str
    generator_version: str
    source_root: str
    source_commit: str | None = None
    input_ref_hash: str
    output_tree_hash: str
    cache_only: bool
    allowed_consumers: list[str] = Field(default_factory=list)
    forbidden_consumers: list[str] = Field(default_factory=list)
    created_at: str
    generated_at: str

    @model_validator(mode="after")
    def _manifest_is_shadow_only(self) -> HkpManifest:
        if not UID_RE.match(self.bundle_uid):
            raise ValueError("bundle_uid must be an hkp uid")
        if not self.cache_only:
            raise ValueError("HKP validator-first bundles must be cache_only")
        if LOCAL_PATH_RE.match(self.source_root) or ".." in Path(self.source_root).parts:
            raise ValueError("source_root must be a logical source id without local paths or ..")
        for field_name in ("input_ref_hash", "output_tree_hash"):
            value = getattr(self, field_name)
            if not SHA256_RE.match(value):
                raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")
        missing = sorted(FORBIDDEN_CONSUMERS - set(self.forbidden_consumers))
        if missing:
            raise ValueError(f"manifest forbidden_consumers missing: {', '.join(missing)}")
        unknown_allowed = sorted(set(self.allowed_consumers) - (ALLOWED_CONSUMERS - {"unknown"}))
        if unknown_allowed:
            raise ValueError(
                "manifest allowed_consumers includes unknown consumers: "
                + ", ".join(unknown_allowed)
            )
        unknown_forbidden = sorted(set(self.forbidden_consumers) - ALLOWED_CONSUMERS)
        if unknown_forbidden:
            raise ValueError(
                "manifest forbidden_consumers includes unsupported consumers: "
                + ", ".join(unknown_forbidden)
            )
        blocked_allowed = sorted(VALIDATOR_FIRST_DENY_CONSUMERS & set(self.allowed_consumers))
        if blocked_allowed:
            raise ValueError(
                "manifest allowed_consumers includes validator-first blocked consumers: "
                + ", ".join(blocked_allowed)
            )
        return self


class HkpConsumerPolicyRow(_HkpModel):
    consumer: str
    default: Literal["allow_read_only", "allow_with_ceiling", "deny", "allow_after_explicit_row"]
    allowed_fields: list[str] = Field(default_factory=list)
    forbidden_fields: list[str] = Field(default_factory=list)
    title_leak_policy: str
    body_leak_policy: str
    path_redaction_policy: str
    embedding_allowed: bool = False
    retrieval_allowed: bool = False

    @field_validator("consumer")
    @classmethod
    def _known_consumer(cls, value: str) -> str:
        if value not in ALLOWED_CONSUMERS:
            raise ValueError(f"unknown consumer: {value}")
        return value


class HkpConsumerPolicy(_HkpModel):
    hkp_schema: Literal[1]
    consumers: list[HkpConsumerPolicyRow]

    @model_validator(mode="after")
    def _required_consumers_present(self) -> HkpConsumerPolicy:
        names = {row.consumer for row in self.consumers}
        missing = sorted(ALLOWED_CONSUMERS - names)
        if missing:
            raise ValueError(f"consumer policy missing rows: {', '.join(missing)}")
        violations: list[str] = []
        for row in self.consumers:
            if row.consumer in VALIDATOR_FIRST_DENY_CONSUMERS | {"unknown"}:
                if row.default != "deny":
                    violations.append(f"{row.consumer} must default deny")
                if row.allowed_fields:
                    violations.append(f"{row.consumer} may not expose allowed_fields by default")
                if row.embedding_allowed or row.retrieval_allowed:
                    violations.append(
                        f"{row.consumer} may not allow embedding/retrieval by default"
                    )
        if violations:
            raise ValueError("; ".join(violations))
        return self


class HkpProjectionEvent(_HkpModel):
    schema_version: Literal[1]
    event_id: str
    sequence: int = Field(ge=0)
    timestamp: str
    event_type: Literal[
        "bundle_generated",
        "source_observed",
        "concept_emitted",
        "edge_emitted",
        "validation_failed",
        "staleness_detected",
        "checksum_changed",
        "schema_migrated",
        "tombstone_emitted",
    ]
    actor: str
    subject_uid: str
    payload: dict[str, Any]
    previous_event_hash: str | None = None

    @field_validator("subject_uid")
    @classmethod
    def _subject_uid_shape(cls, value: str) -> str:
        if not UID_RE.match(value):
            raise ValueError("subject_uid must be an hkp uid")
        return value

    @field_validator("previous_event_hash")
    @classmethod
    def _previous_hash_shape(cls, value: str | None) -> str | None:
        if value is not None and not SHA256_RE.match(value):
            raise ValueError("previous_event_hash must be sha256:<64 lowercase hex>")
        return value


class HkpChecksumEntry(_HkpModel):
    hash: str
    hash_scope: Literal["full_content"]
    hash_algorithm: Literal["sha256"]

    @field_validator("hash")
    @classmethod
    def _hash_shape(cls, value: str) -> str:
        if not SHA256_RE.match(value):
            raise ValueError("checksum hash must be sha256:<64 lowercase hex>")
        return value


class HkpChecksumIndex(_HkpModel):
    hkp_schema: Literal[1]
    artifacts: dict[str, HkpChecksumEntry]

    @model_validator(mode="after")
    def _artifact_keys_are_bundle_local(self) -> HkpChecksumIndex:
        for key in self.artifacts:
            if LOCAL_PATH_RE.match(key) or ".." in Path(key).parts:
                raise ValueError(
                    "checksum artifact keys must be bundle-local and must not contain .."
                )
        return self


class HkpSnapshot(_HkpModel):
    hkp_schema: Literal[1]
    bundle_uid: str
    generated_at: str
    concept_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)

    @field_validator("bundle_uid")
    @classmethod
    def _bundle_uid_shape(cls, value: str) -> str:
        if not UID_RE.match(value):
            raise ValueError("bundle_uid must be an hkp uid")
        return value


def validate_bundle(
    bundle_path: Path | str, mode: ValidationMode | str = ValidationMode.GOVERNED
) -> HkpValidationResult:
    bundle = Path(bundle_path)
    validation_mode = ValidationMode(mode)
    validator = _BundleValidator(bundle=bundle, mode=validation_mode)
    return HkpValidationResult(bundle, validation_mode, tuple(validator.validate()))


class _BundleValidator:
    def __init__(self, bundle: Path, mode: ValidationMode) -> None:
        self.bundle = bundle
        self.mode = mode
        self.findings: list[HkpFinding] = []
        self.concept_uids: set[str] = set()
        self.manifest: HkpManifest | None = None
        self.concepts: dict[str, HkpConceptFrontmatter] = {}
        self.concept_paths: dict[str, Path] = {}
        self.source_ref_ids: dict[str, Path] = {}
        self.consumer_policy: HkpConsumerPolicy | None = None
        self.edges: list[HkpEdge] = []
        self.events: list[HkpProjectionEvent] = []
        self.snapshot: HkpSnapshot | None = None
        self.checksum_index: HkpChecksumIndex | None = None

    def validate(self) -> list[HkpFinding]:
        if self.bundle.is_symlink():
            self._error(
                "bundle_root_symlink",
                self.bundle,
                "bundle root must be a real directory, not a symlink; "
                "validate the real bundle directory or regenerate bundle",
            )
            return self.findings
        if not self.bundle.is_dir():
            self._error("bundle_missing", self.bundle, "bundle path must be a directory")
            return self.findings

        required_paths = [
            (self.bundle / "index.md", "file"),
            (self.bundle / "log.md", "file"),
            (self.bundle / "concepts", "dir"),
            (self.bundle / "references", "dir"),
            (self.bundle / "_hkp", "dir"),
            (self.bundle / "_hkp" / "manifest.yaml", "file"),
            (self.bundle / "_hkp" / "consumer_policy.yaml", "file"),
            (self.bundle / "_hkp" / "edges.jsonl", "file"),
            (self.bundle / "_hkp" / "events.jsonl", "file"),
            (self.bundle / "_hkp" / "snapshot.json", "file"),
            (self.bundle / "_hkp" / "checksums.json", "file"),
        ]
        for path, expected_type in required_paths:
            if _has_symlink_in_path(self.bundle, path):
                self._error(
                    "required_path_wrong_type",
                    path,
                    "required HKP path must be a real bundle path, not a symlink; "
                    "copy the artifact into the bundle or regenerate bundle",
                )
            elif not path.exists():
                self._error("required_path_missing", path, "required HKP bundle path is missing")
            elif expected_type == "dir" and not path.is_dir():
                self._error(
                    "required_path_wrong_type", path, "required HKP path must be a directory"
                )
            elif expected_type == "file" and not path.is_file():
                self._error("required_path_wrong_type", path, "required HKP path must be a file")

        self._validate_reserved_names()
        self._validate_bundle_file_whitelist()
        self._validate_manifest()
        self._validate_consumer_policy()
        self._validate_concepts()
        self._validate_edges()
        self._validate_events()
        self._validate_snapshot()
        self._validate_checksums()
        self._validate_cross_artifact_integrity()
        return self.findings

    def _validate_manifest(self) -> None:
        self.manifest = self._validate_yaml_model(
            self.bundle / "_hkp" / "manifest.yaml", HkpManifest, "manifest_invalid"
        )

    def _validate_consumer_policy(self) -> None:
        self.consumer_policy = self._validate_yaml_model(
            self.bundle / "_hkp" / "consumer_policy.yaml",
            HkpConsumerPolicy,
            "consumer_policy_invalid",
        )

    def _validate_reserved_names(self) -> None:
        for path in _iter_bundle_paths(self.bundle):
            if path.is_symlink():
                self._error(
                    "reserved_file_name",
                    path,
                    "HKP bundles must not contain symlinks; copy a redacted file instead",
                )
                continue
            reserved_parts = [
                part
                for part in path.relative_to(self.bundle).parts
                if part in RESERVED_BUNDLE_NAMES
            ]
            if reserved_parts:
                self._error(
                    "reserved_file_name",
                    path,
                    "HKP bundle contains reserved/private-control name; rename or remove: "
                    + ", ".join(reserved_parts),
                )

    def _validate_bundle_file_whitelist(self) -> None:
        for path in _iter_bundle_paths(self.bundle):
            relative = _rel(path, self.bundle)
            allowed = (
                relative in {"index.md", "log.md"}
                or relative in ALLOWED_HKP_FILES
                or (relative.startswith("concepts/") and path.suffix == ".md")
                or relative.startswith("references/")
            )
            if path.is_symlink():
                if not allowed:
                    self._error(
                        "bundle_unexpected_path",
                        path,
                        "HKP bundle contains symlink outside the allowed bundle layout; "
                        "remove the symlink or regenerate bundle",
                    )
                continue
            if path.is_dir():
                if (
                    relative in {"concepts", "references", "_hkp"}
                    or relative.startswith("concepts/")
                    or relative.startswith("references/")
                ):
                    continue
                self._error(
                    "bundle_unexpected_path",
                    path,
                    "HKP bundle contains unexpected directory outside concepts/, references/, "
                    "or _hkp/; remove the directory or regenerate bundle",
                )
                continue
            if not allowed:
                self._error(
                    "bundle_unexpected_path",
                    path,
                    "HKP bundle contains file outside the allowed bundle layout; "
                    "remove the file or regenerate bundle",
                )

    def _validate_concepts(self) -> None:
        concepts_root = self.bundle / "concepts"
        if concepts_root.is_symlink() or not concepts_root.is_dir():
            return
        for path in _iter_bundle_paths(concepts_root):
            if path.is_symlink() or path.suffix != ".md":
                continue
            parsed = parse_frontmatter_with_diagnostics(path)
            if not parsed.ok or parsed.frontmatter is None:
                self._error(
                    "concept_frontmatter_invalid",
                    path,
                    parsed.error_message or "concept markdown must have mapping frontmatter",
                )
                continue
            frontmatter = parsed.frontmatter
            for forbidden in ("concept_id", "provenance"):
                if forbidden in frontmatter:
                    self._error(
                        "reserved_field_misuse",
                        path,
                        f"{forbidden} is reserved locally; use concept_path/projection_provenance",
                    )
            unknown = sorted(
                key
                for key in frontmatter
                if key not in ALLOWED_TOP_LEVEL_CONCEPT_KEYS and not key.startswith("x_")
            )
            if unknown:
                self._error(
                    "unknown_top_level_field",
                    path,
                    "unknown top-level HKP keys must be under extensions/x_hkp: "
                    + ", ".join(unknown),
                )
            try:
                concept = HkpConceptFrontmatter.model_validate(frontmatter)
            except ValidationError as exc:
                self._validation_errors("concept_invalid", path, exc)
                continue
            if concept.type not in CONCEPT_TYPES:
                self._mode_finding(
                    "unknown_concept_type",
                    path,
                    "unknown concept type degrades to generic only in research mode; "
                    f"use a known HKP type or extend CONCEPT_TYPES: {concept.type}",
                )
            if concept.concept_uid in self.concept_uids:
                self._error(
                    "duplicate_concept_uid", path, f"duplicate concept_uid {concept.concept_uid}"
                )
            self.concept_uids.add(concept.concept_uid)
            self.concepts[concept.concept_uid] = concept
            self.concept_paths[concept.concept_uid] = path
            for source_ref in concept.source_refs:
                if source_ref.ref_id in self.source_ref_ids:
                    self._error(
                        "duplicate_source_ref_id",
                        path,
                        f"duplicate source ref id {source_ref.ref_id}; make ref_id bundle-unique",
                    )
                self.source_ref_ids[source_ref.ref_id] = path
            self._validate_markdown_links(path, parsed.body)

    def _validate_edges(self) -> None:
        self.edges = self._validate_jsonl_model(
            self.bundle / "_hkp" / "edges.jsonl", HkpEdge, "edge_invalid"
        )

    def _validate_events(self) -> None:
        self.events = self._validate_jsonl_model(
            self.bundle / "_hkp" / "events.jsonl", HkpProjectionEvent, "event_invalid"
        )

    def _validate_snapshot(self) -> None:
        path = self.bundle / "_hkp" / "snapshot.json"
        text = self._read_artifact_text(path, "snapshot_invalid")
        if text is None:
            return
        try:
            payload = json.loads(text)
            self.snapshot = HkpSnapshot.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            self._error("snapshot_invalid", path, str(exc))

    def _validate_checksums(self) -> None:
        path = self.bundle / "_hkp" / "checksums.json"
        text = self._read_artifact_text(path, "checksums_invalid")
        if text is None:
            return
        try:
            payload = json.loads(text)
            index = HkpChecksumIndex.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            self._error("checksums_invalid", path, str(exc))
            return
        self.checksum_index = index
        self._validate_checksum_artifacts(index)

    def _validate_checksum_artifacts(self, index: HkpChecksumIndex) -> None:
        required = {
            "index.md",
            "log.md",
            "_hkp/manifest.yaml",
            "_hkp/consumer_policy.yaml",
            "_hkp/edges.jsonl",
            "_hkp/events.jsonl",
            "_hkp/snapshot.json",
        }
        concepts_root = self.bundle / "concepts"
        if not concepts_root.is_symlink() and concepts_root.is_dir():
            required.update(
                _rel(path, self.bundle)
                for path in _iter_bundle_paths(concepts_root)
                if not path.is_symlink() and path.suffix == ".md"
            )
        references_root = self.bundle / "references"
        if not references_root.is_symlink() and references_root.is_dir():
            required.update(
                _rel(path, self.bundle)
                for path in _iter_bundle_paths(references_root)
                if not path.is_symlink() and path.is_file()
            )
        missing = sorted(required - set(index.artifacts))
        if missing:
            self._error(
                "checksums_missing_artifact",
                self.bundle / "_hkp" / "checksums.json",
                "checksums.json must include required bundle artifacts: " + ", ".join(missing),
            )
        for relative_path, entry in index.artifacts.items():
            artifact = self.bundle / relative_path
            if _has_symlink_in_path(self.bundle, artifact) or not artifact.is_file():
                self._error(
                    "checksums_artifact_missing",
                    self.bundle / "_hkp" / "checksums.json",
                    "checksum artifact is missing, a symlink, or not a file; "
                    f"add, remove, or copy a real file: {relative_path}",
                )
                continue
            if entry.hash_scope != "full_content":
                continue
            actual = "sha256:" + sha256(artifact.read_bytes()).hexdigest()
            if actual != entry.hash:
                self._error(
                    "checksums_hash_mismatch",
                    self.bundle / "_hkp" / "checksums.json",
                    f"checksum mismatch for {relative_path}; regenerate bundle checksums",
                )

    def _validate_cross_artifact_integrity(self) -> None:
        self._validate_manifest_integrity()
        self._validate_snapshot_integrity()
        self._validate_event_integrity()
        self._validate_concept_and_edge_refs()

    def _validate_manifest_integrity(self) -> None:
        if self.manifest is None:
            return
        actual_tree_hash = _tree_hash(self.bundle)
        if self.manifest.output_tree_hash != actual_tree_hash:
            self._error(
                "manifest_output_tree_hash_mismatch",
                self.bundle / "_hkp" / "manifest.yaml",
                "manifest output_tree_hash does not match bundle contents; regenerate bundle",
            )
        actual_input_hash = _input_ref_hash(self.concepts.values())
        if actual_input_hash is None:
            self._error(
                "manifest_input_ref_hash_mismatch",
                self.bundle / "_hkp" / "manifest.yaml",
                "manifest input_ref_hash cannot be verified because concept source_refs "
                "have no content_hash; restore source refs or regenerate bundle",
            )
        elif self.manifest.input_ref_hash != actual_input_hash:
            self._error(
                "manifest_input_ref_hash_mismatch",
                self.bundle / "_hkp" / "manifest.yaml",
                "manifest input_ref_hash does not match concept source_refs; regenerate bundle",
            )

    def _validate_snapshot_integrity(self) -> None:
        if self.snapshot is None:
            return
        if self.manifest is not None and self.snapshot.bundle_uid != self.manifest.bundle_uid:
            self._error(
                "snapshot_bundle_uid_mismatch",
                self.bundle / "_hkp" / "snapshot.json",
                "snapshot bundle_uid does not match manifest bundle_uid; regenerate bundle",
            )
        if self.snapshot.concept_count != len(self.concepts):
            self._error(
                "snapshot_concept_count_mismatch",
                self.bundle / "_hkp" / "snapshot.json",
                "snapshot concept_count does not match emitted concepts; regenerate bundle",
            )
        if self.snapshot.edge_count != len(self.edges):
            self._error(
                "snapshot_edge_count_mismatch",
                self.bundle / "_hkp" / "snapshot.json",
                "snapshot edge_count does not match emitted edges; regenerate bundle",
            )

    def _validate_event_integrity(self) -> None:
        if not self.events:
            return
        event_ids: set[str] = set()
        for event in self.events:
            if event.event_id in event_ids:
                self._error(
                    "duplicate_event_id",
                    self.bundle / "_hkp" / "events.jsonl",
                    f"duplicate event_id {event.event_id}; regenerate events with unique ids",
                )
            event_ids.add(event.event_id)
        sequences = [event.sequence for event in self.events]
        expected = list(range(len(self.events)))
        if sequences != expected:
            self._error(
                "event_sequence_not_contiguous",
                self.bundle / "_hkp" / "events.jsonl",
                "event sequence must be contiguous and file-ordered from 0: "
                f"{sequences}; regenerate events in projection order",
            )
        previous_hash: str | None = None
        bundle_uid = self.manifest.bundle_uid if self.manifest is not None else None
        for event in self.events:
            if event.previous_event_hash != previous_hash:
                self._error(
                    "event_hash_chain_broken",
                    self.bundle / "_hkp" / "events.jsonl",
                    f"event {event.event_id} previous_event_hash does not match prior row; "
                    "regenerate events from the source projection log",
                )
            if bundle_uid is not None:
                expected_event_id = _projection_event_id(
                    bundle_uid=bundle_uid,
                    sequence=event.sequence,
                    event_type=event.event_type,
                    subject_uid=event.subject_uid,
                )
                if event.event_id != expected_event_id:
                    self._error(
                        "event_id_mismatch",
                        self.bundle / "_hkp" / "events.jsonl",
                        "event_id for sequence "
                        f"{event.sequence} does not match HKP derivation; regenerate events",
                    )
            previous_hash = _json_hash(event.model_dump(mode="json"))

    def _validate_concept_and_edge_refs(self) -> None:
        event_ids = {event.event_id for event in self.events}
        for concept_uid, concept in self.concepts.items():
            path = self.concept_paths.get(concept_uid, self.bundle / "concepts")
            if not concept.projection_provenance.projection_event_ids:
                self._error(
                    "concept_projection_event_missing",
                    path,
                    "projection_event_ids is empty; repair concept provenance or regenerate events",
                )
            for event_id in concept.projection_provenance.projection_event_ids:
                if event_id not in event_ids:
                    self._error(
                        "concept_projection_event_missing",
                        path,
                        f"projection_event_id {event_id} is not present in _hkp/events.jsonl; "
                        "repair concept provenance or regenerate events",
                    )
            for evidence_ref in concept.projection_provenance.evidence_refs:
                if evidence_ref not in self.source_ref_ids:
                    self._error(
                        "concept_evidence_ref_missing",
                        path,
                        f"evidence_ref {evidence_ref} is not present in concept source_refs; "
                        "repair concept source_refs or provenance",
                    )
        for edge in self.edges:
            edge_path = self.bundle / "_hkp" / "edges.jsonl"
            if edge.from_uid not in self.concepts:
                self._error(
                    "edge_from_uid_missing",
                    edge_path,
                    f"edge from_uid {edge.from_uid} is not present in concepts; "
                    "repair edge endpoint or regenerate edges",
                )
            if edge.to_uid and edge.to_uid not in self.concepts:
                self._error(
                    "edge_to_uid_missing",
                    edge_path,
                    f"edge to_uid {edge.to_uid} is not present in concepts; "
                    "repair edge endpoint or regenerate edges",
                )
            if edge.target_path:
                target = self.bundle / edge.target_path
                target_missing = _has_symlink_in_path(self.bundle, target) or not target.is_file()
            else:
                target_missing = False
            if edge.target_path and target_missing:
                self._error(
                    "edge_target_path_missing",
                    edge_path,
                    f"edge target_path {edge.target_path} is not a real file in bundle; "
                    "repair target_path, copy the file, or regenerate edges",
                )
            for source_ref in edge.source_refs:
                if source_ref not in self.source_ref_ids:
                    self._error(
                        "edge_source_ref_missing",
                        edge_path,
                        f"edge source_ref {source_ref} is not present in concept source_refs; "
                        "repair edge source_refs or concept source_refs",
                    )
            if edge.generated_from.projection_event_id not in event_ids:
                self._error(
                    "edge_generated_from_event_missing",
                    edge_path,
                    "edge generated_from.projection_event_id is not present in "
                    "_hkp/events.jsonl; repair edge provenance or regenerate events",
                )

    def _validate_yaml_model(
        self, path: Path, model: type[BaseModel], code: str
    ) -> BaseModel | None:
        text = self._read_artifact_text(path, code)
        if text is None:
            return None
        try:
            payload = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            self._error(code, path, str(exc))
            return None
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            self._validation_errors(code, path, exc)
            return None

    def _validate_jsonl_model(
        self, path: Path, model: type[BaseModel], code: str
    ) -> list[BaseModel]:
        parsed: list[BaseModel] = []
        text = self._read_artifact_text(path, code)
        if text is None:
            return parsed
        lines = text.splitlines()
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                self._error(code, path, f"line {line_number}: {exc}")
                continue
            try:
                parsed.append(model.model_validate(payload))
            except ValidationError as exc:
                self._validation_errors(code, path, exc, line_number=line_number)
        return parsed

    def _read_artifact_text(self, path: Path, code: str) -> str | None:
        if _has_symlink_in_path(self.bundle, path):
            self._error(
                code,
                path,
                "HKP artifact must be a real bundle file, not a symlink; "
                "copy the redacted file into the bundle or regenerate bundle",
            )
            return None
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            self._error(code, path, str(exc))
            return None

    def _validate_markdown_links(self, path: Path, body: str) -> None:
        targets = [*MARKDOWN_LINK_RE.findall(body), *MARKDOWN_REFERENCE_LINK_RE.findall(body)]
        for target in targets:
            target = target.strip().strip("<>")
            if _is_external_link(target) or target.startswith("#"):
                continue
            relative = target.split("#", 1)[0]
            if not relative:
                continue
            if LOCAL_PATH_RE.match(relative):
                self._error(
                    "markdown_path_leak",
                    path,
                    f"markdown link target must not expose a local path: {target}",
                )
                continue
            resolved = (path.parent / relative).resolve()
            if not resolved.is_relative_to(self.bundle.resolve()):
                self._error(
                    "markdown_path_leak",
                    path,
                    f"markdown link target escapes bundle: {target}",
                )
                continue
            if resolved.exists():
                continue
            severity = (
                FindingSeverity.WARNING
                if self.mode == ValidationMode.RESEARCH
                else FindingSeverity.ERROR
            )
            self.findings.append(
                HkpFinding(
                    severity,
                    "broken_markdown_link",
                    _rel(path, self.bundle),
                    f"broken markdown link target: {target}",
                )
            )

    def _mode_finding(self, code: str, path: Path, message: str) -> None:
        severity = (
            FindingSeverity.WARNING
            if self.mode == ValidationMode.RESEARCH
            else FindingSeverity.ERROR
        )
        self.findings.append(HkpFinding(severity, code, _rel(path, self.bundle), message))

    def _validation_errors(
        self,
        code: str,
        path: Path,
        exc: ValidationError,
        *,
        line_number: int | None = None,
    ) -> None:
        prefix = f"line {line_number}: " if line_number is not None else ""
        for error in exc.errors():
            loc = ".".join(str(part) for part in error.get("loc", ()))
            message = error.get("msg", "validation error")
            detail = f"{prefix}{loc}: {message}" if loc else f"{prefix}{message}"
            self._error(code, path, detail)

    def _error(self, code: str, path: Path, message: str) -> None:
        self.findings.append(
            HkpFinding(FindingSeverity.ERROR, code, _rel(path, self.bundle), message)
        )


def _is_external_link(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:"))


def _iter_bundle_paths(root: Path) -> list[Path]:
    if root.is_symlink():
        return [root]
    paths: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        entries = [current / name for name in [*dirnames, *filenames]]
        paths.extend(entries)
        dirnames[:] = [name for name in dirnames if not (current / name).is_symlink()]
    return sorted(paths)


def _has_symlink_in_path(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _tree_hash(bundle: Path) -> str:
    rows: list[dict[str, str]] = []
    for path in _iter_bundle_paths(bundle):
        relative_path = path.relative_to(bundle).as_posix()
        if path.is_symlink() or not path.is_file() or relative_path in TREE_HASH_EXCLUDED_PATHS:
            continue
        rows.append({"path": relative_path, "hash": _file_hash(path)})
    return "sha256:" + sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _input_ref_hash(concepts: Any) -> str | None:
    rows: list[dict[str, str]] = []
    for concept in concepts:
        for source_ref in concept.source_refs:
            if source_ref.content_hash:
                rows.append({"uri": source_ref.uri, "content_hash": source_ref.content_hash})
    if not rows:
        return None
    rows.sort(key=lambda row: row["uri"])
    return "sha256:" + sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _file_hash(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _json_hash(payload: dict[str, Any]) -> str:
    return "sha256:" + sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _projection_event_id(
    *,
    bundle_uid: str,
    sequence: int,
    event_type: str,
    subject_uid: str,
) -> str:
    seed = f"{bundle_uid}:{sequence}:{event_type}:{subject_uid}"
    return f"event:{sha256(seed.encode()).hexdigest()[:24]}"


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)
