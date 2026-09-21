"""Documentation source files and loader for drift detection."""

from __future__ import annotations

from pathlib import Path

from opentelemetry import trace

from shared.prose_assertion_extractor import instruction_source_paths

from .config import (
    AI_AGENTS_DIR,
    CLAUDE_CONFIG_DIR,
    HAPAX_HOME,
    HAPAX_VSCODE_DIR,
    HAPAXROMANA_DIR,
    LOGOS_WEB_DIR,
    OBSIDIAN_HAPAX_DIR,
)

_tracer = trace.get_tracer(__name__)

# ── Documentation sources ────────────────────────────────────────────────────

# Hardware devices removed — Pi fleet handles camera monitoring (see pi-edge/).
EXPECTED_DEVICES: dict[str, str] = {}

HAPAX_REPO_DIRS = [
    AI_AGENTS_DIR,
    HAPAXROMANA_DIR,
    LOGOS_WEB_DIR,
    OBSIDIAN_HAPAX_DIR,
    HAPAX_VSCODE_DIR,
]


def _doc_files() -> list[Path]:
    """Select authored instructions and the existing explicit documentation set."""
    paths = [
        HAPAXROMANA_DIR / "agent-architecture.md",
        HAPAXROMANA_DIR / "operations-manual.md",
        HAPAXROMANA_DIR / "README.md",
        AI_AGENTS_DIR / "docs" / "logos-design-language.md",
        AI_AGENTS_DIR / "systemd" / "README.md",
    ]
    for repo in HAPAX_REPO_DIRS:
        paths.extend(instruction_source_paths(repo, recursive=False))

    shared_policy = AI_AGENTS_DIR / "config" / "agent-instructions" / "AGENTS.md"
    if not shared_policy.is_file():
        paths.append(CLAUDE_CONFIG_DIR / "CLAUDE.md")
    return list(dict.fromkeys(paths))


DOC_FILES = _doc_files()


def load_docs() -> dict[str, str]:
    """Load all documentation files as {short_path: content}."""
    with _tracer.start_as_current_span("drift.load_docs"):
        docs = {}
        seen: set[Path] = set()
        home = str(HAPAX_HOME)
        for path in DOC_FILES:
            try:
                path = path.resolve()
                if path in seen or not path.is_file():
                    continue
                text = path.read_text(errors="replace")
                short = str(path).replace(home, "~")
                docs[short] = text
                seen.add(path)
            except (OSError, RuntimeError):
                continue
        return docs
