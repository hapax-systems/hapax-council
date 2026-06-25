from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]


def _load_validator():
    path = REPO / "config/hapax-assets/scripts/validate_manifest.py"
    spec = importlib.util.spec_from_file_location("hapax_assets_validate_manifest", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hapax_assets_validate_manifest"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_manifest_root(root: Path, *, sha: str | None = None) -> None:
    source_dir = root / "sample-source"
    source_dir.mkdir(parents=True)
    (source_dir / "provenance.yaml").write_text("source: fixture\n", encoding="utf-8")
    asset = root / "sample-source" / "asset.txt"
    asset.write_text("asset bytes\n", encoding="utf-8")
    digest = sha or hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest = {
        "assets": [
            {
                "source": "sample-source",
                "kind": "text",
                "name": "fixture",
                "path": "sample-source/asset.txt",
                "sha256": digest,
                "license": "CC0-1.0",
                "author": "fixture",
                "source_url": "https://example.invalid/asset.txt",
                "extracted_date": "2026-06-25",
            }
        ]
    }
    (root / "_manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")


def test_validate_manifest_accepts_matching_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    validator = _load_validator()
    _write_manifest_root(tmp_path)
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    monkeypatch.setattr(validator, "MANIFEST_PATH", tmp_path / "_manifest.yaml")

    assert validator.main() == 0
    assert "manifest validation passed: 1 asset(s)" in capsys.readouterr().out


def test_validate_manifest_rejects_checksum_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    validator = _load_validator()
    _write_manifest_root(tmp_path, sha="0" * 64)
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    monkeypatch.setattr(validator, "MANIFEST_PATH", tmp_path / "_manifest.yaml")

    with pytest.raises(SystemExit) as exc:
        validator.main()

    assert "sha256 mismatch" in str(exc.value)
