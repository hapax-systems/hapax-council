from __future__ import annotations

import ast
import subprocess
import zipfile
from email.parser import BytesParser
from pathlib import Path

from hapax.context_canon import carrier_json_schema_bytes

PACKAGE_ROOT = Path(__file__).parents[1]
PACKAGE = PACKAGE_ROOT / "src/hapax/context_canon"


def test_checked_carrier_schema_matches_generator() -> None:
    assert (
        PACKAGE / "_data/context-canon-carrier.schema.json"
    ).read_bytes() == carrier_json_schema_bytes()


def test_package_has_no_council_or_compiler_imports() -> None:
    forbidden = {"shared", "yaml"}
    observed: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                observed.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                observed.add(node.module.split(".", 1)[0])
    assert forbidden.isdisjoint(observed)
    assert {path.relative_to(PACKAGE).as_posix() for path in PACKAGE.rglob("*.py")} == {
        "__init__.py",
        "contract.py",
        "event_plane.py",
        "projection.py",
        "schema.py",
    }
    assert {
        path.relative_to(PACKAGE).as_posix()
        for path in (PACKAGE / "_data").rglob("*")
        if path.is_file()
    } == {"_data/context-canon-carrier.schema.json"}
    assert not (PACKAGE.parent / "__init__.py").exists()


def test_built_wheel_inventory_metadata_and_schema(tmp_path: Path) -> None:
    subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            str(PACKAGE_ROOT),
            "--out-dir",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("hapax_context_canon-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert {
            "hapax/context_canon/__init__.py",
            "hapax/context_canon/contract.py",
            "hapax/context_canon/event_plane.py",
            "hapax/context_canon/projection.py",
            "hapax/context_canon/schema.py",
            "hapax/context_canon/py.typed",
            "hapax/context_canon/_data/context-canon-carrier.schema.json",
        } <= names
        assert "hapax/__init__.py" not in names
        assert not any(
            token in name
            for name in names
            for token in ("shared/", "reins", "tests/", "__pycache__", ".pytest_cache")
        )
        assert any(name.endswith(".dist-info/licenses/LICENSE.txt") for name in names)
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        runtime_requires = {
            value for value in metadata.get_all("Requires-Dist", []) if "extra ==" not in value
        }
        assert runtime_requires == {"pydantic==2.13.4", "python-toon==0.1.3"}
        assert metadata["License-Expression"] == "LicenseRef-PolyForm-Strict-1.0.0"
        assert (
            archive.read("hapax/context_canon/_data/context-canon-carrier.schema.json")
            == carrier_json_schema_bytes()
        )
