#!/usr/bin/env python3
"""Run the M1 acceptance mutants in a disposable source overlay, never the live tree.

Usage: uv run --no-sync python scripts/check-quota-headroom-mutations.py [--jobs N] [NAME ...]
Every mutant must produce an assertion failure (pytest exit 1), not a collection
error, timeout, or syntax error. Each worker owns one overlay. Full pytest output and
the matrix stay in the temporary directory printed at the end.
"""

from __future__ import annotations

import argparse
import json
import queue
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
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
        '"claude": ("*quota-wall*.yaml",)',
        '"claude": ("*quota-wall*.yaml", "claude*quota-admission*.yaml")',
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
        "(dated is not None and dated > now)",
        "(dated is not None and dated > now + timedelta(days=1))",
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
        "or session not in (\n                        subscription_sessions\n                    ):",
        "or False:",
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
        'if info.get("status") == "rejected":\n                        pending.append',
        'if info.get("status") == "rejected_never":\n                        pending.append',
    ),
    (
        "claude-overage-is-wall",
        "test_claude_overage_refusal_alone_is_not_a_wall",
        READER,
        'if info.get("status") == "rejected":\n                        pending.append',
        'if "rejected" in (info.get("status"), info.get("overageStatus")):\n'
        "                        pending.append",
    ),
    (
        "derived-supersedes-wall",
        "test_derived_evidence_never_lifts_a_wall_even_if_it_claims_a_serve",
        READER,
        '        row.label == "observed"\n        and served_by_the_subscription(row)',
        '        row.label in {"observed", "derived"}\n        and served_by_the_subscription(row)',
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
        "test_kimi_response_is_a_served_turn_but_never_lifts_the_wall",
        READER,
        "if served_at and int(served[2]) > 0:",
        "if served_at and int(served[2]) > 10**9:",
    ),
    (
        "kimi-zero-token-serve",
        "test_kimi_non_responses_are_not_served_turns",
        READER,
        "if served_at and int(served[2]) > 0:",
        "if served_at and int(served[2]) >= 0:",
    ),
    (
        "kimi-unanchored-response",
        "test_kimi_non_responses_are_not_served_turns",
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
        "in_window = [row for row in window_samples if row[2:4] == (newest_reset, minutes)]",
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
        'info.get("status") == "rejected" or overage_state(info) is True for info in rate_limits',
        "overage_state(info) is True for info in rate_limits",
    ),
    (
        "probe-overage-wall",
        at(PROBE_TEST, "test_probe_overage_refusal_alone_is_not_a_wall"),
        OBSERVER,
        'info.get("status") == "rejected" or overage_state(info) is True for info in rate_limits',
        'info.get("status") == "rejected" or overage_state(info) is True '
        'or info.get("overageStatus") == "rejected" for info in rate_limits',
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
        "targets = route_ids if widen else tuple(routes_missing_passive_evidence)",
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
        "if not args.probe_environment_scrubbed or observation != ALLOWED_OBSERVATIONS[0]:\n"
        "            raise ValueError(\n"
        '                "subscription windows come only',
        "if observation != ALLOWED_OBSERVATIONS[0]:\n"
        "            raise ValueError(\n"
        '                "subscription windows come only',
    ),
    (
        "writer-operator-numbers",
        at(PROBE_TEST, "test_writer_refuses_a_window_it_cannot_vouch_for"),
        ADMISSION,
        "if not args.probe_environment_scrubbed or observation != ALLOWED_OBSERVATIONS[0]:\n"
        "            raise ValueError(\n"
        '                "subscription windows come only',
        "if not args.probe_environment_scrubbed:\n"
        "            raise ValueError(\n"
        '                "subscription windows come only',
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
    # --- PR #4728 review round 1: each repair pinned by the test that reproduced it
    (
        "wall-dated-early",
        "test_stream_wall_is_dated_no_earlier_than_the_next_record",
        READER,
        "at=min(max(at, earliest) if earliest else at, now),",
        "at=min(earliest or at, now),",
    ),
    (
        "wall-date-unclamped",
        "test_a_last_stream_wall_is_dated_by_the_file_mtime_clamped_to_now",
        READER,
        "at=min(max(at, earliest) if earliest else at, now),",
        "at=max(at, earliest) if earliest else at,",
    ),
    (
        "harness-newest-only",
        "test_every_live_harness_wall_is_kept",
        READER,
        "walls.extend([newest, *(row for row in live.values() if row is not newest)])",
        "walls.append(newest)",
    ),
    (
        "refused-reading-lifts",
        "test_a_reading_the_subscription_did_not_serve_never_lifts_a_wall",
        READER,
        '"subscription_served": int(status in SERVED_STATUSES and overage is False),',
        '"subscription_served": int(overage is False),',
    ),
    (
        "overage-reading-lifts",
        "test_a_reading_the_subscription_did_not_serve_never_lifts_a_wall",
        READER,
        '"subscription_served": int(status in SERVED_STATUSES and overage is False),',
        '"subscription_served": int(status in SERVED_STATUSES),',
    ),
    (
        "served-reading-never-lifts",
        "test_a_served_reading_of_any_window_lifts_a_windowless_wall",
        READER,
        'return row.details.get("subscription_served") == 1',
        "return False",
    ),
    (
        "codex-future-row",
        "test_codex_reader_ignores_token_counts_dated_after_now",
        READER,
        "if at is None or (now is not None and at > now):",
        "if at is None:",
    ),
    (
        "lane-wall-unread",
        "test_claude_lane_wall_receipts_named_by_role_are_read",
        READER,
        '"claude": ("*quota-wall*.yaml",),',
        '"claude": ("claude*quota-wall.yaml",),',
    ),
    (
        "lane-wall-any-family",
        "test_claude_lane_wall_receipts_named_by_role_are_read",
        READER,
        'if family == "claude" and not claude_wall_receipt(path, data):',
        "if False:",
    ),
    (
        "one-million-alias-dropped",
        "test_claude_one_million_context_alias_is_a_subscription_session",
        READER,
        r'r"\Aclaude-[a-z0-9.-]+(?:\[[a-z0-9]+\])?\Z"',
        r'r"\Aclaude-[a-z0-9.-]+\Z"',
    ),
    (
        "family-failure-spreads",
        "test_one_corrupt_family_source_never_stops_the_others",
        READER,
        "        except TraceReadError as exc:\n            result[family] = [",
        "        except KeyError as exc:\n            result[family] = [",
    ),
    (
        "partial-line-is-corruption",
        "test_a_partial_last_line_of_a_live_trace_is_not_corruption",
        READER,
        'if not line.endswith(b"\\n"):\n                        return',
        "if False:\n                        return",
    ),
    (
        "burn-provenance-lost",
        "test_codex_burn_names_both_readings_sources",
        READER,
        '"from_source": oldest.source,',
        '"from_source": newest.source,',
    ),
    (
        "transcripts-unfiltered",
        "test_a_transcript_untouched_longer_than_any_window_is_not_scanned",
        READER,
        "        if not recently_changed(path, now=now):\n            continue\n"
        "        for event in json_lines(path):",
        "        for event in json_lines(path):",
    ),
    (
        "probe-wall-unlabelled",
        at(PROBE_TEST, "test_a_quantity_probe_that_hits_a_wall_holds_the_route"),
        OBSERVER,
        'verdict, evidence = "walled", probed',
        "verdict, evidence = probed.kind, probed",
    ),
    (
        "failed-probe-drops-admission",
        at(PROBE_TEST, "test_a_failed_quantity_probe_keeps_the_passive_admission"),
        OBSERVER,
        "            elif not any(by_route.values()):\n",
        "            else:\n",
    ),
    (
        "widen-without-weekly",
        at(PROBE_TEST, "test_a_probe_without_a_live_weekly_window_witnesses_only_missing_routes"),
        OBSERVER,
        "widen = weekly is not None and weekly[1] > probed.at",
        "widen = bool(probed.windows)",
    ),
    (
        "expired-reading-fresh",
        at(PROBE_TEST, "test_a_reading_whose_window_has_reset_is_stale"),
        OBSERVER,
        "        and row.resets_at > now\n",
        "        and row.resets_at > now - timedelta(days=30)\n",
    ),
    (
        "expired-window-minted",
        at(PROBE_TEST, "test_an_expired_probe_window_never_costs_the_receipt"),
        OBSERVER,
        "            if resets_at <= observed_at:\n                continue\n",
        "",
    ),
    (
        "probe-overage-served",
        at(PROBE_TEST, "test_a_probe_served_from_overage_is_a_wall"),
        OBSERVER,
        'info.get("status") == "rejected" or overage_state(info) is True for info in rate_limits',
        'info.get("status") == "rejected" for info in rate_limits',
    ),
    (
        "live-v2-by-default",
        at(WRITER_TEST, "test_live_ledger_stays_schema_1_until_its_readers_take_2"),
        WRITER,
        'return 2 if os.environ.get(LIVE_SCHEMA_ENV, "1").strip() == "2" else 1',
        "return 2",
    ),
    (
        "live-v1-unprojected",
        at(WRITER_TEST, "test_live_ledger_stays_schema_1_until_its_readers_take_2"),
        WRITER,
        'data = ledger.schema_v1_payload() if schema_version == 1 else ledger.model_dump(mode="json")',
        'data = ledger.model_dump(mode="json")',
    ),
    (
        "report-under-v1",
        "test_operator_report_is_refused_while_the_live_ledger_is_schema_1",
        WRITER,
        "    if live_schema_version() != 2:\n",
        "    if False:\n",
    ),
    (
        "measurement-failure-aborts",
        at(WRITER_TEST, "test_unreadable_measurements_still_write_the_admission_ledger"),
        WRITER,
        '            "written without them. Next action: run with --check to see the failing source",\n'
        "            file=sys.stderr,\n        )\n",
        '            "written without them. Next action: run with --check to see the failing source",\n'
        "            file=sys.stderr,\n        )\n        return 1\n",
    ),
    (
        "damaged-previous-blocks",
        at(WRITER_TEST, "test_a_damaged_previous_live_ledger_never_blocks_the_tick"),
        WRITER,
        "except (QuotaSpendLedgerError, OSError, ValueError):\n"
        "                    # A damaged previous file must not block every later tick.",
        "except KeyError:\n                    # A damaged previous file must not block every later tick.",
    ),
    # --- PR #4728 review round 2
    (
        "unwitnessed-reading-lifts",
        "test_a_reading_without_a_subscription_witness_never_lifts_a_wall",
        READER,
        'return row.details.get("subscription_served") == 1',
        'return row.details.get("subscription_served") != 0',
    ),
    (
        "kimi-response-lifts",
        "test_kimi_response_is_a_served_turn_but_never_lifts_the_wall",
        READER,
        'return row.details.get("subscription_served") == 1',
        'return row.details.get("subscription_served") == 1 or row.unit == "tokens"',
    ),
    (
        "longest-window-unbounded",
        "test_a_windowless_wall_without_a_reset_binds_no_longer_than_its_window",
        READER,
        "if isinstance(bound, int) and now >= wall.observed_at + timedelta(hours=bound):",
        "if False:",
    ),
    (
        "overage-strict-true",
        "test_any_truthy_overage_flag_is_overage",
        READER,
        'return not (isinstance(value, str) and value.strip().lower() in {"false", "0", "0.0"})',
        "return False",
    ),
    (
        "reader-error-spreads",
        "test_any_exception_in_one_family_stays_in_that_family",
        READER,
        "        except Exception as exc:  # noqa: BLE001",
        "        except ValueError as exc:  # noqa: BLE001",
    ),
    (
        "writer-defaults-to-v2",
        "test_the_ledger_writer_defaults_to_the_live_schema",
        WRITER,
        "*, schema_version: int = 1) -> None:",
        "*, schema_version: int = 2) -> None:",
    ),
    (
        "failed-probe-exits-zero",
        at(PROBE_TEST, "test_a_failed_probe_still_mints_the_routes_passive_evidence_covers"),
        OBSERVER,
        'elif probe_report is not None and probe_report.get("outcome") == "probe_failed":',
        "elif False:",
    ),
    (
        "refused-reading-reprobed",
        at(PROBE_TEST, "test_a_refused_requests_reading_is_still_the_current_quantity"),
        OBSERVER,
        '        if row.capacity_id == "claude.subscription.weekly"\n',
        '        if row.capacity_id == "claude.subscription.weekly"\n'
        '        and row.details.get("subscription_served") == 1\n',
    ),
    # --- PR #4728 review round 3
    (
        "overage-absent-is-served",
        "test_a_reading_without_an_overage_field_never_lifts_a_wall",
        READER,
        '"subscription_served": int(status in SERVED_STATUSES and overage is False),',
        '"subscription_served": int(status in SERVED_STATUSES and overage is not True),',
    ),
    (
        "overage-numeric-zero",
        "test_explicit_non_overage_values_are_not_overage",
        READER,
        "    if isinstance(value, (int, float)):\n        return value != 0\n",
        "    if isinstance(value, (int, float)):\n        return True\n",
    ),
    (
        "receipt-witness-assumed",
        "test_a_probe_receipt_lifts_a_wall_only_when_it_recorded_the_serve",
        READER,
        'served = {"subscription_served": int(data.get("subscription_served") is True)}',
        'served = {"subscription_served": 1}',
    ),
    (
        "harness-session-unbounded",
        "test_a_harness_wall_is_bounded_only_by_the_window_it_names",
        READER,
        '        return WINDOW_HOURS["session"]\n',
        "        return CLAUDE_LONGEST_WINDOW_HOURS\n",
    ),
    (
        "session-notice-missed",
        "test_a_harness_wall_is_bounded_only_by_the_window_it_names",
        READER,
        "usage limit|weekly limit|session limit|hit your limit",
        "usage limit|weekly limit|hit your limit",
    ),
    (
        "receipt-window-ignored",
        "test_a_receipt_wall_is_bounded_by_its_recorded_window",
        READER,
        'str(data.get("rate_limit_type")),',
        "str(None),",
    ),
    (
        "kimi-bound-dropped",
        "test_a_windowless_wall_without_a_reset_binds_no_longer_than_its_window",
        READER,
        '"binds_at_most_hours": WINDOW_HOURS["weekly"],',
        '"binds_at_most_hours": None,',
    ),
    (
        "unnamed-window-bounded",
        "test_a_wall_naming_no_window_binds_until_its_reset_or_a_witnessed_serve",
        READER,
        'CLAUDE_LONGEST_WINDOW_HOURS if family == "claude" else None,',
        "CLAUDE_LONGEST_WINDOW_HOURS,",
    ),
    (
        "undated-refusal-dropped",
        "test_an_undated_refusal_is_dated_late_and_an_undated_reading_is_not_evidence",
        READER,
        "pending.append((info, dated, source))",
        "pending.append((info, dated, source)) if dated is not None else None",
    ),
    (
        "probe-witness-assumed",
        at(
            PROBE_TEST,
            "test_a_probe_witnesses_the_subscription_only_on_an_explicit_non_overage_serve",
        ),
        OBSERVER,
        "witnessed = bool(rate_limits) and all(",
        "witnessed = True or all(",
    ),
    (
        "mint-drops-witness",
        at(
            PROBE_TEST,
            "test_a_probe_witnesses_the_subscription_only_on_an_explicit_non_overage_serve",
        ),
        OBSERVER,
        "        if route_evidence.subscription_served:\n",
        "        if False:\n",
    ),
    (
        "failed-probe-mints-nothing",
        at(PROBE_TEST, "test_a_failed_probe_mints_exactly_what_passive_evidence_alone_would"),
        OBSERVER,
        "            elif not any(by_route.values()):\n",
        "            else:\n",
    ),
    (
        "writer-unscrubbed-witness",
        at(PROBE_TEST, "test_writer_refuses_a_window_it_cannot_vouch_for"),
        ADMISSION,
        "if not args.probe_environment_scrubbed or observation != ALLOWED_OBSERVATIONS[0]:\n"
        "            raise ValueError(\n"
        '                "--subscription-served comes only',
        "if False:\n            raise ValueError(\n"
        '                "--subscription-served comes only',
    ),
    # --- PR #4728 review round 4: the transcript skip must never change which walls are live
    (
        "claude-unnamed-unbounded",
        "test_the_transcript_skip_never_changes_which_walls_are_live",
        READER,
        "    return CLAUDE_LONGEST_WINDOW_HOURS\n",
        "    return None\n",
    ),
    (
        "reset-uncapped",
        "test_the_transcript_skip_never_changes_which_walls_are_live",
        READER,
        "if isinstance(bound, int) and now >= wall.observed_at + timedelta(hours=bound):",
        "if wall.resets_at is None and isinstance(bound, int)"
        " and now >= wall.observed_at + timedelta(hours=bound):",
    ),
    (
        "stream-type-unbounded",
        "test_a_stream_refusal_of_an_unrecognized_window_binds_at_most_a_week",
        READER,
        "WINDOW_HOURS.get(limit, CLAUDE_LONGEST_WINDOW_HOURS)",
        "WINDOW_HOURS.get(limit)",
    ),
    (
        "horizon-skips-live-wall",
        "test_an_old_transcript_with_a_still_live_wall_is_read_and_walled",
        READER,
        "CLAUDE_WINDOW_HORIZON = timedelta(days=8)",
        "CLAUDE_WINDOW_HORIZON = timedelta(days=5)",
    ),
    # --- routable from this ledger's own admission (agentic-trust boundary, dev8's finding)
    (
        "routable-ignores-state",
        "test_routable_comes_from_this_ledgers_own_fresh_admission",
        READER,
        'and snapshot.get("subscription_quota_state") == "fresh"',
        "and True",
    ),
    (
        "routable-ignores-expiry",
        "test_routable_comes_from_this_ledgers_own_fresh_admission",
        READER,
        'and (snapshot.get("fresh_until") is None or instant(snapshot["fresh_until"]) > now)',
        "and True",
    ),
    (
        "route-probe-suppressed",
        at(PROBE_TEST, "test_a_refused_reading_never_suppresses_a_route_probe"),
        OBSERVER,
        'and (routes_missing_passive_evidence or quantity["stale"])',
        'and quantity["stale"]',
    ),
]


# Symlink untouched dependencies, copy only the mutated files and their tests.
COPIES = {READER, MODEL, WRITER, OBSERVER, ADMISSION, TEST, PROBE_TEST, WRITER_TEST}
DIRECTORIES = {"shared", "scripts", "tests", "tests/shared", "tests/scripts"}


def build_overlay(work: Path, relative: Path = Path()) -> Path:
    for source in (ROOT / relative).iterdir():
        name = relative / source.name
        if source.name in {".git", "__pycache__", ".pytest_cache"}:
            continue
        target = work / name
        if str(name) in DIRECTORIES:
            target.mkdir(parents=True)
            build_overlay(work, name)
        elif str(name) in COPIES:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source)
    return work


def clear_caches(work: Path) -> None:
    # Only the overlay's own directories: a recursive glob follows the overlay's
    # symlinks into the live tree.
    for relative in ("", *DIRECTORIES):
        cache = work / relative / "__pycache__"
        if cache.is_dir() and not cache.is_symlink():
            shutil.rmtree(cache)


def node(test: str) -> str:
    return test if "::" in test else f"{TEST}::{test}"


def run_mutant(work: Path, logs: Path, mutant: tuple[str, str, str, str, str]) -> dict:
    name, test, relative, old, new = mutant
    path = work / relative
    original = (ROOT / relative).read_text()
    mutated = original.replace(old, new, 1)
    path.write_text(mutated)
    try:
        if path.read_text() != mutated:
            raise RuntimeError(f"mutant did not apply: {name}")
        clear_caches(work)
        # A private basetemp per overlay: concurrent runs must not prune each other's tmp dirs.
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    node(test),
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--basetemp",
                    str(work / ".pytest-tmp"),
                ],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            # A hung mutant is a surviving mutant, recorded like any other result.
            partial = (exc.stdout or b"") + (exc.stderr or b"")
            text = partial.decode(errors="replace") if isinstance(partial, bytes) else partial
            (logs / f"{name}.log").write_text(text + "\n[timed out after 300 s]\n")
            return {"mutant": name, "test": test, "killed": False, "exit_code": "timeout"}
        output = completed.stdout + completed.stderr
        (logs / f"{name}.log").write_text(output)
        killed = completed.returncode == 1 and "AssertionError" in output
        return {"mutant": name, "test": test, "killed": killed, "exit_code": completed.returncode}
    finally:
        path.write_text(original)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--jobs", type=int, default=4, help="parallel overlays")
    parser.add_argument("names", nargs="*", help="run only these mutants (default: all)")
    args = parser.parse_args(argv)
    selected = [m for m in MUTANTS if not args.names or m[0] in args.names]
    unknown = set(args.names) - {m[0] for m in MUTANTS}
    if unknown or len({m[0] for m in MUTANTS}) != len(MUTANTS):
        raise ValueError(f"unknown or duplicate mutant names: {sorted(unknown)}")
    # Every anchor is checked before anything runs, so a stale anchor cannot end a run midway.
    for name, _test, relative, old, new in selected:
        if (ROOT / relative).read_text().count(old) != 1 or old == new:
            raise ValueError(f"mutant anchor is not unique or does not change code: {name}")
    logs = Path(tempfile.mkdtemp(prefix="quota-headroom-mutations-"))
    jobs = max(1, min(args.jobs, len(selected) or 1))
    overlays: queue.Queue[Path] = queue.Queue()
    for index in range(jobs):
        overlays.put(build_overlay(logs / f"overlay-{index}"))

    def task(mutant):
        work = overlays.get()
        try:
            return run_mutant(work, logs, mutant)
        finally:
            overlays.put(work)

    results = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for result in pool.map(task, selected):
            results.append(result)
            print(json.dumps(result), flush=True)
    # Every named test must pass unmutated, or a kill proves nothing.
    work = overlays.get()
    clear_caches(work)
    baseline = subprocess.run(
        [sys.executable, "-m", "pytest", *sorted({node(t) for _, t, *_ in selected}), "-q"],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=900,
    )
    (logs / "baseline.log").write_text(baseline.stdout + baseline.stderr)
    print(json.dumps({"baseline_exit_code": baseline.returncode}), flush=True)
    (logs / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"Evidence: {logs / 'results.json'}", flush=True)
    return 0 if all(row["killed"] for row in results) and baseline.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
