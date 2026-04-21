#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Phase 9 of preset-variety-plan: compare baseline vs post-deploy windows.

Reads two JSON artifacts produced by ``scripts/measure-preset-variety-baseline.py``
and prints a diff table with pass/fail against the documented thresholds.
Exits non-zero when any threshold check fails so CI / pre-merge gates can
key on the result.

Acceptance thresholds (plan §1.4):

| Metric                       | Baseline target      | Post-deploy target | Direction |
|------------------------------|----------------------|--------------------|-----------|
| Shannon entropy (family)     | ~0.0 (monoculture)   | ≥ 1.5              | up        |
| colorgrade:halftone ratio    | ≥ 30:1 (sparse)      | ≤ 10:1             | down      |
| recent-10 cosine-min-distance| ≤ 0.25 (clustered)   | ≥ 0.40             | up        |

Usage:
    scripts/compare-preset-variety.py BASELINE.json POSTDEPLOY.json
    scripts/compare-preset-variety.py BASELINE.json POSTDEPLOY.json --strict
    scripts/compare-preset-variety.py --json BASELINE.json POSTDEPLOY.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class MetricCheck:
    name: str
    threshold: float
    direction: Literal["up", "down"]
    description: str


# Plan §1.4: the three quantitative metrics that gate "win declaration."
THRESHOLDS: list[MetricCheck] = [
    MetricCheck(
        name="preset_family_entropy_bits",
        threshold=1.5,
        direction="up",
        description="Shannon entropy >= 1.5 bits (family selection no longer monocultured)",
    ),
    MetricCheck(
        name="colorgrade_halftone_ratio",
        threshold=10.0,
        direction="down",
        description="colorgrade:halftone activation ratio <= 10:1 (catalog gap closed)",
    ),
    MetricCheck(
        name="recent_10_cosine_min_distance_mean",
        threshold=0.40,
        direction="up",
        description="Mean recency-distance >= 0.40 (perceptual variety active)",
    ),
]


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _delta(baseline: Any, post: Any) -> str:
    if not _is_numeric(baseline) or not _is_numeric(post):
        return "-"
    diff = float(post) - float(baseline)
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.3f}"


def _verdict(post: Any, threshold: float, direction: str) -> str:
    if not _is_numeric(post):
        return "NO-DATA"
    if direction == "up":
        return "PASS" if float(post) >= threshold else "FAIL"
    return "PASS" if float(post) <= threshold else "FAIL"


def _render_value(value: Any) -> str:
    if value == "NA":
        return "NA"
    if _is_numeric(value):
        return f"{float(value):.3f}"
    return str(value)


def compute_findings(baseline: dict, post: dict) -> dict:
    """Build the structured comparison report."""
    rows: list[dict] = []
    fail_count = 0
    no_data_count = 0
    for check in THRESHOLDS:
        b_val = baseline.get(check.name, "NA")
        p_val = post.get(check.name, "NA")
        verdict = _verdict(p_val, check.threshold, check.direction)
        if verdict == "FAIL":
            fail_count += 1
        elif verdict == "NO-DATA":
            no_data_count += 1
        rows.append(
            {
                "metric": check.name,
                "description": check.description,
                "baseline": b_val,
                "post_deploy": p_val,
                "delta": _delta(b_val, p_val),
                "threshold": check.threshold,
                "direction": check.direction,
                "verdict": verdict,
            }
        )
    return {
        "baseline_generated_at": baseline.get("generated_at", "?"),
        "post_deploy_generated_at": post.get("generated_at", "?"),
        "summary": {
            "checks": len(rows),
            "passing": sum(1 for r in rows if r["verdict"] == "PASS"),
            "failing": fail_count,
            "no_data": no_data_count,
        },
        "rows": rows,
    }


def render_table(findings: dict) -> str:
    """Pretty-print the comparison rows as a fixed-column table."""
    lines = [
        f"baseline:    {findings['baseline_generated_at']}",
        f"post-deploy: {findings['post_deploy_generated_at']}",
        "",
        f"{'metric':40s}{'baseline':>14s}{'post':>14s}{'delta':>10s}{'threshold':>12s}{'verdict':>10s}",
        "-" * 100,
    ]
    for row in findings["rows"]:
        lines.append(
            f"{row['metric']:40s}"
            f"{_render_value(row['baseline']):>14s}"
            f"{_render_value(row['post_deploy']):>14s}"
            f"{row['delta']:>10s}"
            f"{row['threshold']:>12.2f}"
            f"{row['verdict']:>10s}"
        )
    s = findings["summary"]
    lines.append("")
    lines.append(
        f"summary: {s['passing']} pass / {s['failing']} fail / {s['no_data']} no-data of {s['checks']}"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("baseline", type=Path, help="Baseline JSON artifact")
    parser.add_argument("post_deploy", type=Path, help="Post-deploy JSON artifact")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit findings as JSON to stdout instead of a table.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat NO-DATA as failure (default counts only explicit FAILs).",
    )
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    post = json.loads(args.post_deploy.read_text(encoding="utf-8"))
    findings = compute_findings(baseline, post)

    if args.json:
        print(json.dumps(findings, indent=2, sort_keys=True))
    else:
        print(render_table(findings))

    fail_count = findings["summary"]["failing"]
    if args.strict:
        fail_count += findings["summary"]["no_data"]
    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
