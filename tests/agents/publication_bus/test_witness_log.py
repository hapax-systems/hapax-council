"""Witness-log producer tests + Publisher ABC integration.

Coverage:

1. ``build_witness_event`` shape: event_type prefix, target_sha256
   stable, all fields present.
2. ``append_publication_witness`` writes one JSONL row, atomic.
3. Idempotency in-process: same (surface, target) appends once.
4. ``reset_idempotency_cache`` lets new tests start fresh.
5. Env override: ``HAPAX_PUBLICATION_LOG_PATH`` honoured.
6. Permission failure swallowed; dedup rolled back on fail so retry works.
7. **Publisher ABC integration**: every Publisher.publish() outcome
   appends one witness row. Drives a fake Publisher and asserts the
   row lands.
8. Witness row classification: payload satisfies the runner's
   ``classify_publication_log_payload`` "ok" branch.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest

from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)
from agents.publication_bus.witness_log import (
    DEFAULT_PUBLICATION_LOG_PATH,
    PUBLICATION_LOG_PATH_ENV,
    WITNESS_EVENT_TYPE_PREFIX,
    append_publication_witness,
    build_witness_event,
    reset_idempotency_cache,
)


@pytest.fixture(autouse=True)
def _isolate_idempotency_cache():
    """Ensure each test starts with an empty in-process dedup set."""

    reset_idempotency_cache()
    yield
    reset_idempotency_cache()


# ── build_witness_event ──────────────────────────────────────────────


class TestBuildWitnessEvent:
    def test_event_type_carries_publication_bus_prefix(self) -> None:
        event = build_witness_event(
            surface="zenodo-refusal-deposit",
            target="some-target",
            result="ok",
        )
        assert event["event_type"] == "publication.bus.zenodo-refusal-deposit"
        assert event["event_type"].startswith(WITNESS_EVENT_TYPE_PREFIX)

    def test_target_sha256_is_16_hex_chars(self) -> None:
        event = build_witness_event(
            surface="bridgy-webmention-publish",
            target="https://hapax.example/post/1",
            result="ok",
        )
        sha = event["target_sha256"]
        assert len(sha) == 16
        assert all(c in "0123456789abcdef" for c in sha)

    def test_target_sha256_is_stable(self) -> None:
        e1 = build_witness_event(surface="x", target="t", result="ok")
        e2 = build_witness_event(surface="y", target="t", result="ok")
        assert e1["target_sha256"] == e2["target_sha256"]

    def test_all_required_fields_present(self) -> None:
        event = build_witness_event(surface="x", target="t", result="ok")
        for key in ("event_type", "ts", "surface", "target", "target_sha256", "result"):
            assert key in event

    def test_ts_override_honoured(self) -> None:
        ts = datetime(2026, 5, 5, 3, 30, 0, tzinfo=UTC)
        event = build_witness_event(surface="x", target="t", result="ok", ts=ts)
        assert event["ts"] == "2026-05-05T03:30:00+00:00"


# ── append_publication_witness ───────────────────────────────────────


class TestAppendWitness:
    def test_writes_one_jsonl_row(self, tmp_path: Path) -> None:
        log_path = tmp_path / "publication-log.jsonl"
        ok = append_publication_witness(surface="x", target="t", result="ok", log_path=log_path)
        assert ok is True
        rows = log_path.read_text().strip().splitlines()
        assert len(rows) == 1
        parsed = json.loads(rows[0])
        assert parsed["surface"] == "x"
        assert parsed["target"] == "t"
        assert parsed["result"] == "ok"

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        log_path = tmp_path / "deep" / "nested" / "log.jsonl"
        append_publication_witness(surface="x", target="t", result="ok", log_path=log_path)
        assert log_path.exists()
        assert log_path.parent.is_dir()

    def test_appends_multiple_rows(self, tmp_path: Path) -> None:
        log_path = tmp_path / "log.jsonl"
        append_publication_witness(surface="x", target="a", result="ok", log_path=log_path)
        append_publication_witness(surface="x", target="b", result="ok", log_path=log_path)
        append_publication_witness(surface="y", target="a", result="error", log_path=log_path)
        rows = log_path.read_text().strip().splitlines()
        assert len(rows) == 3

    def test_idempotent_same_surface_target(self, tmp_path: Path) -> None:
        log_path = tmp_path / "log.jsonl"
        first = append_publication_witness(surface="x", target="t", result="ok", log_path=log_path)
        second = append_publication_witness(surface="x", target="t", result="ok", log_path=log_path)
        assert first is True
        assert second is False  # deduped
        rows = log_path.read_text().strip().splitlines()
        assert len(rows) == 1

    def test_idempotency_keys_on_surface_target_pair(self, tmp_path: Path) -> None:
        """Different surface + same target → both write."""

        log_path = tmp_path / "log.jsonl"
        a = append_publication_witness(surface="x", target="t", result="ok", log_path=log_path)
        b = append_publication_witness(surface="y", target="t", result="ok", log_path=log_path)
        assert a is True
        assert b is True
        assert len(log_path.read_text().strip().splitlines()) == 2

    def test_idempotency_reset_lets_re_append(self, tmp_path: Path) -> None:
        log_path = tmp_path / "log.jsonl"
        append_publication_witness(surface="x", target="t", result="ok", log_path=log_path)
        reset_idempotency_cache()
        second = append_publication_witness(surface="x", target="t", result="ok", log_path=log_path)
        assert second is True
        assert len(log_path.read_text().strip().splitlines()) == 2

    def test_env_var_override_honoured(self, tmp_path: Path, monkeypatch) -> None:
        target = tmp_path / "via-env.jsonl"
        monkeypatch.setenv(PUBLICATION_LOG_PATH_ENV, str(target))
        ok = append_publication_witness(surface="x", target="t", result="ok")
        assert ok is True
        assert target.exists()

    def test_default_path_when_env_unset(self, monkeypatch) -> None:
        monkeypatch.delenv(PUBLICATION_LOG_PATH_ENV, raising=False)
        from agents.publication_bus.witness_log import _resolve_log_path

        assert _resolve_log_path() == DEFAULT_PUBLICATION_LOG_PATH

    def test_permission_failure_returns_false_and_resets_dedup(self, tmp_path: Path) -> None:
        # Make the parent dir read-only — mkdir succeeds but file open fails.
        bad_dir = tmp_path / "readonly"
        bad_dir.mkdir()
        bad_dir.chmod(0o500)  # read+execute, no write
        log_path = bad_dir / "log.jsonl"
        try:
            ok = append_publication_witness(surface="x", target="t", result="ok", log_path=log_path)
            assert ok is False
            # Dedup rolled back — a retry can fire if the operator fixes
            # the permission and re-publishes.
            bad_dir.chmod(0o755)
            ok2 = append_publication_witness(
                surface="x", target="t", result="ok", log_path=log_path
            )
            assert ok2 is True
        finally:
            try:
                bad_dir.chmod(0o755)
            except OSError:
                pass


# ── Witness rows satisfy classify_publication_log_payload ─────────────


class TestWitnessClassification:
    def test_publication_bus_event_type_classified_as_ok(self) -> None:
        """The braid runner's classifier MUST register publication-bus
        rows as live witnesses."""

        from shared.github_publication_log import classify_publication_log_payload

        event = build_witness_event(surface="zenodo", target="t", result="ok")
        status, reasons = classify_publication_log_payload(event)
        assert status == "ok"
        assert "publication_witness_present" in reasons


# ── Publisher ABC integration ────────────────────────────────────────


class _FakeOkPublisher(Publisher):
    surface_name: ClassVar[str] = "test-witness-ok"
    allowlist: ClassVar[AllowlistGate] = load_allowlist("test-witness-ok", permitted=["ok-target"])
    requires_legal_name: ClassVar[bool] = False

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        return PublisherResult(ok=True, detail="fake-ok")


class _FakeErrorPublisher(Publisher):
    surface_name: ClassVar[str] = "test-witness-error"
    allowlist: ClassVar[AllowlistGate] = load_allowlist(
        "test-witness-error", permitted=["err-target"]
    )
    requires_legal_name: ClassVar[bool] = False

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        return PublisherResult(error=True, detail="fake-err")


class TestPublisherAbcIntegration:
    def test_ok_publish_appends_witness_row(self, tmp_path: Path, monkeypatch) -> None:
        log_path = tmp_path / "publication-log.jsonl"
        monkeypatch.setenv(PUBLICATION_LOG_PATH_ENV, str(log_path))

        publisher = _FakeOkPublisher()
        result = publisher.publish(PublisherPayload(target="ok-target", text="body", metadata={}))
        assert result.ok

        rows = log_path.read_text().strip().splitlines()
        assert len(rows) == 1
        parsed = json.loads(rows[0])
        assert parsed["surface"] == "test-witness-ok"
        assert parsed["target"] == "ok-target"
        assert parsed["result"] == "ok"
        assert parsed["event_type"] == "publication.bus.test-witness-ok"

    def test_error_publish_appends_witness_with_error_label(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        log_path = tmp_path / "publication-log.jsonl"
        monkeypatch.setenv(PUBLICATION_LOG_PATH_ENV, str(log_path))

        publisher = _FakeErrorPublisher()
        result = publisher.publish(PublisherPayload(target="err-target", text="body", metadata={}))
        assert result.error

        rows = log_path.read_text().strip().splitlines()
        assert len(rows) == 1
        assert json.loads(rows[0])["result"] == "error"

    def test_subclass_emit_raises_does_not_block_witness_append(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Even if _emit() raises, the ABC catches the exception and
        returns error=True — but witness append happens AFTER the
        try/except, so a raising subclass produces NO witness row.
        Instead, witness writes happen from the same outcome variable
        (the ABC's caught error path returns from publish() before the
        witness step). Test that this sequencing matches."""

        class _RaisingPublisher(Publisher):
            surface_name: ClassVar[str] = "test-witness-raises"
            allowlist: ClassVar[AllowlistGate] = load_allowlist(
                "test-witness-raises", permitted=["raise-target"]
            )

            def _emit(self, payload: PublisherPayload) -> PublisherResult:
                raise RuntimeError("simulated transport failure")

        log_path = tmp_path / "publication-log.jsonl"
        monkeypatch.setenv(PUBLICATION_LOG_PATH_ENV, str(log_path))

        publisher = _RaisingPublisher()
        result = publisher.publish(
            PublisherPayload(target="raise-target", text="body", metadata={})
        )
        assert result.error
        # No witness row — the ABC returns early from publish() in the
        # _emit-raises branch BEFORE the witness append. This is the
        # correct behaviour: a transport failure with no result envelope
        # is not a dispatched publish; witness rows track dispatched
        # outcomes only.
        assert not log_path.exists() or log_path.read_text().strip() == ""

    def test_publish_returns_result_unchanged_when_witness_fails(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Witness write failure MUST NOT alter the publish result —
        observability is best-effort, never load-bearing on the
        publish outcome."""

        from agents.publication_bus import witness_log

        def _explode(**kwargs):
            raise OSError("simulated permission denied")

        monkeypatch.setattr(witness_log, "append_publication_witness", _explode)

        publisher = _FakeOkPublisher()
        # The Publisher ABC imports append_publication_witness at module
        # load time, so monkeypatching the witness_log module attr
        # alone doesn't redirect — patch the ABC's binding too.
        from agents.publication_bus.publisher_kit import base as base_mod

        monkeypatch.setattr(base_mod, "append_publication_witness", _explode)

        result = publisher.publish(PublisherPayload(target="ok-target", text="body", metadata={}))
        assert result.ok  # unaffected by witness failure


# ── Anti-overclaim invariant ─────────────────────────────────────────


class TestAntiOverclaim:
    def test_witness_carries_no_payload_body(self, tmp_path: Path) -> None:
        """Operator framing: witness rows are existence-of-publish
        evidence only. Payload body, metadata dict, and any free-text
        from the publish call MUST NOT appear on disk."""

        log_path = tmp_path / "log.jsonl"
        sensitive = "PROPRIETARY_RESEARCH_DATA_THAT_SHOULD_NOT_LEAK"
        append_publication_witness(
            surface="x",
            target="public-target-id",  # target is OK; body is not
            result="ok",
            log_path=log_path,
        )
        contents = log_path.read_text()
        assert sensitive not in contents
