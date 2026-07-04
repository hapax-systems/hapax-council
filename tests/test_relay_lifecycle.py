"""Self-contained tests for the single-source relay-retirement predicate.

These pin the three divergences the module reconciles (vocabulary, file
resolution, parser) plus the canonicalization union. Each test file is
self-contained (no shared conftest), per the workspace convention.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

from shared.relay_lifecycle import (
    RETIRED_PREFIXES,
    lane_is_retired,
    relay_status_values,
    relay_value_is_retired,
    relay_values_are_retired,
)


def _write(path: Path, body: str, *, mtime_offset: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    if mtime_offset:
        # Deterministic mtime ordering (offset relative to "now"); freshest wins.
        stat = path.stat()
        os.utime(path, (stat.st_atime, stat.st_mtime + mtime_offset))


# -------------------------------------------------------------------- vocabulary


def test_each_retired_prefix_matches() -> None:
    for prefix in RETIRED_PREFIXES:
        assert relay_value_is_retired(prefix.title()) is True, prefix
        assert relay_value_is_retired(prefix.lower()) is True, prefix


def test_coordinator_missed_prefixes_now_match() -> None:
    # SUPERSEDED, CLOSED, ANTIGRAVITY_TAKEOVER were absent from the coordinator's
    # six-prefix set -> it routed them -> launcher refused -> rc=6. The lift
    # closes that gap.
    assert relay_value_is_retired("superseded") is True
    assert relay_value_is_retired("closed") is True
    assert relay_value_is_retired("antigravity_takeover") is True
    assert relay_value_is_retired("CLOSED — merged to main") is True


def test_non_retired_statuses_do_not_match() -> None:
    for alive in ("active", "idle", "idle_no_task", "working", "claimed", "executing", "retiring"):
        assert relay_value_is_retired(alive) is False, alive
    assert relay_value_is_retired("") is False
    assert relay_value_is_retired("   ") is False
    assert relay_value_is_retired(None) is False  # type: ignore[arg-type]


def test_prefix_glob_not_substring() -> None:
    # "working retired" must NOT match: the retired token is not the prefix.
    assert relay_value_is_retired("working retired") is False
    # But a leading "retired ..." does match (the launcher's first-token rule).
    assert relay_value_is_retired("retired at 2026-07-03") is True


def test_antigravity_glob_excluded_takeover_included() -> None:
    # The broad ANTIGRAVITY* glob is intentionally out; only the terminal marker.
    assert relay_value_is_retired("antigravity") is False
    assert relay_value_is_retired("antigravity_live") is False
    assert relay_value_is_retired("antigravity_takeover") is True


# ------------------------------------------------------------- canonicalization


def test_hyphen_space_underscore_all_match() -> None:
    # Launcher normalized to uppercase (kept separators); coordinator to hyphen.
    # The lift canonicalizes both hyphens and spaces to underscores.
    assert relay_value_is_retired("wind_down_idle") is True
    assert relay_value_is_retired("wind-down-idle") is True
    assert relay_value_is_retired("wind down idle") is True
    assert relay_value_is_retired("Wound-Down") is True


def test_quotes_and_padding_stripped() -> None:
    assert relay_value_is_retired('  "retired"  ') is True
    assert relay_value_is_retired("'superseded'") is True


def test_any_match_semantics() -> None:
    assert relay_values_are_retired(["active", "idle", "retired"]) is True
    assert relay_values_are_retired(["active", "idle"]) is False
    assert relay_values_are_retired([]) is False
    assert relay_values_are_retired(["active", None, 7, ""]) is False  # type: ignore[list-item]


# ------------------------------------------------------------- multi-key parser


def test_status_values_collect_all_status_keys() -> None:
    relay = {
        "status": "active",
        "state": "idle",
        "relay_status": "retired",  # any retired key -> retired
        "session_state": "working",
        "session_status": "claimed",
        "role": "cx-p0",
    }
    values = relay_status_values(relay)
    assert "retired" in values
    assert relay_values_are_retired(values) is True


def test_role_field_is_harmless_when_not_retired() -> None:
    # role is scraped for parity with the launcher's awk; a role name never
    # matches a retired prefix, so it cannot cause a false positive.
    relay = {"role": "cx-p0", "status": "active"}
    assert relay_values_are_retired(relay_status_values(relay)) is False


# ------------------------------------------------------- file resolution + mtime


def test_freshest_candidate_shadows_stale_retired(tmp_path: Path) -> None:
    # cx-oofta: {role}.yaml retired (old) vs {role}-status.yaml active (fresh).
    # Freshest-of-candidates resolves to active -> NOT retired.
    _write(
        tmp_path / "cx-oofta.yaml",
        "status: retired\nretired_at: 2026-07-01T00:00:00Z\n",
        mtime_offset=-100.0,
    )
    _write(tmp_path / "cx-oofta-status.yaml", "status: idle_no_task\n", mtime_offset=0.0)
    assert lane_is_retired("cx-oofta", relay_dir=tmp_path) is False


def test_freshest_candidate_retired_wins(tmp_path: Path) -> None:
    _write(tmp_path / "cx-fugu-1.yaml", "status: active\n", mtime_offset=-100.0)
    _write(tmp_path / "cx-fugu-1-status.yaml", "status: wound-down\n", mtime_offset=0.0)
    assert lane_is_retired("cx-fugu-1", relay_dir=tmp_path) is True


def test_single_retired_file(tmp_path: Path) -> None:
    _write(tmp_path / "cx-crit.yaml", "status: retired\n", mtime_offset=0.0)
    assert lane_is_retired("cx-crit", relay_dir=tmp_path) is True


def test_missing_relay_is_not_retired(tmp_path: Path) -> None:
    assert lane_is_retired("never-existed", relay_dir=tmp_path) is False


def test_corrupt_relay_is_not_retired(tmp_path: Path) -> None:
    _write(tmp_path / "cx-bad.yaml", "status: [unclosed\n", mtime_offset=0.0)
    assert lane_is_retired("cx-bad", relay_dir=tmp_path) is False


# --------------------------------------------------------- duplicate-key (parser)


def test_duplicate_key_last_wins_resumed_lane(tmp_path: Path) -> None:
    # status: retired (line 1) then status: idle (line 5) -> PyYAML last-wins ->
    # idle -> NOT retired. The launcher's awk scraped BOTH and got stuck retired;
    # this lift corrects that (latest status is the current truth).
    body = "status: retired\nretired_at: 2026-07-01T00:00:00Z\n---\nstatus: idle_no_task\n"
    _write(tmp_path / "cx-resumed.yaml", body, mtime_offset=0.0)
    assert lane_is_retired("cx-resumed", relay_dir=tmp_path) is False


def test_duplicate_key_last_wins_retired(tmp_path: Path) -> None:
    # The cx-crit shape: active first, retired appended last -> retired.
    body = "status: idle_no_task\nlane: cx-crit\n---\nstatus: retired\nretired_at: 2026-07-03T04:15:42Z\n"
    _write(tmp_path / "cx-crit.yaml", body, mtime_offset=0.0)
    assert lane_is_retired("cx-crit", relay_dir=tmp_path) is True


# ----------------------------------------------------------------- vocabulary


def test_superseded_in_status_field_routes_correctly(tmp_path: Path) -> None:
    # The vocabulary gap that produced rc=6: a SUPERSEDED relay the coordinator
    # did not recognize as retired.
    _write(tmp_path / "cx-super.yaml", "status: superseded\n", mtime_offset=0.0)
    assert lane_is_retired("cx-super", relay_dir=tmp_path) is True
