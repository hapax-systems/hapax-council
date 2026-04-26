"""Tests for ``agents.mail_monitor.auto_clicker``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest import mock

from prometheus_client import REGISTRY

from agents.mail_monitor import auto_clicker

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _counter(result: str, condition: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_auto_click_total",
        {"result": result, "condition": condition},
    )
    return val or 0.0


_ALLOWLISTS = {
    "allow_senders": ["noreply@zenodo.org"],
    "allow_link_domains": ["zenodo.org", "sandbox.zenodo.org"],
}


def _good_message() -> dict:
    return {
        "envelope_from": "noreply@zenodo.org",
        "headers": {
            "Authentication-Results": (
                "mx.example.com; dkim=pass header.i=@zenodo.org; "
                "spf=pass smtp.mailfrom=@zenodo.org; dmarc=pass"
            ),
        },
        "body_text": "Confirm at https://zenodo.org/account/verify?token=xyz please.",
    }


def _write_pending_actions(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for r in records:
            fp.write(json.dumps(r) + "\n")


# ── auth check ───────────────────────────────────────────────────────


def test_check_auth_requires_all_three_pass() -> None:
    headers = {
        "Authentication-Results": "mx; dkim=pass; spf=pass; dmarc=pass",
    }
    assert auto_clicker._check_auth(headers) is True


def test_check_auth_fails_on_partial_pass() -> None:
    headers = {"Authentication-Results": "mx; dkim=pass; spf=fail; dmarc=pass"}
    assert auto_clicker._check_auth(headers) is False


def test_check_auth_fails_on_missing_header() -> None:
    assert auto_clicker._check_auth({}) is False


def test_check_auth_treats_any_fail_as_fail_even_if_pass_appears_later() -> None:
    headers = {"Authentication-Results": "mx; dkim=fail; dkim=pass; spf=pass; dmarc=pass"}
    assert auto_clicker._check_auth(headers) is False


# ── sender check ─────────────────────────────────────────────────────


def test_check_sender_passes_on_exact_allowlist_match() -> None:
    assert auto_clicker._check_sender("noreply@zenodo.org", _ALLOWLISTS["allow_senders"]) is True


def test_check_sender_fails_on_non_allowlisted() -> None:
    assert auto_clicker._check_sender("noreply@evil.com", _ALLOWLISTS["allow_senders"]) is False


def test_check_sender_normalizes_case() -> None:
    assert auto_clicker._check_sender("NOREPLY@ZENODO.ORG", _ALLOWLISTS["allow_senders"]) is True


# ── URL extract + redirect resolve ──────────────────────────────────


def test_extract_first_https_finds_url_in_prose() -> None:
    body = "Click https://zenodo.org/x?t=abc and then..."
    assert auto_clicker._extract_first_https(body) == "https://zenodo.org/x?t=abc"


def test_extract_first_https_returns_none_for_http_only() -> None:
    body = "http://insecure.example.com/path"
    assert auto_clicker._extract_first_https(body) is None


def test_resolve_one_redirect_passes_through_2xx_response() -> None:
    fake_resp = mock.Mock(status_code=200, headers={})
    with mock.patch("agents.mail_monitor.auto_clicker.requests.head", return_value=fake_resp):
        final, redirected = auto_clicker._resolve_one_redirect(
            "https://zenodo.org/v?t=abc", _ALLOWLISTS["allow_link_domains"]
        )
    assert final == "https://zenodo.org/v?t=abc"
    assert redirected is None


def test_resolve_one_redirect_follows_one_redirect_to_allowlisted_host() -> None:
    fake_resp = mock.Mock(
        status_code=302,
        headers={"Location": "https://sandbox.zenodo.org/confirm?t=abc"},
    )
    with mock.patch("agents.mail_monitor.auto_clicker.requests.head", return_value=fake_resp):
        final, redirected = auto_clicker._resolve_one_redirect(
            "https://zenodo.org/v?t=abc", _ALLOWLISTS["allow_link_domains"]
        )
    assert final == "https://sandbox.zenodo.org/confirm?t=abc"
    assert redirected == "https://sandbox.zenodo.org/confirm?t=abc"


def test_resolve_one_redirect_aborts_on_non_allowlisted_host() -> None:
    fake_resp = mock.Mock(
        status_code=302,
        headers={"Location": "https://attacker.example.com/exfil"},
    )
    with mock.patch("agents.mail_monitor.auto_clicker.requests.head", return_value=fake_resp):
        final, _ = auto_clicker._resolve_one_redirect(
            "https://zenodo.org/v?t=abc", _ALLOWLISTS["allow_link_domains"]
        )
    assert final is None


def test_resolve_one_redirect_rejects_http_initial() -> None:
    final, _ = auto_clicker._resolve_one_redirect(
        "http://zenodo.org/v?t=abc", _ALLOWLISTS["allow_link_domains"]
    )
    assert final is None


# ── correlation check ───────────────────────────────────────────────


def test_check_correlation_finds_recent_match(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pending.jsonl"
    now = 1_700_000_000.0
    _write_pending_actions(
        path,
        [
            {"sender_domain": "zenodo.org", "ts": now - 60, "action": "deposit"},
            {"sender_domain": "other.org", "ts": now - 60, "action": "x"},
        ],
    )
    rec = auto_clicker._check_correlation("zenodo.org", now=now, path=path)
    assert rec is not None
    assert rec["action"] == "deposit"


def test_check_correlation_skips_outside_window(tmp_path: Path) -> None:
    path = tmp_path / "pending.jsonl"
    now = 1_700_000_000.0
    _write_pending_actions(
        path,
        [
            {"sender_domain": "zenodo.org", "ts": now - 3600, "action": "deposit"},
        ],
    )
    rec = auto_clicker._check_correlation("zenodo.org", now=now, path=path)
    assert rec is None


def test_check_correlation_returns_none_when_file_missing(tmp_path: Path) -> None:
    rec = auto_clicker._check_correlation("zenodo.org", path=tmp_path / "missing.jsonl")
    assert rec is None


# ── working-mode check ─────────────────────────────────────────────


def test_check_working_mode_passes_when_rnd(tmp_path: Path) -> None:
    path = tmp_path / "working-mode"
    path.write_text("rnd\n")
    assert auto_clicker._check_working_mode(None, path=path) is True


def test_check_working_mode_fails_when_research(tmp_path: Path) -> None:
    path = tmp_path / "working-mode"
    path.write_text("research\n")
    assert auto_clicker._check_working_mode(None, path=path) is False


def test_check_working_mode_passes_when_record_opts_unattended(
    tmp_path: Path,
) -> None:
    """Even research mode allows auto-click when the pending action set
    ``auto_unattended=true``. That's the spec §4 condition 5 OR clause."""
    path = tmp_path / "working-mode"
    path.write_text("research\n")
    record = {"auto_unattended": True}
    assert auto_clicker._check_working_mode(record, path=path) is True


def test_check_working_mode_fails_when_file_missing(tmp_path: Path) -> None:
    """Conservative: missing working-mode → block."""
    assert auto_clicker._check_working_mode(None, path=tmp_path / "nope") is False


# ── evaluate_gate end-to-end ────────────────────────────────────────


def test_gate_passes_when_all_five_conditions_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pending_path = tmp_path / "pending.jsonl"
    wm_path = tmp_path / "working-mode"
    wm_path.write_text("rnd\n")
    now = 1_700_000_000.0
    _write_pending_actions(
        pending_path,
        [{"sender_domain": "zenodo.org", "ts": now - 60, "action": "deposit"}],
    )

    fake_resp = mock.Mock(status_code=200, headers={})
    with mock.patch("agents.mail_monitor.auto_clicker.requests.head", return_value=fake_resp):
        result = auto_clicker.evaluate_gate(
            _good_message(),
            allowlists=_ALLOWLISTS,
            now=now,
            pending_actions_path=pending_path,
            working_mode_path=wm_path,
        )

    assert result.passed is True
    assert result.failed_condition == ""


def test_gate_fails_at_auth_when_dkim_missing() -> None:
    msg = _good_message()
    msg["headers"] = {"Authentication-Results": "mx; spf=pass; dmarc=pass"}
    result = auto_clicker.evaluate_gate(msg, allowlists=_ALLOWLISTS)
    assert result.passed is False
    assert result.failed_condition == "auth"


def test_gate_fails_at_sender_when_envelope_not_allowlisted() -> None:
    msg = _good_message()
    msg["envelope_from"] = "noreply@evil.com"
    result = auto_clicker.evaluate_gate(msg, allowlists=_ALLOWLISTS)
    assert result.passed is False
    assert result.failed_condition == "sender"


def test_gate_fails_at_link_when_no_https_in_body() -> None:
    msg = _good_message()
    msg["body_text"] = "Click http://insecure/path"
    result = auto_clicker.evaluate_gate(msg, allowlists=_ALLOWLISTS)
    assert result.passed is False
    assert result.failed_condition == "no_url"


def test_gate_fails_at_correlation_when_no_pending_record(
    tmp_path: Path,
) -> None:
    pending_path = tmp_path / "pending.jsonl"  # not created
    fake_resp = mock.Mock(status_code=200, headers={})
    with mock.patch("agents.mail_monitor.auto_clicker.requests.head", return_value=fake_resp):
        result = auto_clicker.evaluate_gate(
            _good_message(),
            allowlists=_ALLOWLISTS,
            pending_actions_path=pending_path,
        )
    assert result.passed is False
    assert result.failed_condition == "correlation"


def test_gate_fails_at_working_mode_when_research_and_no_opt_in(
    tmp_path: Path,
) -> None:
    pending_path = tmp_path / "pending.jsonl"
    wm_path = tmp_path / "working-mode"
    wm_path.write_text("research\n")
    now = 1_700_000_000.0
    _write_pending_actions(
        pending_path,
        [{"sender_domain": "zenodo.org", "ts": now - 60}],  # no auto_unattended
    )
    fake_resp = mock.Mock(status_code=200, headers={})
    with mock.patch("agents.mail_monitor.auto_clicker.requests.head", return_value=fake_resp):
        result = auto_clicker.evaluate_gate(
            _good_message(),
            allowlists=_ALLOWLISTS,
            now=now,
            pending_actions_path=pending_path,
            working_mode_path=wm_path,
        )
    assert result.passed is False
    assert result.failed_condition == "working_mode"


# ── execute_click ────────────────────────────────────────────────────


def test_execute_click_returns_true_on_2xx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    fake_resp = mock.Mock(status_code=200)
    before = _counter("clicked", "")
    with mock.patch("agents.mail_monitor.auto_clicker.requests.get", return_value=fake_resp):
        ok = auto_clicker.execute_click("https://zenodo.org/v?t=abc")
    assert ok is True
    assert _counter("clicked", "") - before == 1.0


def test_execute_click_returns_false_on_5xx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    fake_resp = mock.Mock(status_code=500)
    with mock.patch("agents.mail_monitor.auto_clicker.requests.get", return_value=fake_resp):
        ok = auto_clicker.execute_click("https://zenodo.org/v?t=abc")
    assert ok is False


def test_execute_click_swallows_request_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import requests

    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    with mock.patch(
        "agents.mail_monitor.auto_clicker.requests.get",
        side_effect=requests.ConnectionError("boom"),
    ):
        ok = auto_clicker.execute_click("https://zenodo.org/v?t=abc")
    assert ok is False


# ── process_message integration ─────────────────────────────────────


def test_process_message_skips_when_gate_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate fails → no HTTP call attempted."""
    monkeypatch.setattr(auto_clicker, "PENDING_ACTIONS_PATH", tmp_path / "missing.jsonl")
    monkeypatch.setattr(auto_clicker, "WORKING_MODE_PATH", tmp_path / "missing-wm")
    msg = _good_message()
    msg["envelope_from"] = "noreply@evil.com"  # fails at sender condition

    with mock.patch("agents.mail_monitor.auto_clicker.requests.get") as get:
        ok = auto_clicker.process_message(msg)
    assert ok is False
    get.assert_not_called()


# ── allowlists.yaml integrity ───────────────────────────────────────


def test_allowlists_file_loads_clean() -> None:
    al = auto_clicker._load_allowlists()
    assert "noreply@zenodo.org" in al["allow_senders"]
    assert "zenodo.org" in al["allow_link_domains"]


def test_allowlists_lowercased_on_load() -> None:
    al = auto_clicker._load_allowlists()
    for sender in al["allow_senders"]:
        assert sender == sender.lower()
    for domain in al["allow_link_domains"]:
        assert domain == domain.lower()


def test_metric_pre_registration() -> None:
    """All known (result, condition) pairs are pre-touched at module load
    so Prometheus stat tiles never render `no data`."""
    for result, condition in (
        ("clicked", ""),
        ("skipped", "auth"),
        ("skipped", "sender"),
        ("skipped", "link"),
        ("skipped", "correlation"),
        ("skipped", "working_mode"),
        ("error", "http"),
    ):
        val = REGISTRY.get_sample_value(
            "hapax_mail_monitor_auto_click_total",
            {"result": result, "condition": condition},
        )
        assert val is not None, (result, condition)
