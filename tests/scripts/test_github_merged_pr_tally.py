from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "github-merged-pr-tally.py"
SPEC = importlib.util.spec_from_file_location("github_merged_pr_tally", SCRIPT)
assert SPEC is not None
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_parse_date_window_uses_requested_timezone() -> None:
    window = module.parse_window("2026-05-03", None, "America/Chicago")

    assert window.since == datetime(2026, 5, 3, 5, tzinfo=UTC)
    assert window.until == datetime(2026, 5, 4, 5, tzinfo=UTC)


def test_filter_merged_prs_uses_half_open_window() -> None:
    window = module.parse_window("2026-05-03T00:00:00Z", "2026-05-04T00:00:00Z", "UTC")
    prs = [
        {"number": 1, "mergedAt": "2026-05-02T23:59:59Z"},
        {"number": 2, "mergedAt": "2026-05-03T00:00:00Z"},
        {"number": 3, "mergedAt": "2026-05-03T12:30:00Z"},
        {"number": 4, "mergedAt": "2026-05-04T00:00:00Z"},
        {"number": 5, "mergedAt": None},
    ]

    selected = module.filter_merged_prs(prs, window)

    assert [pr["number"] for pr in selected] == [2, 3]


def test_render_markdown_includes_count_authors_and_links() -> None:
    window = module.parse_window("2026-05-03T00:00:00Z", "2026-05-04T00:00:00Z", "UTC")
    prs = [
        {
            "number": 42,
            "title": "Ship a verified tally",
            "mergedAt": "2026-05-03T03:04:05Z",
            "url": "https://github.com/example/repo/pull/42",
            "author": {"login": "cx-green"},
        }
    ]

    markdown = module.render_markdown(prs, window)

    assert "- Count: `1`" in markdown
    assert "- `cx-green`: 1" in markdown
    assert "[#42](https://github.com/example/repo/pull/42)" in markdown
    assert "Ship a verified tally" in markdown


def test_load_prs_from_json_file_avoids_gh_call(tmp_path: Path) -> None:
    source = tmp_path / "prs.json"
    source.write_text(json.dumps([{"number": 7, "mergedAt": "2026-05-03T00:00:00Z"}]))

    prs = module.load_prs(source, repo=None, limit=300)

    assert prs == [{"number": 7, "mergedAt": "2026-05-03T00:00:00Z"}]


def test_build_gh_command_is_explicit_and_read_only() -> None:
    command = module.build_gh_command("ryanklee/hapax-council", 50)

    assert command == [
        "gh",
        "pr",
        "list",
        "--state",
        "merged",
        "--limit",
        "50",
        "--json",
        "number,title,mergedAt,author,url,headRefName,baseRefName",
        "--repo",
        "ryanklee/hapax-council",
    ]
