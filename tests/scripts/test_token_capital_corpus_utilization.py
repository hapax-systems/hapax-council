from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "token_capital_corpus_utilization.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_token_capital_corpus_utilization", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_record_includes_text_denominator_and_metadata_exclusion(tmp_path: Path) -> None:
    module = _load_module()
    included = tmp_path / "note.md"
    included.write_text("alpha beta gamma delta", encoding="utf-8")
    metadata = tmp_path / "stub.md"
    metadata.write_text("---\nis_metadata_only: true\n---\nDrive link", encoding="utf-8")

    included_record = module.build_record(included)
    metadata_record = module.build_record(metadata)

    assert included_record.included is True
    assert included_record.estimated_tokens == 6
    assert metadata_record.included is False
    assert "metadata_only_inventory" in metadata_record.exclusion_reasons


def test_denominator_summary_counts_exclusions_and_authority(tmp_path: Path) -> None:
    module = _load_module()
    good = tmp_path / "a.md"
    good.write_text("hello world", encoding="utf-8")
    binary = tmp_path / "b.pdf"
    binary.write_bytes(b"%PDF")

    summary = module.denominator_summary([module.build_record(good), module.build_record(binary)])

    assert summary["files_discovered"] == 2
    assert summary["files_in_denominator"] == 1
    assert summary["files_excluded"] == 1
    assert summary["excluded_by_reason"] == {"binary_or_unsupported_text_extraction": 1}


def test_qdrant_source_index_scrolls_distinct_sources() -> None:
    module = _load_module()

    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def scroll(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return (
                    [
                        SimpleNamespace(payload={"source": "/tmp/a.md"}),
                        SimpleNamespace(payload={"source": "/tmp/a.md"}),
                        SimpleNamespace(payload={"source": "/tmp/b.md"}),
                    ],
                    "next",
                )
            return ([], None)

    index = module.qdrant_source_index(
        collection="documents_v2",
        qdrant_url="http://qdrant.test",
        client=FakeClient(),
    )

    assert index["point_count_scrolled"] == 3
    assert index["distinct_source_count"] == 2
    assert index["chunk_count_by_source"] == {"/tmp/a.md": 2, "/tmp/b.md": 1}


def test_sources_from_eval_report_supports_golden_and_answer_shapes(tmp_path: Path) -> None:
    module = _load_module()
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "suite_id": "suite",
                "retrieval_summary": {
                    "golden_label_utilization_rate": 0.5,
                    "golden_label_utilization_numerator": 1,
                    "golden_label_utilization_denominator": 2,
                },
                "queries": [{"hits": [{"source": "/tmp/a.md"}]}],
                "variants": [
                    {"queries": [{"contexts": [{"source": "/tmp/b.md"}]}]},
                ],
            }
        ),
        encoding="utf-8",
    )

    sources = module.sources_from_eval_report(path)

    assert sources["retrieved_sources"] == ["/tmp/a.md", "/tmp/b.md"]
    assert sources["answer_context_sources"] == ["/tmp/b.md"]
    assert sources["golden_label_utilization_rate"] == 0.5


def test_build_report_distinguishes_index_retrieval_and_answer_context(tmp_path: Path) -> None:
    module = _load_module()
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    c = tmp_path / "c.md"
    for path in (a, b, c):
        path.write_text("one two three four", encoding="utf-8")
    records = [module.build_record(path) for path in (a, b, c)]

    report = module.build_report(
        source_profile="audit-publication",
        collection="documents_v2",
        qdrant_url="http://qdrant.test",
        records=records,
        qdrant_index={
            "collection": "documents_v2",
            "point_count_scrolled": 2,
            "distinct_source_count": 2,
            "chunk_count_by_source": {str(a): 1, str(b): 1},
        },
        eval_reports=[
            {
                "path": "/tmp/report.json",
                "retrieved_sources": [str(b)],
                "answer_context_sources": [str(c)],
            }
        ],
    )

    assert report["utilization"]["indexed_in_qdrant"]["matched_file_count"] == 2
    assert report["utilization"]["retrieved_in_eval_reports"]["matched_file_count"] == 1
    assert report["utilization"]["used_as_answer_context"]["matched_file_count"] == 1
    assert report["utilization"]["downstream_contribution"]["status"] == "not_measured"
