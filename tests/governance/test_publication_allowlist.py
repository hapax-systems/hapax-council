"""Unit tests for shared.governance.publication_allowlist."""

from __future__ import annotations

from pathlib import Path

import yaml
from hypothesis import given
from hypothesis import strategies as st

from shared.governance.publication_allowlist import (
    PublicationContract,
    _apply_redactions,
    _pattern_matches,
    check,
    gated,
    load_contract,
)


def _write_contract(directory: Path, surface: str, **kwargs) -> None:
    payload = {"surface": surface, **kwargs}
    (directory / f"{surface}.yaml").write_text(yaml.dump(payload))


# ── default DENY when no contract ──────────────────────────────────────────


def test_no_contract_denies(tmp_path: Path) -> None:
    result = check("youtube-title", "chronicle.x", {"a": 1}, contracts_dir=tmp_path)
    assert result.decision == "deny"
    assert "no contract" in result.reason


# ── ALLOW path ─────────────────────────────────────────────────────────────


def test_allowed_state_kind(tmp_path: Path) -> None:
    _write_contract(tmp_path, "youtube-title", state_kinds=["chronicle.high_salience"])
    result = check(
        "youtube-title",
        "chronicle.high_salience",
        {"a": 1},
        contracts_dir=tmp_path,
    )
    assert result.decision == "allow"
    assert result.payload == {"a": 1}


def test_wildcard_pattern_matches(tmp_path: Path) -> None:
    _write_contract(tmp_path, "youtube-title", state_kinds=["chronicle.*"])
    result = check(
        "youtube-title",
        "chronicle.high_salience",
        {"a": 1},
        contracts_dir=tmp_path,
    )
    assert result.decision == "allow"


# ── DENY paths ─────────────────────────────────────────────────────────────


def test_state_kind_not_in_list_denies(tmp_path: Path) -> None:
    _write_contract(tmp_path, "youtube-title", state_kinds=["programme.role"])
    result = check(
        "youtube-title",
        "chronicle.high_salience",
        {"a": 1},
        contracts_dir=tmp_path,
    )
    assert result.decision == "deny"


def test_empty_state_kinds_denies(tmp_path: Path) -> None:
    _write_contract(tmp_path, "youtube-community", state_kinds=[])
    result = check("youtube-community", "anything.at_all", {"a": 1}, contracts_dir=tmp_path)
    assert result.decision == "deny"


# ── REDACT path ────────────────────────────────────────────────────────────


def test_redaction_drops_matching_keys(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "youtube-title",
        state_kinds=["profile.public"],
        redactions=["operator_profile.*"],
    )
    payload = {"title": "ok", "operator_profile.name": "leaked"}
    result = check("youtube-title", "profile.public", payload, contracts_dir=tmp_path)
    assert result.decision == "redact"
    assert "operator_profile.name" not in result.payload
    assert result.payload == {"title": "ok"}


def test_redaction_matches_exact_key(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "youtube-title",
        state_kinds=["profile.public"],
        redactions=["chronicle.private_moments"],
    )
    payload = {"title": "ok", "chronicle.private_moments": "leaked"}
    result = check("youtube-title", "profile.public", payload, contracts_dir=tmp_path)
    assert result.decision == "redact"
    assert "chronicle.private_moments" not in result.payload


def test_redaction_string_payload_passes_through(tmp_path: Path) -> None:
    _write_contract(tmp_path, "youtube-title", state_kinds=["x"], redactions=["foo"])
    result = check("youtube-title", "x", "string payload", contracts_dir=tmp_path)
    assert result.decision == "allow"
    assert result.payload == "string payload"


def test_redaction_no_match_yields_allow(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "youtube-title",
        state_kinds=["x"],
        redactions=["operator_profile.*"],
    )
    result = check("youtube-title", "x", {"safe": "ok"}, contracts_dir=tmp_path)
    assert result.decision == "allow"
    assert result.payload == {"safe": "ok"}


# ── decorator ──────────────────────────────────────────────────────────────


def test_decorator_skips_on_deny(tmp_path: Path) -> None:
    calls: list = []

    @gated("youtube-title", "chronicle.x", contracts_dir=tmp_path)
    def publish(payload):
        calls.append(payload)
        return "called"

    assert publish({"a": 1}) is None
    assert calls == []


def test_decorator_passes_redacted_payload(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "youtube-title",
        state_kinds=["chronicle.x"],
        redactions=["secret.*"],
    )
    received: list = []

    @gated("youtube-title", "chronicle.x", contracts_dir=tmp_path)
    def publish(payload):
        received.append(payload)
        return "called"

    publish({"public": "ok", "secret.key": "redacted"})
    assert received == [{"public": "ok"}]


def test_decorator_passes_original_payload_on_allow(tmp_path: Path) -> None:
    _write_contract(tmp_path, "youtube-title", state_kinds=["x"])
    received: list = []

    @gated("youtube-title", "x", contracts_dir=tmp_path)
    def publish(payload):
        received.append(payload)
        return "called"

    publish({"a": 1})
    assert received == [{"a": 1}]


# ── load_contract ──────────────────────────────────────────────────────────


def test_load_contract_missing_returns_none(tmp_path: Path) -> None:
    assert load_contract("nonexistent", contracts_dir=tmp_path) is None


def test_load_contract_malformed_yaml_returns_none(tmp_path: Path) -> None:
    (tmp_path / "youtube-title.yaml").write_text("not: a: valid: mapping:")
    assert load_contract("youtube-title", contracts_dir=tmp_path) is None


def test_load_contract_non_mapping_returns_none(tmp_path: Path) -> None:
    (tmp_path / "youtube-title.yaml").write_text("- just a list\n- of items\n")
    assert load_contract("youtube-title", contracts_dir=tmp_path) is None


def test_load_contract_parses_full_schema(tmp_path: Path) -> None:
    (tmp_path / "youtube-title.yaml").write_text(
        yaml.dump(
            {
                "surface": "youtube-title",
                "state_kinds": ["chronicle.x", "programme.y"],
                "redactions": ["operator_profile.*"],
                "rate_limit": {"per_hour": 2, "per_day": 12},
                "cadence_hint": "Per VOD boundary",
            }
        )
    )
    contract = load_contract("youtube-title", contracts_dir=tmp_path)
    assert contract is not None
    assert contract.state_kinds == ("chronicle.x", "programme.y")
    assert contract.redactions == ("operator_profile.*",)
    assert contract.rate_limit_per_hour == 2
    assert contract.rate_limit_per_day == 12
    assert contract.cadence_hint == "Per VOD boundary"


def test_load_contract_handles_missing_optional_fields(tmp_path: Path) -> None:
    (tmp_path / "youtube-title.yaml").write_text(
        yaml.dump({"surface": "youtube-title", "state_kinds": ["x"]})
    )
    contract = load_contract("youtube-title", contracts_dir=tmp_path)
    assert contract is not None
    assert contract.redactions == ()
    assert contract.rate_limit_per_hour == 0
    assert contract.rate_limit_per_day == 0
    assert contract.cadence_hint == ""


# ── pattern matching ───────────────────────────────────────────────────────


def test_pattern_matches_exact() -> None:
    assert _pattern_matches("chronicle.x", "chronicle.x")
    assert not _pattern_matches("chronicle.x", "chronicle.y")


def test_pattern_matches_dot_wildcard() -> None:
    assert _pattern_matches("chronicle.*", "chronicle.high_salience")
    assert _pattern_matches("chronicle.*", "chronicle.")
    assert not _pattern_matches("chronicle.*", "other.x")


def test_pattern_matches_bare_wildcard() -> None:
    assert _pattern_matches("chronicle*", "chronicle.high_salience")
    assert _pattern_matches("chronicle*", "chronicle")


def test_pattern_matches_empty_pattern_never_matches() -> None:
    assert not _pattern_matches("", "anything")


def test_apply_redactions_no_redactions() -> None:
    payload, changed = _apply_redactions({"a": 1}, ())
    assert payload == {"a": 1}
    assert not changed


def test_apply_redactions_string_passes_through() -> None:
    payload, changed = _apply_redactions("hello", ("operator_profile.*",))
    assert payload == "hello"
    assert not changed


# ── 13 starter contracts validation ────────────────────────────────────────


def test_all_starter_contracts_load_cleanly() -> None:
    """Every shipped contract under axioms/contracts/publication/ parses."""
    expected_surfaces = {
        "youtube-title",
        "youtube-description",
        "youtube-tags",
        "youtube-thumbnail",
        "youtube-chapters",
        "youtube-livechat",
        "youtube-community",
        "channel-trailer",
        "channel-sections",
        "pinned-comment",
        "bluesky-post",
        "discord-webhook",
        "mastodon-post",
    }
    for surface in expected_surfaces:
        contract = load_contract(surface)
        assert contract is not None, f"missing contract: {surface}"
        assert contract.surface == surface


def test_deferred_surfaces_default_deny() -> None:
    """Stubbed-out surfaces (no API in 2026) refuse all emits."""
    for surface in ("youtube-community", "pinned-comment"):
        result = check(surface, "any.state", {"a": 1})
        assert result.decision == "deny", f"{surface} should default DENY"


# ── Hypothesis property: deterministic ─────────────────────────────────────


@given(
    state_kind=st.text(min_size=1, max_size=50).filter(lambda s: "\n" not in s),
)
def test_check_deterministic_same_inputs_same_decision(state_kind: str) -> None:
    """Same inputs → same decision (no hidden state across calls)."""
    contract = PublicationContract(
        surface="youtube-title",
        state_kinds=("chronicle.*", "programme.*"),
        redactions=("secret.*",),
    )
    payload = {"a": 1, "secret.key": "redacted"}
    r1 = check("youtube-title", state_kind, payload, contract=contract)
    r2 = check("youtube-title", state_kind, payload, contract=contract)
    assert r1.decision == r2.decision
    assert r1.payload == r2.payload
