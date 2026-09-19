#!/usr/bin/env python3
"""Report missing X-Hapax-Store metadata on newly added systemd services.

Stage 1 is intentionally advisory: findings are printed and the checker exits
zero. Discovery failures exit nonzero because silently widening the diff would
turn an unknown base into a false clean report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path[:] = [str(REPO_ROOT), *(entry for entry in sys.path if entry != str(REPO_ROOT))]

import shared

SHARED_FILE = getattr(shared, "__file__", None)
if not SHARED_FILE or not Path(SHARED_FILE).resolve().is_relative_to(REPO_ROOT):
    print(
        f"check-estate-store-declarations: shared import outside physical source root "
        f"{REPO_ROOT}: {SHARED_FILE or 'absent'}; remedy: repair the release's shared package "
        "and restart its interpreter with the verified physical script, "
        "without a preloaded foreign shared package",
        file=sys.stderr,
    )
    raise SystemExit(2)
VERIFIED_SHARED_ROOT = str(REPO_ROOT)

from shared.estate_store_registry import DEFAULT_REGISTRY_PATH, RegistryError, load_registry

METADATA = "X-Hapax-Store"


class CheckError(RuntimeError):
    """The requested comparison cannot be performed exactly."""


@dataclass(frozen=True)
class Finding:
    unit: str
    kind: str
    detail: str


def new_service_paths(repo_root: Path, base_ref: str) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "diff",
            "--name-only",
            "--diff-filter=A",
            f"{base_ref}...HEAD",
            "--",
            "systemd/units/*.service",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise CheckError(
            f"cannot resolve exact new-unit set from {base_ref!r}: {result.stderr.strip()}; "
            "remedy: fetch the base ref or pass explicit --unit paths"
        )
    return [repo_root / line for line in result.stdout.splitlines() if line.strip()]


def metadata_values(text: str) -> list[str]:
    values: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(f"{METADATA}="):
            values.append(line.split("=", 1)[1].strip())
    return values


def check_services(paths: list[Path], registered_ids: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CheckError(f"cannot read new unit {path}: {exc}") from exc
        if not any(line.strip().startswith("ExecStart=") for line in text.splitlines()):
            continue
        values = metadata_values(text)
        if not values:
            findings.append(
                Finding(
                    str(path),
                    "missing-store-declaration",
                    f"add {METADATA}=<registered-store-id> or {METADATA}=None",
                )
            )
            continue
        for value in values:
            if not value:
                findings.append(
                    Finding(
                        str(path),
                        "empty-store-declaration",
                        f"replace empty {METADATA} with a registered store id or None",
                    )
                )
            elif value != "None" and value not in registered_ids:
                findings.append(
                    Finding(
                        str(path),
                        "unregistered-store-id",
                        f"{value!r} is not in the estate store registry",
                    )
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--base-ref")
    parser.add_argument("--unit", type=Path, action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.unit and args.base_ref:
            raise CheckError("choose --base-ref or explicit --unit paths, not both")
        if not args.unit and not args.base_ref:
            raise CheckError(
                "an exact comparison is required; remedy: pass --base-ref <ref> or explicit --unit paths"
            )
        registry = load_registry(args.registry)
        paths = args.unit or new_service_paths(args.repo_root, args.base_ref)
        findings = check_services(paths, {store.id for store in registry.stores})
    except (CheckError, RegistryError) as exc:
        print(f"check-estate-store-declarations: {exc}", file=sys.stderr)
        return 2
    payload = {
        "schema": "hapax.estate-store-declaration-report/v1",
        "stage": "report-only",
        "source": {"physical_root": str(REPO_ROOT), "verified_shared_root": VERIFIED_SHARED_ROOT},
        "checked_units": len(paths),
        "finding_count": len(findings),
        "findings": [asdict(finding) for finding in findings],
        "blocking": False,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"estate store declarations: {len(findings)} finding(s) across {len(paths)} new service(s); report-only"
        )
        for finding in findings:
            print(f"  {finding.kind}: {finding.unit}: {finding.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
