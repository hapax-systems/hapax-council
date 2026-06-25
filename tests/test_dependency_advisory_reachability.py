"""Reachability guards for no-patch dependency advisories."""

from __future__ import annotations

from pathlib import Path


SOURCE_ROOTS = ("agents", "logos", "scripts", "shared")


def _source_files() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    files: list[Path] = []
    for root_name in SOURCE_ROOTS:
        files.extend((repo_root / root_name).rglob("*.py"))
    return sorted(files)


def test_no_first_party_nltk_data_load_usage():
    offenders = [
        str(path)
        for path in _source_files()
        if "nltk.data.load" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_no_first_party_torch_jit_usage():
    offenders = [
        str(path)
        for path in _source_files()
        if "torch.jit" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
