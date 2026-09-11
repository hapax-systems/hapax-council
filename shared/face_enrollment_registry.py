"""Per-principal face embedding registry — biometric consent matcher.

Stores 512-d ArcFace embeddings under
``~/hapax-state/face-enrollments/<principal_id>.npz`` keyed by
principal id. Each enrollment requires an active consent contract whose
scope contains ``face_enrollment``; the registry refuses to write
otherwise. Embeddings stay local — never logged, never returned by
enumeration, never egressed.

This module ships the registry + match/revoke primitives. Wiring the
matcher into the live ``FaceDetector`` and into the consent gate's
``consent_to_enroll`` activation path lands as follow-up cc-tasks per
the parent spec
for the per-person consent matcher.

Per the "revoke ships before matcher gate" invariant
(``cc-task: arcface-per-person-matcher-gate``), ``revoke_enrollment``
is a first-class primitive in this module — a future PR cannot wire
the matcher into the gate without a revocation primitive already in
place.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from shared.governance.consent import estate_identity_operation, resolve_principal_id

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

log = logging.getLogger(__name__)

ENROLLMENT_DIR_DEFAULT: Final[Path] = Path.home() / "hapax-state" / "face-enrollments"
EMBEDDING_DIM: Final[int] = 512
DEFAULT_MATCH_THRESHOLD: Final[float] = 0.40
ENROLL_SCOPE: Final[str] = "face_enrollment"


class _ConsentScopeChecker(Protocol):
    """Minimum surface required to verify face-enrollment consent.

    The consent check covers all active contracts for the principal.
    """

    def contract_check(self, person_id: str, data_category: str) -> bool: ...


class FaceEnrollmentError(RuntimeError):
    """Raised when an enrollment operation cannot proceed safely."""


def _enrollment_path(principal_id: str, *, root: Path | None = None) -> Path:
    if not principal_id or any(ch in principal_id for ch in "/\\.\0"):
        raise FaceEnrollmentError(
            f"invalid principal_id {principal_id!r}; must be a path-safe slug"
        )
    principal_id = resolve_principal_id(principal_id) or principal_id
    base = root if root is not None else ENROLLMENT_DIR_DEFAULT
    return base / f"{principal_id}.npz"


def _has_face_enrollment_scope(consent: _ConsentScopeChecker, principal_id: str) -> bool:
    principal_id = resolve_principal_id(principal_id) or principal_id
    return consent.contract_check(principal_id, ENROLL_SCOPE)


def _matching_enrollment_paths(principal_id: str, *, root: Path | None = None) -> list[Path]:
    """Locate current and predecessor filenames without retaining predecessor text."""
    canonical = _enrollment_path(principal_id, root=root)
    return sorted(
        path
        for path in canonical.parent.glob("*.npz")
        if (resolve_principal_id(path.stem) or path.stem) == canonical.stem
    )


@estate_identity_operation()
def enroll_principal(
    principal_id: str,
    embedding: NDArray[np.float32],
    *,
    consent: _ConsentScopeChecker,
    root: Path | None = None,
) -> Path:
    """Persist one principal's 512-d embedding under their consent contract.

    Refuses (raising :class:`FaceEnrollmentError`) when no active contract
    with ``face_enrollment`` scope exists for ``principal_id``. Refuses
    on shape / dtype mismatch. The on-disk file is written atomically
    (tmp + rename) to ``<root>/<principal_id>.npz``.

    Returns the path on disk.
    """

    import numpy as np

    principal_id = resolve_principal_id(principal_id) or principal_id
    if not _has_face_enrollment_scope(consent, principal_id):
        raise FaceEnrollmentError(
            f"refusing to enroll {principal_id!r}: no active "
            f"{ENROLL_SCOPE!r}-scoped consent contract"
        )

    arr = np.asarray(embedding)
    if arr.shape != (EMBEDDING_DIM,):
        raise FaceEnrollmentError(f"embedding shape {arr.shape} != ({EMBEDDING_DIM},)")
    if arr.dtype not in (np.float32, np.float64):
        raise FaceEnrollmentError(f"embedding dtype {arr.dtype} not float32/float64")

    target = _enrollment_path(principal_id, root=root)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    np.savez(tmp, embedding=arr.astype(np.float32, copy=False))
    # ``np.savez`` writes to <tmp>.npz; the with_suffix(.tmp) trick gives
    # us <stem>.npz.tmp.npz on disk. Resolve by writing without the .npz
    # suffix to a sibling temp dir name and moving.
    written = tmp.with_suffix(tmp.suffix + ".npz")
    if written.exists():
        written.replace(target)
    else:
        # numpy ≥1.22 honours the explicit .npz extension; in that case the
        # tmp path itself was used.
        tmp.replace(target)
    # Only a successful, consent-checked enrollment supersedes revocation.
    target.with_suffix(".revoked").unlink(missing_ok=True)
    log.info("Enrolled principal %s at %s", principal_id, target)
    return target


@estate_identity_operation()
def load_enrollment(principal_id: str, *, root: Path | None = None) -> NDArray[np.float32] | None:
    """Read a principal's embedding from disk.

    Returns ``None`` when no enrollment exists. Never raises on a
    missing file — match callers fail-close on ``None``.
    """

    import numpy as np

    path = None
    try:
        path = _enrollment_path(principal_id, root=root)
        if path.with_suffix(".revoked").exists():
            return None
        if not path.exists():
            matches = _matching_enrollment_paths(principal_id, root=root)
            if not matches:
                return None
            path = matches[0]
        with np.load(path) as data:
            embedding = data["embedding"]
        return np.asarray(embedding, dtype=np.float32)
    except Exception as exc:
        with estate_identity_operation() as snapshot:
            private = snapshot.contains_predecessor(f"{principal_id}: {path}: {exc}")
        if private:
            log.warning("enrollment_read_failed")
        else:
            log.warning("Failed to load enrollment for %s", principal_id, exc_info=True)
        return None


@estate_identity_operation()
def revoke_enrollment(principal_id: str, *, root: Path | None = None) -> bool:
    """Disable matching durably, then delete all equivalent enrollment files.

    Per the cc-task invariant, revocation must ship before any matcher
    gate. Returns True only if every matching file was removed, False if
    none existed or deletion was incomplete. A canonical revocation marker
    blocks surviving aliases until a new consent-checked enrollment succeeds.
    Raises FaceEnrollmentError if that marker cannot be persisted; storage
    access must be corrected and revocation retried in that case.
    """

    principal_id = resolve_principal_id(principal_id) or principal_id
    paths = _matching_enrollment_paths(principal_id, root=root)
    if not paths:
        return False
    try:
        _enrollment_path(principal_id, root=root).with_suffix(".revoked").touch()
    except OSError as exc:
        raise FaceEnrollmentError(
            f"Enrollment revocation incomplete ({type(exc).__name__}); "
            "correct storage access and retry"
        ) from None
    complete = True
    for path in paths:
        try:
            path.unlink()
            log.info("Revoked enrollment for principal %s", principal_id)
        except OSError as exc:
            complete = False
            log.warning(
                "Enrollment revocation incomplete (%s); matching remains disabled. "
                "Correct storage access and retry",
                type(exc).__name__,
            )
    return complete


@estate_identity_operation()
def list_enrollments(*, root: Path | None = None) -> list[str]:
    """Return enrolled principal ids (sorted, no embedding content).

    Embeddings themselves are NEVER returned by this function so a
    listing call cannot be used to exfiltrate biometric data.
    """

    base = root if root is not None else ENROLLMENT_DIR_DEFAULT
    if not base.exists():
        return []
    return sorted({resolve_principal_id(p.stem) or p.stem for p in base.glob("*.npz")})


def _cosine_similarity(a: NDArray[np.float32], b: NDArray[np.float32]) -> float:
    import numpy as np

    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a < 1e-6 or norm_b < 1e-6:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


@estate_identity_operation()
def match_principal(
    embedding: NDArray[np.float32] | None,
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
    root: Path | None = None,
    candidates: Iterable[str] | None = None,
) -> str | None:
    """Match a single embedding against enrolled principals.

    Returns the principal_id whose enrolled embedding scores highest
    above ``threshold``. Fail-closed: returns ``None`` when:
    - ``embedding`` is None, empty, or wrong shape (model unavailable
      / no face / low-confidence detection)
    - no candidates score above ``threshold``
    - any registry read fails

    ``candidates`` restricts the match to a named subset (e.g. only
    those principals with active consent contracts at this tick); when
    omitted, all enrolled principals are considered.
    """

    import numpy as np

    if embedding is None:
        return None
    arr = np.asarray(embedding)
    if arr.shape != (EMBEDDING_DIM,):
        return None
    arr = arr.astype(np.float32, copy=False)

    pool = list(candidates) if candidates is not None else list_enrollments(root=root)
    best_id: str | None = None
    best_score = float("-inf")
    for pid in pool:
        enrolled = load_enrollment(pid, root=root)
        if enrolled is None:
            continue
        score = _cosine_similarity(arr, enrolled)
        if score >= threshold and score > best_score:
            best_score = score
            best_id = resolve_principal_id(pid) or pid
    return best_id


__all__ = [
    "DEFAULT_MATCH_THRESHOLD",
    "EMBEDDING_DIM",
    "ENROLLMENT_DIR_DEFAULT",
    "ENROLL_SCOPE",
    "FaceEnrollmentError",
    "enroll_principal",
    "list_enrollments",
    "load_enrollment",
    "match_principal",
    "revoke_enrollment",
]
