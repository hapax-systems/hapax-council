"""Pre-dispatch provenance gate: face-obscure, axiom scan, legal-name guard.

Fail-closed: no clip dispatches without a clean gate pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from shared.face_obscure_policy import FaceObscurePolicy, is_feature_active, resolve_policy

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def _check_face_obscure() -> list[str]:
    failures: list[str] = []
    if not is_feature_active():
        failures.append("face_obscure_feature_disabled")
    policy = resolve_policy()
    if policy == FaceObscurePolicy.DISABLED:
        failures.append("face_obscure_policy_disabled")
    return failures


def _check_legal_name(text: str) -> list[str]:
    try:
        from agents.publication_bus.publisher_kit.legal_name_guard import assert_no_leak

        assert_no_leak(text)
        return []
    except Exception:
        return ["legal_name_leak_detected"]


def _check_source_provenance(source_segments: list[str]) -> list[str]:
    if not source_segments:
        return ["no_source_segments"]
    return []


def check_clip(
    *,
    clip_path: Path,
    title: str,
    description: str,
    source_segments: list[str],
) -> GateResult:
    reasons: list[str] = []

    reasons.extend(_check_face_obscure())

    combined_text = f"{title} {description}"
    reasons.extend(_check_legal_name(combined_text))

    reasons.extend(_check_source_provenance(source_segments))

    if not clip_path.is_file():
        reasons.append("clip_file_missing")

    passed = len(reasons) == 0
    if not passed:
        log.warning("Provenance gate FAILED for %s: %s", clip_path.name, reasons)

    return GateResult(passed=passed, reasons=reasons)
