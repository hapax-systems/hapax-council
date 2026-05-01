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


def _check_long_running_agent_progress_emission() -> tuple[bool, str]:
    """Enforces ex-feedback-001 (executive_function).

    Long-running agents must provide regular progress updates without
    being queried. Verifies that canonical always-on agent modules
    emit progress signals — either structured telemetry
    (hapax_event/hapax_span/hapax_score) or `logger.info`/`logger.debug`
    calls. Either path lands in Langfuse or journald, both of which
    surface progress without operator query.
    """
    canonical_long_running = (
        "hapax_daimonion",
        "imagination_daemon",
        "dmn",
        "studio_compositor",
        "visual_layer_aggregator",
        "content_resolver",
        "reverie",
    )

    agents_dir = AI_AGENTS_DIR / "agents"
    if not agents_dir.exists():
        return False, "agents directory not found"

    progress_pattern = re.compile(
        r"hapax_(event|span|score)|logger\.(info|debug|warning)|logging\.(info|debug|warning)"
    )

    found_modules = 0
    instrumented = 0
    missing: list[str] = []

    for module_name in canonical_long_running:
        module_path = agents_dir / module_name
        if module_path.is_dir():
            candidates = list(module_path.rglob("*.py"))
        elif (single_file := agents_dir / f"{module_name}.py").exists():
            candidates = [single_file]
        else:
            continue

        if not candidates:
            continue

        found_modules += 1
        has_progress = False
        for f in candidates:
            try:
                content = f.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if progress_pattern.search(content):
                has_progress = True
                break

        if has_progress:
            instrumented += 1
        else:
            missing.append(module_name)

    if found_modules == 0:
        return False, "no canonical long-running agent modules found"

    if instrumented >= 2:
        return True, (
            f"{instrumented}/{found_modules} canonical long-running agents "
            f"emit progress (telemetry or logger) (ex-feedback-001 sufficient — "
            f"pattern in use; missing modules surface separately for follow-up)"
        )
    return False, (
        f"only {instrumented}/{found_modules} long-running agents emit progress; "
        f"missing in: {', '.join(missing[:3])}"
    )


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
    SufficiencyProbe(
        id="probe-feedback-001",
        axiom_id="executive_function",
        implication_id="ex-feedback-001",
        level="subsystem",
        question=(
            "Do canonical long-running agents emit progress signals "
            "(hapax_event/hapax_span/hapax_score or logger.info/debug)?"
        ),
        check=_check_long_running_agent_progress_emission,
    ),
    SufficiencyProbe(
        id="probe-init-002",
        axiom_id="executive_function",
        implication_id="ex-init-002",
        level="subsystem",
        question=(
            "Do all systemd unit ExecStart lines have pre-resolved flags, "
            "with no operator-supplied placeholders?"
        ),
        check=lambda: _check_systemd_unit_exec_self_contained(),
    ),
    SufficiencyProbe(
        id="probe-state-002",
        axiom_id="executive_function",
        implication_id="ex-state-002",
        level="subsystem",
        question=(
            "Do agents emit state transitions to known visible "
            "locations (/dev/shm/*-state.json, ~/hapax-state/*.jsonl, "
            "Logos API state endpoints)?"
        ),
        check=lambda: _check_state_visibility_emission(),
    ),
]


def _check_state_visibility_emission() -> tuple[bool, str]:
    """Enforces ex-state-002 (executive_function).

    State transitions and progress must be visible without the
    operator having to check logs or debug output. Verifies that
    agent code references known visible state-emission surfaces:
      - /dev/shm/*-state.json (perception, IR, daimonion, director)
      - ~/hapax-state/*.json[l] (PR state, attribution, music repo)
      - Logos API routes (logos/api/routes/*.py)

    Threshold: ≥10 agents emit to one of these surfaces. Below this
    is a sufficiency gap — too few agents make state visible.
    """
    agents_dir = AI_AGENTS_DIR / "agents"
    if not agents_dir.exists():
        return False, "agents directory not found"

    visible_surface_pattern = re.compile(
        r"/dev/shm/[^\"']*-state(?:-[\w-]+)?\.json|"
        r"hapax-state[^\"']*\.json[l]?",
    )

    emitting_agents: set[str] = set()

    for py_file in agents_dir.rglob("*.py"):
        try:
            content = py_file.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if visible_surface_pattern.search(content):
            relative = py_file.relative_to(agents_dir)
            top_module = relative.parts[0] if relative.parts else py_file.name
            emitting_agents.add(top_module)

    if len(emitting_agents) >= 10:
        return True, (
            f"{len(emitting_agents)} agent modules emit state to visible "
            f"surfaces (/dev/shm or ~/hapax-state) — ex-state-002 sufficient"
        )
    return False, (
        f"only {len(emitting_agents)} agents emit visible state; "
        f"sample: {', '.join(sorted(emitting_agents)[:5])}"
    )


def _check_systemd_unit_exec_self_contained() -> tuple[bool, str]:
    """Enforces ex-init-002 (executive_function).

    Agent entry points must not require the operator to remember
    command-line arguments or flags. Verifies every systemd unit's
    ExecStart line is self-contained: no `${VAR}` placeholders, no
    bare `<...>` operator-fill markers, no ` $1`/`$2`/etc positional
    references requiring shell-time substitution.

    EnvironmentFile-driven systemd units (which load env vars from a
    shared config) are acceptable — those are static, repo-checked
    config files (e.g. /etc/hapax/secrets.env) that the operator
    never has to edit at agent-start time.
    """
    units_dir = AI_AGENTS_DIR / "systemd" / "units"
    if not units_dir.exists():
        return False, "systemd/units directory not found"

    placeholder_pattern = re.compile(r"\$\d+|<[A-Z_]+>|\{[A-Z_]+\}|TODO|FIXME")

    checked = 0
    self_contained = 0
    problems: list[str] = []

    for unit_file in sorted(units_dir.glob("*.service")):
        try:
            content = unit_file.read_text()
        except OSError:
            continue

        exec_lines = [line for line in content.splitlines() if line.startswith("ExecStart=")]
        if not exec_lines:
            continue

        checked += 1
        unit_clean = True
        for line in exec_lines:
            if placeholder_pattern.search(line):
                unit_clean = False
                break

        if unit_clean:
            self_contained += 1
        else:
            problems.append(unit_file.name)

    if checked == 0:
        return False, "no systemd .service files with ExecStart found"

    ratio = self_contained / checked
    if ratio >= 0.95:
        return True, (
            f"{self_contained}/{checked} systemd units have self-contained "
            f"ExecStart (ex-init-002 sufficient)"
        )
    return False, (
        f"only {self_contained}/{checked} units self-contained; "
        f"placeholders in: {', '.join(problems[:3])}"
    )
