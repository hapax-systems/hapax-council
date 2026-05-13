from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "omg_public_surface_source_reconcile.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("omg_public_surface_source_reconcile", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_token_capital_hits_do_not_match_rag_substrings() -> None:
    module = load_script_module()

    assert module.token_capital_hits("historical paragraph and archive framing") == []
    assert module.token_capital_hits("RAG documents_v2 uses Nomic") == [
        "documents_v2",
        "nomic",
        "rag",
    ]


def test_public_surface_reconcile_matches_sources_and_receipts(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    state_root = tmp_path / "state" / "publish"
    research_root = tmp_path / "research"
    publication_log = tmp_path / "publication-log.jsonl"
    output = tmp_path / "report.json"
    markdown = tmp_path / "report.md"
    fixture = tmp_path / "live.json"

    landing_source = "<html><body>governed-path landing page</body></html>"
    show_hn_source = "---\nTitle: Show HN\n---\n\n# Show HN\n\nScoped governed-path copy.\n"
    support_source = "---\nTitle: Support\n---\n\n# Support\n\nReceive-only support copy.\n"

    (repo_root / "agents" / "omg_web_builder" / "static").mkdir(parents=True)
    (repo_root / "agents" / "omg_web_builder" / "static" / "index.html").write_text(
        landing_source,
        encoding="utf-8",
    )
    (repo_root / "docs" / "publication-drafts").mkdir(parents=True)
    (repo_root / "docs" / "publication-drafts" / "show-hn-governance-that-ships.md").write_text(
        show_hn_source,
        encoding="utf-8",
    )
    (repo_root / "docs" / "research" / "evidence").mkdir(parents=True)
    (
        repo_root
        / "docs"
        / "research"
        / "evidence"
        / "2026-05-12-public-surface-claim-inventory.md"
    ).write_text("The support entry was patched and receipted.", encoding="utf-8")
    (research_root / "weblog").mkdir(parents=True)
    (research_root / "weblog" / "unused.md").write_text("# Unused\n", encoding="utf-8")
    (state_root / "published").mkdir(parents=True)
    (state_root / "published" / "show-hn-governance-that-ships.json").write_text(
        json.dumps(
            {
                "slug": "show-hn-governance-that-ships",
                "title": "Show HN",
                "approval": "published",
                "body_md": show_hn_source,
            }
        ),
        encoding="utf-8",
    )
    (state_root / "log").mkdir(parents=True)
    (state_root / "log" / "show-hn-governance-that-ships.omg-weblog.json").write_text(
        json.dumps(
            {
                "slug": "show-hn-governance-that-ships",
                "surface": "omg-weblog",
                "result": "ok",
            }
        ),
        encoding="utf-8",
    )
    publication_log.write_text(
        json.dumps(
            {
                "surface": "omg-lol-weblog-bearer-fanout",
                "target": "show-hn-governance-that-ships",
                "result": "ok",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    fixture.write_text(
        json.dumps(
            {
                "landing_page": {"content": landing_source},
                "entries": [
                    {
                        "entry": "show-hn-governance-that-ships",
                        "location": "/2026/05/show-hn-governance-that-ships",
                        "title": "Show HN",
                        "type": "post",
                        "source": show_hn_source,
                    },
                    {
                        "entry": "support",
                        "location": "/support",
                        "title": "Support",
                        "type": "Page",
                        "source": support_source,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(repo_root),
            "--state-root",
            str(state_root),
            "--publication-log",
            str(publication_log),
            "--research-root",
            str(research_root),
            "--live-json",
            str(fixture),
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--no-vault-markdown",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["live_items"] == 3
    assert report["summary"]["exact_source_matches"] == 2
    rows = {row["item_id"]: row for row in report["rows"]}
    assert rows["landing-page"]["disposition"] == "committed_or_local_source_exact_match"
    assert rows["show-hn-governance-that-ships"]["disposition"] == (
        "committed_or_local_source_exact_match"
    )
    assert rows["support"]["disposition"] == "api_only_with_committed_receipt"
    assert "receive-only support" in rows["support"]["claim_ceiling"]
    assert "Repeatable Command" in markdown.read_text(encoding="utf-8")


def test_public_surface_reconcile_can_fail_on_unreconciled(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    state_root = tmp_path / "state"
    research_root = tmp_path / "research"
    fixture = tmp_path / "live.json"
    output = tmp_path / "report.json"
    markdown = tmp_path / "report.md"
    (repo_root / "agents" / "omg_web_builder" / "static").mkdir(parents=True)
    (repo_root / "agents" / "omg_web_builder" / "static" / "index.html").write_text(
        "landing",
        encoding="utf-8",
    )
    fixture.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "entry": "unbacked-entry",
                        "location": "/unbacked-entry",
                        "title": "Unbacked Entry",
                        "source": "No source candidate.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(repo_root),
            "--state-root",
            str(state_root),
            "--publication-log",
            str(tmp_path / "publication-log.jsonl"),
            "--research-root",
            str(research_root),
            "--live-json",
            str(fixture),
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--no-vault-markdown",
            "--fail-on-unreconciled",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["unreconciled_items"] == ["unbacked-entry"]
