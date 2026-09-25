"""Executor identity follows source bytes and relative paths across deployments."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from shared import gate0b_claim_publication_install as install
from shared.execution_admission import ContentAddress, ExecutorDescriptor

MODULE_NAMES = (
    "coord_projection.py",
    "content_address.py",
    "execution_admission.py",
    "gate0b_claim_publication_install.py",
    "gate0b_claim_publication_lease.py",
    "gate0b_claim_publication_effect.py",
    "sdlc_claim.py",
)
ACTIVATION = ContentAddress(ref="test-activation@sha256:" + "a" * 64, sha256="a" * 64)
INSTALLED_AT = "2026-09-20T03:50:00.000000Z"


@pytest.fixture
def source_bytes() -> dict[str, bytes]:
    shared = Path(install.__file__).resolve().parent
    return {name: (shared / name).read_bytes() for name in MODULE_NAMES}


def _write_tree(root: Path, source_bytes: dict[str, bytes]) -> Path:
    shared = root / "shared"
    shared.mkdir(parents=True)
    for name, payload in source_bytes.items():
        (shared / name).write_bytes(payload)
    return root


def _descriptor(root: Path, monkeypatch: pytest.MonkeyPatch) -> ExecutorDescriptor:
    monkeypatch.setattr(
        install, "__file__", str(root / "shared" / "gate0b_claim_publication_install.py")
    )
    return install._build_executor_descriptor(ACTIVATION, installed_at=INSTALLED_AT)


def test_identical_sources_in_different_releases_have_same_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_bytes: dict[str, bytes]
) -> None:
    releases = tmp_path / ".cache/hapax/source-activation/releases"
    before = _write_tree(releases / "0a426dbc5", source_bytes)
    after = _write_tree(releases / "eaba8669", source_bytes)

    first = _descriptor(before, monkeypatch)
    second = _descriptor(after, monkeypatch)

    assert first.descriptor_hash == second.descriptor_hash
    expected = {ACTIVATION.ref}
    for name, payload in source_bytes.items():
        digest = hashlib.sha256(payload).hexdigest()
        expected.add(f"file:shared/{name}@sha256:{digest}")
    assert {address.ref for address in first.active_generation_roots} == expected


def test_repointing_activation_symlink_preserves_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_bytes: dict[str, bytes]
) -> None:
    activation = tmp_path / ".cache/hapax/source-activation"
    before = _write_tree(activation / "releases/0a426dbc5", source_bytes)
    after = _write_tree(activation / "releases/eaba8669", source_bytes)
    worktree = activation / "worktree"
    worktree.symlink_to(before, target_is_directory=True)
    first = _descriptor(worktree, monkeypatch)

    worktree.unlink()
    worktree.symlink_to(after, target_is_directory=True)

    assert _descriptor(worktree, monkeypatch).descriptor_hash == first.descriptor_hash


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_one_changed_source_byte_changes_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_bytes: dict[str, bytes],
    module_name: str,
) -> None:
    root = _write_tree(tmp_path / "release", source_bytes)
    first = _descriptor(root, monkeypatch)
    source = root / "shared" / module_name
    changed = bytearray(source.read_bytes())
    changed[0] ^= 1
    source.write_bytes(changed)

    assert _descriptor(root, monkeypatch).descriptor_hash != first.descriptor_hash


def test_lane_worktree_matches_identical_release_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_bytes: dict[str, bytes]
) -> None:
    home = tmp_path / "home/hapax"
    release = _write_tree(home / ".cache/hapax/source-activation/releases/eaba8669", source_bytes)
    lane = _write_tree(home / "projects/hapax-council--cx-astra", source_bytes)

    assert (
        _descriptor(lane, monkeypatch).descriptor_hash
        == _descriptor(release, monkeypatch).descriptor_hash
    )


def test_descriptor_binds_source_bytes_to_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_bytes: dict[str, bytes]
) -> None:
    root = _write_tree(tmp_path / "release", source_bytes)
    first = _descriptor(root, monkeypatch)
    left, right = MODULE_NAMES[:2]
    assert source_bytes[left] != source_bytes[right]
    (root / "shared" / left).write_bytes(source_bytes[right])
    (root / "shared" / right).write_bytes(source_bytes[left])

    assert _descriptor(root, monkeypatch).descriptor_hash != first.descriptor_hash


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_missing_source_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_bytes: dict[str, bytes],
    module_name: str,
) -> None:
    root = _write_tree(tmp_path / "release", source_bytes)
    (root / "shared" / module_name).unlink()

    with pytest.raises(ValueError, match="stable owner-bound regular bytes"):
        _descriptor(root, monkeypatch)
