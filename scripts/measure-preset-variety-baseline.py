#!/usr/bin/env python3
"""Preset-variety baseline measurement — Phase 1 of preset-variety plan.

Computes the pre-intervention ground truth that downstream phases
(2-9) measure their effect against. Per
``feedback_verify_before_claiming_done`` and
``feedback_exhaust_research_before_solutioning``, no scoring change
lands without this baseline first.

Inputs (read-only):

- ``~/hapax-state/stream-experiment/structural-intent.jsonl`` — slow
  structural director's emitted intents. Each record carries
  ``preset_family_hint`` ∈ {audio-reactive, calm-textural,
  glitch-dense, warm-minimal}. This is the primary signal for the
  family-distribution histogram.
- ``~/hapax-state/stream-experiment/director-intent.jsonl`` — fast
  narrative director's emitted intents. ``compositional_impingements``
  with ``intent_family == "preset.bias"`` represent the narrative
  director's per-tick preset nudges; we count them to detect the
  per-preset activation imbalance.
- ``~/hapax-state/affordance/recruitment-log.jsonl`` — affordance
  pipeline recruitment records. Optional; skipped with NA in the
  baseline output if missing.

Output: a JSON artifact at the path passed via --output. Default
location is the per-day baseline file under
``docs/research/preset-variety-baseline-<YYYY-MM-DD>.json``.

Plan: docs/superpowers/plans/2026-04-20-preset-variety-plan.md Phase 1.
Research: docs/research/2026-04-19-preset-variety-design.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("preset-variety-baseline")


DEFAULT_WINDOW_S = 60 * 60  # 60-minute window per plan §lines 148-149

DEFAULT_STRUCTURAL_LOG = (
    Path.home() / "hapax-state" / "stream-experiment" / "structural-intent.jsonl"
)
DEFAULT_DIRECTOR_LOG = Path.home() / "hapax-state" / "stream-experiment" / "director-intent.jsonl"
DEFAULT_RECRUITMENT_LOG = Path.home() / "hapax-state" / "affordance" / "recruitment-log.jsonl"


def shannon_entropy(distribution: Counter | dict[str, int]) -> float:
    """Compute Shannon entropy over a count distribution.

    Returns 0.0 for empty distributions OR distributions with one
    non-zero value (perfect monoculture). Higher is better — the
    baseline is expected to be near 0 (research §1) and downstream
    phases lift it toward log2(N families) ≈ 2 for 4-family target.
    """
    total = sum(distribution.values()) if distribution else 0
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in distribution.values():
        if count <= 0:
            continue
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def load_jsonl_window(
    path: Path,
    *,
    now: float,
    window_s: float,
    timestamp_fields: tuple[str, ...] = ("emitted_at", "updated_at", "timestamp"),
) -> list[dict[str, Any]]:
    """Read a JSONL file, return records emitted within ``window_s``.

    Tolerant: missing file → empty list. Malformed lines logged at
    DEBUG and skipped. A record without any of the recognised
    timestamp fields is INCLUDED (may be a non-timestamped log).
    """
    if not path.exists():
        log.info("log file missing: %s — skipping", path)
        return []
    cutoff = now - window_s
    out: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    log.debug("malformed JSONL in %s; skipping", path, exc_info=True)
                    continue
                if not isinstance(rec, dict):
                    continue
                ts = None
                for field in timestamp_fields:
                    if field in rec and isinstance(rec[field], int | float):
                        ts = float(rec[field])
                        break
                if ts is None or ts >= cutoff:
                    out.append(rec)
    except OSError:
        log.warning("failed to read %s", path, exc_info=True)
    return out


def family_histogram(structural_records: list[dict[str, Any]]) -> Counter[str]:
    """Per-family histogram from StructuralIntent records."""
    hist: Counter[str] = Counter()
    for rec in structural_records:
        hint = rec.get("preset_family_hint")
        if isinstance(hint, str) and hint:
            hist[hint] += 1
    return hist


def preset_bias_impingement_count(director_records: list[dict[str, Any]]) -> int:
    """Count compositional_impingements with intent_family == "preset.bias"."""
    n = 0
    for rec in director_records:
        ci = rec.get("compositional_impingements")
        if not isinstance(ci, list):
            continue
        for imp in ci:
            if isinstance(imp, dict) and imp.get("intent_family") == "preset.bias":
                n += 1
    return n


def material_histogram(director_records: list[dict[str, Any]]) -> Counter[str]:
    """Per-material histogram from preset.bias impingements (proxy for
    elemental variety in the absence of explicit family tagging on
    narrative-tier records).
    """
    hist: Counter[str] = Counter()
    for rec in director_records:
        ci = rec.get("compositional_impingements")
        if not isinstance(ci, list):
            continue
        for imp in ci:
            if not isinstance(imp, dict) or imp.get("intent_family") != "preset.bias":
                continue
            mat = imp.get("material")
            if isinstance(mat, str) and mat:
                hist[mat] += 1
    return hist


def per_preset_activation_count(records: list[dict]) -> Counter:
    """Count winning capabilities across the recruitment-log window.

    The recruitment log records one line per ``select()`` winner via
    ``AffordancePipeline._persist_recruitment_winner``. The counter is
    the bedrock for the ``colorgrade_halftone_ratio`` plus per-family
    activation telemetry.
    """
    hist: Counter = Counter()
    for rec in records:
        name = rec.get("capability_name")
        if isinstance(name, str) and name:
            hist[name] += 1
    return hist


def colorgrade_halftone_ratio(per_preset: Counter) -> float | str:
    """Compute the ``colorgrade:halftone`` activation ratio.

    Plan §1: research §1 flagged a ~30:1 colorgrade-to-halftone
    activation imbalance at baseline. Phase 9 acceptance pulls this
    ratio under 10:1. ``halftone`` is the post-Phase-5 family that
    should now be reachable via Qdrant; if it has zero activations we
    return ``"INF"`` (string) so the comparator can mark it FAIL with
    a legible reason rather than emitting a ``ZeroDivisionError``.
    Returns ``"NA"`` when neither family fired.
    """
    cg = sum(c for name, c in per_preset.items() if "colorgrade" in name)
    ht = sum(c for name, c in per_preset.items() if "halftone" in name)
    if cg == 0 and ht == 0:
        return "NA"
    if ht == 0:
        return "INF"
    return cg / ht


def build_baseline(
    *,
    structural_log: Path = DEFAULT_STRUCTURAL_LOG,
    director_log: Path = DEFAULT_DIRECTOR_LOG,
    recruitment_log: Path = DEFAULT_RECRUITMENT_LOG,
    window_s: float = DEFAULT_WINDOW_S,
    now: float | None = None,
) -> dict[str, Any]:
    """Compute the full baseline JSON document."""
    now = now or time.time()
    structural = load_jsonl_window(structural_log, now=now, window_s=window_s)
    director = load_jsonl_window(director_log, now=now, window_s=window_s)
    recruitment_present = recruitment_log.exists()

    fam_hist = family_histogram(structural)
    mat_hist = material_histogram(director)
    bias_count = preset_bias_impingement_count(director)

    if recruitment_present:
        recruitment = load_jsonl_window(recruitment_log, now=now, window_s=window_s)
        per_preset = per_preset_activation_count(recruitment)
        cg_ht_ratio: Any = colorgrade_halftone_ratio(per_preset)
    else:
        recruitment = []
        per_preset = Counter()
        cg_ht_ratio = "NA"

    return {
        "schema_version": 1,
        "generated_at": datetime.fromtimestamp(now, tz=UTC).isoformat(),
        "window_s": window_s,
        "structural_intent_records": len(structural),
        "director_intent_records": len(director),
        "preset_bias_impingements": bias_count,
        "preset_family_histogram": dict(fam_hist),
        "preset_family_entropy_bits": shannon_entropy(fam_hist),
        "material_histogram": dict(mat_hist),
        "material_entropy_bits": shannon_entropy(mat_hist),
        "recruitment_log_present": recruitment_present,
        "recruitment_records": len(recruitment),
        # Per-preset activation count + colorgrade:halftone ratio
        # computed from the recruitment log when present (Phase 1 /
        # Phase 9 acceptance metrics). recent_10_cosine_min_distance_mean
        # requires per-recruitment embedding snapshots — separate
        # workstream; emit NA until that's wired.
        "per_preset_activation_count": dict(per_preset) if recruitment_present else "NA",
        "colorgrade_halftone_ratio": cg_ht_ratio,
        "recent_10_cosine_min_distance_mean": "NA",
    }


def write_baseline(payload: dict[str, Any], output: Path) -> None:
    """Atomic write of the baseline JSON via tmp+rename."""
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(output)


def _default_output_path() -> Path:
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    return Path("docs") / "research" / f"preset-variety-baseline-{today}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=_default_output_path(),
        help="Output JSON path (default: docs/research/preset-variety-baseline-<today>.json)",
    )
    parser.add_argument(
        "--window-s",
        type=float,
        default=DEFAULT_WINDOW_S,
        help=f"Time window in seconds (default: {DEFAULT_WINDOW_S})",
    )
    parser.add_argument(
        "--structural-log",
        type=Path,
        default=DEFAULT_STRUCTURAL_LOG,
    )
    parser.add_argument(
        "--director-log",
        type=Path,
        default=DEFAULT_DIRECTOR_LOG,
    )
    parser.add_argument(
        "--recruitment-log",
        type=Path,
        default=DEFAULT_RECRUITMENT_LOG,
    )
    args = parser.parse_args(argv)
    payload = build_baseline(
        structural_log=args.structural_log,
        director_log=args.director_log,
        recruitment_log=args.recruitment_log,
        window_s=args.window_s,
    )
    write_baseline(payload, args.output)
    log.info(
        "baseline written to %s — entropy=%.4f bits over %d structural records",
        args.output,
        payload["preset_family_entropy_bits"],
        payload["structural_intent_records"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
