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
    """Check obsidian-hapax calls Logos directly through the current src layout."""
    src_dir = OBSIDIAN_HAPAX_DIR / "src"
    if not src_dir.is_dir():
        return False, "obsidian-hapax src directory not found"

    required = {
        "logos-client.ts": src_dir / "logos-client.ts",
        "types.ts": src_dir / "types.ts",
        "settings.ts": src_dir / "settings.ts",
        "main.ts": src_dir / "main.ts",
    }
    missing_files = [name for name, path in required.items() if not path.is_file()]
    if missing_files:
        return False, f"obsidian-hapax current src layout missing: {', '.join(missing_files)}"

    client_content = required["logos-client.ts"].read_text(errors="replace")
    types_content = required["types.ts"].read_text(errors="replace")
    settings_content = required["settings.ts"].read_text(errors="replace")
    main_content = required["main.ts"].read_text(errors="replace")

    has_request_url = "requestUrl" in client_content
    has_configurable_url = "logosApiUrl" in types_content and "Logos API URL" in settings_content
    has_client_wiring = "new LogosClient" in main_content and "updateBaseUrl" in client_content

    if has_request_url and has_configurable_url and has_client_wiring:
        return (
            True,
            "obsidian-hapax current src layout uses LogosClient + Obsidian requestUrl with configurable logosApiUrl",
        )
    missing: list[str] = []
    if not has_request_url:
        missing.append("requestUrl transport")
    if not has_configurable_url:
        missing.append("configurable logosApiUrl setting")
    if not has_client_wiring:
        missing.append("LogosClient wiring")
    return False, f"missing current plugin API support: {', '.join(missing)}"


def _check_plugin_graceful_degradation() -> tuple[bool, str]:
    """Check obsidian-hapax degrades gracefully for localhost Logos API calls."""
    src_dir = OBSIDIAN_HAPAX_DIR / "src"
    client_file = src_dir / "logos-client.ts"
    panel_file = src_dir / "context-panel.ts"
    if not client_file.is_file() or not panel_file.is_file():
        return False, "logos-client.ts or context-panel.ts not found"

    client_content = client_file.read_text(errors="replace")
    panel_content = panel_file.read_text(errors="replace")

    has_error_handling = "catch" in client_content and "catch" in panel_content
    has_availability_flag = "apiAvailable = false" in client_content
    has_timeout = "Request timeout" in client_content and "timeoutMs" in client_content
    has_user_visible_error = "renderError" in panel_content or "Hapax error" in panel_content

    if has_error_handling and has_availability_flag and has_timeout and has_user_visible_error:
        return (
            True,
            "logos-client.ts has timeout/error handling and context-panel.ts renders bounded error state",
        )
    missing: list[str] = []
    if not has_error_handling:
        missing.append("catch blocks")
    if not has_availability_flag:
        missing.append("apiAvailable failure state")
    if not has_timeout:
        missing.append("request timeout")
    if not has_user_visible_error:
        missing.append("bounded panel error render")
    return False, f"logos-client.ts missing graceful degradation: {', '.join(missing)}"


def _check_plugin_credentials_in_settings() -> tuple[bool, str]:
    """Check obsidian-hapax stores API keys in plugin settings only."""
    settings_file = OBSIDIAN_HAPAX_DIR / "src" / "settings.ts"
    types_file = OBSIDIAN_HAPAX_DIR / "src" / "types.ts"
    main_file = OBSIDIAN_HAPAX_DIR / "src" / "main.ts"
    if not settings_file.exists() or not types_file.exists() or not main_file.exists():
        return False, "settings.ts or types.ts not found"

    types_content = types_file.read_text()
    main_content = main_file.read_text(errors="replace")
    has_settings_storage = "HapaxSettings" in types_content and "DEFAULT_SETTINGS" in types_content
    has_obsidian_storage = "loadData" in main_content and "saveData" in main_content
    has_api_key_field = any(
        field in types_content for field in ("apiKey", "apiToken", "accessToken")
    )

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

    if has_settings_storage and has_obsidian_storage and not has_api_key_field:
        return (
            True,
            "plugin declares no API credential fields; configurable settings are stored via Obsidian data.json and no env-based secrets are used",
        )
    if has_settings_storage and has_obsidian_storage and has_api_key_field:
        return (
            True,
            "API credential fields are stored in plugin settings (data.json via Obsidian), no env-based secrets",
        )
    return False, "plugin settings storage not wired through Obsidian loadData/saveData"


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
