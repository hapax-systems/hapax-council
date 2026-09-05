"""Fixture epoch selection, real Git history and producer reads for frame consumer tests."""

import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.frame_verdicts import epoch_produced_at


def alias_member_tree(root: Path) -> Path:
    """A portable file surface with file aliases, directory aliases and nested files."""
    (root / "bin/db5.3/nested").mkdir(parents=True)
    (root / "bin/db5.3/db_dump").write_bytes(b"selected database bytes\n")
    (root / "bin/db5.3/nested/db_load").write_bytes(b"selected nested bytes\n")
    (root / "bin/gawk").write_bytes(b"GNU selected query bytes\n")
    (root / "bin/awk").symlink_to("gawk")
    (root / "sbin").symlink_to("bin", target_is_directory=True)
    (root / "tools").mkdir()
    (root / "tools/unselected").write_bytes(b"unrelated bytes\n")
    (root / "bin/tools").symlink_to("../tools", target_is_directory=True)
    return root


def latest_epoch_dir(procedure_root: Path) -> Path | None:
    """Select the newest persisted test-fixture attempt, independent of publication."""
    epochs = procedure_root / "_runs" / "epochs"
    if not epochs.is_dir():
        return None
    candidates = [
        child
        for child in epochs.iterdir()
        if child.is_dir()
        and epoch_produced_at(child.name) is not None
        and (child / "elements.json").is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda child: child.name)


def producer_glob_bytes(
    root: Path,
    patterns: list[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    excluded: tuple[Path, ...] = (),
    content_query: str | None = None,
    max_unit_bytes: int = 128,
) -> dict[Path, bytes]:
    """Call the installed producer's glob/query selection and byte reader, without a run."""
    base = Path("~/Documents/Personal/30-areas/hapax").expanduser()
    if not (base / "frame/procedure/builtin.py").is_file():
        pytest.skip("installed frame producer is unavailable")
    monkeypatch.syspath_prepend(str(base))
    builtin = importlib.import_module("frame.procedure.builtin")
    declaration = importlib.import_module("frame.procedure.declaration")
    mass = declaration.Declaration(
        version="fixture",
        source_document="fixture",
        members=(),
        exclusions=tuple(
            declaration.Exclusion("excluded", "fixture", "fixture", "test", (str(path),))
            for path in excluded
        ),
        digest="fixture",
        path=root / "mass.yaml",
    )
    values = {"max_unit_bytes": max_unit_bytes, "encoding_error_policy": "strict"}
    location = {"path": str(root), "patterns": patterns}
    reader = builtin.fs_glob
    if content_query is not None:
        location = {"roots": [str(root)], "patterns": patterns, "query": content_query}
        reader = builtin.fs_content_query
    with monkeypatch.context() as fallback:
        if content_query is not None:
            fallback.setattr(builtin.shutil, "which", lambda name: None)
        result = reader(
            SimpleNamespace(
                id="fixture",
                location=location,
                bounds=SimpleNamespace(max_seconds=10, max_units=None),
            ),
            SimpleNamespace(get=lambda name, **kwargs: values[name]),
            mass,
        )
    assert result.complete and result.failure is None
    return {Path(obs.meta["path"]).resolve(strict=True): obs.content for obs in result.observations}


def git_checkout(root: Path, *, history: str) -> None:
    """Create a real checkout with a deterministic root, without invoking commit hooks."""
    root.mkdir(parents=True, exist_ok=True)

    def git(*args: str, data: str | None = None) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            input=data,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    git("init", "--quiet")
    tree = git("mktree", data="")
    commit = git(
        "hash-object",
        "-t",
        "commit",
        "-w",
        "--stdin",
        data=(
            f"tree {tree}\n"
            "author Frame Test <frame@example.invalid> 1 +0000\n"
            "committer Frame Test <frame@example.invalid> 1 +0000\n"
            f"\n{history}\n"
        ),
    )
    git("update-ref", "HEAD", commit)
