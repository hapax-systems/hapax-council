#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import yaml


@dataclass(frozen=True)
class WeightedTestFile:
    path: str
    collected_count: int
    weight: float


@dataclass(frozen=True)
class RuntimeWeightConfig:
    file_weights: Mapping[str, float]
    split_weights: Mapping[str, float]


@dataclass(frozen=True)
class ShardSummary:
    index: int
    load: float
    files: tuple[WeightedTestFile, ...]


@dataclass(frozen=True)
class PytestDuration:
    nodeid: str
    phase: str
    seconds: float


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_DURATION_LINE_RE = re.compile(
    r"(?P<seconds>\d+(?:\.\d+)?)s\s+"
    r"(?P<phase>setup|call|teardown)\s+"
    r"(?P<nodeid>tests/.+)$"
)


def parse_collect_output(collect_output: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in parse_collect_nodeids(collect_output):
        file_path = line.split("::", 1)[0]
        counts[file_path] = counts.get(file_path, 0) + 1
    return counts


def parse_collect_nodeids(collect_output: str) -> tuple[str, ...]:
    nodeids: list[str] = []
    for raw_line in collect_output.splitlines():
        line = raw_line.strip()
        if line.startswith("tests/") and "::" in line:
            nodeids.append(line)
    return tuple(nodeids)


def load_runtime_weights(path: Path) -> dict[str, float]:
    return dict(load_runtime_weight_config(path).file_weights)


def load_runtime_weight_config(path: Path) -> RuntimeWeightConfig:
    with path.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a YAML mapping")

    files = loaded.get("files", {})
    if not isinstance(files, dict):
        raise ValueError(f"{path}: files must be a mapping")

    weights: dict[str, float] = {}
    for test_path, spec in files.items():
        if not isinstance(test_path, str):
            raise ValueError(f"{path}: runtime weight path must be a string")
        weight_value = _extract_weight(path, test_path, spec)
        weight = float(weight_value)
        if weight <= 0:
            raise ValueError(f"{path}: {test_path} weight must be positive")
        weights[test_path] = weight

    split_groups = loaded.get("split_groups", {})
    if not isinstance(split_groups, dict):
        raise ValueError(f"{path}: split_groups must be a mapping")

    split_weights: dict[str, float] = {}
    for node_prefix, spec in split_groups.items():
        if not isinstance(node_prefix, str):
            raise ValueError(f"{path}: split group node prefix must be a string")
        if "::" not in node_prefix:
            raise ValueError(f"{path}: split group {node_prefix} must include a node prefix")
        weight_value = _extract_weight(path, node_prefix, spec)
        weight = float(weight_value)
        if weight <= 0:
            raise ValueError(f"{path}: {node_prefix} weight must be positive")
        split_weights[node_prefix] = weight

    return RuntimeWeightConfig(file_weights=weights, split_weights=split_weights)


def _extract_weight(path: Path, test_path: str, spec: Any) -> int | float:
    if isinstance(spec, int | float):
        return spec
    if isinstance(spec, dict):
        weight_value = spec.get("collected_test_equivalent_weight", spec.get("weight"))
        if isinstance(weight_value, int | float):
            return weight_value
    raise ValueError(f"{path}: {test_path} must define a numeric collected_test_equivalent_weight")


def build_shard_plan(
    collected_counts: Mapping[str, int],
    runtime_weights: Mapping[str, float],
    shard_count: int,
) -> tuple[ShardSummary, ...]:
    if shard_count < 1:
        raise ValueError("shard_count must be positive")

    weighted_files = sorted(
        (
            WeightedTestFile(
                path=path,
                collected_count=count,
                weight=float(runtime_weights.get(path, count)),
            )
            for path, count in collected_counts.items()
        ),
        key=lambda item: (-item.weight, item.path),
    )

    shard_loads = [0.0 for _ in range(shard_count)]
    shard_files: list[list[WeightedTestFile]] = [[] for _ in range(shard_count)]
    for item in weighted_files:
        target = min(
            range(shard_count),
            key=lambda index: (shard_loads[index], len(shard_files[index]), index),
        )
        shard_loads[target] += item.weight
        shard_files[target].append(item)

    return tuple(
        ShardSummary(index=index + 1, load=shard_loads[index], files=tuple(files))
        for index, files in enumerate(shard_files)
    )


def build_shard_plan_from_collect(
    collect_output: str,
    runtime_config: RuntimeWeightConfig,
    shard_count: int,
) -> tuple[ShardSummary, ...]:
    unit_counts: dict[str, int] = {}
    split_prefixes = sorted(runtime_config.split_weights, key=lambda item: (-len(item), item))
    split_files = {prefix.split("::", 1)[0] for prefix in split_prefixes}

    for nodeid in parse_collect_nodeids(collect_output):
        file_path = nodeid.split("::", 1)[0]
        split_prefix = _matching_split_prefix(nodeid, split_prefixes)
        if split_prefix is not None:
            unit = split_prefix
        elif file_path in split_files:
            # A partially split file must never fall back to the whole file path:
            # that would duplicate tests already covered by configured prefixes.
            unit = nodeid
        else:
            unit = file_path
        unit_counts[unit] = unit_counts.get(unit, 0) + 1

    runtime_weights = {
        **runtime_config.file_weights,
        **runtime_config.split_weights,
    }
    return build_shard_plan(unit_counts, runtime_weights, shard_count)


def _matching_split_prefix(nodeid: str, split_prefixes: list[str]) -> str | None:
    for prefix in split_prefixes:
        if nodeid == prefix or nodeid.startswith(prefix + "::"):
            return prefix
    return None


def selected_paths(plan: tuple[ShardSummary, ...], shard: int) -> list[str]:
    if shard < 1 or shard > len(plan):
        raise ValueError(f"shard must be between 1 and {len(plan)}")
    return [item.path for item in plan[shard - 1].files]


def write_plan(plan: tuple[ShardSummary, ...], stream: TextIO) -> None:
    parts = [
        f"{summary.index}={_format_weight(summary.load)}-weight/{len(summary.files)}-units"
        for summary in plan
    ]
    stream.write("Shard plan by runtime weight: " + " ".join(parts) + "\n")


def parse_pytest_duration_output(pytest_output: str) -> tuple[PytestDuration, ...]:
    durations: list[PytestDuration] = []
    for raw_line in pytest_output.splitlines():
        line = _ANSI_RE.sub("", raw_line).strip()
        match = _DURATION_LINE_RE.search(line)
        if match is None:
            continue
        durations.append(
            PytestDuration(
                nodeid=match.group("nodeid").strip(),
                phase=match.group("phase"),
                seconds=float(match.group("seconds")),
            )
        )
    return tuple(
        sorted(
            durations,
            key=lambda item: (-item.seconds, item.phase, item.nodeid),
        )
    )


def build_pytest_duration_artifact(
    durations: tuple[PytestDuration, ...],
    *,
    selected_units: tuple[str, ...],
    shard: int,
    shard_count: int,
    run_id: str,
    run_attempt: str,
    head_sha: str,
    event_name: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_type": "pytest_node_durations",
        "duration_source": "pytest --durations=0 --durations-min=0",
        "run": {
            "id": run_id,
            "attempt": run_attempt,
            "head_sha": head_sha,
            "event_name": event_name,
        },
        "shard": {
            "index": shard,
            "count": shard_count,
            "selected_unit_count": len(selected_units),
        },
        "selected_units": list(selected_units),
        "durations": [
            {
                "nodeid": item.nodeid,
                "phase": item.phase,
                "seconds": item.seconds,
            }
            for item in durations
        ],
    }


def write_pytest_duration_artifact(
    artifact: Mapping[str, Any],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(dict(artifact), sort_keys=False),
        encoding="utf-8",
    )


def _format_weight(weight: float) -> str:
    if weight.is_integer():
        return str(int(weight))
    return f"{weight:.2f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select pytest test units for one deterministic runtime-weighted shard."
    )
    parser.add_argument("--collect-output", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--shard", type=int)
    parser.add_argument("--shards", type=int)
    parser.add_argument("--pytest-output", type=Path)
    parser.add_argument("--duration-artifact", type=Path)
    parser.add_argument("--selected-units", type=Path)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--run-attempt", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--event-name", default="")
    parser.add_argument("--require-durations", action="store_true")
    args = parser.parse_args(argv)

    if args.pytest_output is not None or args.duration_artifact is not None:
        if args.pytest_output is None:
            parser.error("--pytest-output is required with --duration-artifact")
        if args.duration_artifact is None:
            parser.error("--duration-artifact is required with --pytest-output")
        if args.shard is None or args.shards is None:
            parser.error("--shard and --shards are required with --duration-artifact")
        if args.shards < 1:
            parser.error("--shards must be positive")
        if args.shard < 1 or args.shard > args.shards:
            parser.error("--shard must be between 1 and --shards")

        pytest_output = args.pytest_output.read_text(encoding="utf-8")
        durations = parse_pytest_duration_output(pytest_output)
        if args.require_durations and not durations:
            parser.error("no pytest duration lines were found")
        selected_units: tuple[str, ...] = ()
        if args.selected_units is not None and args.selected_units.exists():
            selected_units = tuple(
                line.strip()
                for line in args.selected_units.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        artifact = build_pytest_duration_artifact(
            durations,
            selected_units=selected_units,
            shard=args.shard,
            shard_count=args.shards,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            head_sha=args.head_sha,
            event_name=args.event_name,
        )
        write_pytest_duration_artifact(artifact, args.duration_artifact)
        return 0

    if args.collect_output is None:
        parser.error("--collect-output is required unless writing a duration artifact")
    if args.weights is None:
        parser.error("--weights is required unless writing a duration artifact")
    if args.shard is None:
        parser.error("--shard is required")
    if args.shards is None:
        parser.error("--shards is required")
    if args.shards < 1:
        parser.error("--shards must be positive")
    if args.shard < 1 or args.shard > args.shards:
        parser.error("--shard must be between 1 and --shards")

    collect_output = args.collect_output.read_text(encoding="utf-8")
    runtime_config = load_runtime_weight_config(args.weights)
    plan = build_shard_plan_from_collect(collect_output, runtime_config, args.shards)
    write_plan(plan, sys.stderr)

    for path in selected_paths(plan, args.shard):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
