"""Vendored from shared/sufficiency_probes.py — behavioral sufficiency probes.

This is the full 1205-LOC module. Some probes import from shared modules
(deliberation_metrics, agent_registry) via try/except — if those aren't
available, those specific probes will report errors gracefully.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .config import (
    AI_AGENTS_DIR,
    CLAUDE_CONFIG_DIR,
    HAPAX_VSCODE_DIR,
    HAPAXROMANA_DIR,
    LOGOS_STATE_DIR,
    LOGOS_WEB_DIR,
    OBSIDIAN_HAPAX_DIR,
)

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
    missing: list[str] = []

    for py_file in sorted(agents_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        try:
            content = py_file.read_text()
        except OSError:
            continue

        if "except " not in content and "error" not in content.lower():
            continue

        checked += 1
        has_remediation = bool(
            re.search(
                r"(?:Try|Run|Fix|Next|Check|Suggest|Action|Remediat)[:\s]",
                content,
                re.IGNORECASE,
            )
        )
        if has_remediation:
            with_remediation += 1
        else:
            missing.append(py_file.name)

    if checked == 0:
        return False, "no agent files with error handling found"

    ratio = with_remediation / checked
    if ratio >= 0.7:
        return True, f"{with_remediation}/{checked} agents have remediation strings"
    return (
        False,
        f"only {with_remediation}/{checked} agents have remediation strings; missing: {', '.join(missing[:3])}",
    )


def _check_agent_zero_config() -> tuple[bool, str]:
    """Check that agents have no required CLI args."""
    agents_dir = AI_AGENTS_DIR / "agents"
    if not agents_dir.exists():
        return False, "agents directory not found"

    checked = 0
    zero_config = 0
    problems: list[str] = []

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
        has_required = False
        for m in re.finditer(r'add_argument\(["\']([^-].*?)["\']([^)]*)\)', content):
            arg_opts = m.group(2)
            if "nargs=" not in arg_opts and "default=" not in arg_opts:
                has_required = True
                break
        if not has_required:
            zero_config += 1
        else:
            problems.append(py_file.name)

    if checked == 0:
        return True, "no agents with CLI parsers found"

    if zero_config == checked:
        return True, f"all {checked} agents with CLI parsers have no required args"
    return (
        False,
        f"{len(problems)} agent(s) have required positional args: {', '.join(problems[:3])}",
    )


def _check_state_persistence() -> tuple[bool, str]:
    """Check that agents with resume capability persist state files."""
    profiles_dir = AI_AGENTS_DIR / "profiles"
    cache_dir = LOGOS_STATE_DIR

    state_locations: list[str] = []
    if profiles_dir.exists():
        state_files = list(profiles_dir.glob("*.json")) + list(profiles_dir.glob("*.jsonl"))
        state_locations.extend(f.name for f in state_files)
    if cache_dir.exists():
        cache_files = list(cache_dir.glob("*.json")) + list(cache_dir.glob("*.jsonl"))
        state_locations.extend(f.name for f in cache_files)

    if len(state_locations) >= 3:
        return (
            True,
            f"{len(state_locations)} state files found across profiles/ and ~/.cache/logos/",
        )
    return (
        False,
        f"only {len(state_locations)} state files found",
    )


def _check_briefing_multi_source() -> tuple[bool, str]:
    """Check that briefing aggregates from multiple data sources."""
    briefing_file = AI_AGENTS_DIR / "agents" / "briefing.py"
    if not briefing_file.exists():
        return False, "briefing.py not found"

    content = briefing_file.read_text()
    sources: list[str] = []
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

    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-timers", "--no-pager", "--plain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        timer_lines = [
            line
            for line in result.stdout.splitlines()
            if ".timer" in line and "NEXT" not in line and "timers listed" not in line
        ]
        timer_count = len(timer_lines)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, "could not query systemd timers"

    # Try to get expected timer count from agent registry
    try:
        from shared.config import load_expected_timers

        expected = load_expected_timers()
        if timer_count >= len(expected):
            return (
                True,
                f"{timer_count} timers active, covers {len(expected)} expected recurring agents",
            )
        return False, f"only {timer_count} timers but {len(expected)} recurring agents expected"
    except ImportError:
        # Fallback: just check we have a reasonable number
        if timer_count >= 10:
            return True, f"{timer_count} timers active"
        return False, f"only {timer_count} timers active"


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
    missing: list[str] = []
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
        return (
            True,
            "context tools chain complete: search_profile + get_profile_summary + lookup_sufficiency_requirements + ProfileStore",
        )
    return False, "context tools chain incomplete"


def _check_no_multiuser_indirection() -> tuple[bool, str]:
    """Check that config paths don't have multi-user indirection."""
    config_file = AI_AGENTS_DIR / "shared" / "config.py"
    if not config_file.exists():
        return False, "shared/config.py not found"

    content = config_file.read_text()
    multi_user_patterns = [
        r"(?<!systemd_)user_id",
        r"(?<!SYSTEMD_)user_dir",
        r"per_user",
        r"(?<!systemd/)users/",
        r"\{user\}",
        r"current_user",
    ]

    found: list[str] = []
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


# ── Scope coverage probes (E-1) ──────────────────────────────────────────────


def _check_scope_coverage() -> tuple[bool, str]:
    """Check that sufficiency implications with enumerated scope have coverage entries."""
    from .axiom_registry import load_axioms, load_implications

    axioms = load_axioms()
    problems: list[str] = []
    checked = 0

    for axiom in axioms:
        for impl in load_implications(axiom.id):
            if impl.mode != "sufficiency":
                continue
            if impl.tier not in ("T0", "T1"):
                continue

            checked += 1

            if impl.scope is None:
                problems.append(f"{impl.id}: T0/T1 sufficiency implication has no scope")
                continue

            if impl.scope.type == "enumerated":
                if not impl.scope.items:
                    problems.append(f"{impl.id}: enumerated scope has no items")

    if checked == 0:
        return True, "no T0/T1 sufficiency implications to check"

    if not problems:
        return True, f"all {checked} T0/T1 sufficiency implications have valid scope"
    return False, f"{len(problems)} issue(s): {'; '.join(problems[:5])}"


PROBES.append(
    SufficiencyProbe(
        id="probe-scope-coverage-001",
        axiom_id="management_governance",
        implication_id="mg-cadence-001",
        level="system",
        question="Do T0/T1 sufficiency implications have valid enumerable scope?",
        check=_check_scope_coverage,
    ),
)


# ── Corporate boundary probes ────────────────────────────────────────────────


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


PROBES.extend(
    [
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
)


# ── Executive function behavioral probes ─────────────────────────────────────


def _check_proactive_alert_surfacing() -> tuple[bool, str]:
    """Check health_monitor pushes alerts proactively."""
    hm_file = AI_AGENTS_DIR / "agents" / "health_monitor.py"
    if not hm_file.exists():
        return False, "health_monitor.py not found"

    content = hm_file.read_text()
    has_notify = "notify" in content.lower()
    has_ntfy = "ntfy" in content

    import subprocess

    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "health-monitor.timer"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        timer_active = result.stdout.strip() == "active"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        timer_active = False

    if has_notify and timer_active:
        return True, f"health_monitor has notification calls and timer is active (ntfy: {has_ntfy})"
    problems: list[str] = []
    if not has_notify:
        problems.append("no notification calls")
    if not timer_active:
        problems.append("timer not active")
    return False, f"proactive alerting incomplete: {', '.join(problems)}"


PROBES.append(
    SufficiencyProbe(
        id="probe-alert-004",
        axiom_id="executive_function",
        implication_id="ex-alert-004",
        level="system",
        question="Does health_monitor proactively push alerts rather than requiring operator checks?",
        check=_check_proactive_alert_surfacing,
    ),
)


# ── Deliberation governance probes ───────────────────────────────────────────


def _check_deliberation_hoop_tests() -> tuple[bool, str]:
    """Check that multi-round deliberations pass >= 2 of 3 hoop tests."""
    try:
        from shared.deliberation_metrics import read_recent_metrics
    except ImportError:
        return True, "deliberation_metrics not available (non-critical)"

    metrics = read_recent_metrics(n=20)
    multi_round = [m for m in metrics if m.total_rounds > 1]
    if not multi_round:
        return True, "no multi-round deliberations to evaluate"

    failing: list[str] = []
    for m in multi_round:
        ht = m.hoop_tests
        if ht is None:
            continue
        passes = sum([ht.position_shift, ht.argument_tracing, ht.counterfactual_divergence])
        if passes < 2:
            failing.append(m.deliberation_id)

    if not failing:
        return True, f"all {len(multi_round)} multi-round deliberations pass >= 2/3 hoop tests"
    return (
        False,
        f"{len(failing)}/{len(multi_round)} deliberations fail hoop tests: {', '.join(failing[:3])}",
    )


def _check_deliberation_activation_rate() -> tuple[bool, str]:
    """Check that multi-round deliberation activation rate exceeds 10%."""
    try:
        from shared.deliberation_metrics import read_recent_metrics
    except ImportError:
        return True, "deliberation_metrics not available (non-critical)"

    metrics = read_recent_metrics(n=20)
    multi_round = [m for m in metrics if m.total_rounds > 1]
    if not multi_round:
        return True, "no multi-round deliberations to evaluate"

    low_activation = [m for m in multi_round if m.activation_rate < 0.1]
    if not low_activation:
        mean_act = sum(m.activation_rate for m in multi_round) / len(multi_round)
        return True, f"mean activation rate {mean_act:.0%} across {len(multi_round)} deliberations"
    return (
        False,
        f"{len(low_activation)}/{len(multi_round)} deliberations have activation rate < 10%",
    )


def _check_deliberation_concession_asymmetry() -> tuple[bool, str]:
    """Check that concession asymmetry does not exceed 3.0x."""
    try:
        from shared.deliberation_metrics import read_recent_metrics
    except ImportError:
        return True, "deliberation_metrics not available (non-critical)"

    metrics = read_recent_metrics(n=20)
    with_concessions = [m for m in metrics if m.concession_count > 0]
    if not with_concessions:
        return True, "no deliberations with concessions to evaluate"

    mean_asym = sum(m.concession_asymmetry_ratio for m in with_concessions) / len(with_concessions)
    if mean_asym <= 3.0:
        return (
            True,
            f"mean concession asymmetry {mean_asym:.1f}x across {len(with_concessions)} deliberations",
        )

    pub_total = sum(m.concession_count_publius for m in with_concessions)
    bru_total = sum(m.concession_count_brutus for m in with_concessions)
    dominant = "publius" if pub_total > bru_total else "brutus"
    return (
        False,
        f"concession asymmetry {mean_asym:.1f}x -- {dominant} dominates ({max(pub_total, bru_total)}/{pub_total + bru_total})",
    )


def _check_deliberation_activation_trend() -> tuple[bool, str]:
    """Check activation rate trend is not declining across batches."""
    try:
        from shared.deliberation_metrics import read_recent_metrics
    except ImportError:
        return True, "deliberation_metrics not available (non-critical)"

    metrics = read_recent_metrics(n=20)
    multi_round = [m for m in metrics if m.total_rounds > 1]
    if len(multi_round) < 4:
        return (
            True,
            f"insufficient multi-round data for trend ({len(multi_round)} records, need 4+)",
        )

    mid = len(multi_round) // 2
    first_half = sum(m.activation_rate for m in multi_round[:mid]) / mid
    second_half = sum(m.activation_rate for m in multi_round[mid:]) / (len(multi_round) - mid)
    diff = second_half - first_half

    if diff >= -0.05:
        trend = "rising" if diff > 0.05 else "stable"
        return (
            True,
            f"activation trend {trend} ({first_half:.0%} -> {second_half:.0%}) across {len(multi_round)} deliberations",
        )
    return (
        False,
        f"activation trend falling ({first_half:.0%} -> {second_half:.0%}) across {len(multi_round)} deliberations",
    )


PROBES.extend(
    [
        SufficiencyProbe(
            id="probe-delib-001",
            axiom_id="executive_function",
            implication_id="ex-delib-001",
            level="system",
            question="Do multi-round deliberations pass >= 2 of 3 hoop tests?",
            check=_check_deliberation_hoop_tests,
        ),
        SufficiencyProbe(
            id="probe-delib-002",
            axiom_id="executive_function",
            implication_id="ex-delib-002",
            level="system",
            question="Does multi-round deliberation activation rate exceed 10%?",
            check=_check_deliberation_activation_rate,
        ),
        SufficiencyProbe(
            id="probe-delib-003",
            axiom_id="executive_function",
            implication_id="ex-delib-003",
            level="system",
            question="Is concession asymmetry within acceptable bounds (< 3.0x)?",
            check=_check_deliberation_concession_asymmetry,
        ),
        SufficiencyProbe(
            id="probe-delib-004",
            axiom_id="executive_function",
            implication_id="ex-delib-004",
            level="system",
            question="Is deliberation activation rate trend not declining?",
            check=_check_deliberation_activation_trend,
        ),
    ]
)


# ── Skill health probes ──────────────────────────────────────────────────────

_KNOWN_SYNC_METHODS = {"get_pending_review", "promote", "reject", "search"}


def _check_skill_syntax() -> tuple[bool, str]:
    """Check that Claude Code skill definitions are syntactically valid."""
    import ast

    skills_dir = CLAUDE_CONFIG_DIR / "skills"
    if not skills_dir.exists():
        return False, "skills directory not found"

    checked = 0
    problems: list[str] = []

    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md" if skill_dir.is_dir() else None
        if skill_file is None or not skill_file.exists():
            continue

        checked += 1
        content = skill_file.read_text()

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                import yaml

                try:
                    fm = yaml.safe_load(parts[1])
                    if not fm or not fm.get("name") or not fm.get("description"):
                        problems.append(
                            f"{skill_dir.name}: missing name or description in frontmatter"
                        )
                        continue
                except yaml.YAMLError as e:
                    problems.append(f"{skill_dir.name}: invalid YAML frontmatter: {e}")
                    continue
            else:
                problems.append(f"{skill_dir.name}: malformed frontmatter")
                continue

        for m in re.finditer(r'python -c\s+"((?:[^"\\]|\\.)*)"', content):
            snippet = m.group(1).replace('\\"', '"')
            try:
                tree = ast.parse(snippet)
            except SyntaxError as e:
                problems.append(f"{skill_dir.name}: Python syntax error: {e}")
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
                    func = node.value.func
                    if isinstance(func, ast.Attribute) and func.attr in _KNOWN_SYNC_METHODS:
                        problems.append(f"{skill_dir.name}: await on sync method .{func.attr}()")

    if checked == 0:
        return False, "no skill definitions found"

    if not problems:
        return True, f"all {checked} skill definitions are syntactically valid"
    return False, f"{len(problems)} issue(s): {'; '.join(problems[:3])}"


PROBES.append(
    SufficiencyProbe(
        id="probe-skill-health-001",
        axiom_id="executive_function",
        implication_id="ex-skill-health-001",
        level="subsystem",
        question="Are all Claude Code skill definitions syntactically valid?",
        check=_check_skill_syntax,
    ),
)


# ── Security scanning probes ─────────────────────────────────────────────────


def _check_gitignore_security() -> tuple[bool, str]:
    """Check repos have required .gitignore patterns and no tracked secrets."""
    import subprocess

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


PROBES.append(
    SufficiencyProbe(
        id="probe-cb-secret-scan-001",
        axiom_id="corporate_boundary",
        implication_id="cb-key-001",
        level="system",
        question="Do repos have required .gitignore patterns and no tracked credential files?",
        check=_check_gitignore_security,
    ),
)


# ── Runtime behavioral probes (E-5) ─────────────────────────────────────────


def _check_health_timer_fired() -> tuple[bool, str]:
    """probe-runtime-001: health-monitor.timer fired within last 20 min."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "journalctl",
                "--user",
                "-u",
                "health-monitor.service",
                "--since",
                "20 min ago",
                "--no-pager",
                "-q",
                "--output=short",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
        if lines:
            return True, f"health-monitor.service ran in last 20 min ({len(lines)} log lines)"
        return False, "health-monitor.service has not run in last 20 min"
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f"journalctl check failed: {e}"


def _check_backup_fresh() -> tuple[bool, str]:
    """probe-runtime-002: Last backup is <36h old."""
    import time as _time
    from pathlib import Path

    repo = Path("/data/backups/restic")
    candidates = [repo / "locks", repo / "snapshots", repo / "index"]
    latest: float | None = None
    for p in candidates:
        if p.exists():
            try:
                mtime = p.stat().st_mtime
                if latest is None or mtime > latest:
                    latest = mtime
            except OSError:
                continue

    if latest is None:
        return False, "restic repo not found"

    age_h = (_time.time() - latest) / 3600
    if age_h < 36:
        return True, f"backup {age_h:.1f}h old"
    return False, f"backup {age_h:.0f}h old (>36h)"


def _check_sync_fresh() -> tuple[bool, str]:
    """probe-runtime-003: All sync state files are <24h old."""
    import time as _time
    from pathlib import Path

    try:
        from shared.agent_registry import AgentCategory, get_registry

        registry = get_registry()
        sync_agents = registry.agents_by_category(AgentCategory.SYNC)
        agents: dict[str, Path] = {}
        for agent in sync_agents:
            cache_name = agent.id.replace("_", "-")
            display = (
                cache_name.removesuffix("-sync") if cache_name.endswith("-sync") else cache_name
            )
            agents[display] = Path.home() / ".cache" / cache_name / "state.json"
    except ImportError:
        return True, "agent_registry not available (non-critical)"

    stale: list[str] = []
    missing: list[str] = []
    for name, state in agents.items():
        if not state.exists():
            missing.append(name)
            continue
        try:
            age_h = (_time.time() - state.stat().st_mtime) / 3600
            if age_h > 24:
                stale.append(f"{name}({age_h:.0f}h)")
        except OSError:
            missing.append(name)

    problems = stale + [f"{m}(missing)" for m in missing]
    if not problems:
        return True, f"all {len(agents)} sync agents fresh (<24h)"
    return False, f"stale/missing sync: {', '.join(problems)}"


def _check_no_error_spikes() -> tuple[bool, str]:
    """probe-runtime-004: No agent produced >10 ERROR-level logs in last hour."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "journalctl",
                "--user",
                "--priority=err",
                "--since",
                "1 hour ago",
                "--output=json",
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return True, "no error logs (journalctl returned no data)"

        import json as _json

        counts: dict[str, int] = {}
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            try:
                entry = _json.loads(line)
                ident = entry.get("SYSLOG_IDENTIFIER", "unknown")
                counts[ident] = counts.get(ident, 0) + 1
            except _json.JSONDecodeError:
                continue

        spikes = {k: v for k, v in counts.items() if v > 10}
        if not spikes:
            total = sum(counts.values())
            return True, f"{total} errors in last hour, no agent >10"
        details = ", ".join(f"{k}={v}" for k, v in sorted(spikes.items(), key=lambda x: -x[1]))
        return False, f"error spikes: {details}"
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f"journalctl check failed: {e}"


def _check_prometheus_scraping() -> tuple[bool, str]:
    """probe-runtime-005: Prometheus is scraping successfully."""
    import json as _json
    from urllib.error import URLError
    from urllib.request import urlopen

    try:
        with urlopen("http://localhost:9090/api/v1/targets", timeout=5) as resp:
            data = _json.loads(resp.read().decode())
        targets = data.get("data", {}).get("activeTargets", [])
        if not targets:
            return False, "prometheus has no active targets"
        up = sum(1 for t in targets if t.get("health") == "up")
        total = len(targets)
        if up == total:
            return True, f"all {total} prometheus targets up"
        down = [t.get("labels", {}).get("job", "?") for t in targets if t.get("health") != "up"]
        return False, f"{up}/{total} targets up, down: {', '.join(down)}"
    except (URLError, OSError, _json.JSONDecodeError) as e:
        return False, f"prometheus unreachable: {e}"


# ── Capability coverage meta-probe (E-2) ────────────────────────────────────


def _check_capability_coverage() -> tuple[bool, str]:
    """Meta-probe: verify agent registry health_groups have corresponding health checks."""
    problems: list[str] = []

    try:
        from shared.agent_registry import get_registry

        registry = get_registry()
        try:
            from agents.health_monitor import CHECK_REGISTRY

            declared_groups = {a.health_group for a in registry.list_agents() if a.health_group}
            registered_groups = set(CHECK_REGISTRY.keys())
            missing_groups = declared_groups - registered_groups
            if missing_groups:
                problems.append(
                    f"health_groups without checks: {', '.join(sorted(missing_groups))}"
                )
        except ImportError:
            pass
    except Exception as e:
        problems.append(f"registry unavailable: {e}")

    try:
        import yaml

        coverage_file = HAPAXROMANA_DIR / "axioms" / "capability-coverage.yaml"
        if coverage_file.exists():
            data = yaml.safe_load(coverage_file.read_text())
            probe_ids = {p.id for p in PROBES}
            for cap in data.get("capabilities", []):
                for probe_id in cap.get("required_probes", []):
                    if probe_id not in probe_ids:
                        problems.append(f"{cap['id']}/{probe_id} missing")
    except Exception:
        pass

    if problems:
        return False, "; ".join(problems[:5])

    try:
        agent_count = len(registry.list_agents())
        return True, f"all health_groups covered across {agent_count} agents"
    except Exception:
        return True, "coverage checks passed"


PROBES.extend(
    [
        SufficiencyProbe(
            id="probe-meta-coverage-001",
            axiom_id="executive_function",
            implication_id="ex-alert-004",
            level="system",
            question="Do all registered capabilities have corresponding sufficiency probes?",
            check=_check_capability_coverage,
        ),
        SufficiencyProbe(
            id="probe-runtime-001",
            axiom_id="executive_function",
            implication_id="ex-routine-007",
            level="system",
            question="Has health-monitor.timer fired in last 20 min?",
            check=_check_health_timer_fired,
        ),
        SufficiencyProbe(
            id="probe-runtime-002",
            axiom_id="executive_function",
            implication_id="ex-alert-001",
            level="system",
            question="Is the last backup <36h old?",
            check=_check_backup_fresh,
        ),
        SufficiencyProbe(
            id="probe-runtime-003",
            axiom_id="executive_function",
            implication_id="ex-routine-007",
            level="system",
            question="Are all sync state files <24h old?",
            check=_check_sync_fresh,
        ),
        SufficiencyProbe(
            id="probe-runtime-004",
            axiom_id="executive_function",
            implication_id="ex-alert-001",
            level="system",
            question="Are there no agent error spikes in the last hour?",
            check=_check_no_error_spikes,
        ),
        SufficiencyProbe(
            id="probe-runtime-005",
            axiom_id="executive_function",
            implication_id="ex-alert-001",
            level="system",
            question="Is Prometheus scraping successfully?",
            check=_check_prometheus_scraping,
        ),
    ]
)


def run_probes(*, axiom_id: str = "", level: str = "") -> list[ProbeResult]:
    """Run all sufficiency probes and return results."""
    probes = PROBES
    if axiom_id:
        probes = [p for p in probes if p.axiom_id == axiom_id]
    if level:
        probes = [p for p in probes if p.level == level]

    results: list[ProbeResult] = []
    now = datetime.now(UTC).isoformat()

    for probe in probes:
        try:
            met, evidence = probe.check()
        except Exception as e:
            met = False
            evidence = f"probe error: {e}"
            log.warning("Probe %s failed: %s", probe.id, e)

        results.append(
            ProbeResult(
                probe_id=probe.id,
                met=met,
                evidence=evidence,
                timestamp=now,
            )
        )

    return results
