from __future__ import annotations

import importlib.machinery
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-hkp-ci-advisory"
GENERATED_AT = "2026-06-19T20:00:00Z"

_mod = importlib.machinery.SourceFileLoader("hkp_ci_advisory", str(SCRIPT)).load_module()
run_advisory = _mod.run_advisory
_redact = _mod._redact
BANNER = _mod.BANNER
main = _mod.main


def test_advisory_warns_on_unparseable_markdown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    doc = repo / "docs" / "plain.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# Plain doc\nno frontmatter\n", encoding="utf-8")
    body = run_advisory([doc], repo_root=repo, generated_at=GENERATED_AT)
    assert BANNER in body
    assert "source_frontmatter_unparseable" in body
    assert "not a merge gate" in body.lower()


def test_advisory_excludes_error_severity_findings(tmp_path: Path, monkeypatch) -> None:
    # a cc-task missing route metadata yields a route_metadata_gap *error* (high-risk
    # source class) — an error-severity / hard finding that must NOT be surfaced.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    doc = repo / "20-projects" / "hapax-cc-tasks" / "active" / "t.md"
    doc.parent.mkdir(parents=True)
    fm = {
        "type": "cc-task",
        "task_id": "ci-err",
        "title": "T",
        "status": "offered",
        "mutation_surface": "source",
    }
    doc.write_text(
        "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n# T\nbody\n", encoding="utf-8"
    )
    body = run_advisory([doc], repo_root=repo, generated_at=GENERATED_AT)
    assert "route_metadata_gap" not in body  # error-severity finding excluded


def test_advisory_empty_for_non_markdown(tmp_path: Path) -> None:
    py = tmp_path / "x.py"
    py.write_text("print('hi')\n", encoding="utf-8")
    assert run_advisory([py], repo_root=tmp_path, generated_at=GENERATED_AT) == ""


def test_redact_scrubs_paths_and_secrets() -> None:
    out = _redact("leak /private/secrets/key.pem and Bearer abcdefgh12345678")
    assert "/private/secrets/key.pem" not in out
    assert "abcdefgh12345678" not in out


def test_cli_smoke(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    doc = repo / "docs" / "p.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# p\nno frontmatter\n", encoding="utf-8")
    rc = main(["--changed", str(doc), "--repo-root", str(repo)])
    assert rc == 0
    assert BANNER in capsys.readouterr().out
