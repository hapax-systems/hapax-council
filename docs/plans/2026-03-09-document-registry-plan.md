# Document Registry & Coverage Enforcement — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a document registry (YAML) and coverage enforcement checker to the drift detector so it detects absent documents, missing sections, undocumented CIs, and cross-repo awareness gaps.

**Architecture:** A YAML registry at `hapaxromana/docs/document-registry.yaml` declares archetypes, repos, coverage rules, and mutual awareness constraints. A new module `shared/document_registry.py` loads and validates the registry. A new function `check_document_registry()` in `drift_detector.py` runs deterministic checks and returns DriftItems. Existing `check_project_memory()` and `check_cross_project_boundary()` are subsumed.

**Tech Stack:** Python 3.12, PyYAML (already in deps), existing drift_detector.py patterns, unittest.mock for tests.

**Design doc:** `docs/plans/2026-03-09-document-registry-design.md`

---

### Task 1: Add missing path constants to shared/config.py

**Files:**
- Modify: `shared/config.py:56-61`
- Test: `tests/test_config_paths.py` (existing, verify no breakage)

**Step 1: Add HAPAX_VSCODE_DIR and HAPAX_CONTAINERIZATION_DIR**

Add after line 61 in `shared/config.py`:

```python
HAPAX_VSCODE_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-vscode"
HAPAX_CONTAINERIZATION_DIR: Path = HAPAX_PROJECTS_DIR / "hapax-containerization"
```

**Step 2: Update HAPAX_REPO_DIRS in drift_detector.py**

In `agents/drift_detector.py`, update the `HAPAX_REPO_DIRS` list (lines 94-101) to add the two new entries:

```python
HAPAX_REPO_DIRS = [
    AI_AGENTS_DIR,
    HAPAXROMANA_DIR,
    HAPAX_SYSTEM_DIR,
    RAG_PIPELINE_DIR,
    COCKPIT_WEB_DIR,
    OBSIDIAN_HAPAX_DIR,
    HAPAX_VSCODE_DIR,
    HAPAX_CONTAINERIZATION_DIR,
]
```

Update the import at the top of drift_detector.py to include the new constants:

```python
from shared.config import (
    get_model, CLAUDE_CONFIG_DIR, HAPAXROMANA_DIR, HAPAX_PROJECTS_DIR,
    HAPAX_HOME, AI_AGENTS_DIR, HAPAX_SYSTEM_DIR, RAG_PIPELINE_DIR,
    OBSIDIAN_HAPAX_DIR, COCKPIT_WEB_DIR,
    HAPAX_VSCODE_DIR, HAPAX_CONTAINERIZATION_DIR,
)
```

**Step 3: Run existing tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_drift_detector.py -q --tb=short`
Expected: All pass (no behavior change, just constants added)

**Step 4: Commit**

```bash
git add shared/config.py agents/drift_detector.py
git commit -m "feat: add hapax-vscode and hapax-containerization to repo dirs"
```

---

### Task 2: Create the document registry YAML

**Files:**
- Create: `~/projects/hapaxromana/docs/document-registry.yaml`

**Step 1: Write the registry file**

```yaml
# Document Registry — consumed by drift_detector for coverage enforcement.
#
# Defines document archetypes, per-repo required documents, CI-to-document
# coverage rules, and cross-repo mutual awareness constraints.
#
# Formal foundations:
#   - CMDB: CIs with typed relationships to documentation
#   - DITA: Document archetypes with required structural sections
#   - ADR: Design records as a first-class archetype
#
# See: docs/plans/2026-03-09-document-registry-design.md

version: 1

# ── Document archetypes ──────────────────────────────────────────────
archetypes:
  project-context:
    description: "Per-repo working context for Claude Code"
    required_sections:
      - "## Project Memory"
      - "## Conventions"
    composite: true
  specification:
    description: "Architectural design, invariants, contracts"
    required_sections:
      - "## Architecture"
    composite: false
  reference:
    description: "Canonical lookup tables, single source of truth"
    required_sections: []
    composite: false
  operational:
    description: "Procedures, workflows, troubleshooting"
    required_sections: []
    composite: false
  governance:
    description: "Axioms, rules, constraints, boundaries"
    required_sections: []
    composite: false
  design-record:
    description: "Point-in-time design decisions"
    required_sections:
      - "## Goal"
    composite: false

# ── Repo declarations ────────────────────────────────────────────────
repos:
  ai-agents:
    path: ~/projects/hapax-council
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
    ci_sources:
      agents: "agents/"
  hapaxromana:
    path: ~/projects/hapaxromana
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
      - path: agent-architecture.md
        archetype: specification
      - path: operations-manual.md
        archetype: operational
      - path: README.md
        archetype: project-context
  hapax-system:
    path: ~/projects/hapax-system
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
      - path: rules/axioms.md
        archetype: governance
      - path: rules/system-context.md
        archetype: reference
      - path: rules/management-context.md
        archetype: governance
  hapax-logos:
    path: ~/projects/hapax-logos
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
  hapax-vscode:
    path: ~/projects/hapax-vscode
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
  rag-pipeline:
    path: ~/projects/rag-pipeline
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
  obsidian-hapax:
    path: ~/projects/obsidian-hapax
    required_docs:
      - path: CLAUDE.md
        archetype: project-context
  hapax-containerization:
    path: ~/projects/hapax-containerization
    required_docs:
      - path: CLAUDE.md
        archetype: project-context

# ── Coverage rules ───────────────────────────────────────────────────
# "For every CI of type X, there must be a reference in document Y."
coverage_rules:
  - ci_type: agent
    reference_doc: "~/projects/hapax-system/rules/system-context.md"
    reference_section: "## Management Agents"
    match_by: name
    severity: medium
    description: "Every agent module must have a row in system-context.md"
  - ci_type: agent
    reference_doc: "~/projects/hapaxromana/agent-architecture.md"
    match_by: name_in_heading
    severity: low
    description: "Every agent should have a section in agent-architecture.md"
  - ci_type: timer
    reference_doc: "~/projects/hapax-system/rules/system-context.md"
    reference_section: "## Management Timers"
    match_by: name
    severity: medium
    description: "Every systemd timer must have a row in system-context.md"
  - ci_type: service
    reference_doc: "~/.claude/rules/environment.md"
    match_by: name
    severity: medium
    description: "Every Docker service must be documented in environment.md"
  - ci_type: repo
    reference_doc: "~/projects/hapaxromana/CLAUDE.md"
    reference_section: "## Related Repos"
    match_by: name
    severity: medium
    description: "Every hapax repo must appear in hapaxromana's Related Repos"
  - ci_type: mcp_server
    reference_doc: "~/.claude/CLAUDE.md"
    reference_section: "## MCP Servers"
    match_by: name
    severity: low
    description: "Every MCP server should be listed in global CLAUDE.md"

# ── Mutual awareness ────────────────────────────────────────────────
mutual_awareness:
  - type: repo_registry
    description: "All hapax repos must appear in hapaxromana's Related Repos"
    registry_doc: "~/projects/hapaxromana/CLAUDE.md"
    registry_section: "## Related Repos"
    severity: medium
  - type: spec_reference
    description: "Every repo should reference hapaxromana as spec source"
    target_phrase: "hapaxromana"
    severity: low
  - type: byte_identical
    description: "Cross-project boundary must be identical in both repos"
    docs:
      - "~/projects/hapaxromana/docs/cross-project-boundary.md"
      - "~/projects/hapax-containerization/docs/cross-project-boundary.md"
    severity: high
```

**Step 2: Commit in hapaxromana**

```bash
cd ~/projects/hapaxromana
git add docs/document-registry.yaml
git commit -m "feat: add document registry for drift coverage enforcement"
```

---

### Task 3: Create shared/document_registry.py — registry loader

**Files:**
- Create: `shared/document_registry.py`
- Test: `tests/test_document_registry.py`

**Step 1: Write failing tests for registry loading**

Create `tests/test_document_registry.py`:

```python
"""Tests for shared/document_registry.py — registry loading and validation."""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from shared.document_registry import (
    load_registry,
    DocumentRegistry,
    Archetype,
    RepoDeclaration,
    CoverageRule,
    MutualAwarenessRule,
)


MINIMAL_YAML = textwrap.dedent("""\
    version: 1
    archetypes:
      project-context:
        description: "Per-repo context"
        required_sections: ["## Project Memory"]
        composite: true
    repos:
      test-repo:
        path: ~/projects/test-repo
        required_docs:
          - path: CLAUDE.md
            archetype: project-context
    coverage_rules:
      - ci_type: agent
        reference_doc: "~/projects/test/system-context.md"
        match_by: name
        severity: medium
        description: "test rule"
    mutual_awareness:
      - type: repo_registry
        description: "test awareness"
        registry_doc: "~/projects/test/CLAUDE.md"
        registry_section: "## Related Repos"
        severity: medium
""")


def test_load_registry_from_string():
    reg = load_registry(yaml_content=MINIMAL_YAML)
    assert isinstance(reg, DocumentRegistry)
    assert reg.version == 1


def test_archetypes_parsed():
    reg = load_registry(yaml_content=MINIMAL_YAML)
    assert "project-context" in reg.archetypes
    arch = reg.archetypes["project-context"]
    assert isinstance(arch, Archetype)
    assert arch.required_sections == ["## Project Memory"]
    assert arch.composite is True


def test_repos_parsed():
    reg = load_registry(yaml_content=MINIMAL_YAML)
    assert "test-repo" in reg.repos
    repo = reg.repos["test-repo"]
    assert isinstance(repo, RepoDeclaration)
    assert repo.path == "~/projects/test-repo"
    assert len(repo.required_docs) == 1
    assert repo.required_docs[0]["archetype"] == "project-context"


def test_coverage_rules_parsed():
    reg = load_registry(yaml_content=MINIMAL_YAML)
    assert len(reg.coverage_rules) == 1
    rule = reg.coverage_rules[0]
    assert isinstance(rule, CoverageRule)
    assert rule.ci_type == "agent"
    assert rule.severity == "medium"


def test_mutual_awareness_parsed():
    reg = load_registry(yaml_content=MINIMAL_YAML)
    assert len(reg.mutual_awareness) == 1
    ma = reg.mutual_awareness[0]
    assert isinstance(ma, MutualAwarenessRule)
    assert ma.type == "repo_registry"


def test_load_registry_from_file(tmp_path):
    p = tmp_path / "registry.yaml"
    p.write_text(MINIMAL_YAML)
    reg = load_registry(path=p)
    assert reg.version == 1
    assert "project-context" in reg.archetypes


def test_load_registry_missing_file():
    reg = load_registry(path=Path("/nonexistent/registry.yaml"))
    assert reg is None


def test_load_registry_invalid_yaml():
    reg = load_registry(yaml_content=":::not yaml:::")
    assert reg is None
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_document_registry.py -q --tb=short`
Expected: FAIL — `shared.document_registry` does not exist

**Step 3: Implement shared/document_registry.py**

```python
"""Document registry loader — parses document-registry.yaml for drift enforcement.

Provides typed dataclasses for archetypes, repo declarations, coverage rules,
and mutual awareness constraints. Zero LLM calls, pure parsing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


@dataclass
class Archetype:
    """A document archetype with required structural sections."""
    description: str = ""
    required_sections: list[str] = field(default_factory=list)
    composite: bool = False


@dataclass
class RepoDeclaration:
    """A declared repo with its required documents."""
    path: str = ""
    required_docs: list[dict] = field(default_factory=list)
    ci_sources: dict[str, str] = field(default_factory=dict)


@dataclass
class CoverageRule:
    """A CI-to-document coverage assertion."""
    ci_type: str = ""
    reference_doc: str = ""
    reference_section: str = ""
    match_by: str = "name"
    severity: str = "medium"
    description: str = ""


@dataclass
class MutualAwarenessRule:
    """A cross-repo awareness constraint."""
    type: str = ""
    description: str = ""
    registry_doc: str = ""
    registry_section: str = ""
    target_phrase: str = ""
    docs: list[str] = field(default_factory=list)
    severity: str = "medium"


@dataclass
class DocumentRegistry:
    """Parsed document registry."""
    version: int = 1
    archetypes: dict[str, Archetype] = field(default_factory=dict)
    repos: dict[str, RepoDeclaration] = field(default_factory=dict)
    coverage_rules: list[CoverageRule] = field(default_factory=list)
    mutual_awareness: list[MutualAwarenessRule] = field(default_factory=list)


def load_registry(
    *,
    path: Path | None = None,
    yaml_content: str | None = None,
) -> DocumentRegistry | None:
    """Load and parse a document registry from file or string.

    Returns None if the file doesn't exist or YAML is invalid.
    """
    if yaml_content is None:
        if path is None or not path.is_file():
            return None
        try:
            yaml_content = path.read_text()
        except OSError as e:
            log.warning("Cannot read registry file %s: %s", path, e)
            return None

    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        log.warning("Invalid registry YAML: %s", e)
        return None

    if not isinstance(data, dict):
        return None

    reg = DocumentRegistry(version=data.get("version", 1))

    # Parse archetypes
    for name, info in data.get("archetypes", {}).items():
        reg.archetypes[name] = Archetype(
            description=info.get("description", ""),
            required_sections=info.get("required_sections", []),
            composite=info.get("composite", False),
        )

    # Parse repos
    for name, info in data.get("repos", {}).items():
        reg.repos[name] = RepoDeclaration(
            path=info.get("path", ""),
            required_docs=info.get("required_docs", []),
            ci_sources=info.get("ci_sources", {}),
        )

    # Parse coverage rules
    for rule_data in data.get("coverage_rules", []):
        reg.coverage_rules.append(CoverageRule(
            ci_type=rule_data.get("ci_type", ""),
            reference_doc=rule_data.get("reference_doc", ""),
            reference_section=rule_data.get("reference_section", ""),
            match_by=rule_data.get("match_by", "name"),
            severity=rule_data.get("severity", "medium"),
            description=rule_data.get("description", ""),
        ))

    # Parse mutual awareness
    for ma_data in data.get("mutual_awareness", []):
        reg.mutual_awareness.append(MutualAwarenessRule(
            type=ma_data.get("type", ""),
            description=ma_data.get("description", ""),
            registry_doc=ma_data.get("registry_doc", ""),
            registry_section=ma_data.get("registry_section", ""),
            target_phrase=ma_data.get("target_phrase", ""),
            docs=ma_data.get("docs", []),
            severity=ma_data.get("severity", "medium"),
        ))

    return reg
```

**Step 4: Run tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_document_registry.py -q --tb=short`
Expected: All pass

**Step 5: Commit**

```bash
git add shared/document_registry.py tests/test_document_registry.py
git commit -m "feat: add document registry loader with dataclass models"
```

---

### Task 4: CI discovery functions

**Files:**
- Create: `shared/ci_discovery.py`
- Test: `tests/test_ci_discovery.py`

**Step 1: Write failing tests**

Create `tests/test_ci_discovery.py`:

```python
"""Tests for shared/ci_discovery.py — CI discovery functions."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from shared.ci_discovery import (
    discover_agents,
    discover_timers,
    discover_services,
    discover_repos,
    discover_mcp_servers,
)


class TestDiscoverAgents:
    def test_finds_agent_modules(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "__init__.py").write_text("")
        (agents_dir / "briefing.py").write_text('if __name__ == "__main__":\n    pass')
        (agents_dir / "health_monitor.py").write_text('if __name__ == "__main__":\n    pass')
        (agents_dir / "shared_util.py").write_text("# no main block")
        (agents_dir / "__pycache__").mkdir()

        result = discover_agents(agents_dir)
        assert "briefing" in result
        assert "health-monitor" in result
        assert "shared-util" not in result
        assert "__init__" not in result

    def test_empty_dir(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        assert discover_agents(agents_dir) == []

    def test_normalizes_underscores(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "drift_detector.py").write_text('if __name__ == "__main__":\n    pass')
        result = discover_agents(agents_dir)
        assert "drift-detector" in result


class TestDiscoverTimers:
    @patch("subprocess.run")
    def test_parses_timer_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="daily-briefing.timer       enabled  enabled\nhealth-monitor.timer      enabled  enabled\n",
        )
        result = discover_timers()
        assert "daily-briefing" in result
        assert "health-monitor" in result

    @patch("subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        assert discover_timers() == []

    @patch("subprocess.run")
    def test_subprocess_failure(self, mock_run):
        mock_run.side_effect = OSError("systemctl not found")
        assert discover_timers() == []


class TestDiscoverServices:
    @patch("subprocess.run")
    def test_parses_docker_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="litellm\nqdrant\npostgres\n",
        )
        result = discover_services()
        assert "litellm" in result
        assert "qdrant" in result
        assert "postgres" in result

    @patch("subprocess.run")
    def test_subprocess_failure(self, mock_run):
        mock_run.side_effect = OSError("docker not found")
        assert discover_services() == []


class TestDiscoverRepos:
    def test_finds_hapax_repos(self, tmp_path):
        # Create fake repos
        for name in ["ai-agents", "hapax-vscode", "unrelated"]:
            repo = tmp_path / name
            repo.mkdir()
            (repo / ".git").mkdir()
        # ai-agents has CLAUDE.md mentioning hapax
        (tmp_path / "ai-agents" / "CLAUDE.md").write_text("Part of hapax system")
        # hapax-vscode matches prefix
        (tmp_path / "hapax-vscode" / "CLAUDE.md").write_text("Extension project")
        # unrelated has no CLAUDE.md
        result = discover_repos(tmp_path)
        assert "ai-agents" in result
        assert "hapax-vscode" in result
        assert "unrelated" not in result


class TestDiscoverMcpServers:
    def test_parses_mcp_config(self, tmp_path):
        config = tmp_path / "mcp_servers.json"
        config.write_text('{"memory": {"command": "uvx"}, "tavily": {"command": "npx"}}')
        result = discover_mcp_servers(config)
        assert "memory" in result
        assert "tavily" in result

    def test_missing_config(self, tmp_path):
        assert discover_mcp_servers(tmp_path / "nonexistent.json") == []
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_ci_discovery.py -q --tb=short`
Expected: FAIL — module does not exist

**Step 3: Implement shared/ci_discovery.py**

```python
"""CI discovery — find live Configuration Items for coverage enforcement.

Discovers agents, timers, services, repos, and MCP servers from the
filesystem, systemd, and Docker. Zero LLM calls.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def discover_agents(agents_dir: Path | None = None) -> list[str]:
    """Discover agent modules by scanning for files with __main__ blocks."""
    if agents_dir is None:
        from shared.config import AI_AGENTS_DIR
        agents_dir = AI_AGENTS_DIR / "agents"

    if not agents_dir.is_dir():
        return []

    agents = []
    for py_file in sorted(agents_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            content = py_file.read_text(errors="replace")
            if '__name__' in content and '__main__' in content:
                name = py_file.stem.replace("_", "-")
                agents.append(name)
        except OSError:
            continue
    return agents


def discover_timers() -> list[str]:
    """Discover active systemd user timers."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-unit-files", "*.timer", "--no-legend"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        timers = []
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if parts:
                name = parts[0].removesuffix(".timer")
                timers.append(name)
        return timers
    except (OSError, subprocess.TimeoutExpired):
        return []


def discover_services(compose_dir: Path | None = None) -> list[str]:
    """Discover running Docker Compose services."""
    if compose_dir is None:
        from shared.config import LLM_STACK_DIR
        compose_dir = LLM_STACK_DIR

    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}}"],
            capture_output=True, text=True, timeout=15,
            cwd=str(compose_dir) if compose_dir.is_dir() else None,
        )
        if result.returncode != 0:
            return []
        return [s.strip() for s in result.stdout.strip().splitlines() if s.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def discover_repos(projects_dir: Path | None = None) -> list[str]:
    """Discover hapax-related git repos.

    A repo is hapax-related if its name starts with 'hapax-' or it has a
    CLAUDE.md containing 'hapax' (case-insensitive).
    """
    if projects_dir is None:
        from shared.config import HAPAX_PROJECTS_DIR
        projects_dir = HAPAX_PROJECTS_DIR

    if not projects_dir.is_dir():
        return []

    repos = []
    for entry in sorted(projects_dir.iterdir()):
        if not entry.is_dir() or not (entry / ".git").exists():
            continue
        # Match by name prefix
        if entry.name.startswith("hapax-"):
            repos.append(entry.name)
            continue
        # Match by CLAUDE.md content
        claude_md = entry / "CLAUDE.md"
        if claude_md.is_file():
            try:
                content = claude_md.read_text(errors="replace")[:2000]
                if "hapax" in content.lower():
                    repos.append(entry.name)
            except OSError:
                continue
    return repos


def discover_mcp_servers(config_path: Path | None = None) -> list[str]:
    """Discover configured MCP servers from Claude Code config."""
    if config_path is None:
        from shared.config import CLAUDE_CONFIG_DIR
        config_path = CLAUDE_CONFIG_DIR / "mcp_servers.json"

    if not config_path.is_file():
        return []

    try:
        data = json.loads(config_path.read_text())
        return sorted(data.keys()) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError):
        return []
```

**Step 4: Run tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_ci_discovery.py -q --tb=short`
Expected: All pass

**Step 5: Commit**

```bash
git add shared/ci_discovery.py tests/test_ci_discovery.py
git commit -m "feat: add CI discovery functions for document registry enforcement"
```

---

### Task 5: Registry enforcement checker

**Files:**
- Create: `shared/registry_checks.py`
- Test: `tests/test_registry_checks.py`

This is the core enforcement logic — four sub-checks that produce DriftItems.

**Step 1: Write failing tests**

Create `tests/test_registry_checks.py`:

```python
"""Tests for shared/registry_checks.py — document registry enforcement."""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agents.drift_detector import DriftItem
from shared.document_registry import load_registry
from shared.registry_checks import (
    check_required_docs,
    check_archetype_sections,
    check_coverage_rules,
    check_mutual_awareness,
    check_document_registry,
)


REGISTRY_YAML = textwrap.dedent("""\
    version: 1
    archetypes:
      project-context:
        description: "Per-repo context"
        required_sections: ["## Project Memory", "## Conventions"]
        composite: true
    repos:
      test-repo:
        path: {tmpdir}/test-repo
        required_docs:
          - path: CLAUDE.md
            archetype: project-context
          - path: README.md
            archetype: project-context
    coverage_rules:
      - ci_type: agent
        reference_doc: "{tmpdir}/system-context.md"
        reference_section: "## Agents"
        match_by: name
        severity: medium
        description: "agents in system-context"
    mutual_awareness:
      - type: repo_registry
        description: "repos in registry"
        registry_doc: "{tmpdir}/registry-doc.md"
        registry_section: "## Related Repos"
        severity: medium
      - type: spec_reference
        description: "repos reference hapaxromana"
        target_phrase: "hapaxromana"
        severity: low
      - type: byte_identical
        description: "boundary must match"
        docs:
          - "{tmpdir}/boundary-a.md"
          - "{tmpdir}/boundary-b.md"
        severity: high
""")


@pytest.fixture
def registry_env(tmp_path):
    """Set up a minimal filesystem for registry checks."""
    # Create repo with CLAUDE.md (has Project Memory but no Conventions)
    repo = tmp_path / "test-repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("# Test\\n\\n## Project Memory\\nStuff here\\n")
    # README.md missing — should be detected

    # System-context doc with one agent listed
    (tmp_path / "system-context.md").write_text(
        "# System\\n\\n## Agents\\n| briefing | yes |\\n"
    )

    # Registry doc for mutual awareness
    (tmp_path / "registry-doc.md").write_text(
        "# Main\\n\\n## Related Repos\\n| test-repo | desc |\\n"
    )

    # Boundary docs — different content
    (tmp_path / "boundary-a.md").write_text("Version A content")
    (tmp_path / "boundary-b.md").write_text("Version B content")

    yaml_text = REGISTRY_YAML.replace("{tmpdir}", str(tmp_path))
    reg = load_registry(yaml_content=yaml_text)
    return reg, tmp_path


class TestCheckRequiredDocs:
    def test_detects_missing_doc(self, registry_env):
        reg, tmp_path = registry_env
        items = check_required_docs(reg)
        missing = [i for i in items if i.category == "missing-required-doc"]
        assert len(missing) == 1
        assert "README.md" in missing[0].doc_file

    def test_existing_doc_no_drift(self, registry_env):
        reg, tmp_path = registry_env
        # Create the missing README
        (tmp_path / "test-repo" / "README.md").write_text("# Readme\\n\\n## Project Memory\\n\\n## Conventions\\n")
        items = check_required_docs(reg)
        missing = [i for i in items if i.category == "missing-required-doc"]
        assert len(missing) == 0


class TestCheckArchetypeSections:
    def test_detects_missing_section(self, registry_env):
        reg, tmp_path = registry_env
        items = check_archetype_sections(reg)
        missing = [i for i in items if i.category == "missing-section"]
        # CLAUDE.md has ## Project Memory but not ## Conventions
        assert any("Conventions" in i.reality for i in missing)

    def test_all_sections_present(self, registry_env):
        reg, tmp_path = registry_env
        (tmp_path / "test-repo" / "CLAUDE.md").write_text(
            "# Test\\n\\n## Project Memory\\nstuff\\n\\n## Conventions\\nmore stuff\\n"
        )
        items = check_archetype_sections(reg)
        missing = [i for i in items if "test-repo/CLAUDE.md" in i.doc_file]
        assert len(missing) == 0


class TestCheckCoverageRules:
    def test_detects_undocumented_agent(self, registry_env):
        reg, tmp_path = registry_env
        # briefing is documented, drift-detector is not
        agents = ["briefing", "drift-detector"]
        items = check_coverage_rules(reg, discovered_cis={"agent": agents})
        gaps = [i for i in items if i.category == "coverage-gap"]
        assert any("drift-detector" in i.reality for i in gaps)
        assert not any("briefing" in i.reality for i in gaps)

    def test_no_gaps_when_all_documented(self, registry_env):
        reg, tmp_path = registry_env
        agents = ["briefing"]
        items = check_coverage_rules(reg, discovered_cis={"agent": agents})
        gaps = [i for i in items if i.category == "coverage-gap"]
        assert len(gaps) == 0


class TestCheckMutualAwareness:
    def test_byte_identical_mismatch(self, registry_env):
        reg, tmp_path = registry_env
        items = check_mutual_awareness(reg)
        boundary = [i for i in items if i.category == "boundary-mismatch"]
        assert len(boundary) == 1
        assert boundary[0].severity == "high"

    def test_byte_identical_match(self, registry_env):
        reg, tmp_path = registry_env
        (tmp_path / "boundary-b.md").write_text("Version A content")
        items = check_mutual_awareness(reg)
        boundary = [i for i in items if i.category == "boundary-mismatch"]
        assert len(boundary) == 0

    def test_spec_reference_gap(self, registry_env):
        reg, tmp_path = registry_env
        # CLAUDE.md doesn't mention hapaxromana
        items = check_mutual_awareness(reg, known_repos={"test-repo": tmp_path / "test-repo"})
        spec_gaps = [i for i in items if i.category == "spec-reference-gap"]
        assert len(spec_gaps) == 1


class TestCheckDocumentRegistryIntegration:
    @patch("shared.registry_checks.discover_agents", return_value=["briefing", "drift-detector"])
    @patch("shared.registry_checks.discover_timers", return_value=[])
    @patch("shared.registry_checks.discover_services", return_value=[])
    @patch("shared.registry_checks.discover_repos", return_value=["test-repo"])
    @patch("shared.registry_checks.discover_mcp_servers", return_value=[])
    def test_full_check(self, mock_mcp, mock_repos, mock_svcs, mock_timers, mock_agents, registry_env):
        reg, tmp_path = registry_env
        items = check_document_registry(registry=reg)
        assert isinstance(items, list)
        assert all(isinstance(i, DriftItem) for i in items)
        # Should find: missing README, missing Conventions section,
        # drift-detector coverage gap, boundary mismatch, spec reference gap
        categories = {i.category for i in items}
        assert "missing-required-doc" in categories
        assert "coverage-gap" in categories
        assert "boundary-mismatch" in categories
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_registry_checks.py -q --tb=short`
Expected: FAIL — module does not exist

**Step 3: Implement shared/registry_checks.py**

```python
"""Registry enforcement checks — produces DriftItems from document registry rules.

Four sub-checks:
1. Required document existence
2. Archetype section validation
3. CI coverage rules
4. Mutual awareness constraints
"""
from __future__ import annotations

import logging
from pathlib import Path

from agents.drift_detector import DriftItem
from shared.document_registry import (
    DocumentRegistry,
    load_registry,
)
from shared.ci_discovery import (
    discover_agents,
    discover_timers,
    discover_services,
    discover_repos,
    discover_mcp_servers,
)

log = logging.getLogger(__name__)


def _expand_path(p: str) -> Path:
    """Expand ~ in a path string to the actual home directory."""
    return Path(p.replace("~", str(Path.home())))


# ── Sub-check 1: Required document existence ─────────────────────────

def check_required_docs(registry: DocumentRegistry) -> list[DriftItem]:
    """Check that every declared required_doc exists on disk."""
    items: list[DriftItem] = []
    for repo_name, repo in registry.repos.items():
        repo_path = _expand_path(repo.path)
        for doc in repo.required_docs:
            doc_path = repo_path / doc["path"]
            if not doc_path.is_file():
                items.append(DriftItem(
                    severity="medium",
                    category="missing-required-doc",
                    doc_file=f"{repo_name}/{doc['path']}",
                    doc_claim=f"Registry requires {doc['path']} in {repo_name}",
                    reality="File does not exist",
                    suggestion=f"Create {doc['path']} in {repo_name} with archetype '{doc.get('archetype', 'unknown')}'",
                ))
    return items


# ── Sub-check 2: Archetype section validation ────────────────────────

def check_archetype_sections(registry: DocumentRegistry) -> list[DriftItem]:
    """Check that documents have the required sections for their archetype."""
    items: list[DriftItem] = []
    for repo_name, repo in registry.repos.items():
        repo_path = _expand_path(repo.path)
        for doc in repo.required_docs:
            archetype_name = doc.get("archetype", "")
            if archetype_name not in registry.archetypes:
                continue
            archetype = registry.archetypes[archetype_name]
            if not archetype.required_sections:
                continue

            doc_path = repo_path / doc["path"]
            if not doc_path.is_file():
                continue  # Already caught by check_required_docs

            try:
                content = doc_path.read_text(errors="replace")
            except OSError:
                continue

            for section in archetype.required_sections:
                if section not in content:
                    items.append(DriftItem(
                        severity="medium",
                        category="missing-section",
                        doc_file=f"{repo_name}/{doc['path']}",
                        doc_claim=f"Archetype '{archetype_name}' requires section: {section}",
                        reality=f"Section '{section}' not found in {doc['path']}",
                        suggestion=f"Add '{section}' section to {repo_name}/{doc['path']}",
                    ))
    return items


# ── Sub-check 3: CI coverage rules ──────────────────────────────────

def check_coverage_rules(
    registry: DocumentRegistry,
    *,
    discovered_cis: dict[str, list[str]] | None = None,
) -> list[DriftItem]:
    """Check that every discovered CI is referenced in its coverage doc."""
    if discovered_cis is None:
        discovered_cis = {
            "agent": discover_agents(),
            "timer": discover_timers(),
            "service": discover_services(),
            "repo": discover_repos(),
            "mcp_server": discover_mcp_servers(),
        }

    items: list[DriftItem] = []

    for rule in registry.coverage_rules:
        ci_names = discovered_cis.get(rule.ci_type, [])
        if not ci_names:
            continue

        ref_path = _expand_path(rule.reference_doc)
        if not ref_path.is_file():
            log.debug("Coverage rule reference doc not found: %s", rule.reference_doc)
            continue

        try:
            content = ref_path.read_text(errors="replace")
        except OSError:
            continue

        # If a section is specified, only search within that section
        search_text = content
        if rule.reference_section:
            section_start = content.find(rule.reference_section)
            if section_start >= 0:
                # Find the next ## heading after this section
                rest = content[section_start + len(rule.reference_section):]
                next_section = rest.find("\n## ")
                if next_section >= 0:
                    search_text = rest[:next_section]
                else:
                    search_text = rest
            else:
                search_text = ""  # Section not found — all CIs will be gaps

        for ci_name in ci_names:
            # Check if CI name appears in the search text
            # Try both hyphenated and underscored forms
            name_variants = {ci_name, ci_name.replace("-", "_"), ci_name.replace("_", "-")}
            found = any(variant in search_text for variant in name_variants)

            if not found:
                short_ref = rule.reference_doc.replace(str(Path.home()), "~")
                items.append(DriftItem(
                    severity=rule.severity,
                    category="coverage-gap",
                    doc_file=short_ref,
                    doc_claim=rule.description,
                    reality=f"{rule.ci_type} '{ci_name}' not found in {rule.reference_section or 'document'}",
                    suggestion=f"Add '{ci_name}' to {short_ref}",
                ))

    return items


# ── Sub-check 4: Mutual awareness ───────────────────────────────────

def check_mutual_awareness(
    registry: DocumentRegistry,
    *,
    known_repos: dict[str, Path] | None = None,
) -> list[DriftItem]:
    """Check cross-repo awareness constraints."""
    items: list[DriftItem] = []

    if known_repos is None:
        known_repos = {}
        for repo_name, repo in registry.repos.items():
            repo_path = _expand_path(repo.path)
            if repo_path.is_dir():
                known_repos[repo_name] = repo_path

    for rule in registry.mutual_awareness:
        if rule.type == "byte_identical":
            paths = [_expand_path(d) for d in rule.docs]
            if len(paths) < 2:
                continue
            if not all(p.is_file() for p in paths):
                missing = [str(p) for p in paths if not p.is_file()]
                for m in missing:
                    items.append(DriftItem(
                        severity=rule.severity,
                        category="boundary-mismatch",
                        doc_file=m.replace(str(Path.home()), "~"),
                        doc_claim=rule.description,
                        reality="File does not exist",
                        suggestion=f"Create or copy file: {m}",
                    ))
                continue
            contents = [p.read_bytes() for p in paths]
            if len(set(contents)) > 1:
                items.append(DriftItem(
                    severity=rule.severity,
                    category="boundary-mismatch",
                    doc_file=", ".join(str(p).replace(str(Path.home()), "~") for p in paths),
                    doc_claim=rule.description,
                    reality="Files differ",
                    suggestion="Diff and reconcile the files, then copy to both locations",
                ))

        elif rule.type == "spec_reference":
            phrase = rule.target_phrase
            if not phrase:
                continue
            for repo_name, repo_path in known_repos.items():
                claude_md = repo_path / "CLAUDE.md"
                if not claude_md.is_file():
                    continue
                try:
                    content = claude_md.read_text(errors="replace")
                except OSError:
                    continue
                if phrase.lower() not in content.lower():
                    items.append(DriftItem(
                        severity=rule.severity,
                        category="spec-reference-gap",
                        doc_file=f"{repo_name}/CLAUDE.md",
                        doc_claim=rule.description,
                        reality=f"'{phrase}' not found in {repo_name}/CLAUDE.md",
                        suggestion=f"Add reference to {phrase} in {repo_name}/CLAUDE.md",
                    ))

        elif rule.type == "repo_registry":
            registry_path = _expand_path(rule.registry_doc)
            if not registry_path.is_file():
                continue
            try:
                content = registry_path.read_text(errors="replace")
            except OSError:
                continue

            for repo_name in known_repos:
                # Check if repo name appears in registry doc
                if repo_name not in content:
                    items.append(DriftItem(
                        severity=rule.severity,
                        category="repo-awareness-gap",
                        doc_file=rule.registry_doc.replace(str(Path.home()), "~"),
                        doc_claim=rule.description,
                        reality=f"Repo '{repo_name}' not found in registry document",
                        suggestion=f"Add '{repo_name}' to {rule.registry_section or 'document'}",
                    ))

    return items


# ── Main entry point ─────────────────────────────────────────────────

def check_document_registry(
    *,
    registry: DocumentRegistry | None = None,
    registry_path: Path | None = None,
) -> list[DriftItem]:
    """Run all document registry checks and return DriftItems.

    If no registry is provided, loads from the default path at
    hapaxromana/docs/document-registry.yaml.
    """
    if registry is None:
        if registry_path is None:
            from shared.config import HAPAXROMANA_DIR
            registry_path = HAPAXROMANA_DIR / "docs" / "document-registry.yaml"
        registry = load_registry(path=registry_path)

    if registry is None:
        log.info("No document registry found, skipping registry checks")
        return []

    items: list[DriftItem] = []
    items.extend(check_required_docs(registry))
    items.extend(check_archetype_sections(registry))
    items.extend(check_coverage_rules(registry))
    items.extend(check_mutual_awareness(registry))
    return items
```

**Step 4: Run tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_registry_checks.py -q --tb=short`
Expected: All pass

**Step 5: Commit**

```bash
git add shared/registry_checks.py tests/test_registry_checks.py
git commit -m "feat: add document registry enforcement checks"
```

---

### Task 6: Wire registry checks into drift_detector.py

**Files:**
- Modify: `agents/drift_detector.py:540-666`
- Test: `tests/test_drift_detector.py` (add new tests)

**Step 1: Write failing test for registry integration**

Add to `tests/test_drift_detector.py`:

```python
class TestRegistryIntegration:
    """Test that check_document_registry is called in detect_drift."""

    @patch("agents.drift_detector.check_document_registry")
    @patch("agents.drift_detector.check_project_memory")
    @patch("agents.drift_detector.check_cross_project_boundary")
    @patch("agents.drift_detector.check_screen_context_drift")
    @patch("agents.drift_detector.check_doc_freshness")
    @patch("agents.drift_detector.scan_sufficiency_gaps")
    @patch("agents.drift_detector.scan_axiom_violations")
    @patch("agents.drift_detector.drift_agent")
    @patch("agents.drift_detector.load_docs")
    @patch("agents.drift_detector.generate_manifest")
    def test_detect_drift_calls_registry_check(
        self, mock_manifest, mock_docs, mock_agent, mock_axiom, mock_suff,
        mock_fresh, mock_screen, mock_boundary, mock_memory, mock_registry,
    ):
        mock_manifest.return_value = MagicMock()
        mock_docs.return_value = {"test.md": "content"}
        mock_agent.run = AsyncMock(return_value=MagicMock(
            output=DriftReport(drift_items=[], docs_analyzed=[], summary="clean"),
        ))
        mock_axiom.return_value = []
        mock_suff.return_value = []
        mock_fresh.return_value = []
        mock_screen.return_value = []
        mock_boundary.return_value = []
        mock_memory.return_value = []
        mock_registry.return_value = [
            DriftItem(
                severity="medium", category="coverage-gap",
                doc_file="test.md", doc_claim="test", reality="gap",
                suggestion="fix it",
            )
        ]

        import asyncio
        report = asyncio.run(detect_drift())
        mock_registry.assert_called_once()
        assert any(i.category == "coverage-gap" for i in report.drift_items)
```

**Step 2: Run test to verify it fails**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_drift_detector.py::TestRegistryIntegration -q --tb=short`
Expected: FAIL — check_document_registry not imported

**Step 3: Wire into detect_drift()**

In `agents/drift_detector.py`, add the import near the top (after existing imports):

```python
from shared.registry_checks import check_document_registry
```

In the `detect_drift()` function, after the `memory_drift = check_project_memory()` line (line 561), add:

```python
    # Run document registry checks (subsumes project_memory and cross_project_boundary)
    registry_drift = check_document_registry()
```

Update the deterministic_items merge (line 648) to include `registry_drift`:

```python
    deterministic_items = (
        axiom_violations + sufficiency_gaps + stale_docs
        + screen_context_drift + boundary_drift + memory_drift
        + registry_drift
    )
```

Add a summary part for registry drift (after the memory_drift summary, around line 663):

```python
        if registry_drift:
            parts.append(f"{len(registry_drift)} registry coverage gap(s)")
```

**Step 4: Run all drift detector tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/test_drift_detector.py -q --tb=short`
Expected: All pass

**Step 5: Commit**

```bash
git add agents/drift_detector.py tests/test_drift_detector.py
git commit -m "feat: wire document registry checks into drift detector"
```

---

### Task 7: Run full test suite and verify integration

**Files:**
- No new files — validation only

**Step 1: Run full test suite**

Run: `cd ~/projects/hapax-council && uv run pytest tests/ -q --tb=short --ignore=tests/test_vault_writer.py`
Expected: All tests pass (including new registry tests)

**Step 2: Run drift detector manually to verify**

Run: `cd ~/projects/hapax-council && eval "$(<.envrc)" && uv run python -m agents.drift_detector --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); cats=[i['category'] for i in d['drift_items']]; print(f'Total: {len(d[\"drift_items\"])}'); [print(f'  {c}: {cats.count(c)}') for c in sorted(set(cats))]"`

Expected: New categories like `coverage-gap`, `missing-section`, `repo-awareness-gap` should appear alongside existing drift items.

**Step 3: Verify no regressions in existing drift categories**

Existing categories (`config_mismatch`, `stale_doc`, `missing_project_memory`, etc.) should still appear. The registry checks add items but don't remove existing ones.

---

### Task 8: Remove subsumed checks (optional, can defer)

**Files:**
- Modify: `agents/drift_detector.py`

Once Task 7 confirms the registry checks work, the following can be removed since they're fully subsumed:

- `check_project_memory()` → subsumed by `check_archetype_sections()` (project-context archetype requires `## Project Memory`)
- `check_cross_project_boundary()` → subsumed by `check_mutual_awareness()` (byte_identical rule)

**This task is optional.** Keeping both provides defense-in-depth. Removing reduces code. Recommendation: defer until the registry has been running for a few cycles.

**If removing:**

1. Remove the function bodies from `drift_detector.py`
2. Remove their calls from `detect_drift()`
3. Remove `boundary_drift` and `memory_drift` from the deterministic_items merge
4. Run tests: `uv run pytest tests/test_drift_detector.py -q --tb=short`

**Do NOT remove yet if any test depends on the exact output of these functions.**
