"""Tests for ``agents.mail_monitor.processors.operational``.

Category-D dispatch: Let's Encrypt expiry warnings, GitHub Dependabot
alerts, Porkbun DNS notices parsed into structured operational events.
Phase 1 ships the per-sender parsers + JSONL event log + counter +
chronicle hook. Awareness-state extension and waybar surfaces are
follow-ups in adjacent lanes.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.mail_monitor.processors.operational import (
    OPERATIONAL_KIND_DEPENDABOT,
    OPERATIONAL_KIND_DNS,
    OPERATIONAL_KIND_TLS,
    classify_operational_kind,
    parse_dependabot,
    parse_letsencrypt,
    parse_porkbun,
    process_operational,
)


def _msg(
    *,
    message_id: str = "op-1",
    sender: str = "noreply@letsencrypt.org",
    subject: str = "Your certificate for example.com expires in 14 days",
    body: str = "Renewal reminder for example.com — expires 2026-05-10.\n",
) -> dict:
    return {
        "id": message_id,
        "messageId": message_id,
        "sender": sender,
        "subject": subject,
        "body": body,
    }


# ── classify_operational_kind ───────────────────────────────────────


class TestClassifyOperationalKind:
    def test_letsencrypt_sender_is_tls(self):
        assert classify_operational_kind(_msg()) == OPERATIONAL_KIND_TLS

    def test_github_dependabot_subject_is_dependabot(self):
        msg = _msg(
            sender="noreply@github.com",
            subject="[GitHub] Dependabot alert: high severity in pyyaml",
        )
        assert classify_operational_kind(msg) == OPERATIONAL_KIND_DEPENDABOT

    def test_github_non_dependabot_returns_none(self):
        msg = _msg(
            sender="noreply@github.com",
            subject="[GitHub] PR review requested",
        )
        assert classify_operational_kind(msg) is None

    def test_porkbun_sender_is_dns(self):
        msg = _msg(
            sender="support@porkbun.com",
            subject="Renewal reminder: example.com expires soon",
        )
        assert classify_operational_kind(msg) == OPERATIONAL_KIND_DNS

    def test_unrelated_sender_returns_none(self):
        msg = _msg(sender="random@example.com", subject="Hello")
        assert classify_operational_kind(msg) is None


# ── parse_letsencrypt ─────────────────────────────────────────────


class TestParseLetsEncrypt:
    def test_extracts_domain_from_subject(self):
        msg = _msg(subject="Your certificate for example.com expires in 14 days")
        result = parse_letsencrypt(msg)
        assert result["domain"] == "example.com"

    def test_extracts_subdomain(self):
        msg = _msg(
            subject="Your certificate for api.example.org expires in 7 days",
        )
        result = parse_letsencrypt(msg)
        assert result["domain"] == "api.example.org"

    def test_returns_none_domain_when_unparseable(self):
        msg = _msg(subject="Notification: something happened")
        result = parse_letsencrypt(msg)
        assert result["domain"] is None


# ── parse_dependabot ──────────────────────────────────────────────


class TestParseDependabot:
    def test_extracts_repo_from_body(self):
        msg = _msg(
            sender="noreply@github.com",
            subject="[GitHub] Dependabot alert: pyyaml high severity",
            body="A new high severity Dependabot alert was found in ryanklee/hapax-council.\n",
        )
        result = parse_dependabot(msg)
        assert result["repo"] == "ryanklee/hapax-council"

    def test_extracts_severity_from_subject(self):
        msg = _msg(
            sender="noreply@github.com",
            subject="[GitHub] Dependabot alert: high severity in pyyaml",
        )
        result = parse_dependabot(msg)
        assert result["severity"] == "high"

    def test_unknown_severity_returns_none_field(self):
        msg = _msg(
            sender="noreply@github.com",
            subject="[GitHub] Dependabot alert: pyyaml found",
        )
        result = parse_dependabot(msg)
        assert result["severity"] is None


# ── parse_porkbun ─────────────────────────────────────────────────


class TestParsePorkbun:
    def test_extracts_domain_from_subject(self):
        msg = _msg(
            sender="support@porkbun.com",
            subject="Renewal reminder: example.com expires soon",
        )
        result = parse_porkbun(msg)
        assert result["domain"] == "example.com"


# ── process_operational ───────────────────────────────────────────


class TestProcessOperational:
    def test_writes_jsonl_event_for_letsencrypt(self, tmp_path: Path, monkeypatch):
        events_dir = tmp_path / "operational"
        monkeypatch.setattr(
            "agents.mail_monitor.processors.operational.EVENTS_DIR",
            events_dir,
        )
        result = process_operational(_msg(message_id="ev-tls-1"))
        assert result is True
        events_file = events_dir / "operational-events.jsonl"
        assert events_file.exists()
        lines = events_file.read_text().splitlines()
        assert len(lines) == 1
        ev = json.loads(lines[0])
        assert ev["kind"] == OPERATIONAL_KIND_TLS
        assert ev["payload"]["domain"] == "example.com"

    def test_idempotent_on_message_id(self, tmp_path: Path, monkeypatch):
        events_dir = tmp_path / "operational"
        monkeypatch.setattr(
            "agents.mail_monitor.processors.operational.EVENTS_DIR",
            events_dir,
        )
        msg = _msg(message_id="ev-dupe-1")
        process_operational(msg)
        process_operational(msg)
        lines = (events_dir / "operational-events.jsonl").read_text().splitlines()
        assert len(lines) == 1

    def test_returns_false_for_unrelated_sender(self, tmp_path: Path, monkeypatch):
        events_dir = tmp_path / "operational"
        monkeypatch.setattr(
            "agents.mail_monitor.processors.operational.EVENTS_DIR",
            events_dir,
        )
        msg = _msg(sender="random@example.com", subject="Hello")
        result = process_operational(msg)
        assert result is False
        assert not (events_dir / "events.jsonl").exists()

    def test_handles_dependabot(self, tmp_path: Path, monkeypatch):
        events_dir = tmp_path / "operational"
        monkeypatch.setattr(
            "agents.mail_monitor.processors.operational.EVENTS_DIR",
            events_dir,
        )
        msg = _msg(
            message_id="ev-dep-1",
            sender="noreply@github.com",
            subject="[GitHub] Dependabot alert: high severity in pyyaml",
            body="A new high severity Dependabot alert was found in ryanklee/hapax-council.\n",
        )
        result = process_operational(msg)
        assert result is True
        ev = json.loads((events_dir / "operational-events.jsonl").read_text().splitlines()[0])
        assert ev["kind"] == OPERATIONAL_KIND_DEPENDABOT
        assert ev["payload"]["repo"] == "ryanklee/hapax-council"
        assert ev["payload"]["severity"] == "high"
