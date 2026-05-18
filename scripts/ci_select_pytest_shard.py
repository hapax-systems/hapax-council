#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
class ShardSummary:
    index: int
    load: float
    files: tuple[WeightedTestFile, ...]


def parse_collect_output(collect_output: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw_line in collect_output.splitlines():
        line = raw_line.strip()
        if not line.startswith("tests/") or "::" not in line:
            continue
        file_path = line.split("::", 1)[0]
        counts[file_path] = counts.get(file_path, 0) + 1
    return counts


def load_runtime_weights(path: Path) -> dict[str, float]:
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
    return weights


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


def selected_paths(plan: tuple[ShardSummary, ...], shard: int) -> list[str]:
    if shard < 1 or shard > len(plan):
        raise ValueError(f"shard must be between 1 and {len(plan)}")
    return [item.path for item in plan[shard - 1].files]


def write_plan(plan: tuple[ShardSummary, ...], stream: TextIO) -> None:
    parts = [
        f"{summary.index}={_format_weight(summary.load)}-weight/{len(summary.files)}-files"
        for summary in plan
    ]
    stream.write("Shard plan by runtime weight: " + " ".join(parts) + "\n")


def _format_weight(weight: float) -> str:
    if weight.is_integer():
        return str(int(weight))
    return f"{weight:.2f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select pytest files for one deterministic runtime-weighted shard."
    )
    parser.add_argument("--collect-output", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, required=True)
    args = parser.parse_args(argv)

    if args.shards < 1:
        parser.error("--shards must be positive")
    if args.shard < 1 or args.shard > args.shards:
        parser.error("--shard must be between 1 and --shards")

    collected_counts = parse_collect_output(args.collect_output.read_text(encoding="utf-8"))
    runtime_weights = load_runtime_weights(args.weights)
    plan = build_shard_plan(collected_counts, runtime_weights, args.shards)
    write_plan(plan, sys.stderr)

    for path in selected_paths(plan, args.shard):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
