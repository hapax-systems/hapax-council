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
    (source_dir / "c.py").write_text("print('covered')")
    (source_dir / "ignored.bin").write_text("ignored")
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(
        """
        {
          "queries": [
            {
              "id": "q1",
              "expected_sources": [
                {"source_contains": "a.md", "grade": 3},
                {"text_contains": "covered", "grade": 2}
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    report = shadow.build_reindex_report(
        source_dirs=[source_dir],
        source_collection="documents",
        target_collection="documents_v2",
        max_files=None,
        dry_run=True,
        report_only=False,
        force=False,
        qdrant_url="http://qdrant",
        embedding_model="nomic-embed-cpu",
        source_profile="all",
        suite_path=suite_path,
    )

    assert report["writes_enabled"] is False
    assert report["files_discovered"] == 3
    assert report["files_selected"] == 3
    assert any(path.endswith("a.md") for path in report["selected_files"])
    assert any(path.endswith("c.py") for path in report["selected_files"])
    assert report["selected_source_categories"] == {"other": 3}
    coverage = report["golden_label_coverage"]
    assert coverage["covered_label_count"] == 2
    assert coverage["expected_label_count"] == 2


def test_default_source_dirs_include_audit_research_and_code_roots(
    tmp_path: Path, monkeypatch
) -> None:
    shadow = _load_script_module()
    personal = tmp_path / "Personal"
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_PERSONAL_ROOT", str(personal))
    monkeypatch.setenv("HAPAX_REPO_ROOT", str(repo))
    monkeypatch.setenv("HAPAX_HOME", str(home))

    dirs = [str(path) for path in shadow.default_source_dirs()]

    assert str(personal / "20-projects" / "hapax-research" / "audit") in dirs
    assert str(personal / "20-projects" / "hapax-research" / "foundations") in dirs
    assert str(personal / "20-projects" / "hapax-research" / "lab-journals") in dirs
    assert str(personal / "20-projects" / "hapax-requests" / "active") in dirs
    assert str(personal / "20-projects" / "hapax-cc-tasks" / "closed") in dirs
    assert str(repo / "scripts") in dirs
    assert str(repo / "shared") in dirs


def test_audit_publication_source_profile_excludes_raw_rag_firehose(
    tmp_path: Path, monkeypatch
) -> None:
    shadow = _load_script_module()
    personal = tmp_path / "Personal"
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    monkeypatch.setenv("HAPAX_PERSONAL_ROOT", str(personal))
    monkeypatch.setenv("HAPAX_REPO_ROOT", str(repo))
    monkeypatch.setenv("HAPAX_HOME", str(home))

    dirs = [str(path) for path in shadow.default_source_dirs("audit-publication")]

    assert str(home / "documents" / "rag-sources") not in dirs
    assert str(personal / "20-projects" / "hapax-research" / "audit") in dirs
    assert str(personal / "20-projects" / "hapax-research" / "codex-handoffs") in dirs
    assert str(personal / "20-projects" / "hapax-requests" / "active") in dirs
    assert str(personal / "20-projects" / "hapax-cc-tasks" / "active") in dirs
    assert str(repo / "docs") in dirs
    assert str(repo / "packages" / "agentgov") in dirs


def test_parser_coverage_fail_closed_when_docling_required_but_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    shadow = _load_script_module()
    (tmp_path / "audit.pdf").write_bytes(b"%PDF-1.7")
    (tmp_path / "note.md").write_text("plain text", encoding="utf-8")
    monkeypatch.setattr(
        shadow,
        "_docling_status",
        lambda: {
            "available": False,
            "error_type": "ModuleNotFoundError",
            "error": "No module named 'docling'",
            "imports": {
                "docling.document_converter.DocumentConverter": False,
                "docling.chunking.HybridChunker": False,
            },
        },
    )

    coverage = shadow.parser_coverage([tmp_path / "audit.pdf", tmp_path / "note.md"])

    assert coverage["by_extension"] == {".md": 1, ".pdf": 1}
    assert coverage["parser_modes"]["plain_text_fast_path"]["file_count"] == 1
    assert coverage["parser_modes"]["docling"]["file_count"] == 1
    assert coverage["parser_modes"]["docling"]["available"] is False
    assert coverage["unsupported_extensions"] == [".pdf"]
    assert coverage["unsupported_file_count"] == 1
    assert coverage["fail_closed_required"] is True


def test_build_reindex_report_can_omit_full_selected_file_list(tmp_path: Path, monkeypatch) -> None:
    shadow = _load_script_module()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for index in range(55):
        (source_dir / f"doc-{index:02d}.md").write_text(str(index), encoding="utf-8")
    monkeypatch.setattr(
        shadow,
        "_docling_status",
        lambda: {
            "available": True,
            "imports": {
                "docling.document_converter.DocumentConverter": True,
                "docling.chunking.HybridChunker": True,
            },
        },
    )

    report = shadow.build_reindex_report(
        source_dirs=[source_dir],
        source_collection="documents",
        target_collection="documents_v2",
        max_files=None,
        dry_run=True,
        report_only=True,
        force=False,
        qdrant_url="http://qdrant",
        embedding_model="nomic-embed-cpu",
        source_profile="audit-publication",
        include_selected_files=False,
    )

    assert report["source_profile"] == "audit-publication"
    assert report["files_selected"] == 55
    assert "selected_files" not in report
    assert len(report["selected_files_sample"]) == 50
    assert report["selected_files_omitted"] == 5
    assert report["selected_parser_coverage"]["fail_closed_required"] is False


def test_golden_label_coverage_surfaces_source_label_text_evidence(tmp_path: Path) -> None:
    shadow = _load_script_module()
    source = tmp_path / "audit.md"
    source.write_text("The LivingPresentEnvelope appears in text, not path.", encoding="utf-8")
    suite = tmp_path / "suite.json"
    suite.write_text(
        """
        {
          "queries": [
            {
              "id": "q1",
              "expected_sources": [
                {"source_contains": "LivingPresentEnvelope", "grade": 3}
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    coverage = shadow.golden_label_coverage([source], suite)

    assert coverage["covered_label_count"] == 0
    assert coverage["source_label_text_evidence"][0]["label"] == {
        "source_contains": "LivingPresentEnvelope"
    }


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


def test_run_ingest_command_uses_exact_source_file_list(tmp_path: Path) -> None:
    shadow = _load_script_module()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    selected = source_dir / "selected.md"
    selected.write_text("selected", encoding="utf-8")
    ignored = source_dir / "ignored.bin"
    ignored.write_bytes(b"ignored")
    recorded = {}

    def runner(cmd, check):
        list_path = Path(cmd[cmd.index("--source-file-list") + 1])
        recorded["cmd"] = cmd
        recorded["check"] = check
        recorded["list_path"] = list_path
        recorded["source_files"] = list_path.read_text(encoding="utf-8").splitlines()
        return SimpleNamespace(returncode=0)

    result = shadow._run_ingest_command(
        selected_files=[selected],
        target_collection="documents_v2",
        qdrant_url="http://qdrant",
        embedding_model="nomic-embed-cpu",
        max_files=None,
        force=True,
        runner=runner,
    )

    assert result.returncode == 0
    assert recorded["check"] is False
    assert "--watch-dir" not in recorded["cmd"]
    assert recorded["source_files"] == [str(selected.resolve())]
    assert "--force" in recorded["cmd"]
    assert recorded["list_path"].exists() is False


def test_run_reindex_passes_checked_manifest_to_ingest(tmp_path: Path, monkeypatch) -> None:
    shadow = _load_script_module()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    first = source_dir / "first.md"
    second = source_dir / "second.md"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    calls = {"discover": 0}
    captured = {}

    def discover(source_dirs):
        calls["discover"] += 1
        assert source_dirs == [source_dir]
        return [first, second]

    def fake_ingest(**kwargs):
        captured["selected_files"] = kwargs["selected_files"]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(shadow, "discover_source_files", discover)
    monkeypatch.setattr(shadow, "embedding_dimensions", lambda **kwargs: 768)
    monkeypatch.setattr(shadow, "_make_qdrant_client", lambda qdrant_url: object())
    monkeypatch.setattr(shadow, "ensure_collection", lambda *args, **kwargs: False)
    monkeypatch.setattr(shadow, "_run_ingest_command", fake_ingest)
    args = SimpleNamespace(
        source_dir=[source_dir],
        source_profile="audit-publication",
        source_collection="documents",
        target_collection="documents_v2",
        max_files=1,
        dry_run=False,
        report_only=False,
        force=True,
        qdrant_url="http://qdrant",
        embedding_model="nomic-embed-cpu",
        omit_selected_files=True,
        suite=None,
        allow_parser_gaps=False,
        vector_size=None,
        ollama_url="http://ollama",
        output=None,
    )

    assert shadow.run_reindex(args) == 0
    assert calls["discover"] == 1
    assert captured["selected_files"] == [first]


def test_parser_exposes_reindex_safety_modes() -> None:
    shadow = _load_script_module()

    args = shadow.build_parser().parse_args(
        [
            "reindex",
            "--target-collection",
            "documents_v2",
            "--dry-run",
            "--report-only",
            "--source-profile",
            "audit-publication",
            "--max-files",
            "5",
            "--omit-selected-files",
            "--allow-parser-gaps",
        ]
    )

    assert args.target_collection == "documents_v2"
    assert args.source_profile == "audit-publication"
    assert args.dry_run is True
    assert args.report_only is True
    assert args.max_files == 5
    assert args.omit_selected_files is True
    assert args.allow_parser_gaps is True


def test_run_reindex_fails_closed_before_write_when_binary_parser_missing(
    tmp_path: Path, monkeypatch
) -> None:
    shadow = _load_script_module()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "audit.pdf").write_bytes(b"%PDF-1.7")
    monkeypatch.setattr(
        shadow,
        "_docling_status",
        lambda: {
            "available": False,
            "error_type": "ModuleNotFoundError",
            "error": "No module named 'docling'",
            "imports": {
                "docling.document_converter.DocumentConverter": False,
                "docling.chunking.HybridChunker": False,
            },
        },
    )
    monkeypatch.setattr(shadow, "attach_collection_reports", lambda report, qdrant_url: None)

    def fail_ingest(**kwargs):
        raise AssertionError("ingest should not run when parser coverage is fail-closed")

    monkeypatch.setattr(shadow, "_run_ingest_command", fail_ingest)
    args = SimpleNamespace(
        source_dir=[source_dir],
        source_profile="audit-publication",
        source_collection="documents",
        target_collection="documents_v2",
        max_files=None,
        dry_run=False,
        report_only=False,
        force=True,
        qdrant_url="http://qdrant",
        embedding_model="nomic-embed-cpu",
        omit_selected_files=True,
        suite=None,
        allow_parser_gaps=False,
        vector_size=768,
        ollama_url="http://ollama",
        output=tmp_path / "report.json",
    )

    assert shadow.run_reindex(args) == 3
    report = (tmp_path / "report.json").read_text(encoding="utf-8")
    assert "parser_coverage_gap" in report
    assert "audit.pdf" in report
