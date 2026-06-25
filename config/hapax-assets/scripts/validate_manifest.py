from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "_manifest.yaml"


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    manifest = load_yaml(MANIFEST_PATH)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("assets"), list):
        raise SystemExit("_manifest.yaml must contain an assets list")

    failures: list[str] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for index, asset in enumerate(manifest["assets"], start=1):
        if not isinstance(asset, dict):
            failures.append(f"asset #{index}: entry must be a mapping")
            continue

        required = [
            "source",
            "kind",
            "name",
            "path",
            "sha256",
            "license",
            "author",
            "source_url",
            "extracted_date",
        ]
        missing = [field for field in required if not asset.get(field)]
        if missing:
            failures.append(f"asset #{index}: missing required fields: {', '.join(missing)}")
            continue

        key = (str(asset["source"]), str(asset["kind"]), str(asset["name"]))
        if key in seen_keys:
            failures.append(f"asset #{index}: duplicate asset key {key}")
        seen_keys.add(key)

        asset_path = ROOT / str(asset["path"])
        if not asset_path.is_file():
            failures.append(f"asset #{index}: missing file {asset['path']}")
            continue

        actual = sha256(asset_path)
        expected = str(asset["sha256"])
        if actual != expected:
            failures.append(
                f"asset #{index}: sha256 mismatch for {asset['path']}: expected {expected}, got {actual}"
            )

        provenance_path = ROOT / str(asset["source"]) / "provenance.yaml"
        if not provenance_path.is_file():
            failures.append(
                f"asset #{index}: missing provenance file {provenance_path.relative_to(ROOT)}"
            )

    if failures:
        raise SystemExit("\n".join(failures))

    print(f"manifest validation passed: {len(manifest['assets'])} asset(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
