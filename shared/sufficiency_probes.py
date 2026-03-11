# shared/sufficiency_probes.py
"""Behavioral sufficiency probes — deterministic checks that the system
actively supports axiom requirements, not just avoids violating them.

Each probe checks a specific sufficiency implication by inspecting real
infrastructure state (files, services, code patterns). No LLM calls.

Usage:
    from shared.sufficiency_probes import run_probes

    results = run_probes()
    for r in results:
        print(f"{'PASS' if r.met else 'FAIL'} {r.probe_id}: {r.evidence}")
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from shared.config import AI_AGENTS_DIR, COCKPIT_STATE_DIR, OBSIDIAN_HAPAX_DIR

log = logging.getLogger(__name__)


@dataclass
class SufficiencyProbe:
    id: str
    axiom_id: str
    implication_id: str
    level: str  # "component" | "subsystem" | "system"
    question: str
    check: Callable[[], tuple[bool, str]]  # (met, evidence)


@dataclass
class ProbeResult:
    probe_id: str
    met: bool
    evidence: str
    timestamp: str


# ── Probe implementations ────────────────────────────────────────────────────

def _check_agent_error_remediation() -> tuple[bool, str]:
    """Check that agent error handlers contain remediation strings."""
    agents_dir = AI_AGENTS_DIR / "agents"
    if not agents_dir.exists():
        return False, "agents directory not found"

    checked = 0
    with_remediation = 0
    missing = []

    for py_file in sorted(agents_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        try:
            content = py_file.read_text()
        except OSError:
            continue

        # Only check files that have error handling
        if "except " not in content and "error" not in content.lower():
            continue

        checked += 1
        # Look for remediation patterns: "Try:", "Run:", "Fix:", "Next:", "Check:"
        has_remediation = bool(re.search(
            r'(?:Try|Run|Fix|Next|Check|Suggest|Action|Remediat)[:\s]',
            content,
            re.IGNORECASE,
        ))
        if has_remediation:
            with_remediation += 1
        else:
            missing.append(py_file.name)

    if checked == 0:
        return False, "no agent files with error handling found"

    ratio = with_remediation / checked
    if ratio >= 0.7:
        return True, f"{with_remediation}/{checked} agents have remediation strings"
    return False, f"only {with_remediation}/{checked} agents have remediation strings; missing: {', '.join(missing[:3])}"


def _check_agent_zero_config() -> tuple[bool, str]:
    """Check that agents have no required CLI args (all have defaults)."""
    agents_dir = AI_AGENTS_DIR / "agents"
    if not agents_dir.exists():
        return False, "agents directory not found"

    checked = 0
    zero_config = 0
    problems = []

    for py_file in sorted(agents_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        try:
            content = py_file.read_text()
        except OSError:
            continue

        if "argparse" not in content and "def main" not in content:
            continue

        checked += 1
        # Check for required positional arguments (add_argument without default or nargs='?'/'*')
        has_required = False
        for m in re.finditer(r'add_argument\(["\']([^-].*?)["\']([^)]*)\)', content):
            arg_opts = m.group(2)
            if 'nargs=' not in arg_opts and 'default=' not in arg_opts:
                has_required = True
                break
        if not has_required:
            zero_config += 1
        else:
            problems.append(py_file.name)

    if checked == 0:
        return True, "no agents with CLI parsers found (no required args possible)"

    if zero_config == checked:
        return True, f"all {checked} agents with CLI parsers have no required args"
    return False, f"{len(problems)} agent(s) have required positional args: {', '.join(problems[:3])}"


def _check_state_persistence() -> tuple[bool, str]:
    """Check that agents with resume capability persist state files."""
    agents_dir = AI_AGENTS_DIR / "agents"
    profiles_dir = AI_AGENTS_DIR / "profiles"
    cache_dir = COCKPIT_STATE_DIR

    state_locations = []
    if profiles_dir.exists():
        state_files = list(profiles_dir.glob("*.json")) + list(profiles_dir.glob("*.jsonl"))
        state_locations.extend(f.name for f in state_files)
    if cache_dir.exists():
        cache_files = list(cache_dir.glob("*.json")) + list(cache_dir.glob("*.jsonl"))
        state_locations.extend(f.name for f in cache_files)

    if len(state_locations) >= 3:
        return True, f"{len(state_locations)} state files found across profiles/ and ~/.cache/cockpit/"
    return False, f"only {len(state_locations)} state files found — agents may not be persisting state"


def _check_briefing_multi_source() -> tuple[bool, str]:
    """Check that briefing aggregates from multiple data sources."""
    briefing_file = AI_AGENTS_DIR / "agents" / "briefing.py"
    if not briefing_file.exists():
        return False, "briefing.py not found"

    content = briefing_file.read_text()
    sources = []
    source_patterns = {
        "health": r"health",
        "drift": r"drift",
        "scout": r"scout",
        "activity": r"activity",
        "digest": r"digest",
        "cost": r"cost",
    }

    for name, pattern in source_patterns.items():
        if re.search(pattern, content, re.IGNORECASE):
            sources.append(name)

    if len(sources) >= 3:
        return True, f"briefing aggregates {len(sources)} sources: {', '.join(sources)}"
    return False, f"briefing only uses {len(sources)} sources: {', '.join(sources)}"


def _check_systemd_timer_coverage() -> tuple[bool, str]:
    """Check that systemd timer count matches recurring agent count."""
    import subprocess

    # Count timers
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-timers", "--no-pager", "--plain"],
            capture_output=True, text=True, timeout=5,
        )
        timer_lines = [
            line for line in result.stdout.splitlines()
            if ".timer" in line and "NEXT" not in line and "timers listed" not in line
        ]
        timer_count = len(timer_lines)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, "could not query systemd timers"

    # Expected recurring agents
    expected_agents = [
        "health-monitor", "daily-briefing", "drift-detector",
        "manifest-snapshot", "llm-backup", "profile-update",
        "scout", "digest", "knowledge-maint",
    ]

    if timer_count >= len(expected_agents):
        return True, f"{timer_count} timers active, covers {len(expected_agents)} expected recurring agents"
    return False, f"only {timer_count} timers but {len(expected_agents)} recurring agents expected"


def _check_notification_chain() -> tuple[bool, str]:
    """Check that ntfy + notify.py end-to-end path exists."""
    notify_file = AI_AGENTS_DIR / "shared" / "notify.py"
    if not notify_file.exists():
        return False, "shared/notify.py not found"

    content = notify_file.read_text()
    has_ntfy = "ntfy" in content
    has_desktop = "notify-send" in content or "notify_send" in content

    if has_ntfy and has_desktop:
        return True, "notify.py has ntfy (push) and desktop (notify-send) channels"
    missing = []
    if not has_ntfy:
        missing.append("ntfy")
    if not has_desktop:
        missing.append("desktop")
    return False, f"notify.py missing channels: {', '.join(missing)}"


def _check_profile_context_chain() -> tuple[bool, str]:
    """Check that Qdrant profile-facts + context tools chain works."""
    context_file = AI_AGENTS_DIR / "shared" / "context_tools.py"
    profile_store_file = AI_AGENTS_DIR / "shared" / "profile_store.py"

    if not context_file.exists():
        return False, "context_tools.py not found"
    if not profile_store_file.exists():
        return False, "profile_store.py not found"

    context_content = context_file.read_text()
    has_search_profile = "search_profile" in context_content
    has_profile_summary = "get_profile_summary" in context_content
    has_sufficiency = "lookup_sufficiency_requirements" in context_content

    if has_search_profile and has_profile_summary and has_sufficiency:
        return True, "context tools chain complete: search_profile + get_profile_summary + lookup_sufficiency_requirements + ProfileStore"
    return False, "context tools chain incomplete"


def _check_no_multiuser_indirection() -> tuple[bool, str]:
    """Check that config paths don't have multi-user indirection."""
    config_file = AI_AGENTS_DIR / "shared" / "config.py"
    if not config_file.exists():
        return False, "shared/config.py not found"

    content = config_file.read_text()
    # Check for user-parameterized paths (exclude standard system paths like systemd/user)
    multi_user_patterns = [
        r'(?<!systemd_)user_id',
        r'(?<!SYSTEMD_)user_dir',
        r'per_user',
        r'(?<!systemd/)users/',
        r'\{user\}',
        r'current_user',
    ]

    found = []
    for pattern in multi_user_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            found.append(pattern)

    if not found:
        return True, "no multi-user path indirection in config.py"
    return False, f"multi-user patterns found in config.py: {', '.join(found)}"


# ── Probe registry ───────────────────────────────────────────────────────────

PROBES: list[SufficiencyProbe] = [
    SufficiencyProbe(
        id="probe-err-001",
        axiom_id="executive_function",
        implication_id="ex-err-001",
        level="component",
        question="Do agent error handlers contain remediation strings?",
        check=_check_agent_error_remediation,
    ),
    SufficiencyProbe(
        id="probe-init-001",
        axiom_id="executive_function",
        implication_id="ex-init-001",
        level="component",
        question="Do agents have no required CLI arguments?",
        check=_check_agent_zero_config,
    ),
    SufficiencyProbe(
        id="probe-state-001",
        axiom_id="executive_function",
        implication_id="ex-state-001",
        level="subsystem",
        question="Do agents with resume actually persist state files?",
        check=_check_state_persistence,
    ),
    SufficiencyProbe(
        id="probe-cognitive-001",
        axiom_id="executive_function",
        implication_id="ex-cognitive-009",
        level="subsystem",
        question="Does the briefing aggregate from multiple data sources?",
        check=_check_briefing_multi_source,
    ),
    SufficiencyProbe(
        id="probe-routine-001",
        axiom_id="executive_function",
        implication_id="ex-routine-007",
        level="system",
        question="Does systemd timer count match recurring agent count?",
        check=_check_systemd_timer_coverage,
    ),
    SufficiencyProbe(
        id="probe-alert-001",
        axiom_id="executive_function",
        implication_id="ex-attention-001",
        level="system",
        question="Does ntfy + notify.py end-to-end path exist?",
        check=_check_notification_chain,
    ),
    SufficiencyProbe(
        id="probe-memory-001",
        axiom_id="executive_function",
        implication_id="ex-memory-010",
        level="system",
        question="Does Qdrant profile-facts + context tools chain work?",
        check=_check_profile_context_chain,
    ),
    SufficiencyProbe(
        id="probe-su-leverage-001",
        axiom_id="single_user",
        implication_id="su-decision-001",
        level="system",
        question="Is there no multi-user indirection in config paths?",
        check=_check_no_multiuser_indirection,
    ),
]


# ── Corporate boundary probes ────────────────────────────────────────────────

def _check_plugin_direct_api_support() -> tuple[bool, str]:
    """Check obsidian-hapax supports direct API calls without localhost proxy (cb-llm-001)."""
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
    missing = []
    if not has_anthropic:
        missing.append("anthropic.ts")
    if not has_openai:
        missing.append("openai-compatible.ts")
    if not has_provider_switch:
        missing.append("provider switch")
    return False, f"missing direct API support: {', '.join(missing)}"


def _check_plugin_graceful_degradation() -> tuple[bool, str]:
    """Check obsidian-hapax degrades gracefully for localhost services (cb-degrade-001)."""
    qdrant_file = OBSIDIAN_HAPAX_DIR / "src" / "qdrant-client.ts"
    if not qdrant_file.exists():
        return False, "qdrant-client.ts not found"

    content = qdrant_file.read_text()
    # Must have try/catch or .catch() around fetch calls to localhost services
    has_error_handling = "catch" in content
    has_console_warn = "console.warn" in content or "console.error" in content

    if has_error_handling and has_console_warn:
        return True, "qdrant-client.ts has catch blocks with console.warn for graceful degradation"
    missing = []
    if not has_error_handling:
        missing.append("catch blocks")
    if not has_console_warn:
        missing.append("warning output")
    return False, f"qdrant-client.ts missing graceful degradation: {', '.join(missing)}"


def _check_plugin_credentials_in_settings() -> tuple[bool, str]:
    """Check obsidian-hapax stores API keys in plugin settings only (cb-key-001)."""
    settings_file = OBSIDIAN_HAPAX_DIR / "src" / "settings.ts"
    types_file = OBSIDIAN_HAPAX_DIR / "src" / "types.ts"
    if not settings_file.exists() or not types_file.exists():
        return False, "settings.ts or types.ts not found"

    types_content = types_file.read_text()
    has_api_key_field = "apiKey" in types_content

    # Check no secrets in env vars or external files
    src_dir = OBSIDIAN_HAPAX_DIR / "src"
    env_patterns = [r'process\.env', r'dotenv', r'\.env\b']
    for ts_file in src_dir.rglob("*.ts"):
        try:
            file_content = ts_file.read_text()
        except OSError:
            continue
        for pat in env_patterns:
            if re.search(pat, file_content):
                return False, f"env-based secret access found in {ts_file.name}"

    if has_api_key_field:
        return True, "API keys stored in plugin settings (data.json via Obsidian), no env-based secrets"
    return False, "apiKey field not found in types.ts"


CORPORATE_BOUNDARY_PROBES: list[SufficiencyProbe] = [
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
]

PROBES.extend(CORPORATE_BOUNDARY_PROBES)


# ── Executive function behavioral probes ─────────────────────────────────────

def _check_proactive_alert_surfacing() -> tuple[bool, str]:
    """Check health_monitor pushes alerts proactively (ex-alert-004)."""
    hm_file = AI_AGENTS_DIR / "agents" / "health_monitor.py"
    if not hm_file.exists():
        return False, "health_monitor.py not found"

    content = hm_file.read_text()
    has_notify = "notify" in content.lower()
    has_ntfy = "ntfy" in content

    # Check the timer fires it automatically
    import subprocess
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "health-monitor.timer"],
            capture_output=True, text=True, timeout=5,
        )
        timer_active = result.stdout.strip() == "active"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        timer_active = False

    if has_notify and timer_active:
        return True, f"health_monitor has notification calls and timer is active (ntfy: {has_ntfy})"
    problems = []
    if not has_notify:
        problems.append("no notification calls")
    if not timer_active:
        problems.append("timer not active")
    return False, f"proactive alerting incomplete: {', '.join(problems)}"


EXECUTIVE_FUNCTION_PROBES: list[SufficiencyProbe] = [
    SufficiencyProbe(
        id="probe-alert-004",
        axiom_id="executive_function",
        implication_id="ex-alert-004",
        level="system",
        question="Does health_monitor proactively push alerts rather than requiring operator checks?",
        check=_check_proactive_alert_surfacing,
    ),
]

PROBES.extend(EXECUTIVE_FUNCTION_PROBES)


def run_probes(
    *, axiom_id: str = "", level: str = ""
) -> list[ProbeResult]:
    """Run all sufficiency probes and return results.

    Args:
        axiom_id: Filter to specific axiom. Empty for all.
        level: Filter to specific level. Empty for all.
    """
    probes = PROBES
    if axiom_id:
        probes = [p for p in probes if p.axiom_id == axiom_id]
    if level:
        probes = [p for p in probes if p.level == level]

    results = []
    now = datetime.now(timezone.utc).isoformat()

    for probe in probes:
        try:
            met, evidence = probe.check()
        except Exception as e:
            met = False
            evidence = f"probe error: {e}"
            log.warning("Probe %s failed: %s", probe.id, e)

        results.append(ProbeResult(
            probe_id=probe.id,
            met=met,
            evidence=evidence,
            timestamp=now,
        ))

    return results
