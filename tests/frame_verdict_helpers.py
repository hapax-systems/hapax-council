"""Real Git history and producer reads for the frame consumer's regressions."""

import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def producer_glob_bytes(
    root: Path,
    patterns: list[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    excluded: tuple[Path, ...] = (),
) -> dict[Path, bytes]:
    """Call the installed producer's selection, exclusion and byte reader, without a run."""
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
    values = {"max_unit_bytes": 128, "encoding_error_policy": "strict"}
    result = builtin.fs_glob(
        SimpleNamespace(id="fixture", location={"path": str(root), "patterns": patterns}),
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
