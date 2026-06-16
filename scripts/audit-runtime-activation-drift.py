#!/usr/bin/env python3
"""Audit source-vs-runtime activation drift for Hapax user services."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIT_DIR = REPO_ROOT / "systemd" / "units"
DEFAULT_CACHE_ROOT = Path.home() / ".cache" / "hapax"

GOOD_UNIT_FILE_STATES = {
    "alias",
    "enabled",
    "enabled-runtime",
    "generated",
    "indirect",
    "linked",
    "linked-runtime",
    "static",
    "transient",
}
GOOD_ACTIVE_STATES = {"active", "activating", "reloading"}

CRITICAL_UNITS = frozenset(
    {
        "hapax-cc-hygiene.timer",
        "hapax-cc-pr-autoqueue.timer",
        "hapax-cc-pr-merge-watcher.timer",
        "hapax-coord.service",
        "hapax-coordinator.service",
        "hapax-operator-current-state.timer",
        "hapax-relay-to-cc-tasks.timer",
        "hapax-request-intake-consumer.timer",
        "hapax-security-signal-intake.timer",
        "hapax-source-activate.timer",
        "hapax-triage-officer.service",
    }
)

CRITICAL_ARTIFACTS = (
    ("operator_current_state", Path("operator-current-state.json"), 900),
    ("planning_feed_state", Path("planning-feed-state.json"), 900),
    ("cc_hygiene_state", Path("cc-hygiene-state.json"), 900),
    ("security_signal_intake_state", Path("security-signal-intake-state.json"), 7200),
)

CRITICAL_UNIT_CONTENT_CONTRACTS: dict[str, tuple[tuple[str, str], ...]] = {
    "hapax-request-intake-consumer.service": (
        (
            "fulfillment_report_environment",
            "Environment=HAPAX_REQUEST_FULFILLMENT_REPORT=%h/.cache/hapax/request-fulfillment-reconciler.json",
        ),
        (
            "fulfillment_reconciler_exec_start_post",
            "ExecStartPost=%h/.local/bin/uv --directory %h/.cache/hapax/source-activation/worktree run python scripts/request-fulfillment-reconciler --apply --write-report --report-path %h/.cache/hapax/request-fulfillment-reconciler.json --quiet",
        ),
    ),
}


@dataclass(frozen=True)
class UnitSpec:
    name: str
    path: str
    kind: str
    installable: bool
    critical: bool


@dataclass(frozen=True)
class RuntimeUnit:
    name: str
    file_state: str | None = None
    load_state: str | None = None
    active_state: str | None = None
    sub_state: str | None = None


@dataclass(frozen=True)
class Finding:
    severity: str
    kind: str
    subject: str
    detail: str


def parse_unit_file(path: Path, *, critical_units: frozenset[str] = CRITICAL_UNITS) -> UnitSpec:
    section = None
    installable = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "Install" and "=" in line:
            installable = True
    return UnitSpec(
        name=path.name,
        path=str(path),
        kind=path.suffix.removeprefix("."),
        installable=installable,
        critical=path.name in critical_units,
    )


def repo_unit_specs(unit_dir: Path) -> list[UnitSpec]:
    return sorted(
        [
            parse_unit_file(path)
            for path in unit_dir.iterdir()
            if path.is_file() and path.suffix in {".service", ".timer"}
        ],
        key=lambda spec: spec.name,
    )


def run_systemctl(args: list[str]) -> str:
    proc = subprocess.run(
        ["systemctl", "--user", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode not in {0, 3}:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip() or "systemctl failed")
    return proc.stdout


def _clean_unit_name(value: str) -> str:
    return value.strip().lstrip("●").strip()


def parse_unit_files_output(text: str) -> dict[str, RuntimeUnit]:
    units: dict[str, RuntimeUnit] = {}
    for raw_line in text.splitlines():
        parts = raw_line.split()
        if len(parts) < 2:
            continue
        name = _clean_unit_name(parts[0])
        if not name.endswith((".service", ".timer")):
            continue
        units[name] = RuntimeUnit(name=name, file_state=parts[1])
    return units


def parse_units_output(text: str) -> dict[str, RuntimeUnit]:
    units: dict[str, RuntimeUnit] = {}
    for raw_line in text.splitlines():
        parts = raw_line.split()
        if parts and parts[0] == "●":
            parts = parts[1:]
        if len(parts) < 4:
            continue
        name = _clean_unit_name(parts[0])
        if not name.endswith((".service", ".timer")):
            continue
        units[name] = RuntimeUnit(
            name=name,
            load_state=parts[1],
            active_state=parts[2],
            sub_state=parts[3],
        )
    return units


def merge_runtime(
    unit_files: dict[str, RuntimeUnit], active_units: dict[str, RuntimeUnit]
) -> dict[str, RuntimeUnit]:
    names = set(unit_files) | set(active_units)
    merged: dict[str, RuntimeUnit] = {}
    for name in names:
        file_row = unit_files.get(name, RuntimeUnit(name=name))
        active_row = active_units.get(name, RuntimeUnit(name=name))
        merged[name] = RuntimeUnit(
            name=name,
            file_state=file_row.file_state,
            load_state=active_row.load_state,
            active_state=active_row.active_state,
            sub_state=active_row.sub_state,
        )
    return merged


def collect_runtime_units() -> dict[str, RuntimeUnit]:
    unit_files = parse_unit_files_output(
        run_systemctl(["list-unit-files", "--no-pager", "--no-legend"])
    )
    active_units = parse_units_output(
        run_systemctl(["list-units", "--all", "--no-pager", "--no-legend"])
    )
    return merge_runtime(unit_files, active_units)


def cat_runtime_unit(name: str) -> str | None:
    proc = subprocess.run(
        ["systemctl", "--user", "cat", name, "--no-pager"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def classify_unit_findings(specs: list[UnitSpec], runtime: dict[str, RuntimeUnit]) -> list[Finding]:
    findings: list[Finding] = []
    spec_names = {spec.name for spec in specs}
    for spec in specs:
        row = runtime.get(spec.name)
        severity = "critical" if spec.critical else "warning"
        if spec.installable and row is None:
            findings.append(
                Finding(
                    severity=severity,
                    kind="unit_missing",
                    subject=spec.name,
                    detail=f"installable repo unit absent from user manager ({spec.path})",
                )
            )
            continue
        if row is None:
            continue
        if row.active_state == "failed" or row.sub_state == "failed":
            findings.append(
                Finding(
                    severity=severity,
                    kind="unit_failed",
                    subject=spec.name,
                    detail=f"runtime state is {row.active_state or 'unknown'}/{row.sub_state or 'unknown'}",
                )
            )
        companion_timer = spec.name.removesuffix(".service") + ".timer"
        companion_timer_state = runtime.get(companion_timer)
        timer_driven = (
            spec.kind == "service"
            and companion_timer in spec_names
            and companion_timer_state is not None
            and companion_timer_state.file_state in GOOD_UNIT_FILE_STATES
        )
        if spec.installable and not timer_driven and row.file_state not in GOOD_UNIT_FILE_STATES:
            findings.append(
                Finding(
                    severity=severity,
                    kind="unit_not_enabled",
                    subject=spec.name,
                    detail=f"unit-file state is {row.file_state or 'unknown'}",
                )
            )
        if spec.critical and row.active_state not in GOOD_ACTIVE_STATES:
            findings.append(
                Finding(
                    severity="critical",
                    kind="critical_unit_inactive",
                    subject=spec.name,
                    detail=f"runtime state is {row.active_state or 'missing'}/{row.sub_state or 'missing'}",
                )
            )
    return findings


def classify_unit_content_findings(
    unit_dir: Path,
    runtime: dict[str, RuntimeUnit],
    *,
    unit_text_loader: Callable[[str], str | None] = cat_runtime_unit,
    contracts: dict[str, tuple[tuple[str, str], ...]] = CRITICAL_UNIT_CONTENT_CONTRACTS,
) -> list[Finding]:
    findings: list[Finding] = []
    for unit_name, requirements in contracts.items():
        repo_unit = unit_dir / unit_name
        if not repo_unit.is_file():
            findings.append(
                Finding(
                    severity="critical",
                    kind="critical_unit_source_contract_missing",
                    subject=unit_name,
                    detail=f"{repo_unit} is missing",
                )
            )
            continue

        row = runtime.get(unit_name)
        if row is None:
            continue

        repo_text = repo_unit.read_text(encoding="utf-8")
        runtime_text = unit_text_loader(unit_name)
        if runtime_text is None:
            findings.append(
                Finding(
                    severity="critical",
                    kind="critical_unit_content_unreadable",
                    subject=unit_name,
                    detail="systemctl --user cat could not read installed unit text",
                )
            )
            continue

        for label, snippet in requirements:
            if snippet not in repo_text:
                findings.append(
                    Finding(
                        severity="critical",
                        kind="critical_unit_source_contract_missing",
                        subject=unit_name,
                        detail=f"canonical unit is missing required contract {label}",
                    )
                )
            elif snippet not in runtime_text:
                findings.append(
                    Finding(
                        severity="critical",
                        kind="critical_unit_content_drift",
                        subject=unit_name,
                        detail=f"installed unit is missing required contract {label}",
                    )
                )
    return findings


def classify_artifact_findings(cache_root: Path, now: datetime) -> list[Finding]:
    findings: list[Finding] = []
    for label, relative_path, ttl_seconds in CRITICAL_ARTIFACTS:
        path = cache_root / relative_path
        if not path.exists():
            findings.append(
                Finding(
                    severity="critical",
                    kind="artifact_missing",
                    subject=label,
                    detail=f"{path} is missing",
                )
            )
            continue
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        age_seconds = int((now - modified_at).total_seconds())
        if age_seconds > ttl_seconds:
            findings.append(
                Finding(
                    severity="critical",
                    kind="artifact_stale",
                    subject=label,
                    detail=f"{path} age {age_seconds}s exceeds ttl {ttl_seconds}s",
                )
            )
    return findings


def summarize(findings: list[Finding]) -> dict[str, int]:
    counts = {"critical": 0, "warning": 0, "info": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return counts


def render_text(payload: dict[str, object]) -> str:
    counts = payload["summary"]
    lines = [
        "runtime activation drift audit",
        f"generated_at: {payload['generated_at']}",
        f"summary: critical={counts['critical']} warning={counts['warning']} info={counts['info']}",
    ]
    for finding in payload["findings"]:
        lines.append(
            f"[{finding['severity']}] {finding['kind']} {finding['subject']}: {finding['detail']}"
        )
    return "\n".join(lines)


def build_payload(unit_dir: Path, cache_root: Path) -> dict[str, object]:
    now = datetime.now(UTC)
    specs = repo_unit_specs(unit_dir)
    runtime = collect_runtime_units()
    findings = classify_unit_findings(specs, runtime)
    findings.extend(classify_unit_content_findings(unit_dir, runtime))
    findings.extend(classify_artifact_findings(cache_root, now))
    findings = sorted(
        findings, key=lambda item: (item.severity != "critical", item.kind, item.subject)
    )
    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "unit_dir": str(unit_dir),
        "cache_root": str(cache_root),
        "summary": summarize(findings),
        "findings": [asdict(finding) for finding in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audit-runtime-activation-drift")
    parser.add_argument("--unit-dir", type=Path, default=DEFAULT_UNIT_DIR)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--fail-on",
        choices=("none", "critical", "warning"),
        default="critical",
        help="exit non-zero at or above this finding severity",
    )
    args = parser.parse_args(argv)

    payload = build_payload(args.unit_dir, args.cache_root)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_text(payload))

    counts = payload["summary"]
    if args.fail_on == "critical" and counts["critical"]:
        return 1
    if args.fail_on == "warning" and (counts["critical"] or counts["warning"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
