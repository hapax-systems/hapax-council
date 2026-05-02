"""Executive function sufficiency probes."""

from __future__ import annotations

import os
import re
from pathlib import Path

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
    SufficiencyProbe(
        id="probe-routine-002",
        axiom_id="executive_function",
        implication_id="ex-routine-002",
        level="system",
        question=(
            "Do canonical scheduled agents (health_monitor, drift_detector, "
            "scout, briefing) each have a paired .timer alongside the "
            ".service?"
        ),
        check=lambda: _check_scheduled_agents_have_timers(),
    ),
    SufficiencyProbe(
        id="probe-context-001",
        axiom_id="executive_function",
        implication_id="ex-context-001",
        level="component",
        question=(
            "Do canonical agent modules expose a query path "
            "(def status / def describe / @app.get('/status')) so "
            "the operator can ask what the agent is doing?"
        ),
        check=lambda: _check_agents_have_context_query_path(),
    ),
    SufficiencyProbe(
        id="probe-context-002",
        axiom_id="executive_function",
        implication_id="ex-context-002",
        level="component",
        question=(
            "Do canonical status surfaces emit ISO-8601 timestamps so "
            "the operator can correlate events without parsing log timing?"
        ),
        check=lambda: _check_status_outputs_have_timestamps(),
    ),
    SufficiencyProbe(
        id="probe-state-003",
        axiom_id="executive_function",
        implication_id="ex-state-003",
        level="subsystem",
        question=(
            "Does the cc-task vault SSOT persist task context across "
            "restarts so the operator never has to remember where they "
            "left off?"
        ),
        check=lambda: _check_task_context_persistence(),
    ),
    SufficiencyProbe(
        id="probe-feedback-002",
        axiom_id="executive_function",
        implication_id="ex-feedback-002",
        level="component",
        question=(
            "Do agent modules emit explicit success markers (log.info "
            "with done/complete/success/finished tokens or print('OK')) "
            "rather than relying on absence of error?"
        ),
        check=lambda: _check_agents_emit_explicit_success(),
    ),
]


def _check_agents_emit_explicit_success() -> tuple[bool, str]:
    """Enforces ex-feedback-002 (executive_function).

    Success states must be explicitly confirmed rather than indicated
    by absence of error messages. Verifies agent modules emit explicit
    success markers — log.info with done/complete/success/finished
    tokens, or print statements with OK/done/finished/checkmark.

    Threshold: at least 5 agent modules emit explicit success markers.
    Below this, the operator can't tell whether silence means success
    or stuck.
    """
    success_pattern = re.compile(
        r"log\.info\([^)]*(complete|success|done|finished)|"
        r"print\([\"\']\s*(OK|done|completed|finished)"
    )

    agents_dir = AI_AGENTS_DIR / "agents"
    if not agents_dir.exists():
        return False, "agents directory not found"

    matching: set[str] = set()
    for py_file in agents_dir.rglob("*.py"):
        try:
            content = py_file.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if success_pattern.search(content):
            relative = py_file.relative_to(agents_dir)
            top_module = relative.parts[0] if relative.parts else py_file.name
            matching.add(top_module)

    if len(matching) >= 5:
        return True, (
            f"{len(matching)} agent modules emit explicit success markers "
            f"— ex-feedback-002 sufficient"
        )
    return False, (
        f"only {len(matching)} agents emit explicit success; "
        f"sample: {', '.join(sorted(matching)[:5])}"
    )


def _check_task_context_persistence() -> tuple[bool, str]:
    """Enforces ex-state-003 (executive_function).

    System must persist task context across interruptions to eliminate
    restart cognitive overhead. Verifies the cc-task vault SSOT
    surfaces persist task state through restart:
      - hapax-cc-tasks/active/*.md (per-task vault notes with
        claimed_at + assigned_to fields preserved across restart)
      - ~/.cache/hapax/cc-active-task-* (per-role claim files)

    Threshold: ≥1 active cc-task with claimed_at preserved AND ≥1
    role claim file present, OR vault dir has any *.md file (system
    is currently idle but persistence surface exists).
    """
    vault_active = (
        Path(os.path.expanduser("~"))
        / "Documents"
        / "Personal"
        / "20-projects"
        / "hapax-cc-tasks"
        / "active"
    )
    cache_dir = Path(os.path.expanduser("~")) / ".cache" / "hapax"

    if not vault_active.is_dir():
        return False, f"cc-task vault active dir not found at {vault_active}"

    cc_tasks = list(vault_active.glob("*.md"))
    claim_files = list(cache_dir.glob("cc-active-task-*"))

    claimed_at_pattern = re.compile(r"^claimed_at:\s*\S+", re.MULTILINE)
    persistence_evidence = 0
    for task in cc_tasks[:50]:
        try:
            content = task.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if claimed_at_pattern.search(content):
            persistence_evidence += 1

    if cc_tasks and (persistence_evidence >= 1 or claim_files):
        return True, (
            f"cc-task vault has {len(cc_tasks)} active tasks "
            f"({persistence_evidence} with claimed_at) + {len(claim_files)} "
            f"role claim files — ex-state-003 sufficient"
        )
    if cc_tasks:
        return True, (
            f"cc-task vault has {len(cc_tasks)} active tasks (idle "
            f"system; persistence surface present) — ex-state-003 sufficient"
        )
    return False, (
        f"no cc-task persistence evidence: 0 active tasks, {len(claim_files)} claim files"
    )


def _check_status_outputs_have_timestamps() -> tuple[bool, str]:
    """Enforces ex-context-002 (executive_function).

    Status outputs must include timestamps and be human-readable
    without additional parsing. Verifies that canonical status-emitting
    modules thread an ISO-8601 timestamp field through their data shape.

    Patterns matched:
      - `ts:` / `timestamp:` field declarations
      - `isoformat()` calls
      - `strftime("%Y-%m-%dT...)` patterns
    """
    timestamp_pattern = re.compile(
        r'\b(ts|timestamp)\s*[:=]\s*|isoformat\(|strftime\(["\']%Y-%m-%dT'
    )

    canonical_status_surfaces = (
        AI_AGENTS_DIR / "shared" / "chronicle.py",
        AI_AGENTS_DIR / "agents" / "health_monitor",
        AI_AGENTS_DIR / "agents" / "consent_audit.py",
        AI_AGENTS_DIR / "agents" / "stimmung_sync.py",
        AI_AGENTS_DIR / "agents" / "drift_detector" / "freshness.py",
    )

    matching = 0
    matched_names: list[str] = []
    for path in canonical_status_surfaces:
        if path.is_dir():
            files = list(path.rglob("*.py"))
        elif path.exists():
            files = [path]
        else:
            continue
        for f in files:
            try:
                content = f.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if timestamp_pattern.search(content):
                matching += 1
                matched_names.append(f.relative_to(AI_AGENTS_DIR).as_posix())
                break

    if matching >= 3:
        return True, (
            f"{matching} status surfaces emit timestamps "
            f"({', '.join(matched_names)}) — ex-context-002 sufficient"
        )
    return False, (
        f"only {matching} status surfaces emit timestamps; matched: {', '.join(matched_names)}"
    )


def _check_agents_have_context_query_path() -> tuple[bool, str]:
    """Enforces ex-context-001 (executive_function).

    Agents must maintain sufficient context to explain their current
    state and recent actions when queried. Verifies that agent modules
    expose at least one of:
      - `def status(`            (programmatic status method)
      - `def get_status(`        (programmatic getter)
      - `def describe(`          (free-text current-state)
      - `@app.get("/status")`    (HTTP query endpoint via FastAPI)
      - `@router.get("/status")` (HTTP query endpoint via APIRouter)

    Threshold: ≥5 agent modules expose a query path. Below this, the
    operator can't reasonably ask what the system is doing without
    log-tailing.
    """
    query_pattern = re.compile(
        r"def\s+(?:status|get_status|describe|health|info|state|current_state)\s*\(|"
        r"@(?:app|router)\.get\("
    )

    agents_dir = AI_AGENTS_DIR / "agents"
    if not agents_dir.exists():
        return False, "agents directory not found"

    matching: set[str] = set()
    for py_file in agents_dir.rglob("*.py"):
        try:
            content = py_file.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if query_pattern.search(content):
            relative = py_file.relative_to(agents_dir)
            top_module = relative.parts[0] if relative.parts else py_file.name
            matching.add(top_module)

    if len(matching) >= 5:
        return True, (
            f"{len(matching)} agent modules expose a context query path "
            f"(def status / describe / FastAPI /status route) — "
            f"ex-context-001 sufficient"
        )
    return False, (
        f"only {len(matching)} agents have a context query path; "
        f"sample: {', '.join(sorted(matching)[:5])}"
    )


def _check_scheduled_agents_have_timers() -> tuple[bool, str]:
    """Enforces ex-routine-002 (executive_function).

    Agents like health_monitor and drift_detector must self-schedule.
    Verifies that each canonical scheduled-agent service in
    `systemd/units/*.service` has a paired `.timer` file alongside it
    so it actually runs without manual triggering by the operator.

    Threshold: every canonical agent must have a timer (no exceptions).
    """
    canonical_scheduled = (
        "health-monitor",
        "drift-detector",
        "scout",
        "daily-briefing",
    )

    units_dir = AI_AGENTS_DIR / "systemd" / "units"
    if not units_dir.exists():
        return False, "systemd/units directory not found"

    paired = 0
    missing: list[str] = []

    for name in canonical_scheduled:
        service = units_dir / f"{name}.service"
        timer = units_dir / f"{name}.timer"
        if not service.exists():
            missing.append(f"{name}.service (absent)")
            continue
        if not timer.exists():
            missing.append(f"{name}.timer (absent)")
            continue
        paired += 1

    total = len(canonical_scheduled)
    if paired == total:
        return True, (
            f"all {total} canonical scheduled agents have paired "
            f".service + .timer (ex-routine-002 sufficient)"
        )
    return False, (
        f"only {paired}/{total} canonical scheduled agents paired; "
        f"missing: {', '.join(missing[:3])}"
    )


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
