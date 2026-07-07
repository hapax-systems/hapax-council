"""Tests for ``agents.publication_bus.omg_rss_fanout``."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agents.publication_bus import omg_rss_fanout
from agents.publication_bus.omg_rss_fanout import (
    FANOUT_LOOP_HEADER_PREFIX,
    FANOUT_REQUIRED_GATES,
    OmgFanoutConfig,
    fanout,
    load_fanout_config,
)

_RECEIPT_ROOT: Path | None = None
PUBLIC_GATE_AUTHORITY_BLOCK = (
    "authority_case: CASE-PUBLIC-EGRESS-TEST\n"
    "acceptor: claim-verification-council\n"
    "review_profile: claim_verification_council_public_egress\n"
    "evidence_ref: review-dossier:public-gate-test\n"
)


@pytest.fixture(autouse=True)
def durable_public_gate_receipts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global _RECEIPT_ROOT
    root = tmp_path / "public-gate-receipts"
    root.mkdir()
    _write_public_gate_review_evidence(root)
    _RECEIPT_ROOT = root
    monkeypatch.setattr(omg_rss_fanout, "PUBLIC_GATE_RECEIPT_ROOTS", (root,))


def _write_public_gate_review_evidence(root: Path) -> None:
    (root / "public-gate-test.yaml").write_text(
        "dossier_schema: 1\n"
        "review_team_verdict: quorum-accept\n"
        "quorum_required: 1\n"
        "accept_count: 1\n"
        "reviewers:\n"
        "  - id: cvc-1\n"
        "    family: cvc\n"
        "    verdict: accept\n",
        encoding="utf-8",
    )


def _make_client(enabled: bool = True) -> MagicMock:
    client = MagicMock()
    client.enabled = enabled
    client.set_entry = MagicMock(return_value={"id": "entry-1"})
    return client


def _gate_receipts(
    *,
    source_address: str = "hapax",
    entry_id: str = "entry-1",
    content: str = "hello",
    targets: tuple[str, ...] = ("oudepode",),
) -> dict[str, str]:
    if _RECEIPT_ROOT is None:
        raise AssertionError("receipt root fixture did not run")
    target_yaml = "\n".join(f"  - {target}" for target in sorted(targets))
    for gate in FANOUT_REQUIRED_GATES:
        (_RECEIPT_ROOT / f"{gate}.yaml").write_text(
            f"gate_id: {gate}\n"
            "status: passed\n"
            f"{PUBLIC_GATE_AUTHORITY_BLOCK}"
            f"source_address: {source_address}\n"
            f"entry_id: {entry_id}\n"
            f"content_sha256: {sha256(content.encode('utf-8')).hexdigest()}\n"
            "target_addresses:\n"
            f"{target_yaml}\n",
            encoding="utf-8",
        )
    return {gate: f"public-gate:{gate}.yaml" for gate in FANOUT_REQUIRED_GATES}


def _unbound_gate_receipts() -> dict[str, str]:
    if _RECEIPT_ROOT is None:
        raise AssertionError("receipt root fixture did not run")
    for gate in FANOUT_REQUIRED_GATES:
        (_RECEIPT_ROOT / f"{gate}.yaml").write_text(
            f"gate_id: {gate}\nstatus: passed\n{PUBLIC_GATE_AUTHORITY_BLOCK}",
            encoding="utf-8",
        )
    return {gate: f"public-gate:{gate}.yaml" for gate in FANOUT_REQUIRED_GATES}


def _required_gates_yaml(gates: tuple[str, ...] = FANOUT_REQUIRED_GATES) -> str:
    return "\n".join(f"    - {gate}" for gate in gates)


class TestLoadFanoutConfig:
    def test_loads_addresses_list(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text(
            "publication_frontmatter_policy:\n"
            "  required_gates:\n"
            f"{_required_gates_yaml()}\n"
            "addresses:\n"
            "  - hapax\n"
            "  - oudepode\n"
        )
        config = load_fanout_config(path=path)
        assert config.addresses == ["hapax", "oudepode"]
        assert config.required_gates == list(FANOUT_REQUIRED_GATES)
        assert config.gate_policy_error is None

    def test_incomplete_gate_policy_is_fail_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text(
            "publication_frontmatter_policy:\n"
            "  required_gates:\n"
            "    - source_artifact_public_safe\n"
            "    - source_refs_present\n"
            "addresses:\n"
            "  - hapax\n"
            "  - oudepode\n"
        )
        config = load_fanout_config(path=path)
        assert config.required_gates == list(FANOUT_REQUIRED_GATES)
        assert config.gate_policy_error is not None
        assert "rights_privacy_redaction_pass" in config.gate_policy_error

    def test_malformed_gate_policy_is_fail_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text(
            "publication_frontmatter_policy:\n"
            "  required_gates:\n"
            f"{_required_gates_yaml()}\n"
            "    - ''\n"
            "addresses:\n"
            "  - hapax\n"
            "  - oudepode\n"
        )
        config = load_fanout_config(path=path)
        assert config.required_gates == list(FANOUT_REQUIRED_GATES)
        assert config.gate_policy_error is not None
        assert "blank or non-string" in config.gate_policy_error

    def test_missing_file_returns_empty_config(self, tmp_path: Path) -> None:
        config = load_fanout_config(path=tmp_path / "missing.yaml")
        assert config.addresses == []

    def test_empty_yaml_returns_empty_config(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text("")
        config = load_fanout_config(path=path)
        assert config.addresses == []


class TestFanout:
    def test_posts_to_every_target_except_source(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax", "oudepode", "third"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="hello",
            config=config,
            client=client,
            gate_receipts=_gate_receipts(targets=("oudepode", "third")),
        )
        # Two non-source targets
        assert client.set_entry.call_count == 2
        targets_called = {call.args[0] for call in client.set_entry.call_args_list}
        assert targets_called == {"oudepode", "third"}
        assert result["oudepode"] == "ok"
        assert result["third"] == "ok"

    def test_skips_source_address(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="hello",
            config=config,
            client=client,
            gate_receipts=_gate_receipts(targets=("oudepode",)),
        )
        client.set_entry.assert_not_called()
        assert result == {}

    def test_loop_prevention_skips_already_fanned_out_content(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"])
        # Content already contains the fanout-source header
        body = f"{FANOUT_LOOP_HEADER_PREFIX} hapax -->\nthis entry already came from hapax fanout\n"
        result = fanout(
            source_address="oudepode",  # different "source" but body still has header
            entry_id="entry-1",
            content=body,
            config=config,
            client=client,
        )
        # Skipped due to loop-prevention
        client.set_entry.assert_not_called()
        assert result == {}

    def test_disabled_client_short_circuits(self) -> None:
        client = _make_client(enabled=False)
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="hello",
            config=config,
            client=client,
            gate_receipts=_gate_receipts(targets=("oudepode",)),
        )
        client.set_entry.assert_not_called()
        assert result == {"oudepode": "client-disabled"}

    def test_set_entry_failure_records_error(self) -> None:
        client = _make_client()
        client.set_entry = MagicMock(return_value=None)
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="hello",
            config=config,
            client=client,
            gate_receipts=_gate_receipts(),
        )
        assert result["oudepode"] == "error"

    def test_injects_fanout_source_header(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"])
        fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="body",
            config=config,
            client=client,
            gate_receipts=_gate_receipts(content="body", targets=("oudepode",)),
        )
        sent = client.set_entry.call_args.kwargs["content"]
        assert FANOUT_LOOP_HEADER_PREFIX in sent
        assert "hapax" in sent  # source address recorded
        assert "body" in sent

    def test_empty_config_no_targets(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=[])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="x",
            config=config,
            client=client,
        )
        assert result == {}
        client.set_entry.assert_not_called()

    def test_missing_gate_receipts_blocks_before_public_egress(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="body",
            config=config,
            client=client,
            gate_receipts={},
        )
        assert result == {"oudepode": "gate-blocked"}
        client.set_entry.assert_not_called()

    def test_direct_config_cannot_weaken_required_gates(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"], required_gates=[])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="body",
            config=config,
            client=client,
            gate_receipts={},
        )
        assert result == {"oudepode": "gate-blocked"}
        client.set_entry.assert_not_called()

    def test_unbound_gate_receipts_block_before_public_egress(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="hello",
            config=config,
            client=client,
            gate_receipts=_unbound_gate_receipts(),
        )
        assert result == {"oudepode": "gate-blocked"}
        client.set_entry.assert_not_called()

    def test_forged_gate_receipts_block_before_public_egress(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="body",
            config=config,
            client=client,
            gate_receipts={gate: "public-gate:forged" for gate in FANOUT_REQUIRED_GATES},
        )
        assert result == {"oudepode": "gate-blocked"}
        client.set_entry.assert_not_called()

    def test_config_gate_policy_error_blocks_before_public_egress(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(
            addresses=["hapax", "oudepode"],
            gate_policy_error="fanout config required_gates missing required gate ids",
        )
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="body",
            config=config,
            client=client,
            gate_receipts=_gate_receipts(),
        )
        assert result == {"oudepode": "gate-policy-blocked"}
        client.set_entry.assert_not_called()
