"""End-to-end segment smoke for the content-programming pipeline.

Outcome 2 in the segment-observability master task is programme
authoring: a segmented-content programme should be selected, prepared,
loadable, backed by role assets, and representable as a content programme
run envelope. This module wraps that path in ``SegmentRecorder`` so the
operator can see ``started`` -> ``happened`` plus a coarse
``quality.programme_authoring`` verdict in ``segments.jsonl``.

The live runner calls ``daily_segment_prep.run_prep``. Tests inject
deterministic fakes for the prep, load, asset, and run-envelope seams so
the smoke stays fast and service-free while still exercising the same
read-after-write contract.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from shared.content_programme_run_store import (
    ContentProgrammeRunEnvelope,
    FixtureCaseId,
    build_fixture_envelope,
)
from shared.segment_observability import QualityRating, SegmentRecorder

log = logging.getLogger(__name__)

PROGRAMME_AUTHORING_SEGMENT_ROLE = "programme_authoring"
DEFAULT_EXPECTED_PROGRAMMES = 1

RunPrepFn = Callable[[Path], Sequence[Path]]
LoadPrepFn = Callable[..., Sequence[Mapping[str, Any]]]
AssetResolverFn = Callable[..., Any]
EnvelopeBuilderFn = Callable[[Mapping[str, Any]], Any]


@dataclass(frozen=True)
class ContentProgrammingAssessment:
    """Coarse programme-authoring quality verdict for one smoke run."""

    rating: QualityRating
    notes: str
    expected_programmes: int
    saved_count: int | None
    loaded_count: int
    artifact_ok_count: int
    asset_resolved_count: int
    asset_checked_count: int
    envelope_ok_count: int
    envelope_checked_count: int


@dataclass(frozen=True)
class ContentProgrammingSmokeResult:
    """Structured result returned after the segment event is written."""

    assessment: ContentProgrammingAssessment
    saved_paths: tuple[Path, ...]
    loaded_artifacts: tuple[Mapping[str, Any], ...]
    assets_by_programme: Mapping[str, Any] = field(default_factory=dict)
    run_envelopes: tuple[Any, ...] = ()


def run_content_programming_smoke(
    *,
    prep_dir: Path | None = None,
    expected_programmes: int = DEFAULT_EXPECTED_PROGRAMMES,
    topic_seed: str | None = None,
    log_path: Path | None = None,
    run_prep_fn: RunPrepFn | None = None,
    load_prepped_fn: LoadPrepFn | None = None,
    asset_resolver: AssetResolverFn | None = None,
    envelope_builder: EnvelopeBuilderFn | None = None,
) -> ContentProgrammingSmokeResult:
    """Run the content-programming prep path and emit a segment event.

    Args:
        prep_dir: Base directory for ``daily_segment_prep`` artifacts.
        expected_programmes: Minimum number of newly saved programmes the
            smoke expects from this run.
        topic_seed: Optional seed copied into ``SegmentEvent.topic_seed``.
        log_path: Optional ``segments.jsonl`` override.
        run_prep_fn/load_prepped_fn/asset_resolver/envelope_builder: Test
            seams. Production callers leave these unset.

    Returns:
        A ``ContentProgrammingSmokeResult`` containing the quality
        assessment and read-back artifacts.
    """

    from agents.hapax_daimonion import daily_segment_prep

    target_prep_dir = prep_dir or daily_segment_prep.DEFAULT_PREP_DIR
    run_prep = run_prep_fn or daily_segment_prep.run_prep
    load_prepped = load_prepped_fn or daily_segment_prep.load_prepped_programmes

    saved_paths: tuple[Path, ...] = ()
    loaded_artifacts: tuple[Mapping[str, Any], ...] = ()
    assets_by_programme: Mapping[str, Any] = {}
    run_envelopes: tuple[Any, ...] = ()
    assessment: ContentProgrammingAssessment | None = None

    with SegmentRecorder(
        PROGRAMME_AUTHORING_SEGMENT_ROLE,
        topic_seed=topic_seed,
        log_path=log_path,
    ) as event:
        try:
            saved_paths = tuple(Path(path) for path in run_prep(target_prep_dir))
            loaded_artifacts = tuple(
                load_prepped(
                    target_prep_dir,
                    require_selected=False,
                    strict_release_contract=False,
                )
            )
            assets_by_programme = resolve_assets_for_artifacts(
                loaded_artifacts,
                resolver=asset_resolver,
            )
            run_envelopes = build_run_envelopes_for_artifacts(
                loaded_artifacts,
                builder=envelope_builder,
            )
            assessment = assess_content_programming_quality(
                expected_programmes=expected_programmes,
                saved_paths=saved_paths,
                loaded_artifacts=loaded_artifacts,
                assets_by_programme=assets_by_programme,
                run_envelopes=run_envelopes,
            )
            event.quality.programme_authoring = assessment.rating
            event.quality.notes = assessment.notes
        except Exception as exc:
            event.quality.programme_authoring = QualityRating.POOR
            event.quality.notes = f"content programming smoke raised {type(exc).__name__}: {exc}"
            raise

    assert assessment is not None
    return ContentProgrammingSmokeResult(
        assessment=assessment,
        saved_paths=saved_paths,
        loaded_artifacts=loaded_artifacts,
        assets_by_programme=assets_by_programme,
        run_envelopes=run_envelopes,
    )


def assess_content_programming_quality(
    *,
    expected_programmes: int,
    saved_paths: Sequence[Path] | None,
    loaded_artifacts: Sequence[Mapping[str, Any]],
    assets_by_programme: Mapping[str, Any] | None = None,
    run_envelopes: Sequence[Any] = (),
) -> ContentProgrammingAssessment:
    """Grade read-back artifacts against the programme-authoring smoke rubric."""

    expected = max(0, int(expected_programmes))
    saved_count = None if saved_paths is None else len(saved_paths)
    loaded_count = len(loaded_artifacts)
    artifact_ok_count = sum(1 for artifact in loaded_artifacts if _artifact_authoring_ok(artifact))
    asset_map = assets_by_programme or {}
    asset_checked_count = len(asset_map)
    asset_resolved_count = sum(1 for assets in asset_map.values() if _asset_has_material(assets))
    envelope_checked_count = len(run_envelopes)
    envelope_ok_count = sum(1 for envelope in run_envelopes if _run_envelope_ok(envelope))

    rating = _rate_programme_authoring(
        expected=expected,
        saved_count=saved_count,
        loaded_count=loaded_count,
        artifact_ok_count=artifact_ok_count,
        asset_checked_count=asset_checked_count,
        asset_resolved_count=asset_resolved_count,
        envelope_checked_count=envelope_checked_count,
        envelope_ok_count=envelope_ok_count,
    )
    notes = (
        f"expected={expected}; "
        f"saved={'unknown' if saved_count is None else saved_count}; "
        f"loaded={loaded_count}; "
        f"artifacts_ok={artifact_ok_count}/{loaded_count}; "
        f"assets_resolved={asset_resolved_count}/{asset_checked_count}; "
        f"envelopes_ok={envelope_ok_count}/{envelope_checked_count}; "
        f"rating={rating.value}"
    )
    return ContentProgrammingAssessment(
        rating=rating,
        notes=notes,
        expected_programmes=expected,
        saved_count=saved_count,
        loaded_count=loaded_count,
        artifact_ok_count=artifact_ok_count,
        asset_resolved_count=asset_resolved_count,
        asset_checked_count=asset_checked_count,
        envelope_ok_count=envelope_ok_count,
        envelope_checked_count=envelope_checked_count,
    )


def resolve_assets_for_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    resolver: AssetResolverFn | None = None,
) -> dict[str, Any]:
    """Resolve role assets for each loaded prepared programme artifact."""

    if resolver is None:
        from agents.programme_authors.asset_resolver import resolve_assets as resolver

    out: dict[str, Any] = {}
    for index, artifact in enumerate(artifacts):
        programme_id = str(artifact.get("programme_id") or f"artifact-{index}")
        role = str(artifact.get("role") or "")
        topic = str(artifact.get("topic") or artifact.get("narrative_beat") or "")
        source_uri = _first_string(
            artifact.get("source_uri"),
            artifact.get("selected_input_refs"),
            artifact.get("source_refs"),
        )
        subject = str(artifact.get("subject") or topic)
        try:
            out[programme_id] = resolver(
                role,
                topic=topic,
                source_uri=source_uri,
                subject=subject,
            )
        except Exception:
            log.debug("asset resolution failed for %s", programme_id, exc_info=True)
            out[programme_id] = None
    return out


def build_run_envelopes_for_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    builder: EnvelopeBuilderFn | None = None,
) -> tuple[Any, ...]:
    """Build or validate a run envelope per loaded prepared programme."""

    if builder is None:
        builder = _default_envelope_for_artifact
    out: list[Any] = []
    for artifact in artifacts:
        try:
            out.append(builder(artifact))
        except Exception:
            log.debug(
                "run-envelope build failed for %s", artifact.get("programme_id"), exc_info=True
            )
    return tuple(out)


def _rate_programme_authoring(
    *,
    expected: int,
    saved_count: int | None,
    loaded_count: int,
    artifact_ok_count: int,
    asset_checked_count: int,
    asset_resolved_count: int,
    envelope_checked_count: int,
    envelope_ok_count: int,
) -> QualityRating:
    """Apply the operator's four-bucket happened-well rubric."""

    if expected == 0 and loaded_count == 0:
        return QualityRating.UNMEASURED
    if saved_count == 0 or loaded_count == 0:
        return QualityRating.POOR

    required = expected or loaded_count
    if saved_count is not None and saved_count < required:
        return QualityRating.ACCEPTABLE
    if loaded_count < required:
        return QualityRating.ACCEPTABLE
    if artifact_ok_count < loaded_count:
        return QualityRating.ACCEPTABLE
    if envelope_checked_count < loaded_count or envelope_ok_count < loaded_count:
        return QualityRating.ACCEPTABLE
    if asset_checked_count >= loaded_count and asset_resolved_count >= loaded_count:
        return QualityRating.EXCELLENT
    return QualityRating.GOOD


def _artifact_authoring_ok(artifact: Mapping[str, Any]) -> bool:
    """Return whether a loaded prep artifact carries the required contracts."""

    script = artifact.get("prepared_script")
    beats = artifact.get("segment_beats")
    if not artifact.get("programme_id") or not artifact.get("role"):
        return False
    if not isinstance(script, list) or not script:
        return False
    if not isinstance(beats, list) or len(beats) != len(script):
        return False
    if (artifact.get("actionability_alignment") or {}).get("ok") is not True:
        return False
    if (artifact.get("segment_prep_contract_report") or {}).get("ok") is not True:
        return False
    if (artifact.get("segment_live_event_report") or {}).get("ok") is not True:
        return False
    source_hashes = artifact.get("source_hashes")
    return isinstance(source_hashes, Mapping) and bool(source_hashes)


def _asset_has_material(assets: Any) -> bool:
    """Check whether a role-asset object has usable resolved material."""

    if assets is None:
        return False
    is_empty = getattr(assets, "is_empty", None)
    if isinstance(is_empty, bool):
        return not is_empty
    if isinstance(assets, Mapping):
        if assets.get("is_empty") is True:
            return False
        return any(
            bool(value)
            for key, value in assets.items()
            if key not in {"topic", "source_uri", "resolution_failed"}
        )
    return bool(assets)


def _run_envelope_ok(envelope: Any) -> bool:
    """Validate the content-programme run envelope used by the smoke."""

    try:
        run = (
            envelope
            if isinstance(envelope, ContentProgrammeRunEnvelope)
            else ContentProgrammeRunEnvelope.model_validate(envelope)
        )
    except (TypeError, ValueError, ValidationError):
        return False
    event_types = {event.event_type for event in run.events}
    has_boundary = any(boundary.boundary_type for boundary in run.boundary_event_refs)
    return (
        "started" in event_types
        and has_boundary
        and run.final_status
        in {
            "blocked",
            "completed",
            "conversion_held",
            "corrected",
            "refused",
        }
    )


def _default_envelope_for_artifact(artifact: Mapping[str, Any]) -> ContentProgrammeRunEnvelope:
    role = str(artifact.get("role") or "")
    case_id: FixtureCaseId = "dry_run_tier_list" if role == "tier_list" else "dry_run"
    return build_fixture_envelope(case_id)


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item
    return None
