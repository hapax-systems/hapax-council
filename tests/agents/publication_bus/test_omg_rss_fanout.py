"""Tests for ``agents.publication_bus.omg_rss_fanout``."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from agents.publication_bus import omg_rss_fanout
from agents.publication_bus.omg_rss_fanout import (
    FANOUT_LOOP_HEADER_PREFIX,
    FANOUT_REQUIRED_GATES,
    OmgFanoutConfig,
    fanout,
    load_fanout_config,
)
from shared import public_gate_receipts

_CURRENT_REPO_HEAD_SHA = omg_rss_fanout._current_repo_head_sha
_RECEIPT_ROOT: Path | None = None
TASK_ID = "cc-task-public-gate-test"
AUTHORITY_SECRET = "test-public-gate-authority-secret"
PUBLIC_GATE_AUTHORITY_BLOCK = (
    "authority_case: CASE-PUBLIC-EGRESS-TEST\n"
    "acceptor: claim-verification-council\n"
    "review_profile: claim_verification_council_public_egress\n"
    f"evidence_ref: review-dossier:{TASK_ID}\n"
)


@pytest.fixture(autouse=True)
def durable_public_gate_receipts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global _RECEIPT_ROOT
    root = tmp_path / "public-gate-receipts"
    authority_root = tmp_path / "public-gate-authority"
    root.mkdir()
    authority_root.mkdir()
    monkeypatch.setattr(public_gate_receipts, "PUBLIC_GATE_AUTHORITY_ROOTS", (authority_root,))
    monkeypatch.setenv(public_gate_receipts.PUBLIC_GATE_AUTHORITY_SECRET_ENV, AUTHORITY_SECRET)
    monkeypatch.setattr(omg_rss_fanout, "_current_repo_head_sha", lambda: "a" * 40)
    _write_public_gate_review_evidence(root, gates=FANOUT_REQUIRED_GATES)
    _RECEIPT_ROOT = root
    monkeypatch.setattr(omg_rss_fanout, "PUBLIC_GATE_RECEIPT_ROOTS", (root,))


def test_current_repo_head_sha_uses_fixed_git_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=("a" * 40) + "\n")

    monkeypatch.setattr(omg_rss_fanout, "_current_repo_head_sha", _CURRENT_REPO_HEAD_SHA)
    monkeypatch.setattr(omg_rss_fanout.subprocess, "run", fake_run)

    assert omg_rss_fanout._current_repo_head_sha(tmp_path) == "a" * 40

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["git", "rev-parse", "--verify", "HEAD"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["capture_output"] is True
    assert kwargs["check"] is False
    assert kwargs["text"] is True
    assert "shell" not in kwargs


def _write_public_gate_review_evidence(
    root: Path,
    *,
    gates: tuple[str, ...],
    receipt_refs: tuple[str, ...] | None = None,
    source_address: str | None = None,
    entry_id: str | None = None,
    content_sha256: str | None = None,
    targets: tuple[str, ...] | None = None,
) -> None:
    del root
    gate_yaml = "\n".join(f"  - {gate}" for gate in gates)
    receipt_yaml = "\n".join(f"  - {receipt_ref}" for receipt_ref in (receipt_refs or ()))
    binding_yaml = ""
    if source_address is not None:
        binding_yaml += f"source_address: {source_address}\n"
    if entry_id is not None:
        binding_yaml += f"entry_id: {entry_id}\n"
    if content_sha256 is not None:
        binding_yaml += f"content_sha256: {content_sha256}\n"
    if targets is not None:
        target_yaml = "\n".join(f"  - {target}" for target in sorted(targets))
        binding_yaml += f"target_addresses:\n{target_yaml}\n"
    payload = yaml.safe_load(
        "dossier_schema: 1\n"
        f"task_id: {TASK_ID}\n"
        "head_sha: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "review_team_verdict: quorum-accept\n"
        "quorum_required: 1\n"
        "accept_count: 1\n"
        "required_gates:\n"
        f"{gate_yaml}\n"
        "authorized_public_gate_receipts:\n"
        f"{receipt_yaml}\n"
        f"{binding_yaml}"
        "authority_issuer: claim-verification-council\n"
        "reviewers:\n"
        "  - id: cvc-1\n"
        "    family: cvc\n"
        "    verdict: accept\n"
    )
    payload["authority_signature"] = public_gate_receipts.public_gate_authority_signature(
        payload,
        AUTHORITY_SECRET,
    )
    (
        public_gate_receipts.PUBLIC_GATE_AUTHORITY_ROOTS[0] / f"{TASK_ID}.review-dossier.yaml"
    ).write_text(
        yaml.safe_dump(payload, sort_keys=False),
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
    content_hash = sha256(content.encode("utf-8")).hexdigest()
    receipt_refs = tuple(f"public-gate:{gate}.yaml" for gate in FANOUT_REQUIRED_GATES)
    _write_public_gate_review_evidence(
        _RECEIPT_ROOT,
        gates=FANOUT_REQUIRED_GATES,
        receipt_refs=receipt_refs,
        source_address=source_address,
        entry_id=entry_id,
        content_sha256=content_hash,
        targets=targets,
    )
    target_yaml = "\n".join(f"  - {target}" for target in sorted(targets))
    for gate in FANOUT_REQUIRED_GATES:
        (_RECEIPT_ROOT / f"{gate}.yaml").write_text(
            f"gate_id: {gate}\n"
            "status: passed\n"
            f"{PUBLIC_GATE_AUTHORITY_BLOCK}"
            f"source_address: {source_address}\n"
            f"entry_id: {entry_id}\n"
            f"content_sha256: {content_hash}\n"
            "target_addresses:\n"
            f"{target_yaml}\n",
            encoding="utf-8",
        )
    return {gate: f"public-gate:{gate}.yaml" for gate in FANOUT_REQUIRED_GATES}


def _unbound_gate_receipts() -> dict[str, str]:
    if _RECEIPT_ROOT is None:
        raise AssertionError("receipt root fixture did not run")
    _write_public_gate_review_evidence(
        _RECEIPT_ROOT,
        gates=FANOUT_REQUIRED_GATES,
        receipt_refs=tuple(f"public-gate:{gate}.yaml" for gate in FANOUT_REQUIRED_GATES),
    )
    for gate in FANOUT_REQUIRED_GATES:
        (_RECEIPT_ROOT / f"{gate}.yaml").write_text(
            f"gate_id: {gate}\nstatus: passed\n{PUBLIC_GATE_AUTHORITY_BLOCK}",
            encoding="utf-8",
        )
    return {gate: f"public-gate:{gate}.yaml" for gate in FANOUT_REQUIRED_GATES}


def _required_gates_yaml(gates: tuple[str, ...] = FANOUT_REQUIRED_GATES) -> str:
    return "\n".join(f"    - {gate}" for gate in gates)


def _fanout_policy_yaml(
    *,
    gates: tuple[str, ...] = FANOUT_REQUIRED_GATES,
    status: str = "guarded_public_fanout",
    target_surfaces: tuple[str, ...] = ("omg-lol-weblog-bearer-fanout", "omg-weblog"),
    publication_allowed_without_bus: str = "false",
    direct_public_egress_allowed: str = "false",
    review_required: str = "Claim Verification Council",
    claim_ceiling: str = "Repeat only already-approved public artifacts.",
) -> str:
    surfaces_yaml = "\n".join(f"    - {surface}" for surface in target_surfaces)
    return (
        "publication_frontmatter_policy:\n"
        f"  status: {status}\n"
        f"  publication_allowed_without_bus: {publication_allowed_without_bus}\n"
        f"  direct_public_egress_allowed: {direct_public_egress_allowed}\n"
        f"  review_required: {review_required}\n"
        "  target_surfaces:\n"
        f"{surfaces_yaml}\n"
        f"  claim_ceiling: {claim_ceiling}\n"
        "  required_gates:\n"
        f"{_required_gates_yaml(gates)}\n"
    )


def _config(
    *,
    addresses: list[str] | None = None,
    required_gates: list[str] | None = None,
    gate_policy_error: str | None = None,
    publication_policy_verified: bool = True,
    expected_head_sha: str | None = "a" * 40,
) -> OmgFanoutConfig:
    return OmgFanoutConfig(
        addresses=addresses if addresses is not None else ["hapax", "oudepode"],
        required_gates=required_gates
        if required_gates is not None
        else list(FANOUT_REQUIRED_GATES),
        gate_policy_error=gate_policy_error,
        publication_policy_verified=publication_policy_verified,
        expected_head_sha=expected_head_sha,
    )


class TestLoadFanoutConfig:
    def test_loads_addresses_list(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text(_fanout_policy_yaml() + "addresses:\n  - hapax\n  - oudepode\n")
        config = load_fanout_config(path=path)
        assert config.addresses == ["hapax", "oudepode"]
        assert config.required_gates == list(FANOUT_REQUIRED_GATES)
        assert config.gate_policy_error is None
        assert config.publication_policy_verified is True

    def test_loads_expected_head_sha(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text(
            _fanout_policy_yaml() + "expected_head_sha: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
            "addresses:\n"
            "  - hapax\n"
            "  - oudepode\n"
        )
        config = load_fanout_config(path=path)
        assert config.expected_head_sha == "a" * 40

    def test_incomplete_gate_policy_is_fail_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text(
            _fanout_policy_yaml(gates=("source_artifact_public_safe", "source_refs_present"))
            + "addresses:\n"
            "  - hapax\n"
            "  - oudepode\n"
        )
        config = load_fanout_config(path=path)
        assert config.required_gates == list(FANOUT_REQUIRED_GATES)
        assert config.gate_policy_error is not None
        assert "rights_privacy_redaction_pass" in config.gate_policy_error
        assert config.publication_policy_verified is False

    def test_malformed_gate_policy_is_fail_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text(
            _fanout_policy_yaml(gates=(*FANOUT_REQUIRED_GATES, "")) + "addresses:\n"
            "  - hapax\n"
            "  - oudepode\n"
        )
        config = load_fanout_config(path=path)
        assert config.required_gates == list(FANOUT_REQUIRED_GATES)
        assert config.gate_policy_error is not None
        assert "blank or non-string" in config.gate_policy_error
        assert config.publication_policy_verified is False

    @pytest.mark.parametrize(
        ("policy", "expected"),
        (
            (_fanout_policy_yaml(status="guarded_public_channel"), "status"),
            (_fanout_policy_yaml(publication_allowed_without_bus="true"), "publication_allowed"),
            (_fanout_policy_yaml(direct_public_egress_allowed="true"), "direct_public"),
            (_fanout_policy_yaml(review_required="review-later"), "review_required"),
            (_fanout_policy_yaml(target_surfaces=("omg-weblog",)), "target_surfaces"),
            (_fanout_policy_yaml(claim_ceiling=""), "claim_ceiling"),
        ),
    )
    def test_incomplete_publication_policy_shape_is_fail_closed(
        self,
        tmp_path: Path,
        policy: str,
        expected: str,
    ) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text(
            policy + "addresses:\n" + "  - hapax\n" + "  - oudepode\n",
            encoding="utf-8",
        )

        config = load_fanout_config(path=path)

        assert config.gate_policy_error is not None
        assert expected in config.gate_policy_error
        assert config.publication_policy_verified is False

    def test_malformed_addresses_are_fail_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text(_fanout_policy_yaml() + "addresses:\n  - hapax\n  - ../escape\n  - 12\n")
        config = load_fanout_config(path=path)
        assert config.addresses == ["hapax"]
        assert config.gate_policy_error is not None
        assert "malformed address ids" in config.gate_policy_error

    def test_duplicate_addresses_are_fail_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text(
            _fanout_policy_yaml() + "addresses:\n  - hapax\n  - oudepode\n  - oudepode\n"
        )
        config = load_fanout_config(path=path)
        assert config.addresses == ["hapax", "oudepode", "oudepode"]
        assert config.gate_policy_error is not None
        assert "duplicate address ids: oudepode" in config.gate_policy_error

    def test_missing_file_returns_empty_config(self, tmp_path: Path) -> None:
        config = load_fanout_config(path=tmp_path / "missing.yaml")
        assert config.addresses == []

    def test_empty_yaml_returns_empty_config(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text("")
        config = load_fanout_config(path=path)
        assert config.addresses == []

    def test_malformed_yaml_is_fail_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text("addresses: [")
        config = load_fanout_config(path=path)
        assert config.gate_policy_error is not None
        assert "YAML is malformed" in config.gate_policy_error
        assert "next action" in config.gate_policy_error

    def test_non_mapping_yaml_is_fail_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text("- hapax\n")
        config = load_fanout_config(path=path)
        assert config.gate_policy_error is not None
        assert "must be a mapping" in config.gate_policy_error


class TestFanout:
    def test_posts_to_every_target_except_source(self) -> None:
        client = _make_client()
        config = _config(addresses=["hapax", "oudepode", "third"])
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
        config = _config(addresses=["hapax"])
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

    def test_loop_prevention_skips_already_fanned_out_content(self, caplog) -> None:
        client = _make_client()
        config = _config()
        # Content already contains the fanout-source header
        body = f"{FANOUT_LOOP_HEADER_PREFIX} hapax -->\nthis entry already came from hapax fanout\n"
        counter = omg_rss_fanout.omg_fanouts_total.labels(
            source="oudepode",
            target="hapax",
            result="loop-skipped",
        )
        before = counter._value.get()
        with caplog.at_level("WARNING", logger=omg_rss_fanout.__name__):
            result = fanout(
                source_address="oudepode",  # different "source" but body still has header
                entry_id="entry-1",
                content=body,
                config=config,
                client=client,
            )
        # Skipped due to loop-prevention
        client.set_entry.assert_not_called()
        assert result == {"hapax": "loop-skipped"}
        assert counter._value.get() == before + 1
        assert "loop-prevention header detected" in caplog.text
        assert "next action" in caplog.text

    @pytest.mark.parametrize(
        ("source_address", "entry_id", "addresses", "expected"),
        (
            (
                "../escape",
                "entry-1",
                ["hapax", "oudepode"],
                {"hapax": "gate-policy-blocked", "oudepode": "gate-policy-blocked"},
            ),
            ("hapax", "../escape", ["hapax", "oudepode"], {"oudepode": "gate-policy-blocked"}),
            ("hapax", "entry-1", ["hapax", "../escape"], {"../escape": "gate-policy-blocked"}),
            (
                "hapax",
                "entry-1",
                ["hapax", "oudepode", "oudepode"],
                {"oudepode": "gate-policy-blocked"},
            ),
        ),
    )
    def test_loop_prevention_does_not_mask_fanout_policy_errors(
        self,
        source_address: str,
        entry_id: str,
        addresses: list[str],
        expected: dict[str, str],
    ) -> None:
        client = _make_client()
        config = _config(addresses=addresses)
        body = f"{FANOUT_LOOP_HEADER_PREFIX} hapax -->\nreplayed body\n"

        result = fanout(
            source_address=source_address,
            entry_id=entry_id,
            content=body,
            config=config,
            client=client,
        )

        assert result == expected
        client.set_entry.assert_not_called()

    def test_disabled_client_short_circuits(self) -> None:
        client = _make_client(enabled=False)
        config = _config()
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
        config = _config()
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
        config = _config()
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
        config = _config(addresses=[])
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
        config = _config()
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

    def test_duplicate_targets_block_before_public_egress(self) -> None:
        client = _make_client()
        config = _config(addresses=["hapax", "oudepode", "oudepode"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="body",
            config=config,
            client=client,
            gate_receipts=_gate_receipts(targets=("oudepode",)),
        )
        assert result == {"oudepode": "gate-policy-blocked"}
        client.set_entry.assert_not_called()

    def test_malformed_target_blocks_before_public_egress(self) -> None:
        client = _make_client()
        config = _config(addresses=["hapax", "../escape"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="body",
            config=config,
            client=client,
            gate_receipts=_gate_receipts(targets=("../escape",)),
        )
        assert result == {"../escape": "gate-policy-blocked"}
        client.set_entry.assert_not_called()

    @pytest.mark.parametrize("entry_id", ("../escape", "entry?draft=true", "entry#frag", ""))
    def test_malformed_entry_id_blocks_before_public_egress(self, entry_id: str) -> None:
        client = _make_client()
        config = _config()
        result = fanout(
            source_address="hapax",
            entry_id=entry_id,
            content="body",
            config=config,
            client=client,
            gate_receipts=_gate_receipts(entry_id=entry_id),
        )
        assert result == {"oudepode": "gate-policy-blocked"}
        client.set_entry.assert_not_called()

    def test_direct_config_cannot_weaken_required_gates(self) -> None:
        client = _make_client()
        config = _config(required_gates=[])
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

    def test_unknown_required_gate_id_blocks_before_public_egress(self) -> None:
        client = _make_client()
        config = _config(
            required_gates=[*FANOUT_REQUIRED_GATES, "Source_Artifact_Public_Safe"],
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

    def test_unbound_gate_receipts_block_before_public_egress(self) -> None:
        client = _make_client()
        config = _config()
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

    def test_gate_receipts_for_unexpected_head_block_before_public_egress(self) -> None:
        client = _make_client()
        config = _config(expected_head_sha="b" * 40)
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="hello",
            config=config,
            client=client,
            gate_receipts=_gate_receipts(),
        )
        assert result == {"oudepode": "gate-blocked"}
        client.set_entry.assert_not_called()

    def test_forged_gate_receipts_block_before_public_egress(self) -> None:
        client = _make_client()
        config = _config()
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
        config = _config(
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

    def test_unverified_direct_config_blocks_before_public_egress(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"])
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
