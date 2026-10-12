"""Tests for hooks/scripts/write-stamp-ahead-guard.sh and its analyzer.

Row `write-stamp-ahead-of-clock-hook-20261004`; glm-steward dispatch terms
2026-10-04T23:24:46Z bind the implementation:

* threshold 15 s ahead of the clock (not 60);
* both filename precisions, ``YYYYMMDDTHHMMZ`` and ``YYYYMMDDTHHMMSSZ``,
  strict prefix, UTC/Z;
* when filename stamp and frontmatter ``created_at`` both parse, refuse on the
  max of the two;
* fail open on unparseable stamps, logging near-miss prefixes;
* refuse-and-print only -- the hook never rewrites or corrects a stamp;
* Write-only and vault-scoped; past stamps always pass.

Red-first: each case below was observed failing (exit 0 / no refusal) before
the analyzer existed. Self-contained per testing conventions: no shared
fixtures.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_MOD = _REPO / "hooks" / "scripts" / "write_stamp_ahead_guard.py"
_SHIM = _REPO / "hooks" / "scripts" / "write-stamp-ahead-guard.sh"

_spec = importlib.util.spec_from_file_location("write_stamp_ahead_guard", _MOD)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
# Register before exec: the analyzer's frozen dataclass needs its module in
# sys.modules (dataclasses resolves annotations through cls.__module__).
sys.modules["write_stamp_ahead_guard"] = guard
_spec.loader.exec_module(guard)

NOW = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)
NOW_EPOCH = int(NOW.timestamp())


def _minute(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%MZ")


def _seconds(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# unit: the pure decision function
# --------------------------------------------------------------------------


def test_evaluate_refuses_16s_ahead() -> None:
    # A seconds-form stamp is the only surface that can express a sub-minute
    # delta: the minute form floors to the minute and cannot be 16 s ahead.
    verdict = guard.evaluate(NOW_EPOCH, _seconds(NOW + timedelta(seconds=16)), None)
    assert verdict.refuse is True
    assert verdict.ahead_seconds == 16


def test_evaluate_passes_at_exactly_15s() -> None:
    verdict = guard.evaluate(NOW_EPOCH, _seconds(NOW + timedelta(seconds=15)), None)
    assert verdict.refuse is False


def test_evaluate_refuses_a_minute_form_one_minute_ahead() -> None:
    verdict = guard.evaluate(NOW_EPOCH, _minute(NOW + timedelta(minutes=1)), None)
    assert verdict.refuse is True
    assert verdict.ahead_seconds == 60


def test_evaluate_passes_past() -> None:
    assert guard.evaluate(NOW_EPOCH, _minute(NOW - timedelta(hours=3)), None).refuse is False


def test_evaluate_refuses_on_max_of_the_two() -> None:
    # filename past, created_at far ahead -> the max governs.
    verdict = guard.evaluate(
        NOW_EPOCH, _minute(NOW - timedelta(minutes=5)), _iso(NOW + timedelta(seconds=300))
    )
    assert verdict.refuse is True
    assert verdict.ahead_seconds == 300
    assert verdict.source == "created_at"


def test_evaluate_refuses_on_max_when_filename_is_the_ahead_one() -> None:
    verdict = guard.evaluate(
        NOW_EPOCH, _seconds(NOW + timedelta(seconds=270)), _iso(NOW - timedelta(hours=1))
    )
    assert verdict.refuse is True
    assert verdict.ahead_seconds == 270
    assert verdict.source == "filename"


def test_evaluate_fails_open_when_nothing_parses() -> None:
    assert guard.evaluate(NOW_EPOCH, None, None).refuse is False


def test_evaluate_ignores_the_unparseable_leg_when_the_other_parses() -> None:
    assert guard.evaluate(NOW_EPOCH, None, _iso(NOW + timedelta(seconds=90))).refuse is True


def test_parse_filename_stamp_accepts_both_precisions() -> None:
    assert guard.parse_filename_stamp("20261004T2302Z-note.md") == "20261004T2302Z"
    assert guard.parse_filename_stamp("20261004T230230Z-note.md") == "20261004T230230Z"


def test_parse_filename_stamp_requires_strict_prefix() -> None:
    assert guard.parse_filename_stamp("x20261004T2302Z-note.md") is None
    assert guard.parse_filename_stamp("note-20261004T2302Z.md") is None
    assert guard.parse_filename_stamp("2026-10-04T23:02Z-note.md") is None


def test_parse_filename_stamp_rejects_minute_form_of_a_seconds_name() -> None:
    # `^\d{8}T\d{4}Z` must not claim the first 12 chars of a seconds stamp.
    assert guard.parse_filename_stamp("20261004T230230Z") == "20261004T230230Z"


def test_filename_near_miss_names_the_prefix() -> None:
    assert guard.filename_near_miss("20261004T23-note.md") == "20261004T23"
    assert guard.filename_near_miss("2026100T2302Z-note.md") is None
    assert guard.filename_near_miss("20261004T2302Z-note.md") is None


def test_frontmatter_created_at_reads_only_the_leading_block() -> None:
    body_only = "---\ntitle: x\n---\n\ncreated_at: 2099-01-01T00:00:00Z\n"
    assert guard.frontmatter_created_at_raw(body_only) is None
    assert guard.frontmatter_created_at(body_only) is None
    with_value = (
        "---\ntitle: x\ncreated_at: 2026-10-04T23:25:00Z\n---\n\ncreated_at: 2099-01-01T00:00:00Z\n"
    )
    assert guard.frontmatter_created_at(with_value) == "2026-10-04T23:25:00Z"
    assert (
        guard.frontmatter_created_at("no frontmatter\ncreated_at: 2026-10-04T23:25:00Z\n") is None
    )


def test_frontmatter_created_at_ignores_nested_and_quotes_values() -> None:
    nested = "---\nroute_metadata:\n  created_at: 2026-10-04T23:25:00Z\n---\n"
    assert guard.frontmatter_created_at(nested) is None
    quoted = "---\ncreated_at: '2026-10-04T23:25:00Z'\n---\n"
    assert guard.frontmatter_created_at(quoted) == "2026-10-04T23:25:00Z"


def test_stamp_epoch_round_trips_and_refuses_junk() -> None:
    assert guard.stamp_epoch("20261004T2302Z") == int(
        datetime(2026, 10, 4, 23, 2, tzinfo=UTC).timestamp()
    )
    assert guard.stamp_epoch("20261004T230230Z") == int(
        datetime(2026, 10, 4, 23, 2, 30, tzinfo=UTC).timestamp()
    )
    assert guard.stamp_epoch("2026-13-40T99:99:99Z") is None
    assert guard.stamp_epoch("garbage") is None


def test_resolve_vault_root_defaults_and_honours_override() -> None:
    assert guard.resolve_vault_root({"HOME": "/h"}) == Path("/h/Documents/Personal")
    assert guard.resolve_vault_root({"HOME": "/h", "PERSONAL_VAULT_PATH": "/v"}) == Path("/v")
    assert guard.resolve_vault_root({"HOME": "/h", "PERSONAL_VAULT_PATH": "~/v"}) == Path("/h/v")
    assert guard.resolve_vault_root({"HOME": "/h", "PERSONAL_VAULT_PATH": "relative"}) is None
    assert guard.resolve_vault_root({}) is None


def test_vault_root_parity_with_cc_task_root_sh() -> None:
    # The guard rebuilds the Personal-vault path from the same knob and default
    # as hooks/scripts/cc-task-root.sh. Pin the two so they cannot drift into a
    # split SSOT (the hazard the root script's own header names).
    script = (
        'set -e; . "$1/hooks/scripts/cc-task-root.sh"; cc_task_root_resolve >/dev/null; '
        'printf "%s" "$CC_TASK_ROOT"'
    )
    for env_extra in ({}, {"PERSONAL_VAULT_PATH": "/tmp/parity-vault"}):
        env = {**os.environ, "HOME": "/tmp/parity-home", **env_extra}
        out = subprocess.run(
            ["bash", "-c", script, "bash", str(_REPO)],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout
        expected = out[: -len("/20-projects/hapax-cc-tasks")]
        assert str(guard.resolve_vault_root(env)) == expected


# --------------------------------------------------------------------------
# end-to-end: the shim, with the real clock
# --------------------------------------------------------------------------


def _run(
    payload: dict, *, tmp_path: Path, vault: Path | None = None
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    if vault is None:
        vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    env = {**os.environ, "HOME": str(home), "PERSONAL_VAULT_PATH": str(vault)}
    return subprocess.run(
        ["bash", str(_SHIM)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write(path: Path, content: str = "") -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}}


def test_refuses_ahead_filename_minute_form(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ahead = datetime.now(UTC) + timedelta(seconds=300)
    target = vault / "30-areas" / f"{_minute(ahead)}-note.md"
    result = _run(_write(target), tmp_path=tmp_path, vault=vault)
    assert result.returncode == 2
    assert "REFUSED" in result.stderr
    assert datetime.now(UTC).strftime("%Y-%m-%d") in result.stderr


def test_refuses_ahead_filename_seconds_form(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ahead = datetime.now(UTC) + timedelta(seconds=300)
    target = vault / f"{_seconds(ahead)}-note.md"
    result = _run(_write(target), tmp_path=tmp_path, vault=vault)
    assert result.returncode == 2


def test_refuses_ahead_created_at(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ahead = datetime.now(UTC) + timedelta(seconds=300)
    content = f"---\ncreated_at: {_iso(ahead)}\n---\n\n# note\n"
    result = _run(_write(vault / "plain-name.md", content), tmp_path=tmp_path, vault=vault)
    assert result.returncode == 2
    assert "created_at" in result.stderr


def test_refuses_on_max_when_filename_is_past_and_created_at_is_ahead(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    past = datetime.now(UTC) - timedelta(hours=2)
    ahead = datetime.now(UTC) + timedelta(seconds=300)
    content = f"---\ncreated_at: {_iso(ahead)}\n---\n"
    target = vault / f"{_minute(past)}-note.md"
    assert _run(_write(target, content), tmp_path=tmp_path, vault=vault).returncode == 2


def test_passes_past_filename_and_past_created_at(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    past = datetime.now(UTC) - timedelta(hours=2)
    content = f"---\ncreated_at: {_iso(past)}\n---\n"
    target = vault / f"{_minute(past)}-note.md"
    result = _run(_write(target, content), tmp_path=tmp_path, vault=vault)
    assert result.returncode == 0
    assert result.stderr == ""


def test_unparseable_stamp_passes_and_logs_a_near_miss(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    target = vault / "20261004T23-note.md"
    result = _run(_write(target), tmp_path=tmp_path, vault=vault)
    assert result.returncode == 0
    log = tmp_path / "home" / ".cache" / "hapax" / "write-stamp-ahead-near-miss.jsonl"
    assert log.exists()
    assert "20261004T23" in log.read_text(encoding="utf-8")


def test_unparseable_created_at_passes_and_logs_a_near_miss(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    content = "---\ncreated_at: 2026-10-04T23:25\n---\n"
    result = _run(_write(vault / "plain.md", content), tmp_path=tmp_path, vault=vault)
    assert result.returncode == 0
    log = tmp_path / "home" / ".cache" / "hapax" / "write-stamp-ahead-near-miss.jsonl"
    assert "2026-10-04T23:25" in log.read_text(encoding="utf-8")


def test_ignores_a_path_outside_the_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ahead = datetime.now(UTC) + timedelta(seconds=300)
    outside = tmp_path / "elsewhere" / f"{_minute(ahead)}-note.md"
    assert _run(_write(outside), tmp_path=tmp_path, vault=vault).returncode == 0


def test_ignores_non_write_tools(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ahead = datetime.now(UTC) + timedelta(seconds=300)
    target = vault / f"{_minute(ahead)}-note.md"
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(target), "new_string": "x"}}
    assert _run(payload, tmp_path=tmp_path, vault=vault).returncode == 0


def test_ignores_a_filename_stamp_that_is_not_a_strict_prefix(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ahead = datetime.now(UTC) + timedelta(seconds=300)
    target = vault / f"note-{_minute(ahead)}.md"
    assert _run(_write(target), tmp_path=tmp_path, vault=vault).returncode == 0


def test_ignores_created_at_outside_frontmatter(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ahead = datetime.now(UTC) + timedelta(seconds=300)
    # A real frontmatter block IS present; only the body carries created_at.
    content = f"---\ntitle: note\n---\n\ncreated_at: {_iso(ahead)}\n"
    assert _run(_write(vault / "plain.md", content), tmp_path=tmp_path, vault=vault).returncode == 0


def test_refusal_never_rewrites_the_target(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    ahead = datetime.now(UTC) + timedelta(seconds=300)
    target = vault / f"{_minute(ahead)}-note.md"
    target.write_text("untouched\n", encoding="utf-8")
    result = _run(_write(target, "untouched\n"), tmp_path=tmp_path, vault=vault)
    assert result.returncode == 2
    assert target.read_text(encoding="utf-8") == "untouched\n"


def test_refusal_prints_the_current_clock(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    ahead = datetime.now(UTC) + timedelta(seconds=300)
    target = vault / f"{_minute(ahead)}-note.md"
    result = _run(_write(target), tmp_path=tmp_path, vault=vault)
    assert result.returncode == 2
    match = re.search(r"current date -u: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z", result.stderr)
    assert match is not None, result.stderr
    printed = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    assert abs((datetime.now(UTC) - printed).total_seconds()) < 120


def test_fails_open_on_unparseable_input(tmp_path: Path) -> None:
    result = _run({}, tmp_path=tmp_path)
    assert result.returncode == 0


def test_shim_uses_strict_bash() -> None:
    body = _SHIM.read_text(encoding="utf-8")
    assert body.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in body
