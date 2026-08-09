"""Deterministic WHAT/HOW/MUST canon materialization for the SDLC FSM."""

from __future__ import annotations

import ast
import base64
import csv
import importlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Self

import hapax.context_canon as _context_canon_package_module
import hapax.context_canon.contract as _context_canon_contract_module
import hapax.context_canon.event_plane as _context_canon_event_plane_module
import hapax.context_canon.projection as _context_canon_projection_module
import hapax.context_canon.schema as _context_canon_schema_module
import yaml
from hapax.context_canon import (  # noqa: F401 -- Council compatibility reexports
    ENCODER_ID,
    GENERATOR_VERSION,
    LOCKED_CONTEXT_BUNDLE_CONTRACT_SHA256,
    PROJECTION_ALGORITHM,
    REFERENCE_TOKENIZER_ID,
    AuthorityCeiling,
    AuthorizationFlag,
    BoundaryOrientationFacet,
    CanonError,
    CanonicalDecimal,
    CanonicalJsonObject,
    CapabilityBehaviorDatum,
    CapabilityBehaviorObservation,
    CommittedOutcomeReceiptLike,
    ContextAction,
    ContextAirBinding,
    ContextAirPolicy,
    ContextBundleCompatibilityProjection,
    ContextBundleFsm,
    ContextBundleImpingement,
    ContextBundleOrientingSignal,
    ContextBundleProvenance,
    ContextBundleStrata,
    ContextBundleTriAudience,
    ContextBundleWire,
    ContextConfidence,
    ContextExposure,
    ContextExposureComponent,
    ContextExposureDisposition,
    ContextExposureQuantity,
    ContextExposureSegment,
    ContextExposureStage,
    ContextExposureStageKind,
    ContextFact,
    ContextFrame,
    ContextImpingement,
    ContextInfluenceClass,
    ContextPosition,
    ContextProvenance,
    ContextRelation,
    ContextScope,
    ContextSelection,
    ContextSelectionClass,
    ContextSelectionEntry,
    ContextSelectionRequiredness,
    ContextSourceClass,
    ContextState,
    CounterfactualFacet,
    DemandShapeBinding,
    DemandShapeDescriptor,
    DerivationRecord,
    EpistemicEventKind,
    EpistemicEventPayload,
    EpistemicFlowEvent,
    FactFreshness,
    LifecycleDefinition,
    LifecycleFieldProvenance,
    LifecycleGuardEvidence,
    LifecycleOperationAdmission,
    LifecyclePossibilityFacet,
    LifecycleStageDefinition,
    LifecycleTransition,
    MeasurementApplicationReceipt,
    ObservabilityInvalidationResult,
    ObservationEnvelope,
    OrientationValueVector,
    OrientingSignal,
    PortalOffer,
    ProjectedFact,
    ProjectionEnvelope,
    ProjectionLevel,
    ProjectionLoss,
    ProjectionMappingManifest,
    ProvenanceAuthority,
    ProvenanceDerivation,
    ProvenanceKind,
    RedactedContextObject,
    RedactedFact,
    ResolutionCoordinate,
    SignalConstellation,
    SignalEstimate,
    SignalLearningReceipt,
    SignalLens,
    SignalValueAxis,
    SourceAdmission,
    TemporalCoordinate,
    TriAudienceProjectionRefs,
    build_boundary_orientation_facet,
    build_canonical_json_object,
    build_capability_behavior_observation,
    build_context_exposure,
    build_context_exposure_component,
    build_context_exposure_segment,
    build_context_scope,
    build_context_selection,
    build_demand_shape_descriptor,
    build_derivation_record,
    build_epistemic_flow_event,
    build_lifecycle_fsm_fact,
    build_lifecycle_possibility_facet,
    build_measurement_application_receipt,
    build_observation_envelope,
    build_orienting_signal,
    build_projection_mapping_manifest,
    build_resolution_coordinate,
    build_signal_constellation,
    build_signal_estimate,
    build_signal_learning_receipt,
    build_signal_lens,
    build_source_admission,
    build_temporal_coordinate,
    canonical_json_bytes,
    context_bundle_digest,
    context_bundle_json_bytes,
    derive_invalidated_observability_refs,
    lifecycle_operation_admission_ref,
    lifecycle_transition_admission_ref,
    project_context_bundle_v1,
    project_context_frame,
    reference_token_count,
    signal_constellation_loss_manifest_ref,
    validate_context_behavior_learning_join,
    verify_context_bundle_v1,
    verify_projection,
)
from hapax.context_canon.contract import (
    _ATOM_ID_PATTERN,
    _HASH_PATTERN,
    _JSON_SAFE_INTEGER_MAX,
    FrozenModel,
    LifecycleCanonImageCarrier,
    _canon_error,
    _domain_hash,
    _lifecycle_fsm_context_payload,
    _lifecycle_legal_successors,
    _lifecycle_stage,
    _render_canon_stratum,
    _sha256,
)
from hapax.context_canon.contract import (
    _validate_fact_evidence_and_authority as _validate_fact_evidence_and_authority,
)
from pydantic import (
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

import shared.compression.registry as _compression_registry_module
import shared.sdlc_lifecycle as _sdlc_lifecycle_module
from shared.compression.registry import SurfaceSpec, get_surface_spec, parse_registry
from shared.sdlc_lifecycle import (
    SDLC_STAGE_METADATA,
    SDLC_STAGE_METADATA_PATH,
    StageEdgeMetadata,
    StageMetadata,
    StageMetadataCatalog,
    parse_sdlc_stage_metadata,
)

CANON_SOURCE_SCHEMA = "hapax.coordination-canon.source.v1"
CANON_IMAGE_SCHEMA = "hapax.coordination-canon.image.v1"
CANON_BUNDLE_SCHEMA = "hapax.coordination-canon.bundle.v1"
COMPRESSION_SURFACE = "coordination_canon"
PYTHON_TOON_VERSION = "0.1.3"


_REPO_ROOT = Path(__file__).resolve().parents[1]
CANON_SOURCE_PATH = _REPO_ROOT / "config" / "coordination-canon" / "source.yaml"
CANON_SCHEMA_PATH = _REPO_ROOT / "schemas" / "coordination-canon.schema.json"
TLA_PATH = _REPO_ROOT / "docs" / "formal" / "sdlc-ladder.tla"
COMPRESSION_REGISTRY_PATH = _REPO_ROOT / "config" / "compression-surface-registry.yaml"
RUNTIME_DEPENDENCY_RELEASE_SET_PATH = (
    _REPO_ROOT / "config" / "coordination-canon" / "runtime-dependency-release-set.json"
)
_CONTEXT_CANON_SOURCE_PREFIX = "packages/hapax-context-canon/src/hapax/context_canon/"
_CONTEXT_CANON_SOURCE_MODULES = MappingProxyType(
    {
        f"{_CONTEXT_CANON_SOURCE_PREFIX}__init__.py": _context_canon_package_module,
        f"{_CONTEXT_CANON_SOURCE_PREFIX}contract.py": _context_canon_contract_module,
        f"{_CONTEXT_CANON_SOURCE_PREFIX}event_plane.py": _context_canon_event_plane_module,
        f"{_CONTEXT_CANON_SOURCE_PREFIX}projection.py": _context_canon_projection_module,
        f"{_CONTEXT_CANON_SOURCE_PREFIX}schema.py": _context_canon_schema_module,
    }
)
_CONTEXT_CANON_SOURCE_RESOURCES = MappingProxyType(
    {
        f"{_CONTEXT_CANON_SOURCE_PREFIX}_data/context-canon-carrier.schema.json": (
            "_data/context-canon-carrier.schema.json"
        ),
    }
)
_CONTEXT_CANON_RUNTIME_IDENTITIES = MappingProxyType(
    {
        "python-distribution:annotated-types": (
            "annotated-types",
            "0.7.0",
            "annotated_types",
        ),
        "python-distribution:pydantic": ("pydantic", "2.13.4", "pydantic"),
        "python-distribution:pydantic-core": (
            "pydantic-core",
            "2.46.4",
            "pydantic_core",
        ),
        "python-distribution:python-toon": ("python-toon", "0.1.3", "toon"),
        "python-distribution:typing-extensions": (
            "typing-extensions",
            "4.15.0",
            "typing_extensions",
        ),
        "python-distribution:typing-inspection": (
            "typing-inspection",
            "0.4.2",
            "typing_inspection",
        ),
    }
)
_COUNCIL_SOURCE_MODULES = MappingProxyType(
    {
        "shared/compression/registry.py": _compression_registry_module,
        "shared/sdlc_lifecycle.py": _sdlc_lifecycle_module,
    }
)
_COUNCIL_SOURCE_VALUE_REFS = ("shared/coord_projection.py#NO_GO_BOOLEANS",)
_COUNCIL_RUNTIME_IDENTITIES = MappingProxyType(
    {"python-distribution:PyYAML": ("PyYAML", "6.0.3", "yaml")}
)
_SOURCE_HASH_REFS = tuple(
    sorted(
        (
            "config/compression-surface-registry.yaml",
            "config/coordination-canon/source.yaml",
            "config/coordination-canon/runtime-dependency-release-set.json",
            "docs/formal/sdlc-ladder.tla",
            "docs/formal/sdlc-stage-metadata.yaml",
            *_CONTEXT_CANON_SOURCE_MODULES,
            *_CONTEXT_CANON_SOURCE_RESOURCES,
            *_CONTEXT_CANON_RUNTIME_IDENTITIES,
            *_COUNCIL_SOURCE_MODULES,
            *_COUNCIL_SOURCE_VALUE_REFS,
            *_COUNCIL_RUNTIME_IDENTITIES,
            "shared/session_context_canon.py",
        )
    )
)
_LEVEL_ORDER = ("pi0", "pi1", "pi2", "pi3")
_REQUIRED_MUST_IDS_V1 = frozenset(
    {
        "must.atomic-position-chain",
        "must.authorization-absence",
        "must.binding-vocabulary",
        "must.canon-before-prune",
        "must.canon-echo-repair",
        "must.conformance-before-dispatch",
        "must.constraint-mask-before-signal-utility",
        "must.context-action-lifecycle-admission",
        "must.coordinator-engagement",
        "must.escape-grant",
        "must.gate-is-authority",
        "must.grounding.atomic-position-vocabulary",
        "must.grounding.authorization-vocabulary",
        "must.grounding.gate-verdict-vocabulary",
        "must.impingement-offer-plane",
        "must.inv1-deadlock-freedom",
        "must.inv2-liveness",
        "must.inv3-escape",
        "must.inv4-authority-escapable",
        "must.inv5-cognition-writable",
        "must.lockstep-protected-actions",
        "must.learning-receipt-specificity",
        "must.lossless-canon",
        "must.no-silent-downgrade",
        "must.off-limits-surface-principle",
        "must.pi-floor-mask-before-objective",
        "must.projection-loss-manifest",
        "must.provenance-kind-source-binding",
        "must.raw-prose-gate",
        "must.reins-never-authority",
        "must.scope-mask-before-objective",
        "must.singleton-lease",
        "must.signal-estimate-offer-separation",
        "must.source-admission-before-derivation",
        "must.transition-reconsult",
        "must.two-kernel-separation",
        "must.orthogonal-context-coordinates",
    }
)
_REQUIRED_GROUNDING_IDS_V1 = frozenset(
    {
        "how.command-paths",
        "must.authorization-absence",
        "must.binding-vocabulary",
        "must.canon-echo-repair",
        "must.constraint-mask-before-signal-utility",
        "must.context-action-lifecycle-admission",
        "must.coordinator-engagement",
        "must.escape-grant",
        "must.grounding.atomic-position-vocabulary",
        "must.grounding.authorization-vocabulary",
        "must.grounding.gate-verdict-vocabulary",
        "must.lockstep-protected-actions",
        "must.learning-receipt-specificity",
        "must.no-silent-downgrade",
        "must.orthogonal-context-coordinates",
        "must.projection-loss-manifest",
        "must.raw-prose-gate",
        "must.scope-mask-before-objective",
        "must.singleton-lease",
        "must.signal-estimate-offer-separation",
        "must.source-admission-before-derivation",
        "must.transition-reconsult",
        "what.grounding.blocked-repair",
        "what.grounding.disconfirmation-repair",
        "what.grounding.stage-vocabulary",
    }
)


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects last-wins duplicate mappings."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise CanonError(
                "canon_source_invalid_yaml_key",
                repair_action="use scalar mapping keys in the canon source",
            ) from exc
        if duplicate:
            raise CanonError(
                "canon_source_duplicate_yaml_key",
                detail=str(key),
                repair_action="remove the duplicate key; last-wins YAML is forbidden",
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


class WireContract(FrozenModel):
    kind: Literal["context_bundle"]
    sha256: Literal["8204a2b2804aa41ac95f75414b58fa88ae1e76a48e6ef731807f544f4148fbd9"]
    fsm_fields: tuple[Literal["what", "how", "must"], ...]

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        if self.fsm_fields != ("what", "how", "must"):
            raise ValueError("fsm_fields must be exactly what, how, must")
        return self


class CanonAtom(FrozenModel):
    id: str = Field(pattern=_ATOM_ID_PATTERN)
    ordinal: int = Field(ge=0, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    stratum: Literal["what", "how", "must"]
    content: str
    grounding: bool = Field(strict=True)
    applies_to: tuple[str, ...]
    source_refs: tuple[str, ...]

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("content must be nonblank without edge whitespace")
        if not value.isascii():
            raise ValueError("v1 canon content must be ASCII for stable reference tokenization")
        return value

    @field_validator("applies_to", "source_refs")
    @classmethod
    def validate_string_tuple(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item or item != item.strip() for item in value):
            raise ValueError("list entries must be nonblank without edge whitespace")
        if len(value) != len(set(value)):
            raise ValueError("list entries must be unique")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if not self.id.startswith(f"{self.stratum}."):
            raise ValueError("atom id prefix must match stratum")
        if "*" in self.applies_to and self.applies_to != ("*",):
            raise ValueError("global applicability cannot be mixed with stage tokens")
        if self.stratum == "must" and self.applies_to != ("*",):
            raise ValueError("MUST atoms must apply identically to every stage")
        return self


class CanonSource(FrozenModel):
    schema_id: Literal["hapax.coordination-canon.source.v1"] = Field(alias="schema")
    canon_version: int = Field(ge=1, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    domain: Literal["sdlc"]
    generator_version: Literal["hapax.session-context-canon.v1"]
    projection_algorithm: Literal["hapax.sdlc-forward-cone.v1"]
    encoder_id: Literal["python-toon@0.1.3"]
    reference_tokenizer_id: Literal["hapax.ascii-lexeme.v1"]
    wire_contract: WireContract
    atoms: tuple[CanonAtom, ...]

    @model_validator(mode="after")
    def validate_atoms(self) -> Self:
        ids = [atom.id for atom in self.atoms]
        ordinals = [atom.ordinal for atom in self.atoms]
        if len(ids) != len(set(ids)):
            raise ValueError("atom ids must be unique")
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("atom ordinals must be unique")
        if {atom.stratum for atom in self.atoms} != {"what", "how", "must"}:
            raise ValueError("source must declare nonempty WHAT, HOW, and MUST atoms")
        _validate_required_atom_manifest(self.atoms, self.canon_version)
        return self


class SourceHash(FrozenModel):
    source_ref: str
    sha256: str = Field(pattern=_HASH_PATTERN)


class _ReleaseArtifact(FrozenModel):
    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=_HASH_PATTERN)
    size: int = Field(ge=0)
    url: str = Field(min_length=1)

    @field_validator("filename", "url")
    @classmethod
    def validate_ascii_scalar(cls, value: str) -> str:
        if value != value.strip() or not value.isascii():
            raise ValueError("release artifact strings must be edge-trimmed ASCII")
        return value


class _RuntimeDependencyRelease(FrozenModel):
    distribution: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    import_root: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$")
    source_registry: str = Field(min_length=1)
    sdist: _ReleaseArtifact
    version: str = Field(min_length=1)
    wheels: tuple[_ReleaseArtifact, ...] = Field(min_length=1)
    release_set_hash: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_release_set(self) -> Self:
        filenames = tuple(item.filename for item in self.wheels)
        if filenames != tuple(sorted(filenames)) or len(filenames) != len(set(filenames)):
            raise ValueError("release wheel filenames must be unique and sorted")
        body = self.model_dump(mode="json", exclude={"release_set_hash"})
        expected = _domain_hash("hapax.python-distribution.release-set.v1", body)
        if self.release_set_hash != expected:
            raise ValueError("release_set_hash does not bind the release set")
        return self


class _RuntimeDependencyReleaseManifest(FrozenModel):
    dependencies: tuple[_RuntimeDependencyRelease, ...] = Field(min_length=1)
    projection_algorithm: Literal["hapax.uv-lock-release-set.v1"]
    schema_id: Literal["hapax.python-runtime-dependency-release-set.v1"] = Field(alias="schema")
    source_lock_ref: Literal["uv.lock"]
    manifest_hash: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        names = tuple(item.distribution for item in self.dependencies)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("release dependencies must be unique and sorted")
        body = self.model_dump(mode="json", by_alias=True, exclude={"manifest_hash"})
        expected = _domain_hash("hapax.python-runtime-dependency-release-set.v1", body)
        if self.manifest_hash != expected:
            raise ValueError("manifest_hash does not bind the dependency release set")
        return self


class FsmStrata(FrozenModel):
    what: tuple[CanonAtom, ...] = Field(min_length=1)
    how: tuple[CanonAtom, ...] = Field(min_length=1)
    must: tuple[CanonAtom, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        partitions = {"what": self.what, "how": self.how, "must": self.must}
        seen: set[str] = set()
        for stratum, atoms in partitions.items():
            for atom in atoms:
                if atom.stratum != stratum:
                    raise ValueError("atom appears in the wrong stratum")
                if atom.id in seen:
                    raise ValueError("atom appears in more than one stratum")
                seen.add(atom.id)
        return self


class StrataEnvelope(FrozenModel):
    fsm: FsmStrata


class RenderedFsm(FrozenModel):
    what: str
    how: str
    must: str


class CanonKernel(FrozenModel):
    name: str
    omitted_atom_ids: tuple[str, ...]
    omitted_digest: str = Field(pattern=_HASH_PATTERN)
    distortion_class: Literal[
        "none",
        "outside_forward_cone",
        "multi_step_lookahead",
        "fsm_structure_and_procedures",
    ]

    @model_validator(mode="after")
    def validate_kernel(self) -> Self:
        if self.omitted_atom_ids != tuple(sorted(set(self.omitted_atom_ids))):
            raise ValueError("omitted_atom_ids must be sorted and unique")
        expected = _sha256(canonical_json_bytes(list(self.omitted_atom_ids)))
        if self.omitted_digest != expected:
            raise ValueError("omitted_digest does not bind omitted_atom_ids")
        return self


class CanonImage(LifecycleCanonImageCarrier):
    schema_id: Literal["hapax.coordination-canon.image.v1"] = Field(alias="schema")
    canon_version: int = Field(ge=1, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    generator_version: Literal["hapax.session-context-canon.v1"]
    projection_algorithm: Literal["hapax.sdlc-forward-cone.v1"]
    encoder_id: Literal["python-toon@0.1.3"]
    reference_tokenizer_id: Literal["hapax.ascii-lexeme.v1"]
    reference_token_count: int = Field(ge=1, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    stage_token: str
    level: ProjectionLevel
    projection_scope: tuple[str, ...] = Field(min_length=1)
    source_hashes: tuple[SourceHash, ...] = Field(
        min_length=len(_SOURCE_HASH_REFS), max_length=len(_SOURCE_HASH_REFS)
    )
    lifecycle_definition_hash: str = Field(pattern=_HASH_PATTERN)
    canon_hash: str = Field(pattern=_HASH_PATTERN)
    canon_id: str
    strata: StrataEnvelope
    grounding_core: tuple[CanonAtom, ...] = Field(min_length=1)
    kernel: CanonKernel
    rendered_strata: RenderedFsm
    rendered_payload: str
    image_hash: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_image(self) -> Self:
        expected_id = f"coordination-canon@sha256:{self.canon_hash}"
        if self.canon_id != expected_id:
            raise ValueError("canon_id does not bind canon_hash")
        grounding = tuple(
            sorted(
                (
                    atom
                    for atom in (
                        *self.strata.fsm.what,
                        *self.strata.fsm.how,
                        *self.strata.fsm.must,
                    )
                    if atom.grounding
                ),
                key=lambda atom: (atom.ordinal, atom.id),
            )
        )
        if grounding != self.grounding_core:
            raise ValueError("grounding_core does not match projected grounding atoms")
        if tuple(item.source_ref for item in self.source_hashes) != _SOURCE_HASH_REFS:
            raise ValueError("source_hashes do not match the exact ordered source manifest")
        if self.stage_token not in self.projection_scope:
            raise ValueError("projection_scope must include the image stage")
        if self.projection_scope != tuple(dict.fromkeys(self.projection_scope)):
            raise ValueError("projection_scope must be ordered and unique")
        expected_rendered = RenderedFsm(
            what=_render_stratum(self.strata.fsm.what),
            how=_render_stratum(self.strata.fsm.how),
            must=_render_stratum(self.strata.fsm.must),
        )
        if self.rendered_strata != expected_rendered:
            raise ValueError("rendered_strata do not bind the typed strata")
        expected_payload = _render_payload(expected_rendered)
        if self.rendered_payload != expected_payload:
            raise ValueError("rendered_payload does not bind rendered_strata")
        if self.reference_token_count != reference_token_count(expected_payload):
            raise ValueError("reference_token_count does not bind rendered_payload")
        body = self.model_dump(mode="json", by_alias=True, exclude={"image_hash"})
        if self.image_hash != _sha256(canonical_json_bytes(body)):
            raise ValueError("image_hash does not bind the image body")
        return self


class CanonBundle(FrozenModel):
    schema_id: Literal["hapax.coordination-canon.bundle.v1"] = Field(alias="schema")
    canon_version: int = Field(ge=1, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    generator_version: Literal["hapax.session-context-canon.v1"]
    projection_algorithm: Literal["hapax.sdlc-forward-cone.v1"]
    source_hashes: tuple[SourceHash, ...] = Field(
        min_length=len(_SOURCE_HASH_REFS), max_length=len(_SOURCE_HASH_REFS)
    )
    lifecycle_definition: LifecycleDefinition
    canon_hash: str = Field(pattern=_HASH_PATTERN)
    images: tuple[CanonImage, ...] = Field(min_length=1)
    bundle_ref: str
    bundle_hash: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        keys = [(image.stage_token, image.level.value) for image in self.images]
        tokens = tuple(stage.token for stage in self.lifecycle_definition.stages)
        expected_keys = [(stage_token, level) for stage_token in tokens for level in _LEVEL_ORDER]
        if keys != expected_keys:
            raise ValueError("bundle images must be the exact lifecycle stage/level product")
        if tuple(item.source_ref for item in self.source_hashes) != _SOURCE_HASH_REFS:
            raise ValueError("source_hashes do not match the exact ordered source manifest")
        if any(image.canon_hash != self.canon_hash for image in self.images):
            raise ValueError("image canon_hash differs from bundle canon_hash")
        if any(image.source_hashes != self.source_hashes for image in self.images):
            raise ValueError("image source_hashes differ from bundle source_hashes")
        if any(image.canon_version != self.canon_version for image in self.images):
            raise ValueError("image canon_version differs from bundle canon_version")
        if any(
            image.lifecycle_definition_hash != self.lifecycle_definition.definition_hash
            for image in self.images
        ):
            raise ValueError("image lifecycle definition differs from bundle definition")
        stage_source = next(
            item
            for item in self.source_hashes
            if item.source_ref == "docs/formal/sdlc-stage-metadata.yaml"
        )
        if self.lifecycle_definition.source_hash != stage_source.sha256:
            raise ValueError("lifecycle definition does not bind the bundle metadata snapshot")
        full_images = tuple(image for image in self.images if image.level is ProjectionLevel.FULL)
        baseline = full_images[0].strata.fsm
        if any(image.strata.fsm != baseline for image in full_images):
            raise ValueError("pi0 images do not carry one identical exhaustive corpus")
        full_atoms = tuple(
            sorted(
                (*baseline.what, *baseline.how, *baseline.must),
                key=lambda atom: (atom.ordinal, atom.id),
            )
        )
        _validate_required_atom_manifest(full_atoms, self.canon_version, tokens)
        expected_canon_hash = _sha256(
            canonical_json_bytes(_canon_identity_body(self.canon_version, full_atoms))
        )
        if self.canon_hash != expected_canon_hash:
            raise ValueError("canon_hash does not bind the locked semantic corpus")
        for image in self.images:
            expected_scope = _projection_scope_definition(
                image.stage_token, image.level, self.lifecycle_definition
            )
            if image.projection_scope != expected_scope:
                raise ValueError(
                    f"image scope does not match embedded lifecycle: "
                    f"{image.stage_token}/{image.level.value}"
                )
            expected_atoms = _select_atoms_from_full(
                full_atoms, image.stage_token, image.level, scope=expected_scope
            )
            if image.strata.fsm != _strata(expected_atoms):
                raise ValueError(
                    f"image strata do not match projection semantics: {image.stage_token}/{image.level.value}"
                )
            expected_kernel = _kernel_from_full(full_atoms, expected_atoms, image.level)
            if image.kernel != expected_kernel:
                raise ValueError(
                    f"image kernel does not match the exact corpus complement: "
                    f"{image.stage_token}/{image.level.value}"
                )
        body = self.model_dump(mode="json", by_alias=True, exclude={"bundle_ref", "bundle_hash"})
        expected_hash = _domain_hash("hapax.coordination-canon.bundle.v1", body)
        if self.bundle_hash != expected_hash:
            raise ValueError("bundle_hash does not bind the bundle body")
        if self.bundle_ref != f"canon-bundle@sha256:{expected_hash}":
            raise ValueError("bundle_ref does not bind bundle_hash")
        return self


CanonBundle.model_rebuild()


@dataclass(frozen=True)
class CanonCorpus:
    source: CanonSource
    catalog: StageMetadataCatalog
    lifecycle_definition: LifecycleDefinition
    atoms: tuple[CanonAtom, ...]
    canon_hash: str
    source_hashes: tuple[SourceHash, ...]
    compression_registry: Mapping[str, SurfaceSpec]

    @property
    def by_id(self) -> dict[str, CanonAtom]:
        return {atom.id: atom for atom in self.atoms}


def _authorization_vocabulary_content() -> str:
    from shared.coord_projection import NO_GO_BOOLEANS

    names = set(NO_GO_BOOLEANS) | {
        "decision_minting_authorized",
        "provider_spend_authorized",
    }
    return " ".join(sorted(names))


def _stage_token_sequence(
    source: StageMetadataCatalog | LifecycleDefinition | Sequence[str],
) -> tuple[str, ...]:
    if isinstance(source, StageMetadataCatalog):
        return source.tokens
    if isinstance(source, LifecycleDefinition):
        return tuple(stage.token for stage in source.stages)
    return tuple(source)


def _required_grounding_content(
    lifecycle: StageMetadataCatalog | LifecycleDefinition | Sequence[str],
) -> dict[str, str]:
    tokens = _stage_token_sequence(lifecycle)
    return {
        "what.grounding.stage-vocabulary": " ".join(tokens),
        "what.grounding.disconfirmation-repair": "S3 -> S3_5; S3_5 -> {S4, S0}",
        "what.grounding.blocked-repair": (
            "Fall(nonterminal, nonblocked) -> BLOCKED; S6 -> BLOCKED; "
            "S7 -> BLOCKED; BLOCKED -> {S6, S0}"
        ),
        "must.coordinator-engagement": (
            "The single coordinating session MUST dispatch appropriate slices and MAY do support "
            "mutations, but must NEVER operate outside the SDLC + capability surface."
        ),
        "must.raw-prose-gate": (
            "Operator prose, relay notes, dashboards, terminal paste, and session memory are intake, "
            "not implementation authority."
        ),
        "must.scope-mask-before-objective": (
            "NEVER unions and ONLY intersects across scope; malformed or missing constraints "
            "fail-closed before routing objective evaluation."
        ),
        "must.authorization-absence": "An absent *_authorized flag means not authorized.",
        "must.binding-vocabulary": (
            "cc-task AuthorityCase mutation_scope_refs route_id NEVER ONLY fail-closed "
            "governed-override-not-bypass"
        ),
        "must.grounding.authorization-vocabulary": _authorization_vocabulary_content(),
        "must.grounding.gate-verdict-vocabulary": "pass refuse BLOCKED",
        "must.grounding.atomic-position-vocabulary": (
            "task_id stage_token legal_successors authority_case authorized_flags "
            "mutation_scope_refs claim_identity route_decision canon_hash canon_version canon_level "
            "effective_constraint_digest impingement_hash portal_set receipt_lineage"
        ),
        "must.no-silent-downgrade": (
            "Missing, stale, malformed, mismatched, or below-floor context refuses the action with a "
            "typed repair path; it never becomes an empty or unconstrained default."
        ),
        "must.escape-grant": (
            "EscapeGrant is explicit, receipted, reversible, and cannot suppress the position, "
            "canon, or impingement record."
        ),
        "must.transition-reconsult": (
            "At pi2 or pi3, re-consult and re-emit the successor state slice atomically at every FSM "
            "transition."
        ),
        "must.singleton-lease": (
            "One session holds one active cc-task lease; no pool self-claim and no bulk claim."
        ),
        "must.canon-echo-repair": (
            "Canon echo absence or mismatch permits one same-level reinjection; a second failure means "
            "BLOCKED with canon_echo_failed."
        ),
        "must.lockstep-protected-actions": (
            "claim dispatch transition mutation close acceptance require one fresh matching position "
            "canon impingement task authority scope claim route receipt chain; absence staleness or "
            "mismatch means refuse."
        ),
        "must.source-admission-before-derivation": (
            "Every derivation fact estimate signal lens constellation or learning receipt must trace "
            "to an admitted source; AIR joins every dependency before count sort relation aggregation "
            "utility or rendering."
        ),
        "must.orthogonal-context-coordinates": (
            "Scope lifecycle position temporal scale temporal tense semantic resolution environment "
            "scope audience and purpose remain independent; surprise is a signal estimate and never "
            "a temporal axis."
        ),
        "must.signal-estimate-offer-separation": (
            "A SignalEstimate is evidence-derived state; an OrientingSignal is a no-effect attention "
            "offer bound to estimates lens constellation position and optional portal; neither may "
            "authorize."
        ),
        "must.constraint-mask-before-signal-utility": (
            "A signal lens applies the exact constraint mask before utility weighting or constellation "
            "formation; no score signal or pickup can weaken WHAT MUST authority or admission."
        ),
        "must.learning-receipt-specificity": (
            "A learning update requires exposure candidate set selection policy propensity action "
            "outcome effect cost witnesses receipt correction and exactly one named update target."
        ),
        "must.context-action-lifecycle-admission": (
            "Every lifecycle operation or transition shown as an action binds the exact current "
            "position and matching lifecycle admission; unavailable evidence or authority cannot render "
            "the action legal."
        ),
        "must.projection-loss-manifest": (
            "Every projection carries one content-addressed static field mapping and exhaustive omission "
            "manifest plus a deny-oblivious instance loss receipt; hashes prove structure not producer "
            "authenticity."
        ),
        "how.command-paths": (
            "scripts/hapax-methodology-dispatch scripts/cc-claim scripts/cc-close "
            "scripts/cc-stage-advance"
        ),
    }


def _validate_required_atom_manifest(
    atoms: Sequence[CanonAtom],
    canon_version: int,
    lifecycle: StageMetadataCatalog | LifecycleDefinition | Sequence[str] | None = None,
) -> None:
    if canon_version != 1:
        raise ValueError(f"no required atom manifest is defined for canon_version {canon_version}")
    by_id = {atom.id: atom for atom in atoms}
    missing_must = sorted(_REQUIRED_MUST_IDS_V1 - set(by_id))
    if missing_must:
        raise ValueError(f"required MUST atoms are missing: {','.join(missing_must)}")
    missing_grounding = sorted(_REQUIRED_GROUNDING_IDS_V1 - set(by_id))
    if missing_grounding:
        raise ValueError(f"required grounding atoms are missing: {','.join(missing_grounding)}")
    wrong_stratum = sorted(
        atom_id for atom_id in _REQUIRED_MUST_IDS_V1 if by_id[atom_id].stratum != "must"
    )
    if wrong_stratum:
        raise ValueError(f"required MUST atoms have the wrong stratum: {','.join(wrong_stratum)}")
    not_grounding = sorted(
        atom_id for atom_id in _REQUIRED_GROUNDING_IDS_V1 if not by_id[atom_id].grounding
    )
    if not_grounding:
        raise ValueError(f"required grounding atoms are not grounding: {','.join(not_grounding)}")
    if lifecycle is not None:
        for atom_id, expected in _required_grounding_content(lifecycle).items():
            atom = by_id.get(atom_id)
            if atom is None or atom.content != expected:
                raise ValueError(f"required grounding bytes differ: {atom_id}")


def _validate_source_semantics(source: CanonSource) -> None:
    observed = (
        source.schema_id,
        source.domain,
        source.generator_version,
        source.projection_algorithm,
        source.encoder_id,
        source.reference_tokenizer_id,
        source.wire_contract.kind,
        source.wire_contract.sha256,
        source.wire_contract.fsm_fields,
    )
    expected = (
        CANON_SOURCE_SCHEMA,
        "sdlc",
        GENERATOR_VERSION,
        PROJECTION_ALGORITHM,
        ENCODER_ID,
        REFERENCE_TOKENIZER_ID,
        "context_bundle",
        LOCKED_CONTEXT_BUNDLE_CONTRACT_SHA256,
        ("what", "how", "must"),
    )
    if observed != expected:
        raise _canon_error(
            "canon_source_semantic_identity_mismatch",
            "restore the locked source, generator, projection, encoder, tokenizer, and wire identities",
        )


def _read_text(path: Path, *, reason: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _canon_error(reason, f"restore readable UTF-8 source {path}") from exc


def _module_imports(source_text: str) -> tuple[set[str], set[str]]:
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        raise _canon_error(
            "canon_generator_invalid_python",
            "restore parseable generator source before materialization",
        ) from exc
    modules: set[str] = set()
    roots: set[str] = set()
    for node in ast.walk(tree):
        names: tuple[str, ...] = ()
        if isinstance(node, ast.Import):
            names = tuple(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = (node.module,)
        for name in names:
            modules.add(name)
            roots.add(name.split(".", 1)[0])
    return modules, roots


def _verify_runtime_import_closure(
    source_payloads: Mapping[str, str],
    *,
    expected_roots: frozenset[str],
    internal_roots: frozenset[str],
    reason_code: str,
) -> None:
    observed: set[str] = set()
    for source_ref, source_text in source_payloads.items():
        if not source_ref.endswith(".py"):
            continue
        _, roots = _module_imports(source_text)
        observed.update(roots - sys.stdlib_module_names - internal_roots)
    if observed != expected_roots:
        detail = ",".join(sorted(observed ^ expected_roots))
        raise _canon_error(
            reason_code,
            "bind every direct non-standard-library runtime import",
            detail,
        )


def _normalized_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _dependency_release(
    distribution: str,
    expected_version: str,
    import_root: str,
    *,
    release_manifest: _RuntimeDependencyReleaseManifest,
) -> _RuntimeDependencyRelease:
    normalized_distribution = _normalized_distribution_name(distribution)
    release = next(
        (
            item
            for item in release_manifest.dependencies
            if item.distribution == normalized_distribution
        ),
        None,
    )
    if release is None:
        raise _canon_error(
            "canon_runtime_dependency_release_unbound",
            "bind every runtime dependency to the accepted release-set manifest",
            normalized_distribution,
        )
    if release.version != expected_version or release.import_root != import_root:
        raise _canon_error(
            "canon_runtime_dependency_release_mismatch",
            "reconcile dependency coordinates with the accepted release-set manifest",
            normalized_distribution,
        )
    return release


def _distribution_semantic_release_payload(
    distribution: str,
    expected_version: str,
    import_root: str,
    *,
    release_manifest: _RuntimeDependencyReleaseManifest,
) -> str:
    """Return cross-platform dependency semantics without runtime-attestation data."""

    release = _dependency_release(
        distribution,
        expected_version,
        import_root,
        release_manifest=release_manifest,
    )
    identity = {
        "distribution": release.distribution,
        "identity_schema": "hapax.python-distribution.semantic-release.v1",
        "import_root": import_root,
        "release_manifest_ref": (
            f"python-runtime-dependency-release-set@sha256:{release_manifest.manifest_hash}"
        ),
        "release_set_hash": release.release_set_hash,
        "release_set_ref": (f"python-distribution-release-set@sha256:{release.release_set_hash}"),
        "source_registry": release.source_registry,
        "version": expected_version,
    }
    return canonical_json_bytes(identity).decode("utf-8") + "\n"


def _runtime_dependency_record_observation(
    distribution: str,
    expected_version: str,
    import_root: str,
    *,
    release_manifest: _RuntimeDependencyReleaseManifest,
) -> dict[str, object]:
    """Measure installed RECORD consistency without treating it as release provenance."""

    try:
        installed = importlib_metadata.distribution(distribution)
    except importlib_metadata.PackageNotFoundError as exc:
        raise _canon_error(
            "canon_runtime_dependency_unavailable",
            f"install {distribution}=={expected_version}",
            distribution,
        ) from exc
    observed_version = installed.version
    if observed_version != expected_version:
        raise _canon_error(
            "canon_runtime_dependency_version_mismatch",
            f"install {distribution}=={expected_version}",
            f"{distribution}=={observed_version}",
        )
    normalized_distribution = _normalized_distribution_name(distribution)
    metadata_name = installed.metadata["Name"]
    if not isinstance(metadata_name, str) or (
        _normalized_distribution_name(metadata_name) != normalized_distribution
    ):
        raise _canon_error(
            "canon_runtime_dependency_name_mismatch",
            f"install the locked {distribution}=={expected_version} distribution",
            str(metadata_name),
        )
    release = _dependency_release(
        distribution,
        expected_version,
        import_root,
        release_manifest=release_manifest,
    )
    record_entries = [
        path
        for path in (installed.files or ())
        if path.name == "RECORD" and ".dist-info" in path.as_posix()
    ]
    if len(record_entries) != 1:
        raise _canon_error(
            "canon_runtime_dependency_record_unavailable",
            f"reinstall the exact wheel for {distribution}=={expected_version}",
            distribution,
        )
    record_path = Path(installed.locate_file(record_entries[0]))
    try:
        record_bytes = record_path.read_bytes()
        record_text = record_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _canon_error(
            "canon_runtime_dependency_record_unreadable",
            f"reinstall the exact wheel for {distribution}=={expected_version}",
            distribution,
        ) from exc
    verified_files: list[dict[str, object]] = []
    verified_paths: dict[Path, str] = {}
    record_ref = record_entries[0].as_posix()
    try:
        rows = tuple(csv.reader(record_text.splitlines()))
    except csv.Error as exc:
        raise _canon_error(
            "canon_runtime_dependency_record_invalid",
            f"reinstall the exact wheel for {distribution}=={expected_version}",
            distribution,
        ) from exc
    for row in rows:
        if len(row) != 3:
            raise _canon_error(
                "canon_runtime_dependency_record_invalid",
                f"reinstall the exact wheel for {distribution}=={expected_version}",
                distribution,
            )
        relative_path, encoded_hash, encoded_size = row
        if not encoded_hash:
            if relative_path != record_ref or encoded_size:
                raise _canon_error(
                    "canon_runtime_dependency_record_unbound_file",
                    f"reinstall the exact wheel for {distribution}=={expected_version}",
                    relative_path,
                )
            verified_paths[record_path.resolve()] = relative_path
            verified_files.append(
                {
                    "bytes": len(record_bytes),
                    "path": relative_path,
                    "sha256": _sha256(record_bytes),
                }
            )
            continue
        try:
            algorithm, encoded_digest = encoded_hash.split("=", 1)
            expected_digest = base64.urlsafe_b64decode(
                encoded_digest + "=" * (-len(encoded_digest) % 4)
            ).hex()
            expected_size = int(encoded_size)
        except (ValueError, TypeError) as exc:
            raise _canon_error(
                "canon_runtime_dependency_record_invalid",
                f"reinstall the exact wheel for {distribution}=={expected_version}",
                relative_path,
            ) from exc
        if algorithm != "sha256" or len(expected_digest) != 64 or expected_size < 0:
            raise _canon_error(
                "canon_runtime_dependency_record_digest_invalid",
                f"reinstall the exact wheel for {distribution}=={expected_version}",
                relative_path,
            )
        try:
            installed_bytes = Path(installed.locate_file(relative_path)).read_bytes()
        except OSError as exc:
            raise _canon_error(
                "canon_runtime_dependency_artifact_unreadable",
                f"reinstall the exact wheel for {distribution}=={expected_version}",
                relative_path,
            ) from exc
        if len(installed_bytes) != expected_size or _sha256(installed_bytes) != expected_digest:
            raise _canon_error(
                "canon_runtime_dependency_artifact_mismatch",
                f"reinstall the exact wheel for {distribution}=={expected_version}",
                relative_path,
            )
        verified_paths[Path(installed.locate_file(relative_path)).resolve()] = relative_path
        verified_files.append(
            {
                "bytes": expected_size,
                "path": relative_path,
                "sha256": expected_digest,
            }
        )
    direct_url = installed.read_text("direct_url.json")
    if direct_url is not None:
        try:
            direct_url_payload = json.loads(direct_url)
        except json.JSONDecodeError as exc:
            raise _canon_error(
                "canon_runtime_dependency_direct_url_invalid",
                f"reinstall the exact wheel for {distribution}=={expected_version}",
                distribution,
            ) from exc
        if (direct_url_payload.get("dir_info") or {}).get("editable") is True:
            raise _canon_error(
                "canon_runtime_dependency_editable",
                f"install a non-editable wheel for {distribution}=={expected_version}",
                distribution,
            )
    imported = importlib.import_module(import_root)
    module_file = getattr(imported, "__file__", None)
    if not isinstance(module_file, str) or not module_file:
        raise _canon_error(
            "canon_runtime_dependency_import_origin_unavailable",
            f"install the exact wheel for {distribution}=={expected_version}",
            import_root,
        )
    import_origin = Path(module_file).resolve()
    if import_origin not in verified_paths:
        raise _canon_error(
            "canon_runtime_dependency_import_origin_mismatch",
            f"remove shadow modules and reinstall {distribution}=={expected_version}",
            f"{import_root}:{import_origin}",
        )
    verified_files.sort(key=lambda item: str(item["path"]))
    return {
        "admission_state": "hold",
        "distribution": normalized_distribution,
        "import_origin_record_path": verified_paths[import_origin],
        "import_origin_record_member": True,
        "import_root": import_root,
        "installed_manifest_hash": _domain_hash(
            "hapax.python-distribution.installed-manifest.v1", verified_files
        ),
        "may_authorize": False,
        "reason_codes": ["independent_install_receipt_missing"],
        "record_sha256": _sha256(record_bytes),
        "record_self_consistent": True,
        "release_manifest_ref": (
            f"python-runtime-dependency-release-set@sha256:{release_manifest.manifest_hash}"
        ),
        "release_set_hash": release.release_set_hash,
        "schema": "hapax.python-distribution.runtime-record-observation.v1",
        "source_registry": release.source_registry,
        "version": observed_version,
    }


def _context_canon_source_payloads(
    release_manifest: _RuntimeDependencyReleaseManifest | None = None,
) -> Mapping[str, str]:
    release_manifest = release_manifest or _load_runtime_dependency_release_manifest()
    package_file = getattr(_context_canon_package_module, "__file__", None)
    if not isinstance(package_file, str) or not package_file:
        raise _canon_error(
            "canon_generator_unreadable",
            "install the exact hapax-context-canon source-bearing wheel",
        )
    package_root = Path(package_file).resolve().parent
    actual_modules = {
        f"{_CONTEXT_CANON_SOURCE_PREFIX}{path.relative_to(package_root).as_posix()}"
        for path in package_root.rglob("*.py")
        if path.is_file()
    }
    expected_modules = set(_CONTEXT_CANON_SOURCE_MODULES)
    if actual_modules != expected_modules:
        detail = ",".join(sorted(actual_modules ^ expected_modules))
        raise _canon_error(
            "canon_package_module_closure_mismatch",
            "manifest every behavior-bearing hapax-context-canon Python module",
            detail,
        )
    data_root = package_root / "_data"
    actual_resources = {
        f"{_CONTEXT_CANON_SOURCE_PREFIX}{path.relative_to(package_root).as_posix()}"
        for path in data_root.rglob("*")
        if path.is_file()
    }
    expected_resources = set(_CONTEXT_CANON_SOURCE_RESOURCES)
    if actual_resources != expected_resources:
        detail = ",".join(sorted(actual_resources ^ expected_resources))
        raise _canon_error(
            "canon_package_resource_closure_mismatch",
            "manifest every behavior-bearing hapax-context-canon data resource",
            detail,
        )
    payloads: dict[str, str] = {}
    for source_ref, module in _CONTEXT_CANON_SOURCE_MODULES.items():
        module_path = getattr(module, "__file__", None)
        if not isinstance(module_path, str) or not module_path:
            raise _canon_error(
                "canon_generator_unreadable",
                "install the exact hapax-context-canon source-bearing wheel",
                source_ref,
            )
        payloads[source_ref] = _read_text(Path(module_path), reason="canon_generator_unreadable")
    for source_ref, relative_path in _CONTEXT_CANON_SOURCE_RESOURCES.items():
        payloads[source_ref] = _read_text(
            package_root / relative_path, reason="canon_generator_unreadable"
        )
    _verify_runtime_import_closure(
        payloads,
        expected_roots=frozenset({"pydantic", "toon"}),
        internal_roots=frozenset({"hapax"}),
        reason_code="canon_package_runtime_import_closure_mismatch",
    )
    for source_ref, identity in _CONTEXT_CANON_RUNTIME_IDENTITIES.items():
        payloads[source_ref] = _distribution_semantic_release_payload(
            *identity, release_manifest=release_manifest
        )
    expected_payloads = tuple(
        sorted(
            (
                *_CONTEXT_CANON_SOURCE_MODULES,
                *_CONTEXT_CANON_SOURCE_RESOURCES,
                *_CONTEXT_CANON_RUNTIME_IDENTITIES,
            )
        )
    )
    if tuple(sorted(payloads)) != expected_payloads:
        raise _canon_error(
            "canon_package_source_manifest_mismatch",
            "reconcile the package source and runtime identity manifest",
        )
    return MappingProxyType(dict(sorted(payloads.items())))


def _council_source_payloads(
    generator_text: str,
    release_manifest: _RuntimeDependencyReleaseManifest | None = None,
) -> Mapping[str, str]:
    from shared.coord_projection import NO_GO_BOOLEANS

    release_manifest = release_manifest or _load_runtime_dependency_release_manifest()
    payloads: dict[str, str] = {}
    expected_modules = {
        *(module.__name__ for module in _COUNCIL_SOURCE_MODULES.values()),
        "shared.coord_projection",
    }
    generator_modules, _ = _module_imports(generator_text)
    observed_modules = {
        name for name in generator_modules if name == "shared" or name.startswith("shared.")
    }
    if observed_modules != expected_modules:
        detail = ",".join(sorted(observed_modules ^ expected_modules))
        raise _canon_error(
            "canon_council_module_closure_mismatch",
            "manifest every imported Council helper module",
            detail,
        )
    for source_ref, module in _COUNCIL_SOURCE_MODULES.items():
        module_path = getattr(module, "__file__", None)
        if not isinstance(module_path, str) or not module_path:
            raise _canon_error(
                "canon_generator_unreadable",
                "restore the exact Council helper source",
                source_ref,
            )
        payloads[source_ref] = _read_text(Path(module_path), reason="canon_generator_unreadable")
    payloads[_COUNCIL_SOURCE_VALUE_REFS[0]] = (
        canonical_json_bytes(sorted(NO_GO_BOOLEANS)).decode("utf-8") + "\n"
    )
    _verify_runtime_import_closure(
        {"shared/session_context_canon.py": generator_text, **payloads},
        expected_roots=frozenset({"pydantic", "yaml"}),
        internal_roots=frozenset({"hapax", "shared"}),
        reason_code="canon_council_runtime_import_closure_mismatch",
    )
    for source_ref, identity in _COUNCIL_RUNTIME_IDENTITIES.items():
        payloads[source_ref] = _distribution_semantic_release_payload(
            *identity, release_manifest=release_manifest
        )
    if tuple(sorted(payloads)) != tuple(
        sorted(
            (
                *_COUNCIL_SOURCE_MODULES,
                *_COUNCIL_SOURCE_VALUE_REFS,
                *_COUNCIL_RUNTIME_IDENTITIES,
            )
        )
    ):
        raise _canon_error(
            "canon_council_source_manifest_mismatch",
            "reconcile the Council helper and runtime identity manifest",
        )
    return MappingProxyType(dict(sorted(payloads.items())))


def _read_repository_or_package(path: Path, packaged_name: str, *, reason: str) -> str:
    if path.is_file():
        return _read_text(path, reason=reason)
    packaged = resources.files("shared").joinpath("_data", packaged_name)
    try:
        return packaged.read_text(encoding="utf-8")
    except OSError as exc:
        raise _canon_error(reason, f"restore packaged shared/_data/{packaged_name}") from exc


def _runtime_dependency_release_set_text() -> str:
    return _read_repository_or_package(
        RUNTIME_DEPENDENCY_RELEASE_SET_PATH,
        "runtime-dependency-release-set.json",
        reason="canon_runtime_dependency_release_set_unreadable",
    )


def _load_runtime_dependency_release_manifest(
    raw: str | None = None,
) -> _RuntimeDependencyReleaseManifest:
    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            raw if raw is not None else _runtime_dependency_release_set_text(),
            object_pairs_hook=unique_pairs,
        )
        manifest = _RuntimeDependencyReleaseManifest.model_validate(payload)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        raise _canon_error(
            "canon_runtime_dependency_release_set_invalid",
            "regenerate the dependency release set from the accepted uv.lock",
            str(exc),
        ) from exc
    expected = {
        _normalized_distribution_name(identity[0])
        for identity in (
            *_CONTEXT_CANON_RUNTIME_IDENTITIES.values(),
            *_COUNCIL_RUNTIME_IDENTITIES.values(),
        )
    }
    observed = {item.distribution for item in manifest.dependencies}
    if observed != expected:
        raise _canon_error(
            "canon_runtime_dependency_release_set_closure_mismatch",
            "bind exactly the runtime dependencies imported by the canon compiler",
            ",".join(sorted(observed ^ expected)),
        )
    return manifest


def _source_text(path: Path | None) -> str:
    if path is not None:
        return _read_text(path, reason="canon_source_unreadable")
    return _read_repository_or_package(
        CANON_SOURCE_PATH,
        "coordination-canon-source.yaml",
        reason="canon_source_unreadable",
    )


def parse_canon_source(raw: str) -> CanonSource:
    """Parse one already-read WHAT/HOW/MUST source snapshot."""

    try:
        payload = yaml.load(raw, Loader=_UniqueKeyLoader)
    except CanonError:
        raise
    except yaml.YAMLError as exc:
        raise _canon_error("canon_source_yaml_invalid", "repair the canon source YAML") from exc
    if not isinstance(payload, Mapping):
        raise _canon_error("canon_source_root_invalid", "make the canon source root a mapping")
    try:
        return CanonSource.model_validate(payload)
    except ValidationError as exc:
        raise _canon_error(
            "canon_source_schema_invalid", "repair the typed canon source", str(exc)
        ) from exc


def load_canon_source(path: Path | None = None) -> CanonSource:
    """Read and strictly validate the stable WHAT/HOW/MUST atom registry."""

    return parse_canon_source(_source_text(path))


def _strip_tla_comments(tla: str) -> str:
    code = re.sub(r"\(\*.*?\*\)", "", tla, flags=re.DOTALL)
    return "\n".join(line.split(r"\*", 1)[0] for line in code.splitlines())


def verify_tla_topology(tla: str, catalog: StageMetadataCatalog) -> None:
    """Fail closed unless TLA Stages/Terminal/Blocked/Next/Fall match the SSOT."""

    try:
        code = _strip_tla_comments(tla)

        def quoted_set(name: str, following: str) -> frozenset[str]:
            match = re.search(rf"(?ms)^\s*{name}\s*==(?P<body>.*?)(?=^\s*{following}\s*==)", code)
            if match is None:
                raise ValueError(f"missing {name}")
            compact = re.sub(r"\s+", "", match.group("body"))
            if re.fullmatch(r'\{(?:"[A-Z0-9_]+"(?:,"[A-Z0-9_]+")*)?\}', compact) is None:
                raise ValueError(f"malformed {name}")
            return frozenset(re.findall(r'"([A-Z0-9_]+)"', compact))

        expected_tokens = frozenset(catalog.tokens)
        expected_terminal = frozenset(stage.token for stage in catalog.stages if stage.terminal)
        expected_blocked = frozenset(stage.token for stage in catalog.stages if stage.blocked)
        if quoted_set("Stages", "Terminal") != expected_tokens:
            raise ValueError("Stages mismatch")
        if quoted_set("Terminal", "Blocked") != expected_terminal:
            raise ValueError("Terminal mismatch")
        if quoted_set("Blocked", r"Next\(s\)") != expected_blocked:
            raise ValueError("Blocked mismatch")

        next_block = re.search(r"Next\(s\)\s*==(?P<body>.*?)\n\s*\nVARIABLE", code, flags=re.DOTALL)
        if next_block is None:
            raise ValueError("missing Next")
        arm_lines = [line.strip() for line in next_block.group("body").splitlines() if line.strip()]
        if not arm_lines or arm_lines[-1] != "[] OTHER         -> {}":
            raise ValueError("malformed Next default")
        parsed_next: dict[str, frozenset[str]] = {}
        for index, line in enumerate(arm_lines[:-1]):
            arm = re.fullmatch(r'(CASE|\[\])\s+s\s*=\s*"([A-Z0-9_]+)"\s*->\s*\{([^}]*)\}', line)
            if arm is None or arm.group(1) != ("CASE" if index == 0 else "[]"):
                raise ValueError(f"malformed Next arm {line}")
            token = arm.group(2)
            if token in parsed_next:
                raise ValueError(f"duplicate Next arm {token}")
            compact = re.sub(r"\s+", "", arm.group(3))
            if re.fullmatch(r'(?:"[A-Z0-9_]+"(?:,"[A-Z0-9_]+")*)?', compact) is None:
                raise ValueError(f"malformed Next destinations {token}")
            parsed_next[token] = frozenset(re.findall(r'"([A-Z0-9_]+)"', compact))
        expected_next = {
            stage.token: frozenset(edge.to for edge in stage.next_edges) for stage in catalog.stages
        }
        if parsed_next != expected_next:
            raise ValueError("Next mismatch")

        fall_block = re.search(r"Fall\(t\)\s*==(?P<body>.*?)\n\s*\nNxt\s*==", code, flags=re.DOTALL)
        if fall_block is None:
            raise ValueError("missing Fall")
        normalized_fall = " ".join(
            line.strip() for line in fall_block.group("body").splitlines() if line.strip()
        )
        expected_fall = (
            "/\\ stage[t] \\notin (Terminal \\cup Blocked) "
            '/\\ stage\' = [stage EXCEPT ![t] = "BLOCKED"]'
        )
        if normalized_fall != expected_fall:
            raise ValueError("Fall mismatch")
        for stage in catalog.stages:
            destinations = tuple(edge.to for edge in stage.fall_edges)
            expected = () if stage.terminal or stage.blocked else ("BLOCKED",)
            if destinations != expected:
                raise ValueError(f"Fall metadata mismatch {stage.token}")
    except ValueError as exc:
        raise _canon_error(
            "canon_tla_topology_mismatch",
            "reconcile the TLA topology and stage metadata before generation",
            str(exc),
        ) from exc


def _stage_slug(token: str) -> str:
    return token.lower()


def _edge_content(edge: StageEdgeMetadata) -> str:
    ref = f", ref={edge.enforcement_ref}" if edge.enforcement_ref else ""
    return (
        f"{edge.to}[role={edge.projection_role}, authority={edge.authority_capability}, "
        f"guards={','.join(edge.guards)}, actions={','.join(edge.actions)}, "
        f"enforcement={edge.enforcement}{ref}]"
    )


def _stage_atoms(stage: StageMetadata, ordinal: int) -> tuple[CanonAtom, CanonAtom]:
    required = ",".join(stage.deliverable.required_fields)
    gate = CanonAtom(
        id=f"what.stage.{_stage_slug(stage.token)}.gate",
        ordinal=ordinal,
        stratum="what",
        content=(
            f"At {stage.token} ({stage.label}), produce {stage.deliverable.id} with fields "
            f"{required}; report via the existing relay/receipt path."
        ),
        grounding=False,
        applies_to=(stage.token,),
        source_refs=("docs/formal/sdlc-stage-metadata.yaml",),
    )
    next_text = "; ".join(_edge_content(edge) for edge in stage.next_edges) or "none"
    fall_text = "; ".join(_edge_content(edge) for edge in stage.fall_edges) or "none"
    admissions = (
        "; ".join(
            (
                f"{item.operation}[authority={item.authority_capability}, "
                f"guards={','.join(item.guards)}, actions={','.join(item.actions)}, "
                f"enforcement={item.enforcement}, ref={item.enforcement_ref or 'none'}]"
            )
            for item in stage.operation_admissions
        )
        or "none"
    )
    topology = CanonAtom(
        id=f"what.stage.{_stage_slug(stage.token)}.topology",
        ordinal=ordinal + 1,
        stratum="what",
        content=(
            f"{stage.token} next: {next_text}; fall: {fall_text}; "
            f"operation admissions: {admissions}."
        ),
        grounding=False,
        applies_to=(stage.token,),
        source_refs=("docs/formal/sdlc-stage-metadata.yaml", "docs/formal/sdlc-ladder.tla"),
    )
    return gate, topology


def _atom(source: CanonSource, atom_id: str) -> CanonAtom:
    return next(atom for atom in source.atoms if atom.id == atom_id)


def _validate_grounding_contract(source: CanonSource, catalog: StageMetadataCatalog) -> None:
    _validate_required_atom_manifest(source.atoms, source.canon_version, catalog)
    tokens = set(catalog.tokens)
    for atom in source.atoms:
        unknown = set(atom.applies_to) - tokens - {"*"}
        if unknown:
            raise _canon_error(
                "canon_source_unknown_stage",
                "use only stages declared by the stage metadata SSOT",
                f"{atom.id}:{','.join(sorted(unknown))}",
            )
    expected_edges = {
        ("S3", "S3_5"): "branch",
        ("S3_5", "S4"): "advance",
        ("S3_5", "S0"): "repair",
        ("S6", "BLOCKED"): "repair",
        ("S7", "BLOCKED"): "repair",
        ("BLOCKED", "S6"): "repair",
        ("BLOCKED", "S0"): "repair",
    }
    actual_edges = {
        (stage.token, edge.to): edge.projection_role
        for stage in catalog.stages
        for edge in stage.next_edges
    }
    for edge, role in expected_edges.items():
        if actual_edges.get(edge) != role:
            raise _canon_error(
                "canon_repair_edge_contract_mismatch",
                "restore the named disconfirmation and BLOCKED repair edge roles",
                f"{edge[0]}->{edge[1]}",
            )


def _source_hash(source_ref: str, text: str) -> SourceHash:
    return SourceHash(source_ref=source_ref, sha256=_sha256(text.encode("utf-8")))


def build_lifecycle_definition(
    catalog: StageMetadataCatalog,
    *,
    source_hash: str,
    generation: int = 2,
    lifecycle_ref: str = "lifecycle:sdlc0",
    profile_ref: str = "hapax.lifecycle-profile.sdlc0.v1",
    spine_ref: str = "hapax.ndlc.spine.v1",
    plant_type_ref: str = "estate:self",
    unit_type_ref: str = "cc-task",
    initial_stage: str = "S0",
    freeze_pivot: str = "S5",
    source_ref: str = "docs/formal/sdlc-stage-metadata.yaml",
    migration_refs: Sequence[str] = (),
) -> LifecycleDefinition:
    """Normalize one exact lifecycle snapshot into the generic definition contract."""

    stages = tuple(
        LifecycleStageDefinition(
            token=stage.token,
            display_alias=stage.display_alias,
            aliases=tuple(sorted(stage.aliases)),
            deprecated_aliases=tuple(sorted(stage.deprecated_aliases)),
            label=stage.label,
            terminal=stage.terminal,
            blocked=stage.blocked,
            deliverable_id=stage.deliverable.id,
            required_fields=tuple(sorted(stage.deliverable.required_fields)),
            operation_admissions=tuple(
                LifecycleOperationAdmission(
                    operation=item.operation,
                    authority_capability=item.authority_capability,
                    guards=tuple(sorted(item.guards)),
                    actions=tuple(sorted(item.actions)),
                    enforcement=item.enforcement,
                    enforcement_ref=item.enforcement_ref,
                )
                for item in stage.operation_admissions
            ),
            next=tuple(
                LifecycleTransition(
                    to=edge.to,
                    projection_role=edge.projection_role,
                    authority_capability=edge.authority_capability,
                    guards=tuple(sorted(edge.guards)),
                    actions=tuple(sorted(edge.actions)),
                    enforcement=edge.enforcement,
                    enforcement_ref=edge.enforcement_ref,
                )
                for edge in stage.next_edges
            ),
            fall=tuple(
                LifecycleTransition(
                    to=edge.to,
                    projection_role=edge.projection_role,
                    authority_capability=edge.authority_capability,
                    guards=tuple(sorted(edge.guards)),
                    actions=tuple(sorted(edge.actions)),
                    enforcement=edge.enforcement,
                    enforcement_ref=edge.enforcement_ref,
                )
                for edge in stage.fall_edges
            ),
        )
        for stage in catalog.stages
    )
    terminal_stages = tuple(stage.token for stage in stages if stage.terminal)
    blocked_stages = tuple(stage.token for stage in stages if stage.blocked)
    question_refs = tuple(
        sorted(
            f"question:{stage.token}:{field}" for stage in stages for field in stage.required_fields
        )
    )
    obligation_refs = tuple(
        sorted(
            f"obligation:{stage.token}:{field}"
            for stage in stages
            for field in stage.required_fields
        )
    )
    instrument_refs = tuple(
        sorted(
            {
                "docs/formal/sdlc-ladder.tla",
                *(
                    item.enforcement_ref
                    for stage in stages
                    for item in (
                        *stage.operation_admissions,
                        *stage.next,
                        *stage.fall,
                    )
                    if item.enforcement_ref is not None
                ),
            }
        )
    )
    sufficiency_predicates = tuple(
        sorted(
            {
                guard
                for stage in stages
                for item in (*stage.operation_admissions, *stage.next, *stage.fall)
                for guard in item.guards
            }
        )
    )
    terminal_set = set(terminal_stages)
    terminal_conditions = tuple(
        sorted(
            {
                guard
                for stage in stages
                for edge in (*stage.next, *stage.fall)
                if edge.to in terminal_set
                for guard in edge.guards
            }
        )
    )
    recovery_refs = tuple(
        sorted(
            {
                f"transition:{stage.token}->{edge.to}:{action}"
                for stage in stages
                for edge in (*stage.next, *stage.fall)
                if edge.projection_role == "repair"
                for action in edge.actions
            }
        )
    )
    provenance_paths = tuple(
        sorted(
            {
                "/blocked_stages",
                "/freeze_pivot",
                "/generation",
                "/initial_stage",
                "/instrument_refs",
                "/lifecycle_ref",
                "/may_authorize",
                "/migration_refs",
                "/obligation_refs",
                "/plant_type_ref",
                "/profile_ref",
                "/question_refs",
                "/recovery_refs",
                "/source_hash",
                "/source_ref",
                "/spine_ref",
                "/sufficiency_predicates",
                "/terminal_conditions",
                "/terminal_stages",
                "/unit_type_ref",
                *(f"/stages/{stage.token}" for stage in stages),
            }
        )
    )
    field_provenance = tuple(
        LifecycleFieldProvenance(
            field_path=field_path,
            kind="derived",
            source_refs=(source_ref,),
            reason_codes=(),
            may_authorize=False,
        )
        for field_path in provenance_paths
    )
    body = {
        "schema": "hapax.lifecycle-definition.v1",
        "lifecycle_ref": lifecycle_ref,
        "generation": generation,
        "profile_ref": profile_ref,
        "spine_ref": spine_ref,
        "plant_type_ref": plant_type_ref,
        "unit_type_ref": unit_type_ref,
        "initial_stage": initial_stage,
        "terminal_stages": terminal_stages,
        "blocked_stages": blocked_stages,
        "freeze_pivot": freeze_pivot,
        "question_refs": question_refs,
        "obligation_refs": obligation_refs,
        "instrument_refs": instrument_refs,
        "sufficiency_predicates": sufficiency_predicates,
        "terminal_conditions": terminal_conditions,
        "migration_refs": tuple(sorted(set(migration_refs))),
        "recovery_refs": recovery_refs,
        "source_ref": source_ref,
        "source_hash": source_hash,
        "field_provenance": field_provenance,
        "stages": stages,
        "may_authorize": False,
    }
    definition_hash = _domain_hash("hapax.lifecycle-definition.v1", body)
    return LifecycleDefinition(
        **body,
        definition_ref=f"lifecycle-definition@sha256:{definition_hash}",
        definition_hash=definition_hash,
    )


def _projection_scope_definition(
    stage_token: str, level: ProjectionLevel, definition: LifecycleDefinition
) -> tuple[str, ...]:
    tokens = tuple(stage.token for stage in definition.stages)
    _lifecycle_stage(definition, stage_token)
    if level is ProjectionLevel.FULL:
        return tokens
    if level is ProjectionLevel.STATE_CONE:
        by_token = {stage.token: stage for stage in definition.stages}
        visited: set[str] = set()
        pending = [stage_token]
        while pending:
            token = pending.pop()
            if token in visited:
                continue
            visited.add(token)
            pending.extend(
                edge.to
                for edge in (*by_token[token].next, *by_token[token].fall)
                if edge.projection_role in {"advance", "branch"}
            )
        visited.update(definition.blocked_stages)
        return tuple(token for token in tokens if token in visited)
    if level is ProjectionLevel.EDGE:
        selected = {stage_token, *definition.blocked_stages}
        return tuple(token for token in tokens if token in selected)
    return (stage_token,)


def _canon_identity_body(canon_version: int, atoms: Sequence[CanonAtom]) -> dict[str, Any]:
    return {
        "schema": "hapax.coordination-canon.corpus.v1",
        "canon_version": canon_version,
        "domain": "sdlc",
        "generator_version": GENERATOR_VERSION,
        "projection_algorithm": PROJECTION_ALGORITHM,
        "encoder_id": ENCODER_ID,
        "reference_tokenizer_id": REFERENCE_TOKENIZER_ID,
        "wire_contract": {
            "kind": "context_bundle",
            "sha256": LOCKED_CONTEXT_BUNDLE_CONTRACT_SHA256,
            "fsm_fields": ["what", "how", "must"],
        },
        "compression_surface": {
            "surface": COMPRESSION_SURFACE,
            "tier": "lossless_only",
            "codec": "toon",
            "headroom_enabled": False,
        },
        "atoms": [atom.model_dump(mode="json") for atom in atoms],
    }


def build_corpus(
    source: CanonSource,
    *,
    catalog: StageMetadataCatalog = SDLC_STAGE_METADATA,
    lifecycle_definition: LifecycleDefinition | None = None,
    source_hashes: tuple[SourceHash, ...] = (),
    compression_registry: Mapping[str, SurfaceSpec] | None = None,
) -> CanonCorpus:
    """Build the exhaustive disjoint K = WHAT + HOW + MUST atom corpus."""

    _validate_source_semantics(source)
    _validate_grounding_contract(source, catalog)
    if lifecycle_definition is None:
        metadata_text = _read_repository_or_package(
            SDLC_STAGE_METADATA_PATH,
            "sdlc-stage-metadata.yaml",
            reason="canon_stage_metadata_unreadable",
        )
        lifecycle_definition = build_lifecycle_definition(
            catalog, source_hash=_sha256(metadata_text.encode("utf-8"))
        )
    if tuple(stage.token for stage in lifecycle_definition.stages) != catalog.tokens:
        raise _canon_error(
            "canon_lifecycle_catalog_mismatch",
            "build the lifecycle definition and canon corpus from one metadata snapshot",
        )
    generated: list[CanonAtom] = []
    for index, stage in enumerate(catalog.stages):
        generated.extend(_stage_atoms(stage, 1000 + index * 10))
    atoms = tuple(sorted((*source.atoms, *generated), key=lambda atom: (atom.ordinal, atom.id)))
    ids = [atom.id for atom in atoms]
    ordinals = [atom.ordinal for atom in atoms]
    if len(ids) != len(set(ids)) or len(ordinals) != len(set(ordinals)):
        raise _canon_error(
            "canon_corpus_identity_collision",
            "assign unique atom ids and ordinals across source and generated atoms",
        )
    canon_hash = _sha256(canonical_json_bytes(_canon_identity_body(source.canon_version, atoms)))
    registry = (
        compression_registry
        if compression_registry is not None
        else parse_registry(_compression_registry_text(None))
    )
    return CanonCorpus(
        source=source,
        catalog=catalog,
        lifecycle_definition=lifecycle_definition,
        atoms=atoms,
        canon_hash=canon_hash,
        source_hashes=source_hashes,
        compression_registry=MappingProxyType(dict(registry)),
    )


def forward_cone(stage_token: str, corpus: CanonCorpus) -> tuple[str, ...]:
    """Return the acyclic advance/branch cone plus BLOCKED, never traversing repair edges."""

    return _projection_scope_definition(
        stage_token, ProjectionLevel.STATE_CONE, corpus.lifecycle_definition
    )


def _atom_applies(atom: CanonAtom, stages: set[str]) -> bool:
    return atom.applies_to == ("*",) or bool(set(atom.applies_to) & stages)


def _selected_atoms(
    corpus: CanonCorpus, stage_token: str, level: ProjectionLevel
) -> tuple[tuple[CanonAtom, ...], tuple[str, ...]]:
    scope = _projection_scope_definition(stage_token, level, corpus.lifecycle_definition)
    return _select_atoms_from_full(corpus.atoms, stage_token, level, scope=scope), scope


def _select_atoms_from_full(
    full_atoms: Sequence[CanonAtom],
    stage_token: str,
    level: ProjectionLevel,
    *,
    scope: tuple[str, ...],
) -> tuple[CanonAtom, ...]:
    mandatory = {atom.id for atom in full_atoms if atom.stratum == "must" or atom.grounding}
    if level is ProjectionLevel.FULL:
        selected = {atom.id for atom in full_atoms}
    elif level in {ProjectionLevel.STATE_CONE, ProjectionLevel.EDGE}:
        stages = set(scope)
        selected = mandatory | {atom.id for atom in full_atoms if _atom_applies(atom, stages)}
    else:
        selected = mandatory | {f"what.stage.{_stage_slug(stage_token)}.gate"}
    return tuple(atom for atom in full_atoms if atom.id in selected)


def _kernel(
    corpus: CanonCorpus, included: tuple[CanonAtom, ...], level: ProjectionLevel
) -> CanonKernel:
    return _kernel_from_full(corpus.atoms, included, level)


def _kernel_from_full(
    full_atoms: Sequence[CanonAtom], included: Sequence[CanonAtom], level: ProjectionLevel
) -> CanonKernel:
    included_ids = {atom.id for atom in included}
    omitted = tuple(sorted(atom.id for atom in full_atoms if atom.id not in included_ids))
    if any(atom.stratum == "must" or atom.grounding for atom in full_atoms if atom.id in omitted):
        raise _canon_error(
            "canon_projection_cuts_must_or_grounding",
            "raise the projection to preserve every MUST and grounding atom",
            level.value,
        )
    metadata = {
        ProjectionLevel.FULL: ("pi0-none", "none"),
        ProjectionLevel.STATE_CONE: ("pi1-outside-forward-cone", "outside_forward_cone"),
        ProjectionLevel.EDGE: ("pi2-multi-step-lookahead", "multi_step_lookahead"),
        ProjectionLevel.GATE_MINIMAL: (
            "pi3-fsm-structure-and-procedures",
            "fsm_structure_and_procedures",
        ),
    }
    name, distortion = metadata[level]
    return CanonKernel(
        name=name,
        omitted_atom_ids=omitted,
        omitted_digest=_sha256(canonical_json_bytes(list(omitted))),
        distortion_class=distortion,
    )


def _strata(atoms: tuple[CanonAtom, ...]) -> FsmStrata:
    return FsmStrata(
        what=tuple(atom for atom in atoms if atom.stratum == "what"),
        how=tuple(atom for atom in atoms if atom.stratum == "how"),
        must=tuple(atom for atom in atoms if atom.stratum == "must"),
    )


def _render_stratum(atoms: tuple[CanonAtom, ...]) -> str:
    return _render_canon_stratum(atoms)


def _render_payload(rendered: RenderedFsm) -> str:
    return f"FSM WHAT\n{rendered.what}\nFSM HOW\n{rendered.how}\nFSM MUST\n{rendered.must}"


def _verify_encoder_runtime() -> None:
    try:
        observed = importlib_metadata.version("python-toon")
    except importlib_metadata.PackageNotFoundError as exc:
        raise _canon_error(
            "canon_encoder_unavailable",
            f"install python-toon=={PYTHON_TOON_VERSION}",
        ) from exc
    if observed != PYTHON_TOON_VERSION:
        raise _canon_error(
            "canon_encoder_version_mismatch",
            f"install python-toon=={PYTHON_TOON_VERSION}",
            observed,
        )


def project_canon(
    corpus: CanonCorpus, stage_token: str, level: ProjectionLevel | str
) -> CanonImage:
    """Project one content-addressed stage/level image without activating any consumer."""

    _verify_encoder_runtime()
    try:
        parsed_level = level if isinstance(level, ProjectionLevel) else ProjectionLevel(level)
    except ValueError as exc:
        raise _canon_error(
            "canon_projection_level_unknown", "use pi0, pi1, pi2, or pi3", str(level)
        ) from exc
    if stage_token not in {stage.token for stage in corpus.lifecycle_definition.stages}:
        raise _canon_error("canon_stage_unknown", "use an exact canonical stage token", stage_token)
    surface = get_surface_spec(COMPRESSION_SURFACE, dict(corpus.compression_registry))
    if not surface.lossless_allowed or surface.lossy_allowed or surface.headroom_enabled:
        raise _canon_error(
            "canon_compression_surface_not_lossless_only",
            "declare coordination_canon as lossless_only/toon with Headroom disabled",
            surface.tier.value,
        )
    atoms, scope = _selected_atoms(corpus, stage_token, parsed_level)
    strata = _strata(atoms)
    grounding = tuple(atom for atom in atoms if atom.grounding)
    rendered = RenderedFsm(
        what=_render_stratum(strata.what),
        how=_render_stratum(strata.how),
        must=_render_stratum(strata.must),
    )
    payload = _render_payload(rendered)
    body = {
        "schema": CANON_IMAGE_SCHEMA,
        "canon_version": corpus.source.canon_version,
        "generator_version": GENERATOR_VERSION,
        "projection_algorithm": PROJECTION_ALGORITHM,
        "encoder_id": ENCODER_ID,
        "reference_tokenizer_id": REFERENCE_TOKENIZER_ID,
        "reference_token_count": reference_token_count(payload),
        "stage_token": stage_token,
        "level": parsed_level,
        "projection_scope": scope,
        "source_hashes": corpus.source_hashes,
        "lifecycle_definition_hash": corpus.lifecycle_definition.definition_hash,
        "canon_hash": corpus.canon_hash,
        "canon_id": f"coordination-canon@sha256:{corpus.canon_hash}",
        "strata": StrataEnvelope(fsm=strata),
        "grounding_core": grounding,
        "kernel": _kernel(corpus, atoms, parsed_level),
        "rendered_strata": rendered,
        "rendered_payload": payload,
    }
    image_hash = _sha256(canonical_json_bytes(body))
    return CanonImage(**body, image_hash=image_hash)


def _compression_registry_text(path: Path | None) -> str:
    if path is not None:
        return _read_text(path, reason="canon_compression_registry_unreadable")
    return _read_repository_or_package(
        COMPRESSION_REGISTRY_PATH,
        "compression-surface-registry.yaml",
        reason="canon_compression_registry_unreadable",
    )


def build_canon_bundle(
    source_path: Path | None = None,
    *,
    metadata_path: Path | None = None,
    tla_path: Path | None = None,
    compression_registry_path: Path | None = None,
) -> CanonBundle:
    """Build all 14 x 4 deterministic images from the checked sources."""

    _verify_encoder_runtime()
    source_text = _source_text(source_path)
    source = parse_canon_source(source_text)
    metadata_text = (
        _read_text(metadata_path, reason="canon_stage_metadata_unreadable")
        if metadata_path is not None
        else _read_repository_or_package(
            SDLC_STAGE_METADATA_PATH,
            "sdlc-stage-metadata.yaml",
            reason="canon_stage_metadata_unreadable",
        )
    )
    metadata_label = (
        str(metadata_path) if metadata_path is not None else "docs/formal/sdlc-stage-metadata.yaml"
    )
    catalog = parse_sdlc_stage_metadata(metadata_text, source_label=metadata_label)
    tla_text = (
        _read_text(tla_path, reason="canon_tla_unreadable")
        if tla_path is not None
        else _read_repository_or_package(TLA_PATH, "sdlc-ladder.tla", reason="canon_tla_unreadable")
    )
    verify_tla_topology(tla_text, catalog)
    registry_text = _compression_registry_text(compression_registry_path)
    registry = parse_registry(registry_text)
    release_set_text = _runtime_dependency_release_set_text()
    release_manifest = _load_runtime_dependency_release_manifest(release_set_text)
    generator_text = _read_text(Path(__file__), reason="canon_generator_unreadable")
    package_payloads = _context_canon_source_payloads(release_manifest)
    council_payloads = _council_source_payloads(generator_text, release_manifest)
    source_hashes = tuple(
        sorted(
            (
                _source_hash("config/coordination-canon/source.yaml", source_text),
                _source_hash(
                    "config/coordination-canon/runtime-dependency-release-set.json",
                    release_set_text,
                ),
                _source_hash("config/compression-surface-registry.yaml", registry_text),
                _source_hash("docs/formal/sdlc-ladder.tla", tla_text),
                _source_hash("docs/formal/sdlc-stage-metadata.yaml", metadata_text),
                *(
                    _source_hash(source_ref, payload)
                    for source_ref, payload in {
                        **package_payloads,
                        **council_payloads,
                    }.items()
                ),
                _source_hash("shared/session_context_canon.py", generator_text),
            ),
            key=lambda item: item.source_ref,
        )
    )
    lifecycle_definition = build_lifecycle_definition(
        catalog,
        source_hash=_sha256(metadata_text.encode("utf-8")),
    )
    corpus = build_corpus(
        source,
        catalog=catalog,
        lifecycle_definition=lifecycle_definition,
        source_hashes=source_hashes,
        compression_registry=registry,
    )
    images = tuple(
        project_canon(corpus, token, ProjectionLevel(level))
        for token in catalog.tokens
        for level in _LEVEL_ORDER
    )
    body = {
        "schema": CANON_BUNDLE_SCHEMA,
        "canon_version": source.canon_version,
        "generator_version": GENERATOR_VERSION,
        "projection_algorithm": PROJECTION_ALGORITHM,
        "source_hashes": source_hashes,
        "lifecycle_definition": lifecycle_definition,
        "canon_hash": corpus.canon_hash,
        "images": images,
    }
    bundle_hash = _domain_hash("hapax.coordination-canon.bundle.v1", body)
    return CanonBundle(
        **body,
        bundle_ref=f"canon-bundle@sha256:{bundle_hash}",
        bundle_hash=bundle_hash,
    )


def _lifecycle_fsm_source_refs(
    lifecycle_definition: LifecycleDefinition, image: CanonImage
) -> tuple[str, ...]:
    return tuple(
        sorted(
            (
                image.canon_id,
                f"canon-image@sha256:{image.image_hash}",
                lifecycle_definition.definition_ref,
            )
        )
    )


def build_context_position(
    bundle: CanonBundle,
    image: CanonImage,
    *,
    task_ref: str,
    authority_case: str,
    authorized_flags: Sequence[AuthorizationFlag | Mapping[str, Any]],
    mutation_scope_refs: Sequence[str],
    claim_ref: str,
    route_decision_ref: str,
    demand_shape: DemandShapeBinding,
    impingements: Sequence[ContextImpingement],
    portal_offers: Sequence[PortalOffer],
    receipt_lineage: Sequence[str],
) -> ContextPosition:
    """Build the exact action position and derive every caller-forbidden digest."""

    if image not in bundle.images:
        raise ValueError("context position image must belong to its canon bundle")
    flags = tuple(
        sorted(
            (AuthorizationFlag.model_validate(item) for item in authorized_flags),
            key=lambda item: item.name,
        )
    )
    scopes = tuple(sorted(set(mutation_scope_refs)))
    normalized_impingements = tuple(sorted(impingements, key=lambda item: item.impingement_id))
    normalized_portals = tuple(sorted(portal_offers, key=lambda item: item.portal_ref))
    constraint_digest = _domain_hash(
        "hapax.effective-constraints.v1",
        {
            "authority_case": authority_case,
            "authorized_flags": flags,
            "mutation_scope_refs": scopes,
        },
    )
    body = {
        "task_ref": task_ref,
        "stage_token": image.stage_token,
        "lifecycle_definition": bundle.lifecycle_definition,
        "legal_successors": _lifecycle_legal_successors(
            bundle.lifecycle_definition, image.stage_token
        ),
        "authority_case": authority_case,
        "authorized_flags": flags,
        "mutation_scope_refs": scopes,
        "claim_ref": claim_ref,
        "route_decision_ref": route_decision_ref,
        "canon_bundle_ref": bundle.bundle_ref,
        "canon_bundle_hash": bundle.bundle_hash,
        "canon_id": image.canon_id,
        "canon_image_hash": image.image_hash,
        "lifecycle_fsm_data_sha256": build_canonical_json_object(
            _lifecycle_fsm_context_payload(bundle.lifecycle_definition, image)
        ).sha256,
        "canon_version": image.canon_version,
        "canon_level": image.level,
        "lifecycle_definition_ref": bundle.lifecycle_definition.definition_ref,
        "lifecycle_definition_hash": bundle.lifecycle_definition.definition_hash,
        "demand_shape_fingerprint": demand_shape.fingerprint,
        "effective_constraint_digest": constraint_digest,
        "impingement_digest": _domain_hash(
            "hapax.context-impingements.v1", normalized_impingements
        ),
        "portal_set_digest": _domain_hash("hapax.portal-set.v1", normalized_portals),
        "receipt_lineage": tuple(receipt_lineage),
        "may_authorize": False,
    }
    position_hash = _domain_hash("hapax.context-position.v1", body)
    return ContextPosition(
        **body,
        position_ref=f"context-position@sha256:{position_hash}",
        position_hash=position_hash,
    )


def verify_context_frame(bundle: CanonBundle, frame: ContextFrame) -> ContextFrame:
    """Revalidate a frame and its external membership in one canon bundle."""

    checked = ContextFrame.model_validate(frame.model_dump(mode="json", by_alias=True))
    if checked.position.canon_bundle_ref != bundle.bundle_ref:
        raise ValueError("context frame position refers to another canon bundle")
    if checked.position.canon_bundle_hash != bundle.bundle_hash:
        raise ValueError("context frame position has the wrong canon bundle hash")
    if checked.lifecycle_definition != bundle.lifecycle_definition:
        raise ValueError("context frame lifecycle differs from its canon bundle")
    checked_image = checked.canon_image.model_dump(mode="json", by_alias=True)
    if not any(
        image.model_dump(mode="json", by_alias=True) == checked_image for image in bundle.images
    ):
        raise ValueError("context frame image is not a member of its canon bundle")
    return checked


def build_context_frame(
    bundle: CanonBundle,
    image: CanonImage,
    position: ContextPosition,
    *,
    session_ref: str,
    task_ref: str,
    demand_shape: DemandShapeBinding,
    scopes: Sequence[ContextScope],
    temporal_coordinates: Sequence[TemporalCoordinate],
    resolution_coordinates: Sequence[ResolutionCoordinate],
    source_admissions: Sequence[SourceAdmission],
    observations: Sequence[ObservationEnvelope],
    derivations: Sequence[DerivationRecord],
    facts: Sequence[ContextFact],
    relations: Sequence[ContextRelation],
    actions: Sequence[ContextAction],
    impingements: Sequence[ContextImpingement],
    signal_estimates: Sequence[SignalEstimate],
    signal_lenses: Sequence[SignalLens],
    signal_constellations: Sequence[SignalConstellation],
    orienting_signals: Sequence[OrientingSignal],
    portal_offers: Sequence[PortalOffer],
    signal_learning_receipts: Sequence[SignalLearningReceipt],
    events: Sequence[EpistemicFlowEvent],
    orientation_facets: Sequence[BoundaryOrientationFacet],
    lifecycle_possibilities: Sequence[LifecyclePossibilityFacet],
    air_bindings: Sequence[ContextAirBinding],
    audience_policy_generation: str,
    privacy_policy_generation: str,
    observed_at: str,
    checked_at: str,
    stale_after: str,
) -> ContextFrame:
    """Freeze one rich frame; all ordering and content identities are deterministic."""

    body = {
        "schema": "hapax.context-frame.v1",
        "session_ref": session_ref,
        "task_ref": task_ref,
        "lifecycle_definition": bundle.lifecycle_definition,
        "canon_image": image,
        "demand_shape": demand_shape,
        "position": position,
        "scopes": tuple(sorted(scopes, key=lambda item: item.scope_ref)),
        "temporal_coordinates": tuple(
            sorted(temporal_coordinates, key=lambda item: item.temporal_ref)
        ),
        "resolution_coordinates": tuple(
            sorted(resolution_coordinates, key=lambda item: item.resolution_ref)
        ),
        "source_admissions": tuple(sorted(source_admissions, key=lambda item: item.admission_ref)),
        "observations": tuple(sorted(observations, key=lambda item: item.observation_ref)),
        "derivations": tuple(sorted(derivations, key=lambda item: item.derivation_ref)),
        "facts": tuple(sorted(facts, key=lambda item: item.fact_id)),
        "relations": tuple(sorted(relations, key=lambda item: item.relation_id)),
        "actions": tuple(sorted(actions, key=lambda item: item.action_id)),
        "impingements": tuple(sorted(impingements, key=lambda item: item.impingement_id)),
        "signal_estimates": tuple(sorted(signal_estimates, key=lambda item: item.estimate_ref)),
        "signal_lenses": tuple(sorted(signal_lenses, key=lambda item: item.lens_ref)),
        "signal_constellations": tuple(
            sorted(signal_constellations, key=lambda item: item.constellation_ref)
        ),
        "orienting_signals": tuple(sorted(orienting_signals, key=lambda item: item.signal_id)),
        "portal_offers": tuple(sorted(portal_offers, key=lambda item: item.portal_ref)),
        "signal_learning_receipts": tuple(
            sorted(signal_learning_receipts, key=lambda item: item.learning_ref)
        ),
        "events": tuple(
            sorted(
                events,
                key=lambda item: (
                    item.occurred_at,
                    item.generation,
                    item.derivation_depth,
                    item.event_ref,
                ),
            )
        ),
        "orientation_facets": tuple(sorted(orientation_facets, key=lambda item: item.facet_id)),
        "lifecycle_possibilities": tuple(
            sorted(lifecycle_possibilities, key=lambda item: item.facet_id)
        ),
        "air_bindings": tuple(
            sorted(air_bindings, key=lambda item: (item.object_kind, item.object_ref))
        ),
        "audience_policy_generation": audience_policy_generation,
        "privacy_policy_generation": privacy_policy_generation,
        "observed_at": observed_at,
        "checked_at": checked_at,
        "stale_after": stale_after,
        "may_authorize": False,
    }
    frame_hash = _domain_hash("hapax.context-frame.v1", body)
    frame = ContextFrame(
        **body,
        frame_ref=f"context-frame@sha256:{frame_hash}",
        frame_hash=frame_hash,
    )
    return verify_context_frame(bundle, frame)


def context_bundle_fsm(image: CanonImage) -> dict[str, str]:
    """Return exactly the locked context_bundle strata.fsm string fields."""

    return image.rendered_strata.model_dump(mode="json")


def materialize_bundle(path: Path, **build_kwargs: Any) -> CanonBundle:
    """Write one deterministic dormant artifact; this performs no dispatch or activation."""

    bundle = build_canon_bundle(**build_kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(bundle) + b"\n")
    return bundle


def load_materialized_bundle(path: Path) -> CanonBundle:
    """Load a materialized bundle with duplicate-key and self-hash validation."""

    raw = _read_text(path, reason="canon_bundle_unreadable")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _canon_error(
                    "canon_bundle_duplicate_json_key",
                    "remove duplicate JSON object keys",
                    key,
                )
            result[key] = value
        return result

    try:
        payload = json.loads(raw, object_pairs_hook=unique_pairs)
        expected_raw = canonical_json_bytes(payload).decode("ascii") + "\n"
        if raw != expected_raw:
            raise _canon_error(
                "canon_bundle_noncanonical_json",
                "replace the artifact with its exact canonical JSON encoding",
            )
        return CanonBundle.model_validate(payload)
    except CanonError:
        raise
    except (json.JSONDecodeError, ValidationError) as exc:
        raise _canon_error(
            "canon_bundle_invalid", "restore a schema-valid, self-hash-valid canon bundle", str(exc)
        ) from exc


def bundle_json_schema_bytes() -> bytes:
    """Return the generated schema package for every cross-repository contract root."""

    contract = TypeAdapter(
        CanonBundle
        | LifecycleDefinition
        | ContextFrame
        | ContextSelection
        | ContextExposure
        | CapabilityBehaviorObservation
        | MeasurementApplicationReceipt
        | ObservabilityInvalidationResult
        | ProjectionEnvelope
        | ContextBundleCompatibilityProjection
    )
    return canonical_json_bytes(contract.json_schema(by_alias=True)) + b"\n"


def checked_bundle_json_schema_bytes(path: Path | None = None) -> bytes:
    """Read the checked schema from a repository or installed wheel and verify drift."""

    raw = (
        _read_text(path, reason="canon_schema_unreadable")
        if path is not None
        else _read_repository_or_package(
            CANON_SCHEMA_PATH,
            "coordination-canon.schema.json",
            reason="canon_schema_unreadable",
        )
    )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _canon_error("canon_schema_invalid", "regenerate the checked JSON schema") from exc
    observed = canonical_json_bytes(parsed) + b"\n"
    expected = bundle_json_schema_bytes()
    if observed != expected:
        raise _canon_error("canon_schema_drift", "regenerate the checked JSON schema")
    return observed
