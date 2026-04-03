"""Documentation source files and loader for drift detection."""

from __future__ import annotations

from opentelemetry import trace

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

DOC_FILES = [
    CLAUDE_CONFIG_DIR / "CLAUDE.md",
    HAPAXROMANA_DIR / "CLAUDE.md",
    HAPAXROMANA_DIR / "agent-architecture.md",
    HAPAXROMANA_DIR / "operations-manual.md",
    HAPAXROMANA_DIR / "README.md",
    AI_AGENTS_DIR / "CLAUDE.md",
    AI_AGENTS_DIR / "docs" / "logos-design-language.md",
    AI_AGENTS_DIR / "systemd" / "README.md",
]

# Hardware devices removed — Pi fleet handles camera monitoring (see pi-edge/).
EXPECTED_DEVICES: dict[str, str] = {}

HAPAX_REPO_DIRS = [
    AI_AGENTS_DIR,
    HAPAXROMANA_DIR,
    LOGOS_WEB_DIR,
    OBSIDIAN_HAPAX_DIR,
    HAPAX_VSCODE_DIR,
]

# Also check CLAUDE.md in canonical repos (scoped to HAPAX_REPO_DIRS only)
for _p in HAPAX_REPO_DIRS:
    _candidate = _p / "CLAUDE.md"
    if _candidate.is_file() and _candidate not in DOC_FILES:
        DOC_FILES.append(_candidate)


def load_docs() -> dict[str, str]:
    """Load all documentation files as {short_path: content}."""
    with _tracer.start_as_current_span("drift.load_docs"):
        docs = {}
        home = str(HAPAX_HOME)
        for path in DOC_FILES:
            if path.is_file():
                try:
                    text = path.read_text(errors="replace")
                    short = str(path).replace(home, "~")
                    docs[short] = text
                except OSError:
                    continue
        return docs
