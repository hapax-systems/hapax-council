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
OBSERVER = "scripts/hapax-claude-account-live-observe"
ADMISSION = "scripts/hapax-claude-subscription-quota-admission"
TEST = "tests/shared/test_quota_headroom.py"
# A test named without a path runs from TEST; these name their own file.
PROBE_TEST = "tests/scripts/test_hapax_claude_account_live_observe.py"
WRITER_TEST = "tests/scripts/test_hapax_quota_telemetry_writer.py"


def at(test_file: str, test: str) -> str:
    return f"{test_file}::{test}"


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
    # --- Claude subscription windows: parsing the provider's reading
    (
        "claude-unified-ignored",
        "test_claude_unified_windows_are_observed_fractions",
        READER,
        "    if isinstance(unified, dict):\n",
        "    if isinstance(unified, list):\n",
    ),
    (
        "claude-legacy-ignored",
        "test_claude_legacy_single_window_event_is_read",
        READER,
        'candidates[info["rateLimitType"]] = info',
        "pass",
    ),
    (
        "claude-percent-scale",
        "test_claude_unified_windows_are_observed_fractions",
        READER,
        "round(utilization * 100, 6)",
        "round(utilization, 6)",
    ),
    (
        "claude-absent-as-zero",
        "test_claude_window_without_a_numeric_reading_is_absent_never_zero",
        READER,
        'utilization = window.get("utilization") if',
        'utilization = window.get("utilization", 0) if',
    ),
    (
        "claude-bool-utilization",
        "test_claude_window_without_a_numeric_reading_is_absent_never_zero",
        READER,
        "            isinstance(utilization, bool)\n            or not",
        "            not",
    ),
    (
        "claude-negative-utilization",
        "test_claude_window_without_a_numeric_reading_is_absent_never_zero",
        READER,
        "or utilization < 0",
        "or utilization < -1",
    ),
    (
        "claude-closed-window-kept",
        "test_claude_receipt_fraction_requires_a_probe_backed_subscription_receipt",
        READER,
        "        if at < reset\n",
        "        if at < reset + timedelta(days=2)\n",
    ),
    # --- Claude stream events: dating and subscription binding
    (
        "claude-mtime-dated",
        "test_claude_stream_event_is_never_dated_by_file_mtime",
        READER,
        "        subscription_sessions = set()\n        dated = None\n",
        "        subscription_sessions = set()\n"
        "        dated = datetime.fromtimestamp(path.stat().st_mtime, UTC)\n",
    ),
    (
        "claude-future-reading",
        "test_claude_reading_dated_after_now_is_ignored",
        READER,
        "or dated > now",
        "or dated > now + timedelta(days=1)",
    ),
    (
        "claude-horizon-ignored",
        "test_claude_stream_older_than_any_open_window_is_not_read",
        READER,
        ">= now - CLAUDE_WINDOW_HORIZON",
        ">= now - CLAUDE_WINDOW_HORIZON * 100",
    ),
    (
        "claude-session-unbound",
        "test_claude_stream_outside_a_subscription_session_is_not_the_subscription",
        READER,
        "or session not in subscription_sessions",
        "or False",
    ),
    (
        "claude-api-key-session",
        "test_claude_stream_outside_a_subscription_session_is_not_the_subscription",
        READER,
        'record.get("apiKeySource") == "none"',
        'record.get("apiKeySource") != "absent"',
    ),
    (
        "claude-any-model-session",
        "test_claude_stream_outside_a_subscription_session_is_not_the_subscription",
        READER,
        'CLAUDE_MODEL.fullmatch(str(record.get("model")))',
        'str(record.get("model"))',
    ),
    (
        "claude-oldest-wins",
        "test_claude_newest_reading_wins_across_streams_and_probe_receipts",
        READER,
        "row.observed_at > newest[key].observed_at",
        "row.observed_at < newest[key].observed_at",
    ),
    (
        "claude-collect-unwired",
        "test_collect_reads_claude_headless_streams_into_the_ledger",
        READER,
        'stream_root=home / ".cache/hapax/claude-headless",',
        "stream_root=None,",
    ),
    # --- Claude probe receipts
    (
        "claude-receipt-unread",
        "test_claude_probe_receipt_is_read",
        READER,
        'b"_used_percent" not in path.read_bytes()',
        'b"_never_written" not in path.read_bytes()',
    ),
    (
        "claude-operator-numbers",
        "test_claude_receipt_fraction_requires_a_probe_backed_subscription_receipt",
        READER,
        'or data.get("observation") != "subscription_quota_headroom_observed"',
        "or False",
    ),
    (
        "claude-unscrubbed-numbers",
        "test_claude_receipt_fraction_requires_a_probe_backed_subscription_receipt",
        READER,
        'or not data.get("probe_environment_scrubbed")',
        "or False",
    ),
    # --- walls and their supersession
    (
        "claude-rejected-not-wall",
        "test_claude_rejected_window_is_a_wall_with_its_reset",
        READER,
        'if isinstance(info, dict) and info.get("status") == "rejected":',
        'if isinstance(info, dict) and info.get("status") == "rejected_never":',
    ),
    (
        "claude-overage-is-wall",
        "test_claude_overage_refusal_alone_is_not_a_wall",
        READER,
        'if isinstance(info, dict) and info.get("status") == "rejected":',
        'if isinstance(info, dict) and "rejected" in (info.get("status"), info.get("overageStatus")):',
    ),
    (
        "derived-supersedes-wall",
        "test_transcript_spend_never_supersedes_a_wall",
        READER,
        '        row.label == "observed"\n        and row.capacity_id',
        '        row.label in {"observed", "derived"}\n        and row.capacity_id',
    ),
    (
        "wall-never-superseded",
        "test_wall_stands_until_a_newer_provider_observation",
        READER,
        "    return not any(\n        row.label",
        "    return True or not any(\n        row.label",
    ),
    (
        "older-reading-supersedes",
        "test_wall_stands_until_a_newer_provider_observation",
        READER,
        "and wall.observed_at < row.observed_at <= now",
        "and row.observed_at <= now",
    ),
    (
        "wall-window-ignored",
        "test_window_scoped_wall_needs_a_reading_of_the_same_window",
        READER,
        "and (wall.window is None or row.window == wall.window)",
        "and True",
    ),
    (
        "freeze-ignores-supersession",
        "test_wall_stands_until_a_newer_provider_observation",
        READER,
        '(row.label == "wall-signal" and wall_is_live(row, rows, now=now))',
        '(row.label == "wall-signal")',
    ),
    (
        "stage-ignores-supersession",
        "test_wall_stands_until_a_newer_provider_observation",
        READER,
        "if any(wall_is_live(r, measures, now=now) for r in measures):",
        'if any(r.label == "wall-signal" and (r.resets_at is None or now < r.resets_at) '
        "for r in measures):",
    ),
    (
        "kimi-response-ignored",
        "test_kimi_response_after_the_wall_is_a_post_wall_observation",
        READER,
        "if served_at and int(served[2]) > 0:",
        "if served_at and int(served[2]) > 10**9:",
    ),
    (
        "kimi-zero-token-serve",
        "test_kimi_wall_stands_without_a_later_serve",
        READER,
        "if served_at and int(served[2]) > 0:",
        "if served_at and int(served[2]) >= 0:",
    ),
    (
        "kimi-unanchored-response",
        "test_kimi_wall_stands_without_a_later_serve",
        READER,
        "KIMI_RESPONSE.match(line)",
        "KIMI_RESPONSE.search(line)",
    ),
    # --- burn per hour (H1 #3)
    (
        "burn-claude-unwired",
        "test_burn_is_derived_from_two_readings_of_the_same_window",
        READER,
        "    rows.extend(burn_rows(readings))\n",
        "",
    ),
    (
        "burn-promoted",
        "test_burn_is_derived_from_two_readings_of_the_same_window",
        READER,
        'label="derived",\n                source=newest.source,',
        'label="observed",\n                source=newest.source,',
    ),
    (
        "burn-across-reset",
        "test_no_burn_without_a_valid_pair",
        READER,
        "            if row.resets_at == newest.resets_at\n",
        "            if True\n",
    ),
    (
        "burn-short-span",
        "test_no_burn_without_a_valid_pair",
        READER,
        "and row.observed_at <= newest.observed_at - BURN_MIN_SPAN",
        "and row.observed_at < newest.observed_at",
    ),
    (
        "burn-falling",
        "test_no_burn_without_a_valid_pair",
        READER,
        "if newest.quantity < oldest.quantity:",
        "if False:",
    ),
    (
        "burn-no-max-span",
        "test_burn_pairs_the_oldest_reading_inside_the_span",
        READER,
        "and newest.observed_at - BURN_MAX_SPAN <= row.observed_at\n",
        "and True\n",
    ),
    (
        "burn-freezes",
        "test_burn_never_freezes_or_supersedes",
        READER,
        'or (row.label == "observed" and row.unit == "percent_used" and row.quantity >= 100)',
        'or (row.unit.startswith("percent_used") and row.quantity >= 100)',
    ),
    (
        "burn-codex-unwired",
        "test_codex_burn_from_two_token_counts_in_one_window",
        READER,
        "in_window = [row for row in window_samples if row[2:] == (newest_reset, minutes)]",
        "in_window = []",
    ),
    # --- the account-live probe keeps the windows
    (
        "probe-json-reply",
        at(PROBE_TEST, "test_probe_asks_for_the_stream_that_carries_the_windows"),
        OBSERVER,
        '    "stream-json",\n    "--verbose",\n',
        '    "json",\n',
    ),
    (
        "probe-drops-windows",
        at(PROBE_TEST, "test_probe_keeps_the_windows_it_sees"),
        OBSERVER,
        "windows.update(claude_rate_limit_windows(info))",
        "pass",
    ),
    (
        "probe-rejected-served",
        at(PROBE_TEST, "test_probe_rejected_window_is_a_wall_even_when_the_result_was_served"),
        OBSERVER,
        'if any(info.get("status") == "rejected" for info in rate_limits):',
        "if False:",
    ),
    (
        "probe-overage-wall",
        at(PROBE_TEST, "test_probe_overage_refusal_alone_is_not_a_wall"),
        OBSERVER,
        'if any(info.get("status") == "rejected" for info in rate_limits):',
        'if any("rejected" in (info.get("status"), info.get("overageStatus")) '
        "for info in rate_limits):",
    ),
    (
        "probe-stream-text-scan",
        at(PROBE_TEST, "test_probe_stream_without_a_result_is_not_a_serve"),
        OBSERVER,
        "combined = f\"{unparsed} {proc.stderr or ''}\"",
        "combined = f\"{blob} {proc.stderr or ''}\"",
    ),
    (
        "probe-text-refusal-lost",
        at(PROBE_TEST, "test_probe_refusal_printed_outside_the_stream_is_still_a_wall"),
        OBSERVER,
        "combined = f\"{unparsed} {proc.stderr or ''}\"",
        'combined = ""',
    ),
    (
        "mint-drops-windows",
        at(PROBE_TEST, "test_probe_windows_reach_the_ledger_reader"),
        OBSERVER,
        "in sorted(route_evidence.windows.items()):",
        "in sorted({}.items()):",
    ),
    # --- read the quantity before probing for it (H1 #15)
    (
        "fresh-quantity-probed",
        at(PROBE_TEST, "test_a_fresh_quantity_is_not_probed_again"),
        OBSERVER,
        "reading_at is None or (now - reading_at).total_seconds() > args.quantity_max_age_seconds",
        "True",
    ),
    (
        "stale-quantity-unprobed",
        at(PROBE_TEST, "test_a_stale_or_missing_quantity_is_probed_and_the_receipt_keeps_it"),
        OBSERVER,
        'and (routes_missing_passive_evidence or quantity["stale"])',
        "and routes_missing_passive_evidence",
    ),
    (
        "read-error-probes",
        at(PROBE_TEST, "test_an_unreadable_quantity_source_never_triggers_a_probe"),
        OBSERVER,
        'quantity["stale"] = "read_error" not in quantity and (',
        'quantity["stale"] = (',
    ),
    (
        "probe-numbers-unminted",
        at(PROBE_TEST, "test_a_stale_or_missing_quantity_is_probed_and_the_receipt_keeps_it"),
        OBSERVER,
        "targets = route_ids if probed.windows else tuple(routes_missing_passive_evidence)",
        "targets = tuple(routes_missing_passive_evidence)",
    ),
    (
        "walled-quantity-probe",
        at(PROBE_TEST, "test_a_walled_account_is_not_probed_for_its_quantity"),
        OBSERVER,
        '        verdict != "walled"\n        and (routes_missing',
        "        True\n        and (routes_missing",
    ),
    # --- the admission writer keeps only a window it can vouch for
    (
        "writer-drops-windows",
        at(PROBE_TEST, "test_writer_records_probe_windows"),
        ADMISSION,
        "            *windows,\n",
        "",
    ),
    (
        "writer-unscrubbed-numbers",
        at(PROBE_TEST, "test_writer_refuses_a_window_it_cannot_vouch_for"),
        ADMISSION,
        "if not args.probe_environment_scrubbed or observation != ALLOWED_OBSERVATIONS[0]:",
        "if observation != ALLOWED_OBSERVATIONS[0]:",
    ),
    (
        "writer-operator-numbers",
        at(PROBE_TEST, "test_writer_refuses_a_window_it_cannot_vouch_for"),
        ADMISSION,
        "if not args.probe_environment_scrubbed or observation != ALLOWED_OBSERVATIONS[0]:",
        "if not args.probe_environment_scrubbed:",
    ),
    (
        "writer-half-window",
        at(PROBE_TEST, "test_writer_refuses_a_window_it_cannot_vouch_for"),
        ADMISSION,
        "        if used is None or reset is None:\n",
        "        if False:\n",
    ),
    (
        "writer-nonfinite",
        at(PROBE_TEST, "test_writer_refuses_a_window_it_cannot_vouch_for"),
        ADMISSION,
        "if not math.isfinite(percent) or percent < 0:",
        "if percent < 0:",
    ),
    (
        "writer-negative",
        at(PROBE_TEST, "test_writer_refuses_a_window_it_cannot_vouch_for"),
        ADMISSION,
        "if not math.isfinite(percent) or percent < 0:",
        "if not math.isfinite(percent):",
    ),
    (
        "writer-closed-window",
        at(PROBE_TEST, "test_writer_refuses_a_window_it_cannot_vouch_for"),
        ADMISSION,
        "if resets_at is None or resets_at <= observed_at:",
        "if resets_at is None:",
    ),
    # --- the telemetry writer's strict receipt parser admits the window keys
    (
        "window-keys-unadmitted",
        at(WRITER_TEST, "test_claude_probe_windows_keep_the_admission_receipt_admitted"),
        WRITER,
        '        "seven_day_used_percent",\n',
        "",
    ),
]


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="quota-headroom-mutations-"))
    # Symlink untouched dependencies, copy only the mutated files and their tests.
    copies = {READER, MODEL, WRITER, OBSERVER, ADMISSION, TEST, PROBE_TEST, WRITER_TEST}
    directories = {"shared", "scripts", "tests", "tests/shared", "tests/scripts"}

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

    def clear_caches() -> None:
        # Only the overlay's own directories: a recursive glob follows the overlay's
        # symlinks into the live tree.
        for relative in ("", *directories):
            cache = work / relative / "__pycache__"
            if cache.is_dir() and not cache.is_symlink():
                shutil.rmtree(cache)

    def node(test: str) -> str:
        return test if "::" in test else f"{TEST}::{test}"

    overlay(Path())
    results = []
    for name, test, relative, old, new in MUTANTS:
        path = work / relative
        original = (ROOT / relative).read_text()
        if original.count(old) != 1 or old == new:
            raise ValueError(f"mutant anchor is not unique or does not change code: {name}")
        mutated = original.replace(old, new, 1)
        path.write_text(mutated)
        if path.read_text() != mutated:
            raise RuntimeError(f"mutant did not apply: {name}")
        clear_caches()
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", node(test), "-q", "-p", "no:cacheprovider"],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=300,
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
    # Every named test must pass unmutated, or a kill proves nothing.
    clear_caches()
    baseline = subprocess.run(
        [sys.executable, "-m", "pytest", *sorted({node(t) for _, t, *_ in MUTANTS}), "-q"],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=900,
    )
    (work / "baseline.log").write_text(baseline.stdout + baseline.stderr)
    print(json.dumps({"baseline_exit_code": baseline.returncode}), flush=True)
    (work / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"Evidence: {work / 'results.json'}", flush=True)
    return 0 if all(row["killed"] for row in results) and baseline.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
