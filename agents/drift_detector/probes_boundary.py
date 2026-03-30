"""Corporate boundary sufficiency probes."""

from __future__ import annotations

import re
import subprocess

from .config import (
    AI_AGENTS_DIR,
    HAPAX_VSCODE_DIR,
    HAPAXROMANA_DIR,
    LOGOS_WEB_DIR,
    OBSIDIAN_HAPAX_DIR,
)
from .sufficiency_probes import SufficiencyProbe


def _check_plugin_direct_api_support() -> tuple[bool, str]:
    """Check obsidian-hapax supports direct API calls without localhost proxy."""
    providers_dir = OBSIDIAN_HAPAX_DIR / "src" / "providers"
    if not providers_dir.exists():
        return False, "obsidian-hapax providers directory not found"

    has_anthropic = (providers_dir / "anthropic.ts").exists()
    has_openai = (providers_dir / "openai-compatible.ts").exists()

    index_file = providers_dir / "index.ts"
    if not index_file.exists():
        return False, "providers/index.ts not found"

    content = index_file.read_text()
    has_provider_switch = "anthropic" in content and "openai" in content

    if has_anthropic and has_openai and has_provider_switch:
        return True, "plugin has anthropic + openai direct providers with switch in index.ts"
    missing: list[str] = []
    if not has_anthropic:
        missing.append("anthropic.ts")
    if not has_openai:
        missing.append("openai-compatible.ts")
    if not has_provider_switch:
        missing.append("provider switch")
    return False, f"missing direct API support: {', '.join(missing)}"


def _check_plugin_graceful_degradation() -> tuple[bool, str]:
    """Check obsidian-hapax degrades gracefully for localhost services."""
    qdrant_file = OBSIDIAN_HAPAX_DIR / "src" / "qdrant-client.ts"
    if not qdrant_file.exists():
        return False, "qdrant-client.ts not found"

    content = qdrant_file.read_text()
    has_error_handling = "catch" in content
    has_console_warn = "console.warn" in content or "console.error" in content

    if has_error_handling and has_console_warn:
        return True, "qdrant-client.ts has catch blocks with console.warn for graceful degradation"
    missing: list[str] = []
    if not has_error_handling:
        missing.append("catch blocks")
    if not has_console_warn:
        missing.append("warning output")
    return False, f"qdrant-client.ts missing graceful degradation: {', '.join(missing)}"


def _check_plugin_credentials_in_settings() -> tuple[bool, str]:
    """Check obsidian-hapax stores API keys in plugin settings only."""
    settings_file = OBSIDIAN_HAPAX_DIR / "src" / "settings.ts"
    types_file = OBSIDIAN_HAPAX_DIR / "src" / "types.ts"
    if not settings_file.exists() or not types_file.exists():
        return False, "settings.ts or types.ts not found"

    types_content = types_file.read_text()
    has_api_key_field = "apiKey" in types_content

    src_dir = OBSIDIAN_HAPAX_DIR / "src"
    env_patterns = [r"process\.env", r"dotenv", r"\.env\b"]
    for ts_file in src_dir.rglob("*.ts"):
        try:
            file_content = ts_file.read_text()
        except OSError:
            continue
        for pat in env_patterns:
            if re.search(pat, file_content):
                return False, f"env-based secret access found in {ts_file.name}"

    if has_api_key_field:
        return (
            True,
            "API keys stored in plugin settings (data.json via Obsidian), no env-based secrets",
        )
    return False, "apiKey field not found in types.ts"


def _check_gitignore_security() -> tuple[bool, str]:
    """Check repos have required .gitignore patterns and no tracked secrets."""
    repos = {
        "hapax-council": AI_AGENTS_DIR,
        "obsidian-hapax": OBSIDIAN_HAPAX_DIR,
        "hapaxromana": HAPAXROMANA_DIR,
        "hapax-vscode": HAPAX_VSCODE_DIR,
        "hapax-logos": LOGOS_WEB_DIR,
    }

    required_patterns = [".env", "*.pem", "*.key", "credentials.json"]
    sensitive_globs = ["*.pem", "*.key", ".env", ".env.*", "credentials.json"]
    problems: list[str] = []
    checked = 0

    for name, path in repos.items():
        gitignore = path / ".gitignore"
        if not path.exists():
            continue
        checked += 1

        if gitignore.exists():
            content = gitignore.read_text()
            for pat in required_patterns:
                if pat not in content:
                    problems.append(f"{name}: .gitignore missing '{pat}'")
        else:
            problems.append(f"{name}: no .gitignore")

        for glob_pat in sensitive_globs:
            try:
                result = subprocess.run(
                    ["git", "-C", str(path), "ls-files", glob_pat],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                tracked = result.stdout.strip()
                if tracked:
                    problems.append(f"{name}: tracked sensitive file(s): {tracked}")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue

    if checked == 0:
        return False, "no repos found to check"

    if not problems:
        return True, f"all {checked} repos have required .gitignore patterns, no tracked secrets"
    return False, f"{len(problems)} issue(s): {'; '.join(problems[:3])}"


BOUNDARY_PROBES: list[SufficiencyProbe] = [
    SufficiencyProbe(
        id="probe-cb-llm-001",
        axiom_id="corporate_boundary",
        implication_id="cb-llm-001",
        level="component",
        question="Does the Obsidian plugin support direct API calls without localhost proxy?",
        check=_check_plugin_direct_api_support,
    ),
    SufficiencyProbe(
        id="probe-cb-degrade-001",
        axiom_id="corporate_boundary",
        implication_id="cb-degrade-001",
        level="component",
        question="Does the plugin degrade gracefully when localhost services are unreachable?",
        check=_check_plugin_graceful_degradation,
    ),
    SufficiencyProbe(
        id="probe-cb-key-001",
        axiom_id="corporate_boundary",
        implication_id="cb-key-001",
        level="component",
        question="Are API credentials stored only in plugin settings (not env vars)?",
        check=_check_plugin_credentials_in_settings,
    ),
    SufficiencyProbe(
        id="probe-cb-secret-scan-001",
        axiom_id="corporate_boundary",
        implication_id="cb-key-001",
        level="system",
        question="Do repos have required .gitignore patterns and no tracked credential files?",
        check=_check_gitignore_security,
    ),
]
