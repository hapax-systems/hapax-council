"""Redaction + no-secret-logging contract tests.

The cred-monitor's safety property is: no path in the daemon ever reads,
returns, prints, or logs the contents of a ``.gpg`` file. These tests
plant a sentinel byte string in fake ``.gpg`` files and assert the
sentinel never appears in the report JSON, the state file, the arrival
log, the stdout output, or captured log records.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from agents.hapax_cred_monitor.__main__ import main as cli_main
from agents.hapax_cred_monitor.monitor import compute_delta, walk_pass_store
from agents.hapax_cred_monitor.unblocker_report import (
    append_delta_log,
    build_report,
    write_report,
)

if TYPE_CHECKING:
    import pytest

SENTINEL = b"DO_NOT_READ_THIS_VALUE_SENTINEL"
SENTINEL_STR = SENTINEL.decode("ascii")


def _make_store_with_sentinels(root: Path, entries: list[str]) -> Path:
    store = root / ".password-store"
    store.mkdir(parents=True, exist_ok=True)
    for name in entries:
        path = store / f"{name}.gpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(SENTINEL)
    return store


class TestNoValueLeakage:
    def test_report_json_never_contains_sentinel(self, tmp_path: Path) -> None:
        store = _make_store_with_sentinels(
            tmp_path, ["api/anthropic", "zenodo/api-token", "orcid/orcid"]
        )
        snap = walk_pass_store(store)
        report = build_report(snap)
        payload = report.to_json()
        assert SENTINEL_STR not in payload

    def test_state_file_never_contains_sentinel(self, tmp_path: Path) -> None:
        store = _make_store_with_sentinels(tmp_path, ["api/anthropic", "orcid/orcid"])
        cache_dir = tmp_path / "cache"
        snap = walk_pass_store(store)
        report = build_report(snap)
        write_report(report, cache_dir=cache_dir)
        text = (cache_dir / "cred-watch-state.json").read_text(encoding="utf-8")
        assert SENTINEL_STR not in text

    def test_arrival_log_never_contains_sentinel(self, tmp_path: Path) -> None:
        store_a = _make_store_with_sentinels(tmp_path / "a", ["api/anthropic"])
        store_b = _make_store_with_sentinels(tmp_path / "b", ["api/anthropic", "orcid/orcid"])
        snap_a = walk_pass_store(store_a)
        snap_b = walk_pass_store(store_b)
        delta = compute_delta(snap_a, snap_b)
        cache_dir = tmp_path / "cache"
        path = append_delta_log(delta, snap_b.captured_at, cache_dir=cache_dir)
        assert path is not None
        text = path.read_text(encoding="utf-8")
        assert "orcid/orcid" in text  # entry NAME is fine
        assert SENTINEL_STR not in text  # entry VALUE is not

    def test_log_records_never_contain_sentinel(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        store = _make_store_with_sentinels(tmp_path, ["api/anthropic", "orcid/orcid"])
        cache_dir = tmp_path / "cache"
        with caplog.at_level(logging.DEBUG, logger="agents.hapax_cred_monitor"):
            snap = walk_pass_store(store)
            report = build_report(snap)
            write_report(report, cache_dir=cache_dir)
            delta = compute_delta(snap, snap)  # no-op delta
            append_delta_log(delta, snap.captured_at, cache_dir=cache_dir)
        rendered = "\n".join(rec.getMessage() for rec in caplog.records)
        assert SENTINEL_STR not in rendered

    def test_cli_stdout_never_contains_sentinel(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store = _make_store_with_sentinels(tmp_path, ["api/anthropic", "orcid/orcid"])
        cache_dir = tmp_path / "cache"
        rc = cli_main(
            [
                "--store",
                str(store),
                "--cache-dir",
                str(cache_dir),
                "--report",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert SENTINEL_STR not in out


class TestReportShapeIsValueFree:
    """Stronger than the leakage tests above: the *shape* of the report's
    public fields rejects value carriage by construction."""

    def test_missing_unblockers_carry_only_names_and_remediations(self, tmp_path: Path) -> None:
        store = _make_store_with_sentinels(tmp_path, [])  # nothing present
        snap = walk_pass_store(store)
        report = build_report(snap)
        for item in report.missing_unblockers:
            # Each MissingCredItem field is a name, category, service id,
            # remediation command, or note string. None should ever equal
            # the byte sentinel decoded; assert the contract literally.
            assert SENTINEL_STR not in item.entry_name
            assert SENTINEL_STR not in item.remediation
            assert SENTINEL_STR not in item.notes
            for svc in item.unblocks:
                assert SENTINEL_STR not in svc
