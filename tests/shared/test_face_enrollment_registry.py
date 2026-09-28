"""Tests for the per-principal face enrollment registry.

Pin the six non-negotiable invariants from the parent spec
(per-person consent matcher):

1. No biometric embedding without active consent contract.
2. Embeddings stay local. Never egressed; not returned by enumeration.
3. Single-shot capture per enrollment ceremony.
4. Match results are non-persistent (no logged biometric metadata).
5. Fail-closed under uncertainty (no face / low confidence /
   model unavailable / wrong shape → None).
6. ``revoke_enrollment(principal)`` ships before the matcher gate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from shared import face_enrollment_registry as registry  # noqa: E402
from shared.face_enrollment_registry import (  # noqa: E402
    DEFAULT_MATCH_THRESHOLD,
    EMBEDDING_DIM,
    ENROLL_SCOPE,
    FaceEnrollmentError,
    enroll_principal,
    list_enrollments,
    load_enrollment,
    match_principal,
    revoke_enrollment,
)
from tests.shared.synthetic_custody import OLD_PRINCIPAL, PRINCIPAL  # noqa: E402


@dataclass
class _StubContract:
    parties: tuple[str, str]
    scope: frozenset[str] = field(default_factory=frozenset)


@dataclass
class _StubConsent:
    """Minimum surface for the registry's consent check."""

    contracts: dict[str, _StubContract] = field(default_factory=dict)

    def contract_check(self, person_id: str, data_category: str) -> bool:
        contract = self.contracts.get(person_id)
        return contract is not None and data_category in contract.scope

    def grant(self, person_id: str, scope: str = ENROLL_SCOPE) -> None:
        self.contracts[person_id] = _StubContract(
            parties=("operator", person_id), scope=frozenset({scope})
        )


def _embedding(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    return vec / max(1e-6, float(np.linalg.norm(vec)))


# ── Invariant 1: no embedding without active consent ────────────────────


class TestConsentRequired:
    def test_enroll_refuses_without_contract(self, tmp_path: Path) -> None:
        consent = _StubConsent()
        with pytest.raises(FaceEnrollmentError, match="no active"):
            enroll_principal("principal-a1", _embedding(1), consent=consent, root=tmp_path)

    def test_enroll_refuses_with_unrelated_scope(self, tmp_path: Path) -> None:
        consent = _StubConsent()
        consent.grant("principal-a1", scope="something_else")
        with pytest.raises(FaceEnrollmentError, match="no active"):
            enroll_principal("principal-a1", _embedding(1), consent=consent, root=tmp_path)

    def test_enroll_succeeds_with_face_enrollment_scope(self, tmp_path: Path) -> None:
        consent = _StubConsent()
        consent.grant("principal-a1")
        path = enroll_principal("principal-a1", _embedding(1), consent=consent, root=tmp_path)
        assert path.exists()
        assert path.parent == tmp_path


# ── Invariant 2: embeddings stay local; not in enumeration ──────────────


class TestPrivacyFloor:
    def test_list_enrollments_returns_ids_only(self, tmp_path: Path) -> None:
        consent = _StubConsent()
        consent.grant("principal-a1")
        consent.grant("guest")
        enroll_principal("principal-a1", _embedding(1), consent=consent, root=tmp_path)
        enroll_principal("guest", _embedding(2), consent=consent, root=tmp_path)

        result = list_enrollments(root=tmp_path)

        assert result == ["guest", "principal-a1"]
        # Result is plain strings; no embedding content.
        for entry in result:
            assert isinstance(entry, str)

    def test_invalid_principal_id_rejected(self, tmp_path: Path) -> None:
        """Path-traversal-shaped principals are refused at write."""

        consent = _StubConsent()
        consent.grant("../etc/passwd")
        with pytest.raises(FaceEnrollmentError, match="invalid principal_id"):
            enroll_principal("../etc/passwd", _embedding(1), consent=consent, root=tmp_path)

    def test_match_does_not_persist_query_embedding(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A match call leaves no biometric metadata in logs (invariant 4)."""

        consent = _StubConsent()
        consent.grant("principal-a1")
        enroll_principal("principal-a1", _embedding(1), consent=consent, root=tmp_path)

        caplog.set_level(logging.DEBUG, logger="shared.face_enrollment_registry")
        match_principal(_embedding(1), root=tmp_path)

        for record in caplog.records:
            # No log message contains the literal embedding values.
            assert (
                "0." not in record.getMessage().split(" ")[-1] or "Enrolled" in record.getMessage()
            )
            assert "embedding=array" not in record.getMessage()


# ── Invariant 5: fail-closed under uncertainty ──────────────────────────


class TestFailClosed:
    def test_match_returns_none_when_embedding_is_none(self, tmp_path: Path) -> None:
        consent = _StubConsent()
        consent.grant("principal-a1")
        enroll_principal("principal-a1", _embedding(1), consent=consent, root=tmp_path)
        assert match_principal(None, root=tmp_path) is None

    def test_match_returns_none_when_no_enrollments(self, tmp_path: Path) -> None:
        assert match_principal(_embedding(1), root=tmp_path) is None

    def test_match_returns_none_below_threshold(self, tmp_path: Path) -> None:
        """Random embeddings score near zero — well below the 0.40 floor."""

        consent = _StubConsent()
        consent.grant("principal-a1")
        enroll_principal("principal-a1", _embedding(1), consent=consent, root=tmp_path)
        # Different seed → different (orthogonal-ish) vector → low cosine.
        assert match_principal(_embedding(99), root=tmp_path) is None

    def test_match_returns_none_for_wrong_shape(self, tmp_path: Path) -> None:
        consent = _StubConsent()
        consent.grant("principal-a1")
        enroll_principal("principal-a1", _embedding(1), consent=consent, root=tmp_path)
        wrong_shape = np.random.default_rng(0).standard_normal(64).astype(np.float32)
        assert match_principal(wrong_shape, root=tmp_path) is None

    def test_enroll_refuses_wrong_dim(self, tmp_path: Path) -> None:
        consent = _StubConsent()
        consent.grant("principal-a1")
        bad = np.zeros(64, dtype=np.float32)
        with pytest.raises(FaceEnrollmentError, match="shape"):
            enroll_principal("principal-a1", bad, consent=consent, root=tmp_path)

    def test_enroll_refuses_wrong_dtype(self, tmp_path: Path) -> None:
        consent = _StubConsent()
        consent.grant("principal-a1")
        bad = np.zeros(EMBEDDING_DIM, dtype=np.int8)
        with pytest.raises(FaceEnrollmentError, match="dtype"):
            enroll_principal("principal-a1", bad, consent=consent, root=tmp_path)

    def test_load_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert load_enrollment("nobody", root=tmp_path) is None


# ── Match-positive case ────────────────────────────────────────────────


class TestMatchPositive:
    def test_match_returns_principal_for_self(self, tmp_path: Path) -> None:
        """An embedding that matches itself returns its principal id."""

        consent = _StubConsent()
        consent.grant("principal-a1")
        emb = _embedding(7)
        enroll_principal("principal-a1", emb, consent=consent, root=tmp_path)
        assert match_principal(emb, root=tmp_path) == "principal-a1"

    def test_match_picks_highest_when_multiple_above_threshold(self, tmp_path: Path) -> None:
        consent = _StubConsent()
        consent.grant("principal-a1")
        consent.grant("guest")
        primary = _embedding(11)
        # Make ``guest``'s enrolled embedding be a noisy version of primary
        # so cosine similarity is high but lower than self-match.
        rng = np.random.default_rng(0)
        guest_emb = primary + 0.5 * rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        guest_emb = guest_emb / max(1e-6, float(np.linalg.norm(guest_emb)))

        enroll_principal("principal-a1", primary, consent=consent, root=tmp_path)
        enroll_principal("guest", guest_emb, consent=consent, root=tmp_path)

        winner = match_principal(primary, root=tmp_path)
        assert winner == "principal-a1"

    def test_candidates_filter_restricts_pool(self, tmp_path: Path) -> None:
        consent = _StubConsent()
        consent.grant("principal-a1")
        consent.grant("guest")
        emb = _embedding(13)
        enroll_principal("principal-a1", emb, consent=consent, root=tmp_path)
        enroll_principal("guest", emb, consent=consent, root=tmp_path)

        result = match_principal(emb, root=tmp_path, candidates=["guest"])
        assert result == "guest"

    def test_threshold_parameter_governs_floor(self, tmp_path: Path) -> None:
        """Raising the threshold above self-similarity returns None."""

        consent = _StubConsent()
        consent.grant("principal-a1")
        emb = _embedding(19)
        enroll_principal("principal-a1", emb, consent=consent, root=tmp_path)
        # Self-match cosine is ~1.0; threshold 1.5 is unreachable.
        assert match_principal(emb, root=tmp_path, threshold=1.5) is None


# ── Invariant 6: revoke_enrollment ships before any gate ────────────────


class TestRevocation:
    def test_revoke_removes_disk_state(self, tmp_path: Path) -> None:
        consent = _StubConsent()
        consent.grant("principal-a1")
        path = enroll_principal("principal-a1", _embedding(1), consent=consent, root=tmp_path)
        assert path.exists()

        assert revoke_enrollment("principal-a1", root=tmp_path) is True
        assert not path.exists()
        assert load_enrollment("principal-a1", root=tmp_path) is None

    def test_revoke_returns_false_when_no_enrollment(self, tmp_path: Path) -> None:
        assert revoke_enrollment("nobody", root=tmp_path) is False

    def test_revoke_does_not_raise_on_missing_root(self, tmp_path: Path) -> None:
        """Operator must always be able to revoke regardless of disk state."""

        nonexistent = tmp_path / "no-such-dir"
        assert revoke_enrollment("principal-a1", root=nonexistent) is False

    def test_post_revoke_match_returns_none(self, tmp_path: Path) -> None:
        consent = _StubConsent()
        consent.grant("principal-a1")
        emb = _embedding(23)
        enroll_principal("principal-a1", emb, consent=consent, root=tmp_path)
        assert match_principal(emb, root=tmp_path) == "principal-a1"

        revoke_enrollment("principal-a1", root=tmp_path)
        assert match_principal(emb, root=tmp_path) is None


# ── Default values ──────────────────────────────────────────────────────


class TestPublicAPIDefaults:
    def test_default_match_threshold(self) -> None:
        assert pytest.approx(0.40) == DEFAULT_MATCH_THRESHOLD

    def test_default_embedding_dim(self) -> None:
        assert EMBEDDING_DIM == 512

    def test_enroll_scope_constant(self) -> None:
        assert ENROLL_SCOPE == "face_enrollment"


# ── The revocation order contract: the marker is persisted before anything that can fail ──


class TestRevocationOrder:
    def _enroll(self, tmp_path: Path, seed: int = 41) -> np.ndarray:
        consent = _StubConsent()
        consent.grant(PRINCIPAL)
        emb = _embedding(seed)
        enroll_principal(PRINCIPAL, emb, consent=consent, root=tmp_path)
        return emb

    def test_a_failing_scan_still_leaves_the_marker_and_no_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unsafe case: the scan runs first, raises, and the enrollment stays matchable."""
        self._enroll(tmp_path)

        def unreadable(*_args: object, **_kwargs: object) -> list[Path]:
            raise OSError("storage unreadable")

        monkeypatch.setattr(registry, "_matching_enrollment_paths", unreadable)

        with pytest.raises(FaceEnrollmentError):
            revoke_enrollment(PRINCIPAL, root=tmp_path)

        assert (tmp_path / f"{PRINCIPAL}.revoked").exists()
        assert load_enrollment(PRINCIPAL, root=tmp_path) is None

    def test_the_marker_is_written_even_when_nothing_matches(self, tmp_path: Path) -> None:
        """An explicit revocation disables matching for the principal, matched files or not."""
        assert revoke_enrollment(PRINCIPAL, root=tmp_path) is False
        assert (tmp_path / f"{PRINCIPAL}.revoked").exists()
        assert load_enrollment(PRINCIPAL, root=tmp_path) is None

    def test_an_unpersistable_marker_is_a_named_error(self, tmp_path: Path) -> None:
        blocked = tmp_path / "blocked"
        blocked.write_text("a file where the enrollment directory would be", encoding="utf-8")
        with pytest.raises(FaceEnrollmentError):
            revoke_enrollment(PRINCIPAL, root=blocked)

    def test_the_marker_masks_an_enrollment_that_is_still_on_disk(self, tmp_path: Path) -> None:
        path = tmp_path / f"{PRINCIPAL}.npz"
        self._enroll(tmp_path)
        path.with_suffix(".revoked").touch()
        assert path.exists()
        assert load_enrollment(PRINCIPAL, root=tmp_path) is None

    def test_load_falls_back_to_a_predecessor_and_the_marker_masks_it(self, tmp_path: Path) -> None:
        np.savez(tmp_path / f"{OLD_PRINCIPAL}.npz", embedding=_embedding(42).astype(np.float32))
        assert load_enrollment(PRINCIPAL, root=tmp_path) is not None
        (tmp_path / f"{PRINCIPAL}.revoked").touch()
        assert load_enrollment(PRINCIPAL, root=tmp_path) is None

    def test_reenrollment_removes_a_surviving_predecessor_before_clearing_the_marker(
        self, tmp_path: Path
    ) -> None:
        """Unsafe case: clearing the marker resurrects a predecessor left by an earlier revocation."""
        np.savez(tmp_path / f"{OLD_PRINCIPAL}.npz", embedding=_embedding(43).astype(np.float32))
        (tmp_path / f"{PRINCIPAL}.revoked").touch()
        consent = _StubConsent()
        consent.grant(PRINCIPAL)
        fresh = _embedding(44)
        enroll_principal(PRINCIPAL, fresh, consent=consent, root=tmp_path)

        assert not (tmp_path / f"{OLD_PRINCIPAL}.npz").exists()
        assert not (tmp_path / f"{PRINCIPAL}.revoked").exists()
        loaded = load_enrollment(PRINCIPAL, root=tmp_path)
        assert loaded is not None
        assert float(np.linalg.norm(loaded - fresh.astype(np.float32))) < 1e-6

    def test_reenrollment_refuses_to_clear_the_marker_when_a_predecessor_cannot_be_removed(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / f"{OLD_PRINCIPAL}.npz").mkdir()  # unlink() on a directory raises OSError
        (tmp_path / f"{PRINCIPAL}.revoked").touch()
        consent = _StubConsent()
        consent.grant(PRINCIPAL)
        with pytest.raises(FaceEnrollmentError):
            enroll_principal(PRINCIPAL, _embedding(45), consent=consent, root=tmp_path)
        assert (tmp_path / f"{PRINCIPAL}.revoked").exists()
        assert load_enrollment(PRINCIPAL, root=tmp_path) is None

    def test_reenrollment_order_is_durable_at_every_step_before_the_marker_goes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unsafe case: the marker's removal outruns the predecessor's deletion on disk.

        In process order the survivors are removed before the marker, but a file write is not
        durable until its directory entry is flushed. Without an fsync between the two, a crash
        can land the marker's removal while a predecessor's unlink does not, and
        ``load_enrollment`` then falls back to the old embedding. The recorded sequence pins
        the durability order: the new canonical file first, then the survivor removal, then the
        marker's removal — each made durable before the next step runs.
        """

        events: list[str] = []
        real_fsync_dir = registry._fsync_dir

        def observed_fsync_dir(directory: Path) -> None:
            events.append("fsync")
            real_fsync_dir(directory)

        real_unlink = Path.unlink

        def observed_unlink(self: Path, *args: object, **kwargs: object) -> None:
            events.append(f"unlink:{self.name}")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(registry, "_fsync_dir", observed_fsync_dir)
        monkeypatch.setattr(Path, "unlink", observed_unlink)

        np.savez(tmp_path / f"{OLD_PRINCIPAL}.npz", embedding=_embedding(46).astype(np.float32))
        (tmp_path / f"{PRINCIPAL}.revoked").touch()
        consent = _StubConsent()
        consent.grant(PRINCIPAL)
        fresh = _embedding(47)
        enroll_principal(PRINCIPAL, fresh, consent=consent, root=tmp_path)

        marker = f"unlink:{PRINCIPAL}.revoked"
        predecessor = f"unlink:{OLD_PRINCIPAL}.npz"
        assert events == ["fsync", predecessor, "fsync", marker, "fsync"]
        loaded = load_enrollment(PRINCIPAL, root=tmp_path)
        assert loaded is not None
        assert float(np.linalg.norm(loaded - fresh.astype(np.float32))) < 1e-6


def test_snapshot_diagnostic_classifier_is_private_and_exact():
    from shared.governance.consent import load_identity_snapshot

    snapshot = load_identity_snapshot()
    assert snapshot.contains_predecessor("synthetic-predecessor-subject")
    assert snapshot.contains_predecessor("synthetic-predecessor-contract")
    assert not snapshot.contains_predecessor("synthetic-unknown")
