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
    state_kind_claim_policy,
)


def _write_contract(directory: Path, surface: str, **kwargs) -> None:
    payload = {"surface": surface, **kwargs}
    (directory / f"{surface}.yaml").write_text(yaml.dump(payload))


def _grounding_gate(*, mode: str = "public_archive") -> dict:
    return {
        "schema_version": 1,
        "public_private_mode": mode,
        "gate_state": "pass",
        "claim": {
            "evidence_refs": ["source:example"],
            "provenance": {"source_refs": ["chunk:example"]},
            "freshness": {"status": "fresh"},
            "rights_state": "operator_controlled",
            "privacy_state": "public_safe",
            "public_private_mode": mode,
            "refusal_correction_path": {
                "refusal_reason": None,
                "correction_event_ref": None,
                "artifact_ref": None,
            },
        },
        "gate_result": {
            "may_emit_claim": True,
            "may_publish_live": mode == "public_live",
            "may_publish_archive": mode == "public_archive",
            "may_monetize": mode == "public_monetizable",
        },
    }


# ── default DENY when no contract ──────────────────────────────────────────


def test_no_contract_denies(tmp_path: Path) -> None:
    result = check("youtube-title", "chronicle.x", {"a": 1}, contracts_dir=tmp_path)
    assert result.decision == "deny"
    assert "no contract" in result.reason


# ── ALLOW path ─────────────────────────────────────────────────────────────


def test_allowed_state_kind(tmp_path: Path) -> None:
    _write_contract(tmp_path, "youtube-title", state_kinds=["working_mode"])
    result = check(
        "youtube-title",
        "working_mode",
        {"a": 1},
        contracts_dir=tmp_path,
    )
    assert result.decision == "allow"
    assert result.payload == {"a": 1}


def test_wildcard_pattern_matches(tmp_path: Path) -> None:
    _write_contract(tmp_path, "youtube-title", state_kinds=["broadcast.*"])
    result = check(
        "youtube-title",
        "broadcast.boundary",
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


# ── Grounding composition for claim-bearing publication ─────────────────────


def test_state_kind_claim_policy_classifies_claim_and_non_claim_states() -> None:
    assert state_kind_claim_policy("chronicle.high_salience") == "claim_bearing"
    assert state_kind_claim_policy("governance.enforcement") == "claim_bearing"
    assert state_kind_claim_policy("weblog.entry") == "claim_bearing"
    assert state_kind_claim_policy("publication.artifact") == "claim_bearing"
    assert state_kind_claim_policy("velocity.digest") == "claim_bearing"
    assert state_kind_claim_policy("broadcast.boundary") == "non_claim_bearing"
    assert state_kind_claim_policy("broadcast.current_live_url") == "non_claim_bearing"


def test_claim_bearing_state_kind_requires_grounding_gate(tmp_path: Path) -> None:
    _write_contract(tmp_path, "omg-lol-statuslog", state_kinds=["chronicle.high_salience"])
    result = check(
        "omg-lol-statuslog",
        "chronicle.high_salience",
        {"summary": "claim without evidence"},
        contracts_dir=tmp_path,
    )
    assert result.decision == "deny"
    assert "missing grounding gate result" in result.reason


def test_claim_bearing_state_kind_allows_publishable_grounding_gate(tmp_path: Path) -> None:
    _write_contract(tmp_path, "omg-lol-statuslog", state_kinds=["chronicle.high_salience"])
    result = check(
        "omg-lol-statuslog",
        "chronicle.high_salience",
        {"summary": "grounded claim", "grounding_gate_result": _grounding_gate()},
        contracts_dir=tmp_path,
    )
    assert result.decision == "allow"


def test_claim_bearing_state_kind_rejects_empty_evidence_refs(tmp_path: Path) -> None:
    _write_contract(tmp_path, "omg-lol-statuslog", state_kinds=["chronicle.high_salience"])
    gate = _grounding_gate()
    gate["claim"]["evidence_refs"] = []
    result = check(
        "omg-lol-statuslog",
        "chronicle.high_salience",
        {"grounding_gate_result": gate},
        contracts_dir=tmp_path,
    )
    assert result.decision == "deny"
    assert "evidence_refs" in result.reason


def test_claim_bearing_state_kind_rejects_empty_source_refs(tmp_path: Path) -> None:
    _write_contract(tmp_path, "omg-lol-statuslog", state_kinds=["chronicle.high_salience"])
    gate = _grounding_gate()
    gate["claim"]["provenance"]["source_refs"] = []
    result = check(
        "omg-lol-statuslog",
        "chronicle.high_salience",
        {"grounding_gate_result": gate},
        contracts_dir=tmp_path,
    )
    assert result.decision == "deny"
    assert "source_refs" in result.reason


def test_claim_bearing_state_kind_rejects_private_or_dry_run_gate(tmp_path: Path) -> None:
    _write_contract(tmp_path, "omg-lol-statuslog", state_kinds=["chronicle.high_salience"])
    result = check(
        "omg-lol-statuslog",
        "chronicle.high_salience",
        {"grounding_gate_result": _grounding_gate(mode="dry_run")},
        contracts_dir=tmp_path,
    )
    assert result.decision == "deny"
    assert "cannot publish" in result.reason


def test_claim_bearing_state_kind_rejects_unsafe_freshness_rights_or_privacy(
    tmp_path: Path,
) -> None:
    _write_contract(tmp_path, "omg-lol-statuslog", state_kinds=["chronicle.high_salience"])
    gate = _grounding_gate()
    gate["claim"]["freshness"]["status"] = "stale"
    assert (
        check(
            "omg-lol-statuslog",
            "chronicle.high_salience",
            {"grounding_gate_result": gate},
            contracts_dir=tmp_path,
        ).decision
        == "deny"
    )

    gate = _grounding_gate()
    gate["claim"]["rights_state"] = "third_party_uncleared"
    assert (
        check(
            "omg-lol-statuslog",
            "chronicle.high_salience",
            {"grounding_gate_result": gate},
            contracts_dir=tmp_path,
        ).decision
        == "deny"
    )

    gate = _grounding_gate()
    gate["claim"]["privacy_state"] = "consent_required"
    assert (
        check(
            "omg-lol-statuslog",
            "chronicle.high_salience",
            {"grounding_gate_result": gate},
            contracts_dir=tmp_path,
        ).decision
        == "deny"
    )


def test_non_claim_bearing_publication_preserves_allowlist_only_behavior(tmp_path: Path) -> None:
    _write_contract(tmp_path, "channel-trailer", state_kinds=["broadcast.current_live_url"])
    result = check(
        "channel-trailer",
        "broadcast.current_live_url",
        {"broadcast_id": "vid-1"},
        contracts_dir=tmp_path,
    )
    assert result.decision == "allow"


def test_publication_surfaces_compose_with_claim_bearing_grounding(tmp_path: Path) -> None:
    surface_state_pairs = (
        ("omg-lol-statuslog", "chronicle.high_salience"),
        ("omg-lol-weblog", "weblog.entry"),
        ("omg-lol-pastebin", "chronicle.weekly_digest"),
        ("bluesky-post", "chronicle.high_salience"),
        ("bluesky-post", "governance.enforcement"),
        ("bluesky-post", "omg.weblog"),
        ("bluesky-post", "velocity.digest"),
        ("mastodon-post", "chronicle.high_salience"),
        ("mastodon-post", "governance.enforcement"),
        ("mastodon-post", "omg.weblog"),
        ("mastodon-post", "velocity.digest"),
        ("discord-webhook", "chronicle.high_salience"),
        ("arena-post", "chronicle.high_salience"),
        ("arena-post", "governance.enforcement"),
        ("arena-post", "omg.weblog"),
        ("arena-post", "velocity.digest"),
    )
    for surface, state_kind in surface_state_pairs:
        _write_contract(tmp_path, surface, state_kinds=[state_kind])
        denied = check(surface, state_kind, {"summary": surface}, contracts_dir=tmp_path)
        assert denied.decision == "deny", (surface, state_kind)

        allowed = check(
            surface,
            state_kind,
            {"summary": surface, "grounding_gate_result": _grounding_gate()},
            contracts_dir=tmp_path,
        )
        assert allowed.decision == "allow", (surface, state_kind)


def test_real_social_allowlists_include_non_broadcast_syndication_events() -> None:
    surface_state_pairs = (
        ("mastodon-post", "governance.enforcement"),
        ("mastodon-post", "velocity.digest"),
        ("bluesky-post", "governance.enforcement"),
        ("bluesky-post", "velocity.digest"),
        ("arena-post", "governance.enforcement"),
        ("arena-post", "velocity.digest"),
    )
    for surface, state_kind in surface_state_pairs:
        result = check(
            surface,
            state_kind,
            {"summary": surface, "grounding_gate_result": _grounding_gate()},
        )
        assert result.decision == "allow", (surface, state_kind, result.reason)


def test_channel_metadata_remains_non_claim_bearing(tmp_path: Path) -> None:
    _write_contract(tmp_path, "channel-trailer", state_kinds=["broadcast.current_live_url"])
    result = check(
        "channel-trailer",
        "broadcast.current_live_url",
        {"broadcast_id": "incoming-live-id"},
        contracts_dir=tmp_path,
    )
    assert result.decision == "allow"


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
    """Unregistered redaction names are key-patterns; on string payload
    they no-op (no key to match), so the result is allow + unchanged."""
    _write_contract(tmp_path, "youtube-title", state_kinds=["x"], redactions=["foo"])
    result = check("youtube-title", "x", "string payload", contracts_dir=tmp_path)
    assert result.decision == "allow"
    assert result.payload == "string payload"


# ── AUDIT-22 Phase B: registered transforms apply to string payloads ──────


def test_string_payload_operator_legal_name_transform_applied(tmp_path: Path, monkeypatch) -> None:
    """When a contract names ``operator_legal_name`` and a string
    payload contains the operator's name (env var), redaction
    substitutes ``[REDACTED]``."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Real Person")
    _write_contract(
        tmp_path, "youtube-title", state_kinds=["x"], redactions=["operator_legal_name"]
    )
    result = check("youtube-title", "x", "by Real Person today", contracts_dir=tmp_path)
    assert result.decision == "redact"
    assert "Real Person" not in result.payload
    assert "[REDACTED]" in result.payload


def test_string_payload_email_transform_applied(tmp_path: Path) -> None:
    _write_contract(tmp_path, "youtube-title", state_kinds=["x"], redactions=["email_address"])
    result = check("youtube-title", "x", "see user@example.com", contracts_dir=tmp_path)
    assert result.decision == "redact"
    assert "user@example.com" not in result.payload


def test_string_payload_multiple_transforms_compose(tmp_path: Path, monkeypatch) -> None:
    """Multiple registered transforms in the same contract apply in
    order; final string has all matches redacted."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Real Person")
    _write_contract(
        tmp_path,
        "youtube-title",
        state_kinds=["x"],
        redactions=["operator_legal_name", "email_address"],
    )
    payload = "Real Person at user@example.com"
    result = check("youtube-title", "x", payload, contracts_dir=tmp_path)
    assert result.decision == "redact"
    assert "Real Person" not in result.payload
    assert "user@example.com" not in result.payload


def test_string_payload_no_transform_match_passes_through(tmp_path: Path) -> None:
    """Transform registered in contract but content has no match → allow."""
    _write_contract(tmp_path, "youtube-title", state_kinds=["x"], redactions=["email_address"])
    result = check("youtube-title", "x", "no email here", contracts_dir=tmp_path)
    assert result.decision == "allow"


def test_dict_payload_transform_name_skips_key_redaction(tmp_path: Path) -> None:
    """Transform names (eg. ``operator_legal_name``) on dict payloads
    are no-ops — transforms operate on string content. A dict key
    literally named ``operator_legal_name`` would be matched as a
    wildcard pattern, but only if the existing dict-key matcher
    accepts it (no wildcard suffix)."""
    _write_contract(
        tmp_path, "youtube-title", state_kinds=["x"], redactions=["operator_legal_name"]
    )
    result = check(
        "youtube-title",
        "x",
        {"title": "value", "other": "stuff"},
        contracts_dir=tmp_path,
    )
    # No matching key → allow.
    assert result.decision == "allow"


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
