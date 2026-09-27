"""Exercise the Council binding through existing readers and path consumers."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from agents.request_decomposer.models import _is_governance_protected_path
from shared.prose_assertion_extractor import (
    extract_from_directory,
    extract_from_directory_resumable,
)

ROOT = Path(__file__).resolve().parents[1]


def test_council_alias_delivers_the_canonical_body() -> None:
    alias = ROOT / "CLAUDE.md"
    assert alias.is_symlink()
    assert alias.readlink() == Path("AGENTS.md")
    body = (ROOT / "AGENTS.md").read_bytes()
    assert len(body) > 1000
    assert alias.read_bytes() == body


@pytest.mark.parametrize("resumable", [False, True])
def test_existing_assertion_reader_follows_alias_once(tmp_path: Path, resumable: bool) -> None:
    (tmp_path / "AGENTS.md").write_text("# Rules\n\nNEVER bypass the S-4 wet path.\n")
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "CLAUDE.md").write_text("# Legacy\n\nTests MUST pass before release.\n")
    reader = extract_from_directory_resumable if resumable else extract_from_directory
    results = reader(tmp_path, source_kind="claude_md")
    assert len(results) == 2
    assert {r.text for r in results} == {
        "NEVER bypass the S-4 wet path.",
        "Tests MUST pass before release.",
    }
    if resumable:
        assert reader(tmp_path, source_kind="claude_md") == []


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md",
        "nested/AGENTS.md",
        "CLAUDE.md",
        "nested/CLAUDE.md",
        "config/agent-instructions/AGENTS.md",
        "config/agent-instructions/native/claude.md",
        "config/agent-instructions/native/grok.md",
        "config/agent-instructions/native/kimi.md",
        "config/agent-instructions/native/vibe.md",
        "config/agent-instructions/native/future-client.md",
        "config/agent-instructions/bindings.json",
        "docs/runbooks/council-domain-context.md",
        "scripts/install-agent-instructions.py",
    ],
)
def test_codeowners_consumer_protects_instruction_paths(path: str) -> None:
    assert _is_governance_protected_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "docs/AGENTS.md.example",
        "docs/CLAUDE.md.example",
        "agents/helper.py",
        "docs/runbooks/ordinary.md",
        "config/ordinary.yaml",
        "config/agent-instructions/README.md",
        "config/agent-instructions/native/claude.md.example",
        "config/agent-instructions/native-extra/claude.md",
        "config/agent-instructions/bindings.json.example",
        "config/agent-instructions-extra/bindings.json",
        "docs/runbooks/council-domain-context.md.example",
        "docs/runbooks/other-council-domain-context.md",
        "scripts/install-agent-instructions.py.example",
        "scripts/other-install-agent-instructions.py",
    ],
)
def test_codeowners_consumer_does_not_classify_lookalikes(path: str) -> None:
    assert not _is_governance_protected_path(path)


def test_rotation_entrypoints_select_both_instruction_names() -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hooks = [h for repo in config["repos"] for h in repo["hooks"] if h["id"] == "claude-md-rot"]
    assert len(hooks) == 1
    selector = re.compile(hooks[0]["files"])
    for path in ("AGENTS.md", "nested/AGENTS.md", "CLAUDE.md", "nested/CLAUDE.md"):
        assert selector.search(path), path
    assert not selector.search("docs/AGENTS.md.example")
    workflow = yaml.load(
        (ROOT / ".github/workflows/claude-md-rot.yml").read_text(), Loader=yaml.BaseLoader
    )
    for event in ("push", "pull_request"):
        assert "**/AGENTS.md" in workflow["on"][event]["paths"]
        assert "**/CLAUDE.md" in workflow["on"][event]["paths"]
