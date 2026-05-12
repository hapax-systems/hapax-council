"""Tests for ``scripts/rag_documents_v2_shadow.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "rag_documents_v2_shadow.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("_rag_documents_v2_shadow", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_reindex_report_honors_max_files_and_supported_extensions(tmp_path: Path) -> None:
    shadow = _load_script_module()
    source_dir = tmp_path / "rag"
    source_dir.mkdir()
    (source_dir / "a.md").write_text("a")
    (source_dir / "b.txt").write_text("b")
    (source_dir / "ignored.bin").write_text("ignored")

    report = shadow.build_reindex_report(
        source_dirs=[source_dir],
        source_collection="documents",
        target_collection="documents_v2",
        max_files=1,
        dry_run=True,
        report_only=False,
        force=False,
        qdrant_url="http://qdrant",
        embedding_model="nomic-embed-cpu",
    )

    assert report["writes_enabled"] is False
    assert report["files_discovered"] == 2
    assert report["files_selected"] == 1
    assert any(path.endswith("a.md") for path in report["selected_files"])


def test_ensure_collection_creates_shadow_schema_with_selected_vector_size() -> None:
    shadow = _load_script_module()

    class FakeClient:
        def __init__(self) -> None:
            self.created = None

        def get_collections(self):
            return SimpleNamespace(collections=[])

        def create_collection(self, collection_name, vectors_config, **kwargs):
            self.created = {
                "collection_name": collection_name,
                "vectors_config": vectors_config,
                **kwargs,
            }

    client = FakeClient()
    created = shadow.ensure_collection(client, "documents_v2", 1024)

    assert created is True
    assert client.created["collection_name"] == "documents_v2"
    assert client.created["vectors_config"].size == 1024
    assert client.created["vectors_config"].distance.name == "COSINE"


def test_ensure_collection_does_not_recreate_existing_shadow_collection() -> None:
    shadow = _load_script_module()

    class FakeClient:
        def get_collections(self):
            return SimpleNamespace(collections=[SimpleNamespace(name="documents_v2")])

        def create_collection(self, collection_name, vectors_config, **kwargs):
            raise AssertionError("create_collection should not be called")

    assert shadow.ensure_collection(FakeClient(), "documents_v2", 768) is False


def test_compare_shadow_retrieval_queries_documents_and_shadow() -> None:
    shadow = _load_script_module()

    class FakeClient:
        def __init__(self) -> None:
            self.collections = []

        def query_points(self, collection_name, **kwargs):
            self.collections.append(collection_name)
            point = SimpleNamespace(
                score=0.9 if collection_name == "documents" else 0.8,
                payload={
                    "source": f"/{collection_name}/doc.md",
                    "source_service": "obsidian",
                    "text": f"{collection_name} text",
                },
            )
            return SimpleNamespace(points=[point])

    client = FakeClient()
    comparison = shadow.compare_shadow_retrieval(
        client=client,
        query="constitutional memory",
        query_vector=[0.1, 0.2],
        source_collection="documents",
        shadow_collection="documents_v2",
        limit=3,
    )

    assert client.collections == ["documents", "documents_v2"]
    assert comparison["collections"]["documents"]["hits"][0]["score"] == 0.9
    assert comparison["collections"]["documents_v2"]["hits"][0]["score"] == 0.8


def test_parser_exposes_reindex_safety_modes() -> None:
    shadow = _load_script_module()

    args = shadow.build_parser().parse_args(
        [
            "reindex",
            "--target-collection",
            "documents_v2",
            "--dry-run",
            "--report-only",
            "--max-files",
            "5",
        ]
    )

    assert args.target_collection == "documents_v2"
    assert args.dry_run is True
    assert args.report_only is True
    assert args.max_files == 5
