"""Tests for ``agents.mail_monitor.digest``."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from prometheus_client import REGISTRY

from agents.mail_monitor import digest

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _counter(result: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_digest_runs_total",
        {"result": result},
    )
    return val or 0.0


def _write_audit(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for e in entries:
            fp.write(json.dumps(e) + "\n")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _patch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.mail_monitor import audit
    from agents.mail_monitor.processors import refusal_feedback

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(digest, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", tmp_path / "refusals.jsonl")
    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", tmp_path / "salt")


def test_digest_clean_run_emits_no_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_paths(tmp_path, monkeypatch)
    _write_audit(
        tmp_path / "audit.jsonl",
        [
            {"ts": _now_iso(), "method": "messages.get", "label": "Hapax/Verify"},
            {"ts": _now_iso(), "method": "messages.modify", "label": "Hapax/Discard"},
            {"ts": _now_iso(), "method": "users.watch", "label": ""},
        ],
    )

    before = _counter("clean")
    found = digest.run_digest()
    assert found == 0
    assert _counter("clean") - before == 1.0
    assert not (tmp_path / "refusals.jsonl").exists()


def test_digest_surfaces_out_of_label_get(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_paths(tmp_path, monkeypatch)
    _write_audit(
        tmp_path / "audit.jsonl",
        [
            {
                "ts": _now_iso(),
                "method": "messages.get",
                "messageId": "ROGUE-1",
                "label": "INBOX",
            },
            {
                "ts": _now_iso(),
                "method": "messages.get",
                "messageId": "OK-1",
                "label": "Hapax/Verify",
            },
        ],
    )

    before = _counter("out_of_label_found")
    found = digest.run_digest()
    assert found == 1
    assert _counter("out_of_label_found") - before == 1.0
    log_text = (tmp_path / "refusals.jsonl").read_text()
    assert "mail_out_of_label_read" in log_text


def test_digest_respects_lookback_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Old out-of-label entries must NOT fire."""
    _patch_paths(tmp_path, monkeypatch)
    old_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 30 * 86400))
    _write_audit(
        tmp_path / "audit.jsonl",
        [
            {
                "ts": old_ts,
                "method": "messages.get",
                "messageId": "ANCIENT",
                "label": "INBOX",
            },
        ],
    )
    assert digest.run_digest() == 0


def test_digest_handles_corrupt_audit_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_paths(tmp_path, monkeypatch)
    audit_path = tmp_path / "audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        f'{{"ts":"{_now_iso()}","method":"messages.get","label":"Hapax/Verify"}}\n'
        "this is not json\n"
    )
    assert digest.run_digest() == 0


def test_digest_skips_missing_or_invalid_timestamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_paths(tmp_path, monkeypatch)
    _write_audit(
        tmp_path / "audit.jsonl",
        [
            {"method": "messages.get", "label": "INBOX"},  # no ts
            {"ts": "not-iso", "method": "messages.get", "label": "INBOX"},
        ],
    )
    assert digest.run_digest() == 0


def test_main_returns_zero_even_when_offenders_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_paths(tmp_path, monkeypatch)
    _write_audit(
        tmp_path / "audit.jsonl",
        [
            {
                "ts": _now_iso(),
                "method": "messages.get",
                "messageId": "X",
                "label": "INBOX",
            },
        ],
    )
    # Exit 0: digest never fails systemd.
    assert digest.main([]) == 0


def test_module_pre_registers_outcome_labels() -> None:
    for outcome in ("clean", "out_of_label_found", "read_error"):
        val = REGISTRY.get_sample_value(
            "hapax_mail_monitor_digest_runs_total",
            {"result": outcome},
        )
        assert val is not None, outcome


def test_other_api_methods_not_treated_as_in_scope_violations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """messages.modify / users.watch / users.labels.list don't read body
    content, so the digest does NOT flag them when label is empty."""
    _patch_paths(tmp_path, monkeypatch)
    _write_audit(
        tmp_path / "audit.jsonl",
        [
            {"ts": _now_iso(), "method": "messages.modify", "label": ""},
            {"ts": _now_iso(), "method": "users.watch", "label": ""},
            {"ts": _now_iso(), "method": "users.labels.list", "label": ""},
        ],
    )
    assert digest.run_digest() == 0
