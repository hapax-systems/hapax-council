#!/usr/bin/env python3
"""Run the M1 acceptance mutants in a disposable source overlay, never the live tree.

Usage: uv run --no-sync python scripts/check-quota-headroom-mutations.py
Every mutant must produce an assertion failure (pytest exit 1), not a collection
error, timeout, or syntax error. Full pytest output and the matrix stay in /tmp.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READER = "shared/quota_headroom.py"
MODEL = "shared/quota_spend_ledger.py"
WRITER = "scripts/hapax-quota-telemetry-writer"
TEST = "tests/shared/test_quota_headroom.py"

# Each replacement changes a behavior asserted by its named acceptance test.
MUTANTS = [
    (
        "fugu-missing-source",
        "test_capacity_without_source_is_explicit",
        READER,
        '"no_existing_local_usage_capture"',
        '"wrong_fugu_reason"',
    ),
    (
        "aperture-missing-source",
        "test_capacity_without_source_is_explicit",
        READER,
        '"no_reachable_local_resource_capture"',
        '"wrong_aperture_reason"',
    ),
    (
        "muse-provider-event",
        "test_muse_actual_journal_usage_source",
        READER,
        'model_event.get("kind") == "model_completed"',
        'model_event.get("kind") == "wrong_event"',
    ),
    (
        "vibe-derived-promoted",
        "test_vibe_actual_session_stats_source",
        READER,
        'window="completed_session",\n                                    label="derived",',
        'window="completed_session",\n                                    label="observed",',
    ),
    (
        "claude-harness-reset",
        "test_claude_harness_notice_source",
        READER,
        "reset=instant(reset_match[0]) if reset_match else None,",
        "reset=None,",
    ),
    (
        "registry-family-omitted",
        "test_every_registry_family_is_projected",
        READER,
        "for family in sorted(set(routes) | set(UNDECLARED_FAMILIES) | set(readings)):",
        'for family in sorted((set(routes) | set(UNDECLARED_FAMILIES) | set(readings)) - {"fixture_future"}):',
    ),
    (
        "latest-event",
        "test_codex_reader_uses_latest_token_count_not_mtime",
        READER,
        "latest is None or at >= latest[0]",
        "latest is None or at <= latest[0]",
    ),
    (
        "unix-reset",
        "test_codex_reader_maps_resets_at_unix_to_iso_z",
        READER,
        "datetime.fromtimestamp(value, UTC)",
        "datetime.fromtimestamp(value + 60, UTC)",
    ),
    (
        "credit-balance",
        "test_codex_reader_parses_credits_balance_decimal_string",
        READER,
        "quantity=balance,",
        "quantity=balance + 1,",
    ),
    (
        "missing-source",
        "test_codex_reader_missing_events_is_unobserved",
        READER,
        'reason="no_token_count_event"',
        'reason="wrong_missing_reason"',
    ),
    (
        "admission-is-fraction",
        "test_claude_admission_yaml_is_not_weekly_headroom",
        READER,
        '"claude": ("claude*quota-wall.yaml",)',
        '"claude": ("claude*quota-wall.yaml", "claude*quota-admission*.yaml")',
    ),
    (
        "discard-wall-reset",
        "test_claude_wall_yaml_records_resets_at_without_implying_available",
        READER,
        'reset=instant(data.get("resets_at")),\n                    source=source_ref(path, "quota_wall_receipt"),',
        'reset=None,\n                    source=source_ref(path, "quota_wall_receipt"),',
    ),
    (
        "kimi-wall-label",
        "test_kimi_403_is_wall_signal_not_fraction",
        READER,
        "files_with_hit += bool(file_hits)",
        "files_with_hit += 0",
    ),
    (
        "kimi-global-mixed",
        "test_kimi_global_log_counted_separately",
        READER,
        "global_hits = file_hits",
        "hits += file_hits",
    ),
    (
        "missing-family",
        "test_ledger_always_has_codex_claude_kimi_rows",
        READER,
        "for family in sorted(set(routes) | set(UNDECLARED_FAMILIES) | set(readings)):",
        'for family in sorted((set(routes) | set(UNDECLARED_FAMILIES) | set(readings)) - {"kimi"}):',
    ),
    (
        "freeze-threshold",
        "test_freeze_active_when_codex_used_percent_100_and_before_reset",
        READER,
        "row.quantity >= 100",
        "row.quantity > 100",
    ),
    (
        "freeze-expiry",
        "test_freeze_inactive_after_resets_at",
        READER,
        "row.observed_at <= now < row.resets_at",
        "row.observed_at <= now",
    ),
    (
        "non-atomic-write",
        "test_write_is_atomic",
        WRITER,
        "        os.replace(tmp_name, path)",
        "        path.write_text(payload)\n        os.replace(tmp_name, path)",
    ),
    (
        "check-writes",
        "test_check_does_not_write",
        WRITER,
        "        print(json.dumps(payload, indent=2))",
        "        write_ledger_atomic(checked, live_path)\n        print(json.dumps(payload, indent=2))",
    ),
    (
        "stale-fresh",
        "test_stale_event_never_reported_fresh",
        MODEL,
        "self.observed_at <= now < self.measurement_fresh_until",
        "self.observed_at <= now",
    ),
    (
        "derived-promoted",
        "test_derived_is_never_promoted_to_observed",
        READER,
        'unit="tokens",\n                label="derived",',
        'unit="tokens",\n                label="observed",',
    ),
    (
        "unknown-reset-invented",
        "test_wall_without_reset_is_not_headroom",
        READER,
        '"kimi.subscription.wall",\n                at=max(timestamps),',
        '"kimi.subscription.wall",\n                at=max(timestamps), reset=max(timestamps) + timedelta(days=7),',
    ),
    (
        "unattributed-activity-ignored",
        "test_unattributed_consumption_detector",
        READER,
        "and activity == 0",
        "and activity >= 0",
    ),
    (
        "receipt-source-label",
        "test_receipt_family_source",
        READER,
        'reason="admission_witness_has_no_quantity"',
        'reason="incorrect_admission_basis"',
    ),
    (
        "family-source-number",
        "test_other_family_source",
        READER,
        'f"{family}.subscription.usage",\n                            at=at,\n                            quantity=used,',
        'f"{family}.subscription.usage",\n                            at=at,\n                            quantity=used + 1,',
    ),
    (
        "vibe-api-binding",
        "test_vibe_api_binding_and_undeclared_routes",
        READER,
        'primary.details.get("plan_type") == "api"',
        'primary.details.get("plan_type") == "team"',
    ),
    (
        "operator-provenance",
        "test_operator_report_preserves_ambiguous_reset_and_append",
        READER,
        'label="operator-reported",',
        'label="wall-signal",',
    ),
    (
        "legacy-schema",
        "test_schema_v1_migration_and_old_reader_projection",
        MODEL,
        'payload["schema_version"] = 1',
        'payload["schema_version"] = 2',
    ),
    (
        "corrupt-secret-leak",
        "test_corrupt_existing_source_fails_without_leaking_contents",
        READER,
        "raise TraceReadError(f\"corrupt_or_unreadable_source:{source_ref(path, 'jsonl')}\") from exc",
        'raise TraceReadError(f"corrupt_or_unreadable_source:{line!r}") from exc',
    ),
]


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="quota-headroom-mutations-"))
    # Symlink untouched dependencies, copy only the three mutated files and test.
    copies = {READER, MODEL, WRITER, TEST}
    directories = {"shared", "scripts", "tests", "tests/shared"}

    def overlay(relative: Path) -> None:
        for source in (ROOT / relative).iterdir():
            name = relative / source.name
            if source.name in {".git", "__pycache__", ".pytest_cache"}:
                continue
            target = work / name
            if str(name) in directories:
                target.mkdir()
                overlay(name)
            elif str(name) in copies:
                shutil.copyfile(source, target)
            else:
                target.symlink_to(source)

    overlay(Path())
    results = []
    for name, test, relative, old, new in MUTANTS:
        path = work / relative
        original = (ROOT / relative).read_text()
        if original.count(old) != 1 or old == new:
            raise ValueError(f"mutant anchor is not unique or does not change code: {name}")
        path.write_text(original.replace(old, new, 1))
        for cache in (work / "shared/__pycache__", work / "tests/shared/__pycache__"):
            if cache.exists():
                shutil.rmtree(cache)
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", f"{TEST}::{test}", "-q"],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=90,
            )
            output = completed.stdout + completed.stderr
            (work / f"{name}.log").write_text(output)
            killed = completed.returncode == 1 and "AssertionError" in output
            results.append(
                {"mutant": name, "test": test, "killed": killed, "exit_code": completed.returncode}
            )
            print(json.dumps(results[-1]), flush=True)
        finally:
            path.write_text(original)
    (work / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"Evidence: {work / 'results.json'}", flush=True)
    return 0 if all(row["killed"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
