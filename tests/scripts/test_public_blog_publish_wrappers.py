"""Tests for public blog publication wrapper scripts."""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HN_SCRIPT = REPO_ROOT / "scripts" / "publish-hn-blog-post.py"
CONSTITUTIONAL_SCRIPT = REPO_ROOT / "scripts" / "publish-constitutional-blog-post.py"
HN_DRAFT = REPO_ROOT / "docs" / "publication-drafts" / "2026-05-10-show-hn-governance-that-ships.md"
CONSTITUTIONAL_DRAFT = (
    REPO_ROOT
    / "docs"
    / "publication-drafts"
    / "2026-05-11-constitutional-governance-beyond-prompt-engineering.md"
)
FORBIDDEN_DIRECT_IMPORTS = (
    "OmgLolWeblogPublisher",
    "PublisherPayload",
    "OmgLolClient",
    "bridgy_posse_fanout",
)


def _load_script(script_path: Path, module_name: str):
    loader = importlib.machinery.SourceFileLoader(module_name, str(script_path))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_show_hn_wrapper_forwards_to_publication_bus(monkeypatch, tmp_path) -> None:
    module = _load_script(HN_SCRIPT, "publish_hn_blog_post_under_test")
    captured: list[list[str]] = []

    def fake_publish_vault_artifact_main(argv: list[str]) -> int:
        captured.append(argv)
        return 0

    monkeypatch.setattr(module.publish_vault_artifact, "main", fake_publish_vault_artifact_main)

    rc = module.main(
        [
            "--dry-run",
            "--no-posse",
            "--state-root",
            str(tmp_path),
            "--approver",
            "Operator",
        ]
    )

    assert rc == 0
    assert captured == [
        [
            str(HN_DRAFT),
            "--surfaces",
            "omg-weblog",
            "--approver",
            "Operator",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    ]


def test_constitutional_wrapper_forwards_to_publication_bus(monkeypatch, tmp_path) -> None:
    module = _load_script(CONSTITUTIONAL_SCRIPT, "publish_constitutional_blog_post_under_test")
    captured: list[list[str]] = []

    def fake_publish_vault_artifact_main(argv: list[str]) -> int:
        captured.append(argv)
        return 0

    monkeypatch.setattr(module.publish_vault_artifact, "main", fake_publish_vault_artifact_main)

    rc = module.main(
        [
            "--dry-run",
            "--surfaces",
            "omg-weblog,bluesky-post",
            "--state-root",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert captured == [
        [
            str(CONSTITUTIONAL_DRAFT),
            "--surfaces",
            "omg-weblog,bluesky-post",
            "--approver",
            "Oudepode",
            "--state-root",
            str(tmp_path),
            "--dry-run",
        ]
    ]


def test_public_blog_wrappers_have_no_direct_public_publisher_imports() -> None:
    for script_path in (HN_SCRIPT, CONSTITUTIONAL_SCRIPT):
        script = script_path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_DIRECT_IMPORTS:
            assert forbidden not in script
