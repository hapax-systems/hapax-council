#!/usr/bin/env python3
"""M8 Re-Splay smoke verifier — operator post-install check.

Cc-task ``m8-re-splay-operator-install-and-smoke`` (WSJF 8.0). The
operator runs the documented install (``makepkg -si`` + PipeWire
restart + plug M8) per the closed parent task; this script is the
fast-loop verifier that checks the live state and prints pass/fail
per criterion with a remediation hint on failure.

Composes with the M8InstrumentReveal lifecycle shipped in
PR #2492 (cc-task ``activity-reveal-ward-p2-m8-migration``):

* ``M8InstrumentReveal._device_present()`` is the same SHM-mtime probe
  the activity-reveal-ward router uses; the smoke script calls it
  directly so a passing smoke means the router will treat the device
  as present too.
* ``studio.m8_lcd_reveal`` affordance presence is checked against
  ``shared.affordance_registry.ALL_AFFORDANCES`` — same surface the
  AffordancePipeline indexes at startup.
* ``m8-display`` source's ``ward_id`` is checked against the live
  ``config/compositor-layouts/default.json`` — same file the
  compositor loads.
* PipeWire ``54-hapax-m8-instrument.conf`` (or
  ``hapax-m8-loudnorm.conf``) is checked for "routes via L-12, never
  bypasses to livestream-tap" — same invariant
  ``test_re_splay_m8_layout_and_affordance.py`` enforces statically.

Usage:

    python scripts/m8-smoke.py            # all checks, exits 0 if all pass
    python scripts/m8-smoke.py --json     # machine-readable summary
    python scripts/m8-smoke.py --check shm  # one specific check by name

The script is read-only — it never modifies SHM, configs, or the live
compositor state. Safe for the operator to run repeatedly during the
plug/unplug cycle.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Check primitives ─────────────────────────────────────────────────


@dataclass(frozen=True)
class CheckResult:
    """One check's outcome."""

    name: str
    passed: bool
    detail: str
    remediation: str = ""


def _check_shm_freshness(
    *,
    shm_path: Path | None = None,
    freshness_window_s: float = 5.0,
    now: float | None = None,
) -> CheckResult:
    """SHM mtime within freshness window means m8c-hapax is publishing.

    Composes with ``M8InstrumentReveal.DEFAULT_DEVICE_PRESENT_WINDOW_S``
    so a passing smoke matches the activity-reveal-ward router's own
    presence decision.
    """

    target = shm_path if shm_path is not None else Path("/dev/shm/hapax-sources/m8-display.rgba")
    if not target.exists():
        return CheckResult(
            name="shm_freshness",
            passed=False,
            detail=f"SHM file missing at {target}",
            remediation=(
                "Confirm m8c-hapax.service is running:  systemctl --user status hapax-m8-monitor"
                "  — if inactive, the udev rule may not have spawned m8c-hapax on plug."
            ),
        )
    ts = time.time() if now is None else now
    age = max(0.0, ts - target.stat().st_mtime)
    if age <= freshness_window_s:
        return CheckResult(
            name="shm_freshness",
            passed=True,
            detail=f"SHM age {age:.2f}s (window {freshness_window_s:.1f}s) at {target}",
        )
    return CheckResult(
        name="shm_freshness",
        passed=False,
        detail=f"SHM stale: age {age:.1f}s > window {freshness_window_s:.1f}s at {target}",
        remediation=(
            "m8c-hapax is not writing frames. Re-plug the M8 USB cable, then"
            " confirm m8c-hapax journal:  journalctl --user -u hapax-m8-monitor -n 50"
        ),
    )


def _check_affordance_registered() -> CheckResult:
    """``studio.m8_lcd_reveal`` is in ``ALL_AFFORDANCES`` with the right shape."""

    try:
        from shared.affordance_registry import ALL_AFFORDANCES
    except Exception as exc:
        return CheckResult(
            name="affordance_registered",
            passed=False,
            detail=f"failed to import ALL_AFFORDANCES: {exc}",
            remediation="ensure repo root is on PYTHONPATH; run via uv run python scripts/m8-smoke.py",
        )
    by_name = {cap.name: cap for cap in ALL_AFFORDANCES}
    if "studio.m8_lcd_reveal" not in by_name:
        return CheckResult(
            name="affordance_registered",
            passed=False,
            detail="studio.m8_lcd_reveal absent from ALL_AFFORDANCES",
            remediation=(
                "the M8 LCD reveal affordance ships in shared/affordance_registry.py"
                " — confirm the studio.m8_lcd_reveal entry is present."
            ),
        )
    cap = by_name["studio.m8_lcd_reveal"]
    if cap.operational.medium != "visual":
        return CheckResult(
            name="affordance_registered",
            passed=False,
            detail=f"studio.m8_lcd_reveal medium={cap.operational.medium!r}, expected 'visual'",
            remediation="correct the OperationalProperties.medium on the M8 affordance",
        )
    if cap.operational.consent_required is not False:
        return CheckResult(
            name="affordance_registered",
            passed=False,
            detail="studio.m8_lcd_reveal consent_required is True; M8 LCD has no PII so should be False",
            remediation="confirm consent_required=False on the M8 affordance OperationalProperties",
        )
    return CheckResult(
        name="affordance_registered",
        passed=True,
        detail="studio.m8_lcd_reveal registered (medium=visual, consent_required=False)",
    )


def _check_layout_ward_id(
    *,
    layout_path: Path | None = None,
) -> CheckResult:
    """Live ``default.json`` has ``ward_id="m8-display"`` on the M8 source."""

    target = (
        layout_path
        if layout_path is not None
        else (REPO_ROOT / "config/compositor-layouts/default.json")
    )
    if not target.exists():
        return CheckResult(
            name="layout_ward_id",
            passed=False,
            detail=f"default.json missing at {target}",
            remediation="this is a repo-tree problem, not an M8 install issue — confirm hapax-council checkout is intact",
        )
    try:
        layout = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return CheckResult(
            name="layout_ward_id",
            passed=False,
            detail=f"default.json malformed JSON: {exc}",
            remediation="default.json is corrupt — restore from git",
        )
    sources = {s.get("id"): s for s in layout.get("sources", [])}
    m8 = sources.get("m8-display")
    if m8 is None:
        return CheckResult(
            name="layout_ward_id",
            passed=False,
            detail="default.json has no m8-display source",
            remediation="re-splay layout regression — confirm test_re_splay_m8_layout_and_affordance.py contracts pass",
        )
    if m8.get("ward_id") != "m8-display":
        return CheckResult(
            name="layout_ward_id",
            passed=False,
            detail=f"m8-display source ward_id={m8.get('ward_id')!r}, expected 'm8-display'",
            remediation=(
                "M8 source is not paired with the activity-reveal-ward family — "
                "confirm activity-reveal-ward-p2-m8-migration shipped (PR #2492)"
            ),
        )
    return CheckResult(
        name="layout_ward_id",
        passed=True,
        detail="m8-display source declares ward_id='m8-display'",
    )


def _check_pipewire_routing(
    *,
    conf_path: Path | None = None,
) -> CheckResult:
    """Pipewire conf routes via L-12, never bypasses to livestream-tap."""

    target = (
        conf_path
        if conf_path is not None
        else (REPO_ROOT / "config/pipewire/hapax-m8-loudnorm.conf")
    )
    if not target.exists():
        return CheckResult(
            name="pipewire_routing",
            passed=False,
            detail=f"M8 loudnorm conf missing at {target}",
            remediation=(
                "expected at config/pipewire/hapax-m8-loudnorm.conf — confirm the cc-task"
                " re-splay-homage-ward-m8 PR is fully merged and the conf was installed"
            ),
        )
    text = target.read_text(encoding="utf-8")
    code_lines = [
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    target_lines = [line for line in code_lines if "target.object" in line]
    has_l12_target = any("ZOOM_Corporation_L-12" in line for line in target_lines)
    if not has_l12_target:
        return CheckResult(
            name="pipewire_routing",
            passed=False,
            detail="conf has no target.object pointing at the L-12 USB return",
            remediation=(
                "M8 loudnorm output must terminate at the Zoom L-12 USB return per the"
                " operator directive 2026-05-02 (everything wet routes via L-12)"
            ),
        )
    for line in target_lines:
        if 'target.object = "hapax-livestream-tap"' in line:
            return CheckResult(
                name="pipewire_routing",
                passed=False,
                detail=f"conf bypasses L-12 with livestream-tap target: {line.strip()}",
                remediation=(
                    "remove the direct livestream-tap target.object and route via L-12"
                    " — see test_re_splay_m8_layout_and_affordance.py::test_m8_wireplumber_routes_through_l12_not_direct_to_stream"
                ),
            )
        if "evilpet" in line:
            return CheckResult(
                name="pipewire_routing",
                passed=False,
                detail=f"conf references evilpet (deprecated): {line.strip()}",
                remediation="strip evilpet references; route via Zoom L-12 USB return",
            )
    return CheckResult(
        name="pipewire_routing",
        passed=True,
        detail="conf targets L-12 USB return; no livestream-tap bypass; no evilpet",
    )


def _check_activity_reveal_lifecycle(
    *,
    shm_path: Path | None = None,
    now: float | None = None,
) -> CheckResult:
    """``M8InstrumentReveal._device_present`` matches what the router will see."""

    try:
        from agents.studio_compositor.m8_instrument_reveal import M8InstrumentReveal
    except Exception as exc:
        return CheckResult(
            name="activity_reveal_lifecycle",
            passed=False,
            detail=f"M8InstrumentReveal import failed: {exc}",
            remediation=(
                "ensure activity-reveal-ward-p2-m8-migration shipped (PR #2492) and"
                " the gamma worktree is on the latest main"
            ),
        )
    target = shm_path if shm_path is not None else Path("/dev/shm/hapax-sources/m8-display.rgba")
    ward = M8InstrumentReveal(shm_path=target)
    try:
        present = ward._device_present(now=now) if hasattr(ward, "_device_present") else False
        # ``_device_present`` shipped with a ``now`` kwarg in P2; the
        # hasattr guard above is purely defensive — older tree won't
        # have the M8InstrumentReveal at all and import will have
        # failed above.
    finally:
        try:
            ward.stop()
        except Exception:
            log.debug("ward.stop raised", exc_info=True)
    if present:
        return CheckResult(
            name="activity_reveal_lifecycle",
            passed=True,
            detail="M8InstrumentReveal._device_present is True; router will paint the M8 ward",
        )
    return CheckResult(
        name="activity_reveal_lifecycle",
        passed=False,
        detail="M8InstrumentReveal._device_present is False — ward stays at opacity 0.0",
        remediation=(
            "the SHM presence window is 5s; if shm_freshness check passes but this fails,"
            " the import path or kwarg signature drifted — confirm PR #2492 surface."
        ),
    )


# ── Check registry ───────────────────────────────────────────────────


CHECKS: dict[str, callable] = {
    "shm": _check_shm_freshness,
    "affordance": _check_affordance_registered,
    "layout": _check_layout_ward_id,
    "pipewire": _check_pipewire_routing,
    "lifecycle": _check_activity_reveal_lifecycle,
}


def run_checks(check_names: list[str] | None = None) -> list[CheckResult]:
    """Run one or all checks and return their results."""

    targets = check_names if check_names else list(CHECKS.keys())
    results: list[CheckResult] = []
    for name in targets:
        fn = CHECKS.get(name)
        if fn is None:
            results.append(
                CheckResult(
                    name=name,
                    passed=False,
                    detail=f"unknown check {name!r}; known: {sorted(CHECKS.keys())}",
                )
            )
            continue
        try:
            results.append(fn())
        except Exception as exc:
            results.append(
                CheckResult(
                    name=name,
                    passed=False,
                    detail=f"check raised {type(exc).__name__}: {exc}",
                    remediation="report this exception to the operator — smoke checks must not raise",
                )
            )
    return results


# ── CLI ──────────────────────────────────────────────────────────────


def _format_result_line(result: CheckResult) -> str:
    tick = "OK  " if result.passed else "FAIL"
    line = f"  [{tick}] {result.name:24s} {result.detail}"
    if not result.passed and result.remediation:
        line += f"\n         remediation: {result.remediation}"
    return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="m8-smoke",
        description="M8 Re-Splay post-install smoke verifier (read-only).",
    )
    parser.add_argument(
        "--check",
        action="append",
        choices=sorted(CHECKS.keys()),
        help="Run only the named check; may be repeated. Default: all checks.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable lines.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    results = run_checks(args.check)

    if args.json:
        print(
            json.dumps(
                {
                    "results": [asdict(r) for r in results],
                    "all_passed": all(r.passed for r in results),
                },
                indent=2,
            )
        )
    else:
        print("M8 Re-Splay smoke verifier")
        print("=" * 30)
        for result in results:
            print(_format_result_line(result))
        print()
        passed = sum(1 for r in results if r.passed)
        print(f"  {passed}/{len(results)} checks passed")

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


# Re-export the env-var name for tests + future operator-tooling readers.
ACTIVITY_REVEAL_M8_FLAG = "HAPAX_ACTIVITY_REVEAL_M8_ENABLED"


def _is_feature_flag_enabled() -> bool:
    """Mirror of M8InstrumentReveal._feature_flag_enabled — surfaced so the
    smoke output can warn the operator that the runtime ward will stay
    invisible until the flag is flipped, even when all checks pass."""

    raw = os.environ.get(ACTIVITY_REVEAL_M8_FLAG, "0")
    return raw.strip().lower() not in ("", "0", "false", "no", "off")
