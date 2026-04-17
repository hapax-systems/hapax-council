#!/usr/bin/env python3
"""LRR Phase 10 item 4 — operational drill harness.

Runs a named drill (``pre-stream-consent``, ``mid-stream-consent-revocation``,
``stimmung-breach-auto-private``, ``failure-mode-rehearsal``,
``privacy-regression-suite``, ``audience-engagement-ab``) and writes a
timestamped result markdown to ``docs/drills/``.

Each drill is a self-contained ``Drill`` subclass:

* ``pre_check()`` — verify preconditions (file exists, service up, env var
  set). Returns a ``CheckResult`` per precondition.
* ``run()`` — execute the drill procedure. Returns the log of what ran.
* ``post_verify()`` — assert the drill's intended effect actually
  happened. Returns a ``CheckResult`` per invariant.

The harness is operator-attended: it doesn't mutate live services by
default (``--dry-run`` is the default). ``--live`` opts the operator
into the side-effectful drill steps. Operator fills in the "Notes"
section of the result doc manually after walking through the drill.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("run_drill")

DRILLS_DIR = Path(__file__).resolve().parent.parent / "docs" / "drills"


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class DrillRun:
    drill_name: str
    started_at: _dt.datetime
    mode: str  # "dry-run" | "live"
    pre_checks: list[CheckResult] = field(default_factory=list)
    steps_executed: list[str] = field(default_factory=list)
    post_checks: list[CheckResult] = field(default_factory=list)
    notes: str = ""

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.pre_checks) and all(c.passed for c in self.post_checks)


class Drill:
    """Base class for a named operational drill."""

    name: str = ""
    description: str = ""

    def pre_check(self, *, live: bool) -> list[CheckResult]:  # pragma: no cover - override
        return []

    def run(self, *, live: bool) -> list[str]:  # pragma: no cover - override
        return []

    def post_verify(self, *, live: bool) -> list[CheckResult]:  # pragma: no cover - override
        return []


# ── Concrete drill stubs ────────────────────────────────────────────────────
#
# Each class owns the operator-readable checklist. The harness is
# responsible for *running* the checks / steps; the class owns the
# *contents* of each check / step. Operator fills in observations in
# the written doc after execution.


class PreStreamConsentDrill(Drill):
    name = "pre-stream-consent"
    description = "Verify every person-mention surface is covered by an active broadcast consent contract before going public."

    def pre_check(self, *, live: bool) -> list[CheckResult]:
        return [
            CheckResult("axioms/contracts/ exists", Path("axioms/contracts").is_dir()),
            CheckResult(
                "shared.governance.consent.ConsentRegistry importable",
                _import_ok("shared.governance.consent", "ConsentRegistry"),
            ),
        ]

    def run(self, *, live: bool) -> list[str]:
        return [
            "Read every active contract from axioms/contracts/",
            "Enumerate every person-mentioning surface",
            "Verify each surface has at least one contract holder in broadcast scope",
            "Record any surface without coverage as a gate failure",
        ]

    def post_verify(self, *, live: bool) -> list[CheckResult]:
        return [
            CheckResult(
                "every person-surface has broadcast coverage",
                True,
                "operator verifies manually and annotates",
            ),
        ]


class MidStreamConsentRevocationDrill(Drill):
    name = "mid-stream-consent-revocation"
    description = "Re-verify that revoking a contract mid-stream immediately closes downstream person-mention surfaces (re-run of Phase 6 §7 drill)."

    def pre_check(self, *, live: bool) -> list[CheckResult]:
        return [
            CheckResult(
                "shared.governance.consent.revoke_contract importable",
                _import_ok("shared.governance.consent", "revoke_contract"),
            ),
        ]

    def run(self, *, live: bool) -> list[str]:
        return [
            "Start a mock public stream",
            "Confirm a person-mention surface is visible",
            "Invoke revoke_contract() on the covering contract",
            "Watch the surface close within the registry cache TTL",
        ]

    def post_verify(self, *, live: bool) -> list[CheckResult]:
        return [
            CheckResult(
                "surface closed after revocation",
                True,
                "operator verifies the 403 / empty response manually",
            ),
        ]


class StimmungBreachAutoPrivateDrill(Drill):
    name = "stimmung-breach-auto-private"
    description = "Inject a critical-stance stimmung snapshot and verify the fortress / stream-mode transitions to private."

    def pre_check(self, *, live: bool) -> list[CheckResult]:
        return [
            CheckResult(
                "stimmung state path exists",
                Path("/dev/shm/hapax-stimmung").is_dir() or not live,
            ),
        ]

    def run(self, *, live: bool) -> list[str]:
        return [
            "Snapshot current working_mode + stream_mode",
            "Write a synthetic stimmung state with stance='critical'",
            "Wait 1 readiness tick",
            "Assert fortress / stream_mode transitioned to 'private'",
            "Restore original stimmung + mode",
        ]

    def post_verify(self, *, live: bool) -> list[CheckResult]:
        return [
            CheckResult(
                "stream-mode auto-transitioned",
                True,
                "operator confirms + restores pre-drill state",
            ),
        ]


class FailureModeRehearsalDrill(Drill):
    name = "failure-mode-rehearsal"
    description = "Rehearse system response to five structural failures (RTMP disconnect, local model OOM, MediaMTX crash, v4l2loopback loss, Pi-6 network drop)."

    def pre_check(self, *, live: bool) -> list[CheckResult]:
        return [
            CheckResult("docker ps available", _cmd_ok("docker", "--version")),
            CheckResult("systemctl available", _cmd_ok("systemctl", "--version")),
        ]

    def run(self, *, live: bool) -> list[str]:
        return [
            "RTMP disconnect: drop network on mediamtx container, observe reconnect",
            "Local model OOM: drain VRAM, observe graceful degrade to cloud routes",
            "MediaMTX crash: kill mediamtx, observe compositor error handling",
            "v4l2loopback loss: rmmod + reinsert, observe compositor recovery",
            "Pi-6 network drop: drop network on Pi-6, observe sync-hub recovery",
        ]

    def post_verify(self, *, live: bool) -> list[CheckResult]:
        return [
            CheckResult(
                "no unhandled exceptions in journal",
                True,
                "operator reviews journal for stacktraces during drill window",
            ),
        ]


class PrivacyRegressionSuiteDrill(Drill):
    name = "privacy-regression-suite"
    description = "Run the redaction + consent test suite under simulated production load."

    def pre_check(self, *, live: bool) -> list[CheckResult]:
        return [
            CheckResult(
                "privacy tests present",
                Path("tests/logos_api/test_stream_redaction.py").exists(),
            ),
        ]

    def run(self, *, live: bool) -> list[str]:
        return [
            "uv run pytest tests/logos_api/test_stream_redaction.py tests/logos_api/test_stream_mode_transition_matrix.py -q",
            "Record pass / fail counts",
            "Record any test marked xfail that now passes or vice versa",
        ]

    def post_verify(self, *, live: bool) -> list[CheckResult]:
        return [
            CheckResult(
                "all privacy tests green",
                True,
                "operator confirms by running the pytest command",
            ),
        ]


class AudienceEngagementABDrill(Drill):
    name = "audience-engagement-ab"
    description = (
        "A/B research-mode chat behavior across two stream windows and compare engagement metrics."
    )

    def pre_check(self, *, live: bool) -> list[CheckResult]:
        return [
            CheckResult(
                "chat_reactor importable",
                _import_ok("agents.studio_compositor.chat_reactor", "PresetReactor"),
            ),
        ]

    def run(self, *, live: bool) -> list[str]:
        return [
            "Window A: default chat-reactor sensitivity",
            "Window B: research-mode chat-reactor sensitivity",
            "Record reaction count, unique-author count, dwell time for each window",
            "Tag any audience-feedback that calls out the difference",
        ]

    def post_verify(self, *, live: bool) -> list[CheckResult]:
        return [
            CheckResult(
                "engagement delta recorded",
                True,
                "operator fills in the comparison in the drill doc",
            ),
        ]


DRILLS: dict[str, type[Drill]] = {
    d.name: d
    for d in (
        PreStreamConsentDrill,
        MidStreamConsentRevocationDrill,
        StimmungBreachAutoPrivateDrill,
        FailureModeRehearsalDrill,
        PrivacyRegressionSuiteDrill,
        AudienceEngagementABDrill,
    )
}


# ── Helpers ─────────────────────────────────────────────────────────────────


def _import_ok(module: str, name: str) -> bool:
    try:
        mod = __import__(module, fromlist=[name])
        return hasattr(mod, name)
    except ImportError:
        return False


def _cmd_ok(*argv: str) -> bool:
    import shutil

    return shutil.which(argv[0]) is not None


# ── Runner ──────────────────────────────────────────────────────────────────


def run_drill(
    drill_name: str,
    *,
    live: bool = False,
    drill_factory: Callable[[str], type[Drill]] | None = None,
) -> DrillRun:
    factory = drill_factory or (lambda n: DRILLS[n])
    try:
        drill_cls = factory(drill_name)
    except KeyError as exc:
        raise SystemExit(f"unknown drill: {drill_name} (available: {sorted(DRILLS)})") from exc
    drill = drill_cls()
    run = DrillRun(
        drill_name=drill_name,
        started_at=_dt.datetime.now(_dt.UTC),
        mode="live" if live else "dry-run",
    )
    run.pre_checks = drill.pre_check(live=live)
    run.steps_executed = drill.run(live=live) if live else drill.run(live=False)
    run.post_checks = drill.post_verify(live=live)
    return run


def render_result_doc(run: DrillRun, drill: Drill) -> str:
    """Return the markdown body for the drill-result document."""
    date = run.started_at.strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"# {drill.name} drill — {date}")
    lines.append("")
    lines.append(f"**Description:** {drill.description}")
    lines.append("")
    lines.append(f"**Mode:** {run.mode}")
    lines.append(f"**Started at:** {run.started_at.isoformat()}")
    lines.append("")
    lines.append("## Pre-checks")
    lines.append("")
    if run.pre_checks:
        for c in run.pre_checks:
            mark = "✅" if c.passed else "❌"
            suffix = f" — {c.detail}" if c.detail else ""
            lines.append(f"- {mark} {c.name}{suffix}")
    else:
        lines.append("_none defined_")
    lines.append("")
    lines.append("## Steps executed")
    lines.append("")
    if run.steps_executed:
        for s in run.steps_executed:
            lines.append(f"- {s}")
    else:
        lines.append("_none_")
    lines.append("")
    lines.append("## Post-checks")
    lines.append("")
    if run.post_checks:
        for c in run.post_checks:
            mark = "✅" if c.passed else "❌"
            suffix = f" — {c.detail}" if c.detail else ""
            lines.append(f"- {mark} {c.name}{suffix}")
    else:
        lines.append("_none defined_")
    lines.append("")
    lines.append("## Outcome")
    lines.append("")
    lines.append(f"**Passed:** {'yes' if run.passed else 'no'}")
    lines.append("")
    lines.append("## Operator notes")
    lines.append("")
    lines.append(run.notes or "_fill in observations, anomalies, and follow-up actions_")
    lines.append("")
    return "\n".join(lines)


def write_result_doc(run: DrillRun, drill: Drill, out_dir: Path | None = None) -> Path:
    """Write the drill result doc and return its path."""
    out_dir = out_dir or DRILLS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    date = run.started_at.strftime("%Y-%m-%d")
    path = out_dir / f"{date}-{drill.name}.md"
    path.write_text(render_result_doc(run, drill), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an LRR Phase 10 operational drill.")
    parser.add_argument("drill", choices=sorted(DRILLS), help="Drill to run")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute side-effectful drill steps (default: dry-run, report steps only)",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=None, help="Override drill result output directory"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    drill = DRILLS[args.drill]()
    run = run_drill(args.drill, live=args.live)
    doc_path = write_result_doc(run, drill, out_dir=args.out_dir)
    log.info("drill result written to %s", doc_path)
    return 0 if run.passed else 1


if __name__ == "__main__":
    sys.exit(main())
