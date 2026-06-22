"""AVSDLC enforcement — Tier-C verified runtime-media witness receipts.

Closes the self-attestation hole in ``shared.release_gate``: the runtime-media
witness must resolve to an HMAC-signed ``AVWitnessReceipt`` (independent
executor, content-hash + active-source-head bound, OBS-MOVING required) — a
forged / stale / RED / OBS-frozen receipt no longer passes. Real AV *source*
path mutations (compositor/shader/quake) can no longer opt out of the gate by
declaring ``avsdlc_axes: none``.

The hard rejection of legacy plain-string attestation is staged behind
``require_signed_witness`` (default off until the runtime-witness daemon is
proven emitting in production) so the gate never wedges live AV merges.

cc-task: avsdlc-enforcement-witness-v1 (CASE-AVSDLC-ENFORCEMENT-20260621).
Self-contained per workspace test convention.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from shared.governance.coord_capabilities import (
    AVWitnessReceipt,
    mint_av_witness_receipt,
    parse_av_receipt,
    read_av_receipt_file,
    serialize_av_receipt,
    verify_av_witness_receipt,
)
from shared.release_gate import evaluate_avsdlc_release_gate

KEY = b"operator-secret-key-0123456789abcdef"
WRONG_KEY = b"attacker-key-0000000000000000000000"
NOW = 1_800_000_000.0
CONTENT_HASH = "a" * 64
SOURCE_HEAD = "9757f7bde0363d9e3ca0a7692bb172b2a02084ea"


def _pass_receipt(now: float = NOW, ttl_s: float = 3600.0) -> AVWitnessReceipt:
    return mint_av_witness_receipt(
        content_hash=CONTENT_HASH,
        active_source_head=SOURCE_HEAD,
        status="pass",
        obs_moving=True,
        ttl_s=ttl_s,
        key=KEY,
        now=now,
    )


# ── AVWitnessReceipt model ────────────────────────────────────────────


class TestAVWitnessReceipt:
    def test_pass_receipt_verifies(self) -> None:
        receipt = _pass_receipt()
        assert verify_av_witness_receipt(receipt, key=KEY, now=NOW + 60)

    def test_forged_field_rejected(self) -> None:
        receipt = _pass_receipt()
        forged = replace(receipt, content_hash="b" * 64)  # rebind without re-signing
        assert not verify_av_witness_receipt(forged, key=KEY, now=NOW + 60)

    def test_wrong_key_rejected(self) -> None:
        receipt = _pass_receipt()
        assert not verify_av_witness_receipt(receipt, key=WRONG_KEY, now=NOW + 60)

    def test_expired_rejected(self) -> None:
        receipt = _pass_receipt(ttl_s=300.0)
        assert not verify_av_witness_receipt(receipt, key=KEY, now=NOW + 600)

    def test_red_status_rejected(self) -> None:
        receipt = mint_av_witness_receipt(
            content_hash=CONTENT_HASH,
            active_source_head=SOURCE_HEAD,
            status="fail",
            obs_moving=True,
            ttl_s=3600.0,
            key=KEY,
            now=NOW,
        )
        assert not verify_av_witness_receipt(receipt, key=KEY, now=NOW + 60)

    def test_obs_frozen_rejected(self) -> None:
        # status says pass but OBS was not moving → did not reach air → not a pass.
        receipt = mint_av_witness_receipt(
            content_hash=CONTENT_HASH,
            active_source_head=SOURCE_HEAD,
            status="pass",
            obs_moving=False,
            ttl_s=3600.0,
            key=KEY,
            now=NOW,
        )
        assert not verify_av_witness_receipt(receipt, key=KEY, now=NOW + 60)

    def test_content_hash_match_ok(self) -> None:
        receipt = _pass_receipt()
        assert verify_av_witness_receipt(receipt, key=KEY, now=NOW + 60, content_hash=CONTENT_HASH)

    def test_content_hash_mismatch_rejected(self) -> None:
        receipt = _pass_receipt()
        assert not verify_av_witness_receipt(receipt, key=KEY, now=NOW + 60, content_hash="c" * 64)

    def test_file_roundtrip_verifies(self, tmp_path: Path) -> None:
        receipt = _pass_receipt()
        path = tmp_path / "receipt.json"
        path.write_text(serialize_av_receipt(receipt))
        loaded = read_av_receipt_file(path)
        assert loaded is not None
        assert verify_av_witness_receipt(loaded, key=KEY, now=NOW + 60)

    def test_read_missing_file_none(self, tmp_path: Path) -> None:
        assert read_av_receipt_file(tmp_path / "nope.json") is None

    def test_parse_malformed_none(self) -> None:
        assert parse_av_receipt("{not valid json") is None
        assert parse_av_receipt('{"kind":"escape"}') is None

    def test_verify_none_false(self) -> None:
        assert verify_av_witness_receipt(None, key=KEY, now=NOW) is False


# ── gate: runtime-media witness is now receipt-verified ───────────────


def _base_av_fm(witness: str) -> dict:
    return {
        "avsdlc_axes": ["audiovisual"],
        "avsdlc_dossier": "docs/evidence/av.md",
        "audiovisual_witness": "artifacts/sync.md",
        "avsdlc_evidence_collected_at": NOW,
        "runtime_media_impact": True,
        "runtime_media_witness": witness,
    }


class TestRuntimeMediaWitnessVerification:
    def test_signed_pass_receipt_satisfies_gate(self, tmp_path: Path) -> None:
        path = tmp_path / "receipt.json"
        path.write_text(serialize_av_receipt(_pass_receipt()))
        result = evaluate_avsdlc_release_gate(_base_av_fm(str(path)), now=NOW + 60, key=KEY)
        assert result.passed, result.blockers
        assert "missing:runtime_media_witness" not in result.blockers

    def test_forged_receipt_blocks(self, tmp_path: Path) -> None:
        forged = mint_av_witness_receipt(
            content_hash=CONTENT_HASH,
            active_source_head=SOURCE_HEAD,
            status="pass",
            obs_moving=True,
            ttl_s=3600.0,
            key=WRONG_KEY,  # signed by an attacker key
            now=NOW,
        )
        path = tmp_path / "forged.json"
        path.write_text(serialize_av_receipt(forged))
        result = evaluate_avsdlc_release_gate(_base_av_fm(str(path)), now=NOW + 60, key=KEY)
        assert not result.passed
        assert "missing:runtime_media_witness" in result.blockers

    def test_red_receipt_blocks(self, tmp_path: Path) -> None:
        red = mint_av_witness_receipt(
            content_hash=CONTENT_HASH,
            active_source_head=SOURCE_HEAD,
            status="fail",
            obs_moving=False,
            ttl_s=3600.0,
            key=KEY,
            now=NOW,
        )
        path = tmp_path / "red.json"
        path.write_text(serialize_av_receipt(red))
        result = evaluate_avsdlc_release_gate(_base_av_fm(str(path)), now=NOW + 60, key=KEY)
        assert not result.passed
        assert "missing:runtime_media_witness" in result.blockers

    def test_legacy_string_accepted_when_not_strict(self) -> None:
        result = evaluate_avsdlc_release_gate(
            _base_av_fm("artifacts/live-witness.md"),
            now=NOW + 60,
            key=KEY,
            require_signed_witness=False,
        )
        assert result.passed, result.blockers

    def test_legacy_string_rejected_when_strict(self) -> None:
        result = evaluate_avsdlc_release_gate(
            _base_av_fm("artifacts/live-witness.md"),
            now=NOW + 60,
            key=KEY,
            require_signed_witness=True,
        )
        assert not result.passed
        assert "missing:runtime_media_witness" in result.blockers


# ── gate: AV source-path mutation cannot opt out of the gate ──────────


class TestNoAxesOptOutClosedForAvSourcePaths:
    def test_av_source_path_cannot_optout_with_no_axes(self) -> None:
        result = evaluate_avsdlc_release_gate(
            {
                "avsdlc_axes": "none",
                "mutation_scope_refs": ["agents/studio_compositor/layout.py"],
            }
        )
        assert result.required
        assert not result.passed
        assert "avsdlc_axes_missing:visual" in result.blockers

    def test_non_av_test_path_no_axes_still_passes(self) -> None:
        # Regression guard: a test file under tests/ that merely mentions audio
        # must keep the explicit no-axes opt-out (does not touch the live surface).
        result = evaluate_avsdlc_release_gate(
            {
                "avsdlc_axes": "none",
                "tags": ["audio"],
                "mutation_scope_refs": ["tests/shared/test_audio_routing_policy.py"],
            }
        )
        assert result.passed
        assert not result.required

    def test_test_substring_in_filename_not_excluded(self) -> None:
        # M1: "latest_layout.py" contains the substring "test" but is a real AV
        # source file — segment matching must not treat it as a test file.
        result = evaluate_avsdlc_release_gate(
            {
                "avsdlc_axes": "none",
                "mutation_scope_refs": ["agents/studio_compositor/latest_layout.py"],
            }
        )
        assert result.required
        assert "avsdlc_axes_missing:visual" in result.blockers

    def test_docs_md_with_av_word_not_overblocked(self) -> None:
        # M2: a docs/*.md file whose name contains "compositor" is not an AV
        # source mutation — the no-axes opt-out must hold.
        result = evaluate_avsdlc_release_gate(
            {
                "avsdlc_axes": "none",
                "mutation_scope_refs": ["docs/compositor-design-notes.md"],
            }
        )
        assert result.passed
        assert not result.required

    def test_tooling_substring_not_overblocked(self) -> None:
        # M2: a tooling file whose NAME contains an AV word but whose path has no
        # AV segment/extension is not an AV source mutation.
        result = evaluate_avsdlc_release_gate(
            {
                "avsdlc_axes": "none",
                "mutation_scope_refs": ["agents/imagination/pipewire_probe.py"],
            }
        )
        assert result.passed
        assert not result.required


# ── security hardening: empty key, content-hash binding, mode visibility ──


class TestReceiptHardening:
    def test_empty_key_does_not_verify(self) -> None:
        # C1: an absent coord key (b"") must HARD-FAIL verification, not let an
        # attacker reproduce an empty-key HMAC.
        receipt = mint_av_witness_receipt(
            content_hash=CONTENT_HASH,
            active_source_head=SOURCE_HEAD,
            status="pass",
            obs_moving=True,
            ttl_s=3600.0,
            key=b"",
            now=NOW,
        )
        assert not verify_av_witness_receipt(receipt, key=b"", now=NOW + 60)

    def test_empty_content_hash_receipt_rejected(self) -> None:
        # A witness that could not see the deployed bytes (empty content hash) is
        # not a pass, even with a valid signature.
        receipt = mint_av_witness_receipt(
            content_hash="",
            active_source_head=SOURCE_HEAD,
            status="pass",
            obs_moving=True,
            ttl_s=3600.0,
            key=KEY,
            now=NOW,
        )
        assert not verify_av_witness_receipt(receipt, key=KEY, now=NOW + 60)

    def test_tamper_any_field_rejected(self) -> None:
        # M5: tampering ANY signed field (not just content_hash) must fail.
        receipt = _pass_receipt()
        for field, value in (
            ("content_hash", "b" * 64),
            ("active_source_head", "deadbeef"),
            ("status", "fail"),
            ("obs_moving", False),
            ("collected_at", NOW + 5),
            ("expires_at", NOW + 9_999_999),
            ("receipt_id", "forged-id"),
        ):
            forged = replace(receipt, **{field: value})
            assert not verify_av_witness_receipt(forged, key=KEY, now=NOW + 60), (
                f"tampering {field} should fail verification"
            )


class TestContentHashBindingAtGate:
    def test_declared_hash_mismatch_blocks(self, tmp_path: Path) -> None:
        # C2: a genuine fresh PASS receipt for bytes A must NOT release a task
        # that declares it deployed bytes B (no cross-bytes replay).
        path = tmp_path / "receipt.json"
        path.write_text(serialize_av_receipt(_pass_receipt()))  # content_hash = "a"*64
        fm = _base_av_fm(str(path))
        fm["avsdlc_content_hash"] = "b" * 64
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY)
        assert not result.passed
        assert "missing:runtime_media_witness" in result.blockers

    def test_declared_hash_match_passes(self, tmp_path: Path) -> None:
        path = tmp_path / "receipt.json"
        path.write_text(serialize_av_receipt(_pass_receipt()))
        fm = _base_av_fm(str(path))
        fm["avsdlc_content_hash"] = "a" * 64
        result = evaluate_avsdlc_release_gate(fm, now=NOW + 60, key=KEY)
        assert result.passed, result.blockers

    def test_strict_mode_requires_declared_content_hash(self, tmp_path: Path) -> None:
        # In strict mode a receipt with no declared expected hash is a replay
        # oracle → must block until the task declares the deployed bytes.
        path = tmp_path / "receipt.json"
        path.write_text(serialize_av_receipt(_pass_receipt()))
        result = evaluate_avsdlc_release_gate(
            _base_av_fm(str(path)), now=NOW + 60, key=KEY, require_signed_witness=True
        )
        assert not result.passed
        assert "missing:runtime_media_witness" in result.blockers

    def test_strict_mode_with_declared_matching_hash_passes(self, tmp_path: Path) -> None:
        path = tmp_path / "receipt.json"
        path.write_text(serialize_av_receipt(_pass_receipt()))
        fm = _base_av_fm(str(path))
        fm["avsdlc_content_hash"] = "a" * 64
        result = evaluate_avsdlc_release_gate(
            fm, now=NOW + 60, key=KEY, require_signed_witness=True
        )
        assert result.passed, result.blockers


class TestDegradedModeVisibility:
    def test_legacy_acceptance_is_flagged(self) -> None:
        # HIGH-1: when an unsigned legacy string is accepted (staged rollout),
        # the result must mark it so the operator can see verification is not
        # being enforced.
        result = evaluate_avsdlc_release_gate(
            _base_av_fm("artifacts/live-witness.md"),
            now=NOW + 60,
            key=KEY,
            require_signed_witness=False,
        )
        assert result.passed
        assert result.witness_unverified_legacy

    def test_verified_receipt_not_flagged_legacy(self, tmp_path: Path) -> None:
        path = tmp_path / "receipt.json"
        path.write_text(serialize_av_receipt(_pass_receipt()))
        result = evaluate_avsdlc_release_gate(_base_av_fm(str(path)), now=NOW + 60, key=KEY)
        assert result.passed, result.blockers
        assert not result.witness_unverified_legacy
