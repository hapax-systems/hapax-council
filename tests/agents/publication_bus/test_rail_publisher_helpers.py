"""Tests for the cross-cutting rail publisher helpers.

cc-task: jr-monetization-rails-cross-cutting-helpers-extract.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from agents.publication_bus._rail_publisher_helpers import (
    CANCELLATION_REFUSAL_AXIOM,
    auto_link_cancellation_to_refusal_log,
    default_output_dir,
    safe_filename_for_event,
    write_manifest_entry,
)
from agents.publication_bus.publisher_kit import (
    PublisherPayload,
)

# ---------------------------------------------------------------------------
# default_output_dir
# ---------------------------------------------------------------------------


def test_default_output_dir_uses_hapax_home_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    result = default_output_dir("github-sponsors")
    assert result == tmp_path / "hapax-state" / "publications" / "github-sponsors"


def test_default_output_dir_falls_back_to_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HAPAX_HOME", raising=False)
    result = default_output_dir("liberapay")
    assert result == Path.home() / "hapax-state" / "publications" / "liberapay"


@pytest.mark.parametrize(
    "rail_slug",
    [
        "github-sponsors",
        "liberapay",
        "open-collective",
        "stripe-payment-link",
        "ko-fi",
        "patreon",
        "buy-me-a-coffee",
        "mercury",
        "modern-treasury",
        "treasury-prime",
    ],
)
def test_default_output_dir_accepts_all_10_rail_slugs(
    rail_slug: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every Tier 1 rail slug should resolve cleanly."""
    monkeypatch.setenv("HAPAX_HOME", str(tmp_path))
    result = default_output_dir(rail_slug)
    assert result.name == rail_slug
    assert result.parent.name == "publications"


# ---------------------------------------------------------------------------
# safe_filename_for_event
# ---------------------------------------------------------------------------


def test_safe_filename_for_event_basic() -> None:
    assert (
        safe_filename_for_event("created", "abc123def456abc7")
        == "event-created-abc123def456abc7.md"
    )


def test_safe_filename_for_event_dotted_kind() -> None:
    """Dotted event kinds (BMaC, Mercury, etc.) get sanitized."""
    assert (
        safe_filename_for_event("membership.cancelled", "abc1234567890abc")
        == "event-membership_cancelled-abc1234567890abc.md"
    )


def test_safe_filename_for_event_truncates_sha_to_16_chars() -> None:
    long_sha = "a" * 64
    result = safe_filename_for_event("created", long_sha)
    assert result == f"event-created-{'a' * 16}.md"


def test_safe_filename_for_event_handles_empty_sha() -> None:
    """Empty sha falls back to 'unknown'."""
    assert safe_filename_for_event("created", "") == "event-created-unknown.md"


def test_safe_filename_for_event_multiple_dots() -> None:
    """Multiple dots all get replaced."""
    assert safe_filename_for_event("a.b.c", "abc1234567890abc") == "event-a_b_c-abc1234567890abc.md"


# ---------------------------------------------------------------------------
# write_manifest_entry
# ---------------------------------------------------------------------------


def test_write_manifest_entry_writes_file_and_returns_ok(tmp_path: Path) -> None:
    payload = PublisherPayload(
        target="created",
        text="# Manifest body",
        metadata={"raw_payload_sha256": "abc123def456abc7" + "0" * 48},
    )
    log = logging.getLogger("test")
    result = write_manifest_entry(tmp_path, payload, log=log)
    assert result.ok is True
    assert result.error is False
    assert "event-created-abc123def456abc7.md" in result.detail
    files = list(tmp_path.glob("event-created-*.md"))
    assert len(files) == 1
    assert files[0].read_text() == "# Manifest body"


def test_write_manifest_entry_creates_parent_directory(tmp_path: Path) -> None:
    deep_dir = tmp_path / "a" / "b" / "c"
    payload = PublisherPayload(
        target="created",
        text="body",
        metadata={"raw_payload_sha256": "abc1234567890abc"},
    )
    log = logging.getLogger("test")
    result = write_manifest_entry(deep_dir, payload, log=log)
    assert result.ok is True
    assert deep_dir.is_dir()


def test_write_manifest_entry_handles_dotted_event_kind(tmp_path: Path) -> None:
    payload = PublisherPayload(
        target="membership.cancelled",
        text="body",
        metadata={"raw_payload_sha256": "abc1234567890abc"},
    )
    log = logging.getLogger("test")
    result = write_manifest_entry(tmp_path, payload, log=log)
    assert result.ok is True
    files = list(tmp_path.glob("event-membership_cancelled-*.md"))
    assert len(files) == 1


def test_write_manifest_entry_returns_error_on_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If write_text raises OSError, the helper returns error=True."""
    payload = PublisherPayload(
        target="created",
        text="body",
        metadata={"raw_payload_sha256": "abc1234567890abc"},
    )
    log = logging.getLogger("test")

    def fail_write_text(self: Path, *args, **kwargs) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", fail_write_text)
    result = write_manifest_entry(tmp_path, payload, log=log)
    assert result.error is True
    assert "write failed" in result.detail


def test_write_manifest_entry_uses_unknown_when_sha_missing(tmp_path: Path) -> None:
    payload = PublisherPayload(
        target="created",
        text="body",
        metadata={},  # no raw_payload_sha256
    )
    log = logging.getLogger("test")
    result = write_manifest_entry(tmp_path, payload, log=log)
    assert result.ok is True
    files = list(tmp_path.glob("event-created-unknown.md"))
    assert len(files) == 1


# ---------------------------------------------------------------------------
# auto_link_cancellation_to_refusal_log
# ---------------------------------------------------------------------------


@pytest.fixture
def refusal_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log_path = tmp_path / "refusals" / "log.jsonl"
    monkeypatch.setenv("HAPAX_REFUSALS_LOG_PATH", str(log_path))
    return log_path.parent


def test_auto_link_appends_refusal_event_to_log(
    refusal_log_dir: Path,
) -> None:
    payload = PublisherPayload(
        target="cancelled",
        text="body",
        metadata={"raw_payload_sha256": "abc1234567890abc"},
    )
    log = logging.getLogger("test")
    auto_link_cancellation_to_refusal_log(
        payload,
        axiom="full_auto_or_nothing",
        surface="publication_bus:test:cancelled",
        reason="test cancellation",
        log=log,
    )
    log_file = refusal_log_dir / "log.jsonl"
    assert log_file.exists()
    rows = [json.loads(line) for line in log_file.read_text().splitlines() if line]
    assert len(rows) == 1
    assert rows[0]["axiom"] == "full_auto_or_nothing"
    assert rows[0]["surface"] == "publication_bus:test:cancelled"
    assert rows[0]["reason"] == "test cancellation"


def test_auto_link_truncates_long_reason_to_160_chars(
    refusal_log_dir: Path,
) -> None:
    payload = PublisherPayload(target="cancelled", text="b", metadata={})
    log = logging.getLogger("test")
    long_reason = "x" * 500
    auto_link_cancellation_to_refusal_log(
        payload,
        axiom="full_auto_or_nothing",
        surface="publication_bus:test:cancelled",
        reason=long_reason,
        log=log,
    )
    log_file = refusal_log_dir / "log.jsonl"
    rows = [json.loads(line) for line in log_file.read_text().splitlines() if line]
    assert len(rows[0]["reason"]) == 160


def test_auto_link_swallows_exceptions(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Append failures must not break the publish path."""
    import agents.refusal_brief

    def failing_append(*args, **kwargs):
        raise RuntimeError("simulated refusal log failure")

    monkeypatch.setattr(agents.refusal_brief, "append", failing_append)
    payload = PublisherPayload(target="cancelled", text="b", metadata={})
    log = logging.getLogger("test")
    # Should not raise
    auto_link_cancellation_to_refusal_log(
        payload,
        axiom="full_auto_or_nothing",
        surface="publication_bus:test:cancelled",
        reason="test",
        log=log,
    )


# ---------------------------------------------------------------------------
# Module-level pins
# ---------------------------------------------------------------------------


def test_cancellation_refusal_axiom_is_canonical() -> None:
    assert CANCELLATION_REFUSAL_AXIOM == "full_auto_or_nothing"


def test_module_carries_no_outbound_calls() -> None:
    """No actual import or call to outbound HTTP clients.

    Walks AST instead of grep so docstring mentions (e.g. "no
    `requests` / `httpx`") don't false-positive.
    """
    import ast

    import agents.publication_bus._rail_publisher_helpers as mod

    src_tree = ast.parse(Path(mod.__file__).read_text())
    forbidden_modules = {"requests", "httpx", "aiohttp"}
    for node in ast.walk(src_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top not in forbidden_modules, f"forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            assert top not in forbidden_modules, f"forbidden import from: {node.module}"
            # urllib.request is a submodule of urllib; flag it specifically.
            assert node.module != "urllib.request", "forbidden import: urllib.request"


def test_module_carries_no_send_path() -> None:
    import inspect

    import agents.publication_bus._rail_publisher_helpers as mod

    src = inspect.getsource(mod).lower()
    forbidden_verbs = (
        "def send",
        "def initiate",
        "def payout",
        "def transfer",
        "def origination",
    )
    for token in forbidden_verbs:
        assert token not in src, f"unexpected send-path: {token!r}"


def test_publishers_use_helper_module() -> None:
    """All 10 publishers should import from _rail_publisher_helpers (not duplicate)."""
    import inspect

    import agents.publication_bus.buy_me_a_coffee_publisher as bmac
    import agents.publication_bus.github_sponsors_publisher as ghs
    import agents.publication_bus.ko_fi_publisher as kofi
    import agents.publication_bus.liberapay_publisher as lp
    import agents.publication_bus.mercury_publisher as mercury
    import agents.publication_bus.modern_treasury_publisher as mt
    import agents.publication_bus.open_collective_publisher as oc
    import agents.publication_bus.patreon_publisher as patreon
    import agents.publication_bus.stripe_payment_link_publisher as stripe
    import agents.publication_bus.treasury_prime_publisher as tp

    publisher_modules = [bmac, ghs, kofi, lp, mercury, mt, oc, patreon, stripe, tp]
    for mod in publisher_modules:
        src = inspect.getsource(mod)
        assert "from agents.publication_bus._rail_publisher_helpers import" in src, (
            f"{mod.__name__} does not import the cross-cutting helpers"
        )


def test_publishers_no_longer_define_local_default_output_dir() -> None:
    """Refactor pin: no publisher should re-define _default_output_dir locally."""
    import inspect

    import agents.publication_bus.buy_me_a_coffee_publisher as bmac
    import agents.publication_bus.github_sponsors_publisher as ghs
    import agents.publication_bus.ko_fi_publisher as kofi
    import agents.publication_bus.liberapay_publisher as lp
    import agents.publication_bus.mercury_publisher as mercury
    import agents.publication_bus.modern_treasury_publisher as mt
    import agents.publication_bus.open_collective_publisher as oc
    import agents.publication_bus.patreon_publisher as patreon
    import agents.publication_bus.stripe_payment_link_publisher as stripe
    import agents.publication_bus.treasury_prime_publisher as tp

    publisher_modules = [bmac, ghs, kofi, lp, mercury, mt, oc, patreon, stripe, tp]
    for mod in publisher_modules:
        src = inspect.getsource(mod)
        assert "def _default_output_dir" not in src, (
            f"{mod.__name__} still defines a local _default_output_dir; "
            f"should use default_output_dir() from helper module"
        )
