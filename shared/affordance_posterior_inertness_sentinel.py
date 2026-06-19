"""Affordance posterior inertness sentinel.

Writes a unique probe through the single-writer posterior path, then verifies
that the daimonion, fortress, and Logos reader construction paths see it.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.affordance_pipeline import ACTIVATION_STATE_PATH, AffordancePipeline

DEFAULT_ARTIFACT_DIR = (
    Path.home() / ".cache" / "hapax" / "affordance-posterior" / "inertness-sentinel"
)
DEFAULT_POSTERIOR_DIR = Path(tempfile.gettempdir()) / "hapax-affordance-posterior-inertness"
LIVE_POSTERIOR_REFUSAL_NEXT_ACTION = (
    "next action: rerun without --posterior-path for an isolated sentinel posterior, "
    "or pass --allow-live-posterior only after confirming the live posterior owner "
    "can tolerate a probe write"
)


@dataclass(frozen=True)
class ConsumerProbe:
    name: str
    build_pipeline: Callable[[Path], AffordancePipeline]


def _build_daimonion_pipeline(posterior_path: Path) -> AffordancePipeline:
    from agents.hapax_daimonion.affordance_pipeline import build_daimonion_affordance_pipeline

    return build_daimonion_affordance_pipeline(posterior_path=posterior_path)


def _build_fortress_pipeline(posterior_path: Path) -> AffordancePipeline:
    from agents.fortress.affordance_pipeline import build_fortress_affordance_pipeline

    return build_fortress_affordance_pipeline(
        posterior_path=posterior_path,
        index_capabilities=False,
    )


def _build_logos_pipeline(posterior_path: Path) -> AffordancePipeline:
    from logos.engine.affordance_pipeline import build_logos_affordance_pipeline

    return build_logos_affordance_pipeline(posterior_path=posterior_path)


def default_consumers() -> tuple[ConsumerProbe, ConsumerProbe, ConsumerProbe]:
    return (
        ConsumerProbe("daimonion", _build_daimonion_pipeline),
        ConsumerProbe("fortress", _build_fortress_pipeline),
        ConsumerProbe("logos", _build_logos_pipeline),
    )


def run_sentinel(
    *,
    posterior_path: str | Path | None = None,
    artifact_path: str | Path | None = None,
    artifact_dir: str | Path = DEFAULT_ARTIFACT_DIR,
    probe_tag: str | None = None,
    allow_live_posterior: bool = False,
    consumers: Sequence[ConsumerProbe] | None = None,
) -> dict[str, Any]:
    tag = probe_tag or uuid.uuid4().hex
    posterior = (
        Path(posterior_path).expanduser()
        if posterior_path is not None
        else DEFAULT_POSTERIOR_DIR / f"{tag}.json"
    )
    capability_name = f"inertness_sentinel_probe_{tag}"
    cue_value = f"inertness_sentinel:{tag}"
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    consumer_probes = tuple(consumers) if consumers is not None else default_consumers()

    result_base: dict[str, Any] = {
        "timestamp": timestamp,
        "posterior_path": str(posterior),
        "probe": {
            "capability_name": capability_name,
            "cue_value": cue_value,
        },
    }

    if _same_path(posterior, ACTIVATION_STATE_PATH) and not allow_live_posterior:
        return _write_result(
            {
                **result_base,
                "status": "FAIL",
                "consumers": [],
                "errors": [
                    "refusing to write inertness probe to live posterior path "
                    f"{ACTIVATION_STATE_PATH}; {LIVE_POSTERIOR_REFUSAL_NEXT_ACTION}"
                ],
            },
            artifact_path=artifact_path,
            artifact_dir=artifact_dir,
            tag=tag,
        )

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    if not consumer_probes:
        errors.append(
            "no posterior consumers configured; next action: provide daimonion, fortress, "
            "and logos consumer probes"
        )
        return _write_result(
            {
                **result_base,
                "status": "FAIL",
                "consumers": results,
                "errors": errors,
            },
            artifact_path=artifact_path,
            artifact_dir=artifact_dir,
            tag=tag,
        )

    # Build readers before the owner writes. The later forced refresh witnesses
    # the long-running-reader path instead of a fresh load that is tautologically current.
    built_consumers: list[tuple[ConsumerProbe, AffordancePipeline]] = []
    for consumer in consumer_probes:
        try:
            built_consumers.append((consumer, consumer.build_pipeline(posterior)))
        except Exception as exc:
            errors.append(
                f"{consumer.name}: {type(exc).__name__}: {exc}; "
                "next action: inspect the named consumer's affordance pipeline builder"
            )
            results.append({"name": consumer.name, "ok": False, "error": str(exc)})

    owner = AffordancePipeline(
        posterior_mode="owner",
        posterior_client_id="inertness_sentinel",
        posterior_path=posterior,
    )
    owner.record_outcome(
        capability_name,
        success=True,
        context={"inertness_probe": cue_value},
    )
    owner.save_activation_state()
    owner.load_activation_state()

    expected_state = owner.get_activation_state(capability_name).model_dump()
    expected_association = owner.get_context_association(cue_value, capability_name)
    if math.isclose(expected_association, 0.0, rel_tol=0.0, abs_tol=1e-12):
        errors.append(
            "owner probe association was not written; next action: inspect "
            "AffordancePipeline.record_outcome context association updates"
        )

    for consumer, pipeline in built_consumers:
        try:
            refreshed = pipeline.refresh_activation_state_if_changed(force=True)
            observed_state = pipeline.get_activation_state(capability_name).model_dump()
            observed_association = pipeline.get_context_association(cue_value, capability_name)
            state_ok = observed_state == expected_state
            association_ok = math.isclose(
                observed_association,
                expected_association,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            ok = state_ok and association_ok
            if not ok:
                errors.append(
                    f"{consumer.name}: stale or missing posterior probe {capability_name}; "
                    f"expected use_count={expected_state['use_count']} "
                    f"association={expected_association}, observed "
                    f"use_count={observed_state['use_count']} association={observed_association}; "
                    "next action: inspect this consumer's posterior path and refresh path"
                )
            results.append(
                {
                    "name": consumer.name,
                    "ok": ok,
                    "refresh_loaded_change": refreshed,
                    "activation_state": observed_state,
                    "association": observed_association,
                }
            )
        except Exception as exc:
            errors.append(
                f"{consumer.name}: {type(exc).__name__}: {exc}; "
                "next action: inspect this consumer's posterior refresh path"
            )
            results.append({"name": consumer.name, "ok": False, "error": str(exc)})

    result: dict[str, Any] = {
        **result_base,
        "status": "FAIL" if errors else "PASS",
        "probe": {
            "capability_name": capability_name,
            "cue_value": cue_value,
            "expected_activation_state": expected_state,
            "expected_association": expected_association,
        },
        "consumers": results,
        "errors": errors,
    }
    return _write_result(result, artifact_path=artifact_path, artifact_dir=artifact_dir, tag=tag)


def _same_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve(strict=False) == right.expanduser().resolve(strict=False)


def _write_result(
    result: dict[str, Any],
    *,
    artifact_path: str | Path | None,
    artifact_dir: str | Path,
    tag: str,
) -> dict[str, Any]:
    timestamp = str(result["timestamp"])
    if artifact_path is None:
        safe_timestamp = timestamp.replace(":", "").replace("-", "")
        artifact = Path(artifact_dir).expanduser() / f"{safe_timestamp}-{tag}.json"
    else:
        artifact = Path(artifact_path).expanduser()
    result["artifact_path"] = str(artifact)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Write an affordance posterior probe through the owner path and verify "
            "daimonion, fortress, and Logos reader paths see it."
        )
    )
    parser.add_argument(
        "--posterior-path",
        type=Path,
        help="posterior file to probe; defaults to an isolated /tmp sentinel file",
    )
    parser.add_argument(
        "--allow-live-posterior",
        action="store_true",
        help="permit probing the live ACTIVATION_STATE_PATH when --posterior-path selects it",
    )
    parser.add_argument("--artifact-path", type=Path)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--probe-tag")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run_sentinel(
        posterior_path=args.posterior_path,
        artifact_path=args.artifact_path,
        artifact_dir=args.artifact_dir,
        probe_tag=args.probe_tag,
        allow_live_posterior=args.allow_live_posterior,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1
