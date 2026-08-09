"""Immutable availability limits for untrusted evidence inputs.

These ceilings prevent resource-exhaustion during read-only verification. They
are operational safety limits only: changing or hitting one cannot create or
alter scientific evidence, efficacy, authority, or economic conclusions.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from .errors import VerificationResourceLimitExceeded


@dataclass(frozen=True, slots=True)
class VerificationLimits:
    terminal_bundle_bytes: int = 16 * 1024 * 1024
    inventory_bytes: int = 16 * 1024 * 1024
    inventory_entries: int = 100_000
    evidence_object_bytes: int = 256 * 1024 * 1024
    total_evidence_bytes: int = 4 * 1024 * 1024 * 1024
    retained_evidence_bytes: int = 1024 * 1024 * 1024
    artifact_rows: int = 100_000
    receipt_rows: int = 100_002
    canonical_json_bytes: int = 256 * 1024 * 1024
    json_nesting_depth: int = 128
    json_structural_tokens: int = 4_000_000
    relative_path_bytes: int = 4096
    relative_path_components: int = 64
    scheduled_pairs: int = 50_000
    terminal_attempts: int = 200_000

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or value < 1:
                raise ValueError(f"verification limit {field.name} must be a positive integer")


DEFAULT_VERIFICATION_LIMITS = VerificationLimits()


def validate_json_resource_envelope(
    payload: bytes,
    *,
    label: str,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> None:
    """Reject oversized or pathologically nested JSON before decoding it."""

    if type(payload) is not bytes:
        raise TypeError(f"{label} must be exact bytes")
    if not isinstance(limits, VerificationLimits):
        raise TypeError("limits must be a VerificationLimits value")
    if len(payload) > limits.canonical_json_bytes:
        raise VerificationResourceLimitExceeded(
            f"{label} exceeds canonical_json_bytes={limits.canonical_json_bytes}; "
            "next action: split the evidence document or reduce its cardinality"
        )
    depth = 0
    structural_tokens = 0
    in_string = False
    escaped = False
    for value in payload:
        if in_string:
            if escaped:
                escaped = False
            elif value == 0x5C:  # backslash
                escaped = True
            elif value == 0x22:  # quote
                in_string = False
            continue
        if value == 0x22:
            in_string = True
        elif value in {0x5B, 0x7B}:  # [ {
            structural_tokens += 1
            depth += 1
            if depth > limits.json_nesting_depth:
                raise VerificationResourceLimitExceeded(
                    f"{label} exceeds json_nesting_depth={limits.json_nesting_depth}; "
                    "next action: flatten the evidence document"
                )
        elif value in {0x2C, 0x3A}:  # , :
            structural_tokens += 1
        elif value in {0x5D, 0x7D}:  # ] }
            depth -= 1
        if structural_tokens > limits.json_structural_tokens:
            raise VerificationResourceLimitExceeded(
                f"{label} exceeds json_structural_tokens={limits.json_structural_tokens}; "
                "next action: split the evidence document or reduce its cardinality"
            )


def validate_relative_path_resource(
    value: str,
    *,
    label: str,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> None:
    """Bound descriptor-relative path work before any component walk."""

    if type(value) is not str:
        raise TypeError(f"{label} must be exact text")
    if not isinstance(limits, VerificationLimits):
        raise TypeError("limits must be a VerificationLimits value")
    encoded_size = len(value.encode("utf-8"))
    if encoded_size > limits.relative_path_bytes:
        raise VerificationResourceLimitExceeded(
            f"{label} exceeds relative_path_bytes={limits.relative_path_bytes}; "
            "next action: shorten the evidence path"
        )
    component_count = value.count("/") + 1
    if component_count > limits.relative_path_components:
        raise VerificationResourceLimitExceeded(
            f"{label} exceeds relative_path_components={limits.relative_path_components}; "
            "next action: flatten the evidence path"
        )
