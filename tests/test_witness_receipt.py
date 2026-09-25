"""A witness receipt is produced only for a validated, independent, in-window, signed witness act.

The receipt is the existing review-dossier shape, so the existing public-gate resolver accepts it,
bound to one artifact's fingerprint and nonce. Every refusal writes nothing.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from shared import witness_receipt as wr
from shared.public_gate_receipts import (
    public_gate_authority_signature,
    public_gate_receipt_ref_exists,
)
from shared.signing_holder import SigningRefused
from shared.witness_receipt import GATE, Produced, Verdict, produce

SECRET = "test-secret-not-a-real-key"
DIGEST = hashlib.sha256(b"the artifact as the recipient decodes it").hexdigest()
OTHER_DIGEST = hashlib.sha256(b"a different artifact").hexdigest()
NONCE = "0123456789abcdef0123"
HEAD = "b" * 40
T0 = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)
NOW = T0 + timedelta(hours=1)
GEMINI = Verdict("gemini/rota-1", "gemini", "VALIDATED", NOW)
CODEX = Verdict("codex/rota-2", "codex", "VALIDATED", NOW)


def sign(payload: Any) -> str:
    return public_gate_authority_signature(payload, SECRET)


@pytest.fixture
def evidence_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    (root / "note.md").write_text("audience, channel norms, reception scenarios\n")
    return root


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    out = tmp_path / "witness"
    out.mkdir()
    return out


def record(evidence_root: Path, **overrides: Any) -> dict[str, Any]:
    note = (evidence_root / "note.md").read_bytes()
    base: dict[str, Any] = {
        "artifact_fingerprint": DIGEST,
        "nonce": NONCE,
        "policy_ref": "public-gate:cp-artifact-1",
        "audience": "reviewers of the public pull request",
        "channel": "forge",
        "not_before": "2026-09-25T08:00:00Z",
        "not_after": "2026-09-25T20:00:00Z",
        "expected_head_sha": HEAD,
        "author": "claude/dev32",
        "author_family": "claude",
        "tier": "B",
        "evidence_refs": [{"path": "note.md", "sha256": hashlib.sha256(note).hexdigest()}],
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def run(
    evidence_root: Path, out_dir: Path, verdicts=(GEMINI,), *, now=NOW, rec=None, **kw
) -> Produced:
    return produce(
        rec if rec is not None else record(evidence_root),
        list(verdicts),
        out_dir,
        evidence_root=evidence_root,
        now=now,
        sign=kw.pop("sign", sign),
        **kw,
    )


def assert_refused(result: Produced, out_dir: Path) -> None:
    assert result.path is None
    assert result.refusals
    assert all("next action:" in refusal for refusal in result.refusals), result.refusals
    assert list(out_dir.iterdir()) == []


# --- a validated, independent witness produces a signed dossier ---


def test_a_validated_non_author_witness_produces_a_signed_receipt(evidence_root, out_dir) -> None:
    result = run(evidence_root, out_dir)
    assert result.refusals == [] and result.path is not None
    data = yaml.safe_load(result.path.read_text())
    assert result.path.name == f"{data['task_id']}.review-dossier.yaml"
    assert data["dossier_schema"] == 1
    assert data["artifact_fingerprint"] == DIGEST and data["nonce"] == NONCE
    assert data["authority_signature"] == sign(data)


def _receipt(receipts: Path, fingerprint: str, task_id: str) -> None:
    receipts.mkdir(exist_ok=True)
    (receipts / "cp-artifact-1.yaml").write_text(
        yaml.safe_dump(
            {
                "gate": GATE,
                "status": "pass",
                "authority_case": "CASE-SYSTEM-INTEGRITY-20260611",
                "accepted_by": "review-team:witness-rota",
                "review_profile": "communication-pathway-tier-b",
                "evidence_refs": [f"dossier:{task_id}"],
                "artifact_fingerprint": fingerprint,
                "nonce": NONCE,
            }
        )
    )


def _resolves(receipts: Path, out_dir: Path, fingerprint: str) -> bool:
    return public_gate_receipt_ref_exists(
        "public-gate:cp-artifact-1",
        expected_gate=GATE,
        roots=[receipts],
        bindings={"artifact_fingerprint": fingerprint, "nonce": NONCE},
        authority_roots=[out_dir],
        authority_secret=SECRET,
        expected_head_sha=HEAD,
    )


def test_the_existing_resolver_accepts_the_receipt(evidence_root, out_dir, tmp_path) -> None:
    result = run(evidence_root, out_dir)
    assert result.path is not None
    task_id = yaml.safe_load(result.path.read_text())["task_id"]
    _receipt(tmp_path / "receipts", DIGEST, task_id)
    assert _resolves(tmp_path / "receipts", out_dir, DIGEST)


def test_the_resolver_refuses_the_receipt_for_another_artifact(
    evidence_root, out_dir, tmp_path
) -> None:
    result = run(evidence_root, out_dir)
    assert result.path is not None
    task_id = yaml.safe_load(result.path.read_text())["task_id"]
    _receipt(tmp_path / "receipts", OTHER_DIGEST, task_id)
    assert not _resolves(tmp_path / "receipts", out_dir, OTHER_DIGEST)


# --- U3: the witness is independent of the author ---


def test_the_author_cannot_witness_their_own_record(evidence_root, out_dir) -> None:
    own = Verdict("claude/dev32", "gemini", "VALIDATED", NOW)
    assert_refused(run(evidence_root, out_dir, [own]), out_dir)


def test_a_witness_of_the_authors_family_is_refused(evidence_root, out_dir) -> None:
    same_family = Verdict("claude/dev7", "claude", "VALIDATED", NOW)
    assert_refused(run(evidence_root, out_dir, [same_family]), out_dir)


def test_a_witness_outside_the_independent_families_is_refused(evidence_root, out_dir) -> None:
    uncounted = Verdict("kimi/rota-3", "kimi", "VALIDATED", NOW)
    assert_refused(run(evidence_root, out_dir, [uncounted]), out_dir)


def test_only_qualifying_witnesses_are_listed(evidence_root, out_dir) -> None:
    own = Verdict("claude/dev32", "gemini", "VALIDATED", NOW)
    seen = Verdict("codex/rota-4", "codex", "SEEN", NOW)
    result = run(evidence_root, out_dir, [own, GEMINI, seen])
    assert result.path is not None
    reviewers = yaml.safe_load(result.path.read_text())["reviewers"]
    assert [r["witness"] for r in reviewers] == [GEMINI.witness]


def test_a_seen_verdict_produces_nothing(evidence_root, out_dir) -> None:
    seen = Verdict("gemini/rota-1", "gemini", "SEEN", NOW)
    assert_refused(run(evidence_root, out_dir, [seen]), out_dir)


# --- quorum per tier ---


def test_tier_a_needs_two_independent_families(evidence_root, out_dir) -> None:
    rec = record(evidence_root, tier="A")
    assert_refused(run(evidence_root, out_dir, [GEMINI], rec=rec), out_dir)
    result = run(evidence_root, out_dir, [GEMINI, CODEX], rec=rec)
    assert result.path is not None
    data = yaml.safe_load(result.path.read_text())
    assert data["quorum_required"] == 2 and data["accept_count"] == 2


def test_two_witnesses_of_one_family_count_once(evidence_root, out_dir) -> None:
    rec = record(evidence_root, tier="A")
    twin = Verdict("gemini/rota-9", "gemini", "VALIDATED", NOW)
    assert_refused(run(evidence_root, out_dir, [GEMINI, twin], rec=rec), out_dir)


def test_tier_b_needs_one(evidence_root, out_dir) -> None:
    result = run(evidence_root, out_dir)
    assert result.path is not None
    data = yaml.safe_load(result.path.read_text())
    assert data["quorum_required"] == 1 and data["accept_count"] == 1


# --- U4: the validity window ---


@pytest.mark.parametrize("now", [T0 - timedelta(seconds=1), T0 + timedelta(hours=12, seconds=1)])
def test_a_record_outside_its_window_produces_nothing(evidence_root, out_dir, now) -> None:
    late = Verdict("gemini/rota-1", "gemini", "VALIDATED", T0 + timedelta(hours=1))
    assert_refused(run(evidence_root, out_dir, [late], now=now), out_dir)


def test_a_verdict_outside_the_window_is_refused(evidence_root, out_dir) -> None:
    early = Verdict("gemini/rota-1", "gemini", "VALIDATED", T0 - timedelta(minutes=5))
    assert_refused(run(evidence_root, out_dir, [early]), out_dir)


def test_a_verdict_after_the_production_time_is_refused(evidence_root, out_dir) -> None:
    future = Verdict("gemini/rota-1", "gemini", "VALIDATED", NOW + timedelta(minutes=5))
    assert_refused(run(evidence_root, out_dir, [future]), out_dir)


def test_an_inverted_window_is_refused(evidence_root, out_dir) -> None:
    rec = record(evidence_root, not_before="2026-09-25T20:00:00Z", not_after="2026-09-25T08:00:00Z")
    assert_refused(run(evidence_root, out_dir, rec=rec), out_dir)


# --- the evidence the witness saw is the evidence recorded ---


def test_evidence_changed_since_the_record_is_refused(evidence_root, out_dir) -> None:
    rec = record(evidence_root)
    (evidence_root / "note.md").write_text("edited after the record\n")
    assert_refused(run(evidence_root, out_dir, rec=rec), out_dir)


@pytest.mark.parametrize("relative", [True, False])
def test_evidence_outside_the_evidence_root_is_refused(
    evidence_root, out_dir, tmp_path, relative
) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("real evidence, outside the root\n")
    path = "../outside.md" if relative else str(outside)
    sha = hashlib.sha256(outside.read_bytes()).hexdigest()
    rec = record(evidence_root, evidence_refs=[{"path": path, "sha256": sha}])
    assert_refused(run(evidence_root, out_dir, rec=rec), out_dir)


def test_a_record_without_evidence_is_refused(evidence_root, out_dir) -> None:
    assert_refused(
        run(evidence_root, out_dir, rec=record(evidence_root, evidence_refs=[])), out_dir
    )


# --- a malformed record is refused ---


@pytest.mark.parametrize(
    "overrides",
    [
        {"artifact_fingerprint": None},
        {"artifact_fingerprint": "not-a-digest"},
        {"nonce": None},
        {"nonce": "short"},
        {"nonce": "../../etc"},
        {"expected_head_sha": "abc"},
        {"policy_ref": "cp-artifact-1"},
        {"tier": "C"},
        {"author": None},
        {"author_family": None},
        {"not_after": "tomorrow"},
        {"audience": None},
        {"channel": None},
    ],
)
def test_a_malformed_record_is_refused(evidence_root, out_dir, overrides) -> None:
    assert_refused(run(evidence_root, out_dir, rec=record(evidence_root, **overrides)), out_dir)


# --- signing and writing ---


def test_a_refused_signature_writes_nothing(evidence_root, out_dir) -> None:
    def refusing(payload: Any) -> str:
        raise SigningRefused("refused: caller cgroup is not the witness rota unit")

    assert_refused(run(evidence_root, out_dir, sign=refusing), out_dir)


def test_a_second_receipt_for_the_same_record_is_refused(evidence_root, out_dir) -> None:
    first = run(evidence_root, out_dir)
    assert first.path is not None
    before = first.path.read_bytes()
    second = run(evidence_root, out_dir, [CODEX])
    assert second.path is None and second.refusals
    assert first.path.read_bytes() == before


def test_the_default_signer_is_the_holder(evidence_root, out_dir, monkeypatch) -> None:
    calls: list[Any] = []

    def holder(payload: Any) -> str:
        calls.append(payload)
        return sign(payload)

    monkeypatch.setattr(wr, "request_signature", holder)
    result = produce(record(evidence_root), [GEMINI], out_dir, evidence_root=evidence_root, now=NOW)
    assert result.path is not None and len(calls) == 1
