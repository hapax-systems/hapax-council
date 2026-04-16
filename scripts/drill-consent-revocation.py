#!/usr/bin/env python3
"""Mid-stream consent revocation drill (LRR Phase 6 §7).

Spec §7 success criterion: the full revocation cascade completes within
5 seconds, end-to-end. This drill stages a synthetic contract, runs
``ConsentRegistry.revoke_contract``, verifies the in-memory + filesystem
state, and asserts total wall-clock time.

Run from the repo root:

    uv run python scripts/drill-consent-revocation.py

Exit code 0 on PASS, 1 on FAIL. Emits a structured JSON report on stdout
so operators can pipe into logs or a dashboard.

By default the drill operates in a temp directory so the real
``axioms/contracts/`` tree is never touched. Pass ``--live`` to exercise
against the live tree (use only with operator confirmation — will move
a real contract's YAML into ``axioms/contracts/revoked/``).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.governance.consent import (  # noqa: E402
    ConsentRegistry,
)

DRILL_BUDGET_S = 5.0


def _write_synthetic_contract(directory: Path, contract_id: str = "drill-subject") -> None:
    (directory / f"{contract_id}.yaml").write_text(
        f"""\
id: {contract_id}
parties:
  - operator
  - drill-subject
scope:
  - drill-audio
direction: one_way
visibility_mechanism: on_request
created_at: "2026-04-16T00:00:00"
principal_class: adult
"""
    )


def run_drill(contracts_dir: Path) -> dict:
    """Execute the full drill cascade; return a structured report dict."""
    report: dict = {
        "budget_s": DRILL_BUDGET_S,
        "contracts_dir": str(contracts_dir),
        "stages": {},
        "pass": False,
    }

    t_start = time.monotonic()

    # Stage 1: stage synthetic contract + load
    t = time.monotonic()
    _write_synthetic_contract(contracts_dir, "drill-subject")
    registry = ConsentRegistry()
    loaded = registry.load(contracts_dir)
    report["stages"]["load"] = {
        "elapsed_s": round(time.monotonic() - t, 4),
        "loaded_count": loaded,
    }

    # Stage 2: assert contract is active + permits its scope
    t = time.monotonic()
    ok_pre = registry.contract_check("drill-subject", "drill-audio")
    report["stages"]["verify_active"] = {
        "elapsed_s": round(time.monotonic() - t, 4),
        "contract_check_pre": ok_pre,
    }
    if not ok_pre:
        report["failure_reason"] = "contract_check returned False before revocation"
        report["total_elapsed_s"] = round(time.monotonic() - t_start, 4)
        return report

    # Stage 3: revoke — this is the critical path the drill measures
    t = time.monotonic()
    try:
        revoke_elapsed = registry.revoke_contract("drill-subject", contracts_dir=contracts_dir)
    except KeyError as exc:
        report["failure_reason"] = f"revoke_contract raised KeyError: {exc}"
        report["total_elapsed_s"] = round(time.monotonic() - t_start, 4)
        return report
    report["stages"]["revoke"] = {
        "elapsed_s": round(time.monotonic() - t, 4),
        "in_process_s": round(revoke_elapsed, 4),
    }

    # Stage 4: in-memory contract_check MUST now return False
    t = time.monotonic()
    ok_post = registry.contract_check("drill-subject", "drill-audio")
    report["stages"]["verify_revoked_memory"] = {
        "elapsed_s": round(time.monotonic() - t, 4),
        "contract_check_post": ok_post,
    }
    if ok_post:
        report["failure_reason"] = "contract_check returned True after revocation (in-memory)"
        report["total_elapsed_s"] = round(time.monotonic() - t_start, 4)
        return report

    # Stage 5: filesystem — YAML moved to revoked/
    t = time.monotonic()
    src_exists = (contracts_dir / "drill-subject.yaml").exists()
    revoked_dir = contracts_dir / "revoked"
    moved = revoked_dir.exists() and any(
        p.name.endswith("drill-subject.yaml") for p in revoked_dir.iterdir()
    )
    report["stages"]["verify_fs_move"] = {
        "elapsed_s": round(time.monotonic() - t, 4),
        "src_still_exists": src_exists,
        "moved_to_revoked_dir": moved,
    }
    if src_exists or not moved:
        report["failure_reason"] = (
            f"filesystem state wrong — src_exists={src_exists}, moved={moved}"
        )
        report["total_elapsed_s"] = round(time.monotonic() - t_start, 4)
        return report

    # Stage 6: fresh registry load must agree that the contract is revoked
    t = time.monotonic()
    fresh = ConsentRegistry()
    fresh.load(contracts_dir)
    ok_fresh = fresh.contract_check("drill-subject", "drill-audio")
    report["stages"]["verify_fresh_load"] = {
        "elapsed_s": round(time.monotonic() - t, 4),
        "contract_check_fresh": ok_fresh,
    }
    if ok_fresh:
        report["failure_reason"] = (
            "fresh load still sees contract as active "
            "(revoked YAML is re-loaded; check load() filtering)"
        )
        report["total_elapsed_s"] = round(time.monotonic() - t_start, 4)
        return report

    total = time.monotonic() - t_start
    report["total_elapsed_s"] = round(total, 4)
    report["pass"] = total <= DRILL_BUDGET_S
    if not report["pass"]:
        report["failure_reason"] = f"total elapsed {total:.2f}s exceeds budget {DRILL_BUDGET_S}s"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="drill-consent-revocation",
        description="LRR Phase 6 §7 — mid-stream consent revocation drill.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Run against the real axioms/contracts/ tree (moves a real "
            "contract's YAML to axioms/contracts/revoked/). Default: "
            "isolated tmp dir."
        ),
    )
    parser.add_argument(
        "--live-contract-id",
        default=None,
        help="When --live, the contract ID to exercise (must be pre-existing).",
    )
    args = parser.parse_args(argv)

    if args.live:
        if not args.live_contract_id:
            print("--live requires --live-contract-id", file=sys.stderr)
            return 2
        print(
            "WARNING: --live mode will move a real contract YAML. "
            "Operator must have already verified this is intended.",
            file=sys.stderr,
        )
        contracts_dir = Path.home() / "projects" / "hapax-council" / "axioms" / "contracts"
        report = _run_live(contracts_dir, args.live_contract_id)
    else:
        with tempfile.TemporaryDirectory() as td:
            report = run_drill(Path(td))

    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


def _run_live(contracts_dir: Path, contract_id: str) -> dict:
    """Live-mode drill: exercise against a real pre-existing contract.

    Unlike the default tmp-dir mode, this does NOT stage a synthetic
    contract. The caller must confirm the contract_id actually exists
    in the live tree before running.
    """
    report: dict = {
        "budget_s": DRILL_BUDGET_S,
        "contracts_dir": str(contracts_dir),
        "mode": "live",
        "contract_id": contract_id,
        "stages": {},
        "pass": False,
    }

    # Make a backup so we can restore on failure
    backup_root = Path(tempfile.mkdtemp(prefix="drill-backup-"))
    live_yaml = contracts_dir / f"{contract_id}.yaml"
    if not live_yaml.exists():
        report["failure_reason"] = f"live contract YAML not found: {live_yaml}"
        return report
    shutil.copy2(live_yaml, backup_root / live_yaml.name)

    t_start = time.monotonic()
    try:
        registry = ConsentRegistry()
        registry.load(contracts_dir)
        revoke_elapsed = registry.revoke_contract(contract_id, contracts_dir=contracts_dir)
        report["stages"]["revoke"] = {"in_process_s": round(revoke_elapsed, 4)}
        total = time.monotonic() - t_start
        report["total_elapsed_s"] = round(total, 4)
        report["pass"] = total <= DRILL_BUDGET_S
    finally:
        # Always restore the live YAML so the drill is non-destructive
        # from the operator's perspective. The revoke/ move stays, but
        # the active file is put back so the contract remains in effect.
        shutil.copy2(backup_root / live_yaml.name, live_yaml)
        shutil.rmtree(backup_root, ignore_errors=True)

    return report


if __name__ == "__main__":
    raise SystemExit(main())
