"""Content-address a vault artifact that a review team accepts in place of a PR diff.

A vault-only row (no PR) is reviewed as a file set. Its head is a digest over the sorted
``(path, sha256, bytes)`` manifest, so the acceptance it earns covers exactly those bytes.
Both the issuer (``scripts/cc-pr-review-dispatch.py``) and the closure gate
(``shared.sdlc_lifecycle.acceptance_receipt_blockers``) use this module, so there is one
definition of "the accepted bytes".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ARTIFACT_HEAD_PREFIX = "artifact-sha256:"


class ArtifactSetError(ValueError):
    """The file set cannot be reviewed whole (the message is a stable reason code)."""


def build_artifact_manifest(
    paths: Sequence[Path | str], artifact_root: Path, *, max_chars: int
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Sorted (path, sha256, bytes) entries plus each file's text.

    Relative paths resolve against ``artifact_root``. Refused, never truncated or skipped: an
    empty set, a path that resolves (through any symlink) outside the root, a missing or
    non-regular file, non-UTF-8 content, and a set larger than ``max_chars``.
    """

    if not paths:
        raise ArtifactSetError("artifact_set_empty")
    try:
        root = artifact_root.resolve(strict=True)
    except OSError as exc:
        raise ArtifactSetError("artifact_root_missing") from exc
    entries: dict[str, dict[str, Any]] = {}
    contents: dict[str, str] = {}
    total = 0
    for raw in paths:
        path = Path(raw) if Path(raw).is_absolute() else root / raw
        resolved = path.resolve()
        try:
            rel = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise ArtifactSetError(f"artifact_outside_root:{path.name}") from exc
        if not resolved.is_file():
            raise ArtifactSetError(f"artifact_missing_or_not_a_file:{rel}")
        data = resolved.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactSetError(f"artifact_not_utf8_text:{rel}") from exc
        total += len(text)
        if total > max_chars:
            raise ArtifactSetError(f"artifact_set_too_large:>{max_chars}_chars")
        entries[rel] = {"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        contents[rel] = text
    return [entries[rel] for rel in sorted(entries)], contents


def artifact_head_sha(manifest: Sequence[Mapping[str, Any]]) -> str:
    """The artifact's head: a digest over the sorted manifest (paths and content hashes)."""

    canonical = json.dumps(list(manifest), sort_keys=True, separators=(",", ":"))
    return ARTIFACT_HEAD_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def changed_manifest_paths(
    manifest: Sequence[Mapping[str, Any]], artifact_root: Path
) -> tuple[str, ...]:
    """Manifest paths whose bytes under ``artifact_root`` are no longer the recorded bytes."""

    root = artifact_root.resolve()
    changed: list[str] = []
    for entry in manifest:
        rel = str(entry.get("path") or "")
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
            data = path.read_bytes() if path.is_file() else None
        except (ValueError, OSError):
            data = None
        if data is None or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            changed.append(rel)
    return tuple(changed)


def artifact_receipt_blockers(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    """Closure blockers for an acceptance receipt that covers a vault artifact.

    Empty for a receipt without ``artifact_review``. Otherwise the recorded manifest must
    digest to the receipt's ``head_sha`` and every file must still hold the accepted bytes.
    The receipt's head binds a vault row the way a merged head binds a PR row.
    """

    review = receipt.get("artifact_review")
    if review is None:
        return ()
    if not isinstance(review, Mapping):
        return ("acceptance_receipt_artifact_review_malformed",)
    manifest = review.get("manifest")
    if (
        not isinstance(manifest, list)
        or not manifest
        or not all(isinstance(entry, Mapping) for entry in manifest)
    ):
        return ("acceptance_receipt_artifact_review_malformed",)
    if artifact_head_sha(manifest) != str(receipt.get("head_sha") or ""):
        return ("acceptance_receipt_artifact_head_mismatch",)
    root = str(review.get("artifact_root") or "").strip()
    if not root:
        return ("acceptance_receipt_artifact_root_missing",)
    return tuple(
        f"acceptance_receipt_artifact_changed:{rel}"
        for rel in changed_manifest_paths(manifest, Path(root))
    )
