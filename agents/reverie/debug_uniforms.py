"""CLI diagnostic for /dev/shm/hapax-imagination/uniforms.json.

``python -m agents.reverie.debug_uniforms`` prints a structured summary of
the current Reverie → GPU bridge state: how many keys the uniforms file
holds, how many the current plan declares, which plan defaults are missing
or present, and the file mtime age. This is the operator-facing tool for
diagnosing dimensional droughts (delta PR-3 follow-up) — the same class
of silent failure that PR #696 fixed and PR #707 added a liveness
watchdog for.

Exit code is 0 if ``len(uniforms_keys) >= plan_defaults_count -
ALLOWED_DEFICIT``, otherwise 2. The threshold matches the Prometheus
alert used by ``/api/predictions/metrics`` so the CLI and the metric
agree on "broken".

Flags:
    --json       Emit a machine-readable JSON object instead of the
                 formatted text report. Useful from scripts and smoke
                 tests.
    --verbose    Also list every missing/extra key instead of capping at
                 the first few.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agents.reverie._uniforms import _iter_passes

UNIFORMS_FILE = Path("/dev/shm/hapax-imagination/uniforms.json")
PLAN_FILE = Path("/dev/shm/hapax-imagination/pipeline/plan.json")

# Matches the Prometheus alert threshold exported by
# ``logos/api/routes/predictions.py`` as
# ``reverie_uniforms_key_deficit``. A 5-key deficit below the plan
# defaults is the healthy → degraded tripwire: large enough to absorb
# a restart race window, small enough to catch a genuine bridge break.
ALLOWED_DEFICIT = 5


@dataclass
class UniformsSnapshot:
    """Structured summary of a uniforms.json / plan.json pairing."""

    uniforms_path: str
    plan_path: str
    uniforms_exists: bool
    plan_exists: bool
    uniforms_key_count: int
    plan_defaults_count: int
    uniforms_age_s: float | None
    plan_age_s: float | None
    missing_defaults: list[str] = field(default_factory=list)
    extra_keys: list[str] = field(default_factory=list)
    nonnumeric_keys: list[str] = field(default_factory=list)

    @property
    def deficit(self) -> int:
        return max(0, self.plan_defaults_count - self.uniforms_key_count)

    @property
    def healthy(self) -> bool:
        if not (self.uniforms_exists and self.plan_exists):
            return False
        return self.deficit <= ALLOWED_DEFICIT


def _load_uniforms(path: Path) -> tuple[dict | None, float | None]:
    try:
        stat = path.stat()
    except OSError:
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), stat.st_mtime
    except (OSError, json.JSONDecodeError):
        return None, stat.st_mtime


def _load_plan_defaults(path: Path) -> tuple[dict[str, float] | None, float | None]:
    try:
        stat = path.stat()
    except OSError:
        return None, None
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, stat.st_mtime
    defaults: dict[str, float] = {}
    for p in _iter_passes(plan):
        node_id = p.get("node_id", "")
        for k, v in p.get("uniforms", {}).items():
            if isinstance(v, (int, float)):
                defaults[f"{node_id}.{k}"] = float(v)
    return defaults, stat.st_mtime


def snapshot(
    uniforms_path: Path | None = None,
    plan_path: Path | None = None,
    now: float | None = None,
) -> UniformsSnapshot:
    """Build a UniformsSnapshot from the given paths.

    ``uniforms_path`` and ``plan_path`` default to the module-level
    ``UNIFORMS_FILE`` / ``PLAN_FILE`` constants. Resolving them at call
    time (rather than binding at function-definition time) lets tests
    patch the module globals to point at ``tmp_path`` without
    monkeypatching every call site.
    """
    if uniforms_path is None:
        uniforms_path = UNIFORMS_FILE
    if plan_path is None:
        plan_path = PLAN_FILE
    now = now if now is not None else time.time()
    uniforms, u_mtime = _load_uniforms(uniforms_path)
    plan_defaults, p_mtime = _load_plan_defaults(plan_path)

    uniforms_keys: set[str] = set()
    nonnumeric: list[str] = []
    if uniforms is not None:
        for k, v in uniforms.items():
            if isinstance(v, (int, float)):
                uniforms_keys.add(k)
            else:
                nonnumeric.append(k)

    plan_keys: set[str] = set(plan_defaults or {})
    missing = sorted(plan_keys - uniforms_keys)
    # An "extra" key is any uniforms entry that isn't a plan default AND
    # isn't a known cross-cutting signal channel. ``signal.*`` keys are
    # written by the reverie mixer intentionally (stance, color_warmth)
    # and the ``fb.trace_*`` family is the feedback trace produced by
    # ``update_trace``. Exclude both from the "extra" category so the
    # diagnostic does not flag healthy state as suspicious.
    extras = sorted(
        k
        for k in uniforms_keys - plan_keys
        if not (k.startswith("signal.") or k.startswith("fb.trace_"))
    )

    return UniformsSnapshot(
        uniforms_path=str(uniforms_path),
        plan_path=str(plan_path),
        uniforms_exists=uniforms is not None,
        plan_exists=plan_defaults is not None,
        uniforms_key_count=len(uniforms_keys),
        plan_defaults_count=len(plan_keys),
        uniforms_age_s=(now - u_mtime) if u_mtime is not None else None,
        plan_age_s=(now - p_mtime) if p_mtime is not None else None,
        missing_defaults=missing,
        extra_keys=extras,
        nonnumeric_keys=sorted(nonnumeric),
    )


def _format_text_report(snap: UniformsSnapshot, verbose: bool) -> str:
    def _age(a: float | None) -> str:
        if a is None:
            return "missing"
        return f"{a:.1f}s"

    status = "HEALTHY" if snap.healthy else "DEGRADED"
    lines: list[str] = [
        f"reverie uniforms bridge: {status}",
        f"  uniforms.json: {snap.uniforms_path}",
        f"    exists={snap.uniforms_exists}  age={_age(snap.uniforms_age_s)}"
        f"  keys={snap.uniforms_key_count}",
        f"  plan.json:     {snap.plan_path}",
        f"    exists={snap.plan_exists}  age={_age(snap.plan_age_s)}"
        f"  defaults={snap.plan_defaults_count}",
        f"  deficit: {snap.deficit} (allowed: {ALLOWED_DEFICIT})",
    ]
    if snap.missing_defaults:
        limit = len(snap.missing_defaults) if verbose else 10
        sample = snap.missing_defaults[:limit]
        more_n = len(snap.missing_defaults) - limit
        lines.append(f"  missing plan defaults ({len(snap.missing_defaults)}):")
        for key in sample:
            lines.append(f"    - {key}")
        if more_n > 0:
            lines.append(f"    +{more_n} more")
    if snap.extra_keys:
        limit = len(snap.extra_keys) if verbose else 10
        sample = snap.extra_keys[:limit]
        more_n = len(snap.extra_keys) - limit
        lines.append(f"  unexpected extras ({len(snap.extra_keys)}):")
        for key in sample:
            lines.append(f"    - {key}")
        if more_n > 0:
            lines.append(f"    +{more_n} more")
    if snap.nonnumeric_keys:
        lines.append(f"  nonnumeric keys: {', '.join(snap.nonnumeric_keys)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agents.reverie.debug_uniforms",
        description=(
            "Diagnose the Reverie → GPU uniforms bridge. Compares the live "
            "uniforms.json against the current plan.json defaults and "
            "reports whether the bridge is healthy or in drought."
        ),
    )
    parser.add_argument(
        "--uniforms",
        type=Path,
        default=UNIFORMS_FILE,
        help=f"Path to uniforms.json (default: {UNIFORMS_FILE})",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=PLAN_FILE,
        help=f"Path to plan.json (default: {PLAN_FILE})",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="List every missing/extra key instead of capping at 10",
    )
    args = parser.parse_args(argv)

    snap = snapshot(args.uniforms, args.plan)
    if args.json:
        sys.stdout.write(json.dumps(asdict(snap), indent=2) + "\n")
    else:
        sys.stdout.write(_format_text_report(snap, args.verbose) + "\n")
    return 0 if snap.healthy else 2


if __name__ == "__main__":
    raise SystemExit(main())
