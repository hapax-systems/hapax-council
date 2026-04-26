"""Tests for ``agents.mail_monitor.processors.verify``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest import mock

from prometheus_client import REGISTRY

from agents.mail_monitor.processors import verify

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _counter(kind: str, result: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_verify_extracted_total",
        {"kind": kind, "result": result},
    )
    return val or 0.0


# ── extract_doi ──────────────────────────────────────────────────────


def test_extract_doi_finds_zenodo_format() -> None:
    body = "Your deposit is at https://doi.org/10.5281/zenodo.123456 — please cite."
    assert verify.extract_doi(body) == "10.5281/zenodo.123456"


def test_extract_doi_finds_long_suffix() -> None:
    body = "DOI: 10.1234/journal.foo-bar_baz.2026.01"
    assert verify.extract_doi(body) == "10.1234/journal.foo-bar_baz.2026.01"


def test_extract_doi_returns_none_when_absent() -> None:
    assert verify.extract_doi("no doi here, just prose") is None
    assert verify.extract_doi("") is None
    assert verify.extract_doi(None) is None


# ── extract_orcid ────────────────────────────────────────────────────


def test_extract_orcid_finds_canonical_form() -> None:
    body = "ORCID: 0000-0001-2345-6789 confirmed."
    assert verify.extract_orcid(body) == "0000-0001-2345-6789"


def test_extract_orcid_handles_x_checksum() -> None:
    body = "iD: 0000-0002-1825-009X"
    assert verify.extract_orcid(body) == "0000-0002-1825-009X"


def test_extract_orcid_returns_none_on_invalid() -> None:
    assert verify.extract_orcid("0000-0001-2345-678") is None
    assert verify.extract_orcid("0000-0001-23456-789") is None
    assert verify.extract_orcid(None) is None


# ── extract_osf_id ───────────────────────────────────────────────────


def test_extract_osf_id_finds_url_form() -> None:
    body = "Registration available at https://osf.io/abc12/"
    assert verify.extract_osf_id(body) == "abc12"


def test_extract_osf_id_returns_none_when_absent() -> None:
    assert verify.extract_osf_id("no osf here") is None


# ── process_verify ───────────────────────────────────────────────────


def test_process_verify_writes_concept_doi_when_manifest_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(verify, "ARTEFACT_QUEUE_DIR", tmp_path / "queue")

    artefact_id = "art-1"
    manifest = tmp_path / "queue" / artefact_id / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}")

    before = _counter("doi", "manifest_written")
    verify.process_verify(
        mock.Mock(),
        {
            "id": "M-1",
            "body_text": "Your DOI is 10.5281/zenodo.999 — confirmed.",
            "artefact_id": artefact_id,
        },
    )
    payload = json.loads(manifest.read_text())
    assert payload["concept_doi"] == "10.5281/zenodo.999"
    assert _counter("doi", "manifest_written") - before == 1.0


def test_process_verify_writes_version_doi_when_concept_already_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(verify, "ARTEFACT_QUEUE_DIR", tmp_path / "queue")

    artefact_id = "art-rev"
    manifest = tmp_path / "queue" / artefact_id / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"concept_doi": "10.5281/zenodo.111"}))

    verify.process_verify(
        mock.Mock(),
        {
            "id": "M-2",
            "body_text": "New DOI 10.5281/zenodo.222 minted",
            "artefact_id": artefact_id,
        },
    )
    payload = json.loads(manifest.read_text())
    assert payload["concept_doi"] == "10.5281/zenodo.111"
    assert payload["version_doi"] == "10.5281/zenodo.222"


def test_process_verify_idempotent_on_same_doi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(verify, "ARTEFACT_QUEUE_DIR", tmp_path / "queue")

    artefact_id = "art-idem"
    manifest = tmp_path / "queue" / artefact_id / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"concept_doi": "10.5281/zenodo.111"}))

    msg = {
        "id": "M-3",
        "body_text": "DOI 10.5281/zenodo.111",
        "artefact_id": artefact_id,
    }
    verify.process_verify(mock.Mock(), msg)
    verify.process_verify(mock.Mock(), msg)

    payload = json.loads(manifest.read_text())
    assert payload == {"concept_doi": "10.5281/zenodo.111"}


def test_process_verify_emits_refusal_when_no_identifiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit
    from agents.mail_monitor.processors import refusal_feedback

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(verify, "ARTEFACT_QUEUE_DIR", tmp_path / "queue")
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", tmp_path / "refusals.jsonl")
    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", tmp_path / "salt")

    verify.process_verify(
        mock.Mock(),
        {
            "id": "M-empty",
            "body_text": "Verify mail without any DOI/ORCID/OSF identifiers.",
            "sender": "noreply@zenodo.org",
        },
    )

    log_content = (tmp_path / "refusals.jsonl").read_text()
    assert "verify_extraction_failed" in log_content


def test_process_verify_skips_manifest_when_no_artefact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(verify, "ARTEFACT_QUEUE_DIR", tmp_path / "queue")
    before = _counter("doi", "manifest_skipped")

    verify.process_verify(
        mock.Mock(),
        {
            "id": "M-noart",
            "body_text": "DOI 10.5281/zenodo.555 — but no artefact_id supplied",
        },
    )
    assert _counter("doi", "manifest_skipped") - before == 1.0


def test_audit_record_includes_extracted_identifiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit

    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", audit_path)
    monkeypatch.setattr(verify, "ARTEFACT_QUEUE_DIR", tmp_path / "queue")

    verify.process_verify(
        mock.Mock(),
        {
            "id": "M-aud",
            "body_text": "DOI 10.5281/zenodo.42 ORCID 0000-0001-2345-6789",
        },
    )
    entry = audit.read_audit_entries(audit_path)[0]
    assert entry["doi"] == "10.5281/zenodo.42"
    assert entry["orcid"] == "0000-0001-2345-6789"
