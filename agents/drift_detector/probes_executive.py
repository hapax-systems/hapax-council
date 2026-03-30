"""Executive function sufficiency probes."""

from __future__ import annotations

import re

from .config import AI_AGENTS_DIR, LOGOS_STATE_DIR
from .sufficiency_probes import SufficiencyProbe


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
    return False, f"only {len(state_locations)} state files found"


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


EXECUTIVE_PROBES: list[SufficiencyProbe] = [
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
]
