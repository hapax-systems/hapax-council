#!/usr/bin/env python3
"""LRR Phase 5 pre-swap verification — walks the prerequisite table from
the Phase 5 per-phase spec §2 and exits non-zero on any unmet prereq.

Intended to be run interactively at Phase 5 open time, before the
operator triggers the actual substrate change. The script is read-only
against all system state — it never mutates services, registry
files, or config.

AMENDMENT 2026-04-15 (drop #62 Option C): this script was drafted against
the 70B substrate swap assumption (now Phase 5b, deferred behind a
hardware envelope gate). At Phase 5a execution time (Hermes 3 8B parallel
pivot), alpha either parameterizes this script with a --variant 5a flag or
clones it to phase-5a-pre-swap-check.py with:

  - quant path check rewritten from
      ~/projects/tabbyAPI/models/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw/
    to
      ~/projects/tabbyAPI/models/Hermes-3-Llama-3.1-8B-EXL3-5.0bpw/
  - prereq #4 ("3.5bpw fallback present") deleted (5a has no fallback tier;
    rollback is the dispatch flip)
  - prereq #3 (daimonion GPU 0 pin) retained but non-blocking (5a does not
    evict daimonion)
  - new prereq: second TabbyAPI slot/instance config staged

See the Phase 5 spec §0.5 (drop #62 Option C resolution) and
DEVIATION-037 amendment for the full rewrite scope.

Prereqs checked:

  1. Phase 4 complete — Condition A data integrity lock produced
     data-checksums.txt + qdrant-snapshot.tgz + langfuse-scores.jsonl
     under the condition directory
  2. Phase 3 runtime partition Option γ active on tabbyapi
     (CUDA_DEVICE_ORDER=PCI_BUS_ID, CUDA_VISIBLE_DEVICES=0,1)
  3. Phase 3 runtime partition Option γ active on hapax-daimonion
     (CUDA_VISIBLE_DEVICES=0)
  4. Hermes 3 70B EXL3 3.0bpw quant present at expected path
     (~/projects/tabbyAPI/models/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw/
     model-00001-of-*.safetensors ... model-00004-of-*.safetensors)
  5. TabbyAPI config.yml.hermes-draft present in the tabbyAPI clone
     (~/projects/tabbyAPI/config.yml.hermes-draft)
  6. DEVIATION-037 draft committed to research/protocols/deviations/
  7. RESEARCH-STATE.md last commit clean (no unstaged changes under
     agents/hapax_daimonion/proofs/)
  8. Research registry condition.yaml shows collection_halt_at set
     on the current Condition A (Phase 4 has locked the condition)

Exit codes::

    0  all prereqs met — safe to proceed with Phase 5 swap
    1  argparse / environment error
    2  Phase 4 data integrity lock not complete (required)
    3  Phase 3 runtime partition not active (required)
    4  Hermes 3 quant not present (required)
    5  TabbyAPI config.yml.hermes-draft not staged (required)
    6  DEVIATION-037 draft not present (required)
    7  RESEARCH-STATE.md has unstaged changes
    8  Condition A not locked (collection_halt_at missing)

Usage::

    scripts/phase-5-pre-swap-check.py
    scripts/phase-5-pre-swap-check.py --expected-condition <id>
    scripts/phase-5-pre-swap-check.py --json
    scripts/phase-5-pre-swap-check.py --tabbyapi-dir ~/projects/tabbyAPI
    scripts/phase-5-pre-swap-check.py --repo-root ~/projects/hapax-council--beta

The script does NOT check the optional 3.5 bpw fallback quant — if
that's missing, Phase 5 can still open with 3.0 bpw only and rollback
falls back to full Qwen rollback rather than 3.5 bpw fallback. The
operator accepts this trade at phase open.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_EXPECTED_CONDITION = "cond-phase-a-baseline-qwen-001"
DEFAULT_STATE_DIR = Path.home() / "hapax-state"
DEFAULT_REGISTRY_DIR = DEFAULT_STATE_DIR / "research-registry"
DEFAULT_TABBYAPI_DIR = Path.home() / "projects" / "tabbyAPI"
DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HERMES_QUANT_DIR_NAME = "Hermes-3-Llama-3.1-70B-EXL3-3.0bpw"


@dataclass
class CheckResult:
    ok: bool = True
    exit_code: int = 0
    reason: str = ""
    checks: dict[str, Any] = field(default_factory=dict)


def check_phase_4_data_lock(condition_id: str, registry_dir: Path) -> tuple[bool, str]:
    """Prereq 1 — Phase 4 data integrity lock produced the 3 required artifacts."""
    cond_dir = registry_dir / condition_id
    if not cond_dir.exists():
        return False, f"condition directory missing: {cond_dir}"
    checksums = cond_dir / "data-checksums.txt"
    qdrant_snap = cond_dir / "qdrant-snapshot.tgz"
    langfuse_export = cond_dir / "langfuse-scores.jsonl"
    missing: list[str] = []
    for f in (checksums, qdrant_snap, langfuse_export):
        if not f.exists():
            missing.append(str(f))
    if missing:
        return (
            False,
            f"Phase 4 lock artifacts missing: {', '.join(missing)}",
        )
    return (
        True,
        f"Phase 4 lock complete ({checksums.name} + {qdrant_snap.name} + {langfuse_export.name})",
    )


def check_systemctl_environment(service: str, expected_vars: dict[str, str]) -> tuple[bool, str]:
    """Prereqs 2 + 3 — systemd service has the expected environment vars."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", service, "-p", "Environment"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"systemctl invocation failed: {exc}"
    if result.returncode != 0:
        return False, f"systemctl exit {result.returncode}: {result.stderr.strip()[:200]}"
    # Expected output: "Environment=FOO=bar BAZ=qux ..."
    env_line = result.stdout.strip()
    if not env_line.startswith("Environment="):
        return False, f"unexpected systemctl output: {env_line[:120]}"
    env_str = env_line[len("Environment=") :]
    # systemd can return whitespace-separated KEY=VALUE pairs
    env_pairs = dict(tuple(pair.split("=", 1)) for pair in env_str.split() if "=" in pair)
    missing: list[str] = []
    wrong: list[str] = []
    for key, expected in expected_vars.items():
        actual = env_pairs.get(key)
        if actual is None:
            missing.append(f"{key}=<missing>")
        elif actual != expected:
            wrong.append(f"{key}={actual} (expected {expected})")
    if missing or wrong:
        issues = ", ".join(missing + wrong)
        return False, f"{service} env mismatch: {issues}"
    return True, f"{service} env OK"


def check_hermes_quant_present(tabbyapi_dir: Path, quant_dir_name: str) -> tuple[bool, str]:
    """Prereq 4 — Hermes 3 EXL3 quant exists with the expected shards."""
    quant_dir = tabbyapi_dir / "models" / quant_dir_name
    if not quant_dir.exists():
        return False, f"quant directory missing: {quant_dir}"
    shards = sorted(quant_dir.glob("model-*-of-*.safetensors"))
    if not shards:
        return False, f"no safetensors shards in {quant_dir}"
    # Also verify config.json exists (quick sanity check that the quant is complete)
    config = quant_dir / "config.json"
    if not config.exists():
        return False, f"config.json missing in {quant_dir} — quant may be incomplete"
    return True, f"quant present ({len(shards)} shards + config.json)"


def check_hermes_config_staged(tabbyapi_dir: Path) -> tuple[bool, str]:
    """Prereq 5 — TabbyAPI config.yml.hermes-draft is staged."""
    config_draft = tabbyapi_dir / "config.yml.hermes-draft"
    if not config_draft.exists():
        return False, f"staged config missing: {config_draft}"
    return True, f"config staged at {config_draft}"


def check_deviation_037_draft(repo_root: Path) -> tuple[bool, str]:
    """Prereq 6 — DEVIATION-037 draft committed to deviations dir."""
    dev_path = repo_root / "research" / "protocols" / "deviations" / "DEVIATION-037.md"
    if not dev_path.exists():
        return False, f"DEVIATION-037 missing: {dev_path}"
    return True, f"DEVIATION-037 present at {dev_path.name}"


def check_research_state_clean(repo_root: Path) -> tuple[bool, str]:
    """Prereq 7 — RESEARCH-STATE.md (and the rest of proofs/) has no unstaged changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "agents/hapax_daimonion/proofs/"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"git status failed: {exc}"
    if result.returncode != 0:
        return False, f"git status exit {result.returncode}: {result.stderr.strip()[:200]}"
    if result.stdout.strip():
        lines = result.stdout.strip().split("\n")
        return False, f"proofs/ has unstaged changes ({len(lines)} files)"
    return True, "proofs/ clean"


def check_condition_locked(condition_id: str, registry_dir: Path) -> tuple[bool, str]:
    """Prereq 8 — condition.yaml shows collection_halt_at set (Phase 4 completion marker)."""
    cond_yaml = registry_dir / condition_id / "condition.yaml"
    if not cond_yaml.exists():
        return False, f"condition.yaml missing: {cond_yaml}"
    # Cheap substring check first — avoids importing yaml for a file sanity check
    try:
        body = cond_yaml.read_text()
    except OSError as exc:
        return False, f"condition.yaml read failed: {exc}"
    if "collection_halt_at:" not in body:
        return False, "condition.yaml missing collection_halt_at field entirely"
    # Check the field is not null / empty
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("collection_halt_at:"):
            value = stripped[len("collection_halt_at:") :].strip()
            # YAML-ish: null | ~ | '' | "" means unset
            if value in ("", "null", "~", "''", '""'):
                return False, "collection_halt_at is set but empty/null — Phase 4 not complete"
            return True, f"collection_halt_at = {value}"
    return False, "collection_halt_at parse failed"


def run_checks(args: argparse.Namespace) -> CheckResult:
    result = CheckResult()

    # Check 1 — Phase 4 data lock
    ok, msg = check_phase_4_data_lock(args.expected_condition, Path(args.registry_dir))
    result.checks["phase_4_data_lock"] = {"ok": ok, "message": msg}
    if not ok:
        result.ok = False
        result.exit_code = 2
        result.reason = msg
        return result

    # Check 2 — tabbyapi Option γ
    if not args.skip_systemctl:
        ok, msg = check_systemctl_environment(
            "tabbyapi",
            {
                "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
                "CUDA_VISIBLE_DEVICES": "0,1",
            },
        )
        result.checks["tabbyapi_partition"] = {"ok": ok, "message": msg}
        if not ok:
            result.ok = False
            result.exit_code = 3
            result.reason = msg
            return result

        # Check 3 — hapax-daimonion Option γ
        ok, msg = check_systemctl_environment(
            "hapax-daimonion",
            {
                "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
                "CUDA_VISIBLE_DEVICES": "0",
            },
        )
        result.checks["daimonion_partition"] = {"ok": ok, "message": msg}
        if not ok:
            result.ok = False
            result.exit_code = 3
            result.reason = msg
            return result

    # Check 4 — Hermes 3 quant present
    ok, msg = check_hermes_quant_present(Path(args.tabbyapi_dir), args.quant_dir_name)
    result.checks["hermes_quant"] = {"ok": ok, "message": msg}
    if not ok:
        result.ok = False
        result.exit_code = 4
        result.reason = msg
        return result

    # Check 5 — Hermes config staged
    ok, msg = check_hermes_config_staged(Path(args.tabbyapi_dir))
    result.checks["hermes_config"] = {"ok": ok, "message": msg}
    if not ok:
        result.ok = False
        result.exit_code = 5
        result.reason = msg
        return result

    # Check 6 — DEVIATION-037 draft
    ok, msg = check_deviation_037_draft(Path(args.repo_root))
    result.checks["deviation_037"] = {"ok": ok, "message": msg}
    if not ok:
        result.ok = False
        result.exit_code = 6
        result.reason = msg
        return result

    # Check 7 — RESEARCH-STATE clean
    ok, msg = check_research_state_clean(Path(args.repo_root))
    result.checks["research_state_clean"] = {"ok": ok, "message": msg}
    if not ok:
        result.ok = False
        result.exit_code = 7
        result.reason = msg
        return result

    # Check 8 — Condition A locked
    ok, msg = check_condition_locked(args.expected_condition, Path(args.registry_dir))
    result.checks["condition_locked"] = {"ok": ok, "message": msg}
    if not ok:
        result.ok = False
        result.exit_code = 8
        result.reason = msg
        return result

    result.reason = "all Phase 5 prereqs met — safe to proceed with swap"
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="phase-5-pre-swap-check.py",
        description="LRR Phase 5 pre-swap prerequisite verification",
    )
    p.add_argument(
        "--expected-condition",
        default=DEFAULT_EXPECTED_CONDITION,
        help=f"Expected Condition A condition_id (default: {DEFAULT_EXPECTED_CONDITION})",
    )
    p.add_argument(
        "--registry-dir",
        default=str(DEFAULT_REGISTRY_DIR),
        help=f"Research registry directory (default: {DEFAULT_REGISTRY_DIR})",
    )
    p.add_argument(
        "--tabbyapi-dir",
        default=str(DEFAULT_TABBYAPI_DIR),
        help=f"TabbyAPI clone root (default: {DEFAULT_TABBYAPI_DIR})",
    )
    p.add_argument(
        "--quant-dir-name",
        default=DEFAULT_HERMES_QUANT_DIR_NAME,
        help=f"Hermes 3 quant directory name (default: {DEFAULT_HERMES_QUANT_DIR_NAME})",
    )
    p.add_argument(
        "--repo-root",
        default=str(DEFAULT_REPO_ROOT),
        help="hapax-council repo root (default: auto-detected)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit JSON report instead of human-readable output",
    )
    p.add_argument(
        "--skip-systemctl",
        action="store_true",
        help="Skip systemctl checks (useful for CI / testing)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_checks(args)

    if args.as_json:
        print(json.dumps(asdict(result), indent=2))
    else:
        status = "OK" if result.ok else "FAIL"
        print(f"phase-5-pre-swap-check: {status} — {result.reason}")
        for name, check in result.checks.items():
            mark = "✓" if check.get("ok") else "✗"
            print(f"  {mark} {name}: {check.get('message', '')}")

    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
