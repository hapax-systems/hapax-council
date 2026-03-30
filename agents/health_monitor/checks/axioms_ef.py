"""Axiom executive-function compliance checks (settings, zero-config, timers, ntfy)."""

from __future__ import annotations

import json
import re
import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("axioms")
async def check_axiom_settings() -> list[CheckResult]:
    """Check that axiom hooks are properly configured in Claude Code settings."""
    results = []
    t = time.monotonic()

    settings_file = _c.CLAUDE_CONFIG_DIR / "settings.json"
    if not settings_file.exists():
        results.append(
            CheckResult(
                name="axiom.settings",
                group="axioms",
                status=Status.DEGRADED,
                message="Claude Code settings.json not found",
                remediation="Check axiom hooks in ~/.claude/settings.json (PreToolUse/PostToolUse)",
                duration_ms=_u._timed(t),
            )
        )
        return results

    try:
        settings = json.loads(settings_file.read_text())
        hooks = settings.get("hooks", {})

        pre_hooks = hooks.get("PreToolUse", [])
        has_scan = any(
            "axiom-scan.sh" in h.get("command", "")
            for entry in pre_hooks
            for h in entry.get("hooks", [])
        )

        post_hooks = hooks.get("PostToolUse", [])
        has_audit = any(
            "axiom-audit.sh" in h.get("command", "")
            for entry in post_hooks
            for h in entry.get("hooks", [])
        )

        if has_scan and has_audit:
            results.append(
                CheckResult(
                    name="axiom.settings",
                    group="axioms",
                    status=Status.HEALTHY,
                    message="Hooks configured: scan (PreToolUse) + audit (PostToolUse)",
                    duration_ms=_u._timed(t),
                )
            )
        else:
            missing = []
            if not has_scan:
                missing.append("axiom-scan (PreToolUse)")
            if not has_audit:
                missing.append("axiom-audit (PostToolUse)")
            results.append(
                CheckResult(
                    name="axiom.settings",
                    group="axioms",
                    status=Status.DEGRADED,
                    message=f"Missing hooks: {', '.join(missing)}",
                    remediation="Check axiom hooks in ~/.claude/settings.json (PreToolUse/PostToolUse)",
                    duration_ms=_u._timed(t),
                )
            )
    except (json.JSONDecodeError, OSError) as e:
        results.append(
            CheckResult(
                name="axiom.settings",
                group="axioms",
                status=Status.FAILED,
                message="Cannot parse settings.json",
                detail=str(e),
                duration_ms=_u._timed(t),
            )
        )

    return results


@check_group("axioms")
async def check_axiom_ef_zero_config() -> list[CheckResult]:
    """Check that agents are runnable with zero required configuration (ex-init-001)."""
    results = []
    t = time.monotonic()

    agents_dir = _c.AI_AGENTS_DIR / "agents"
    if not agents_dir.exists():
        results.append(
            CheckResult(
                name="axiom.ef_zero_config",
                group="axioms",
                status=Status.FAILED,
                message="Agents directory not found",
                detail=str(agents_dir),
                duration_ms=_u._timed(t),
            )
        )
        return results

    from agents._agent_registry import get_registry

    zero_config_agents = [a.id for a in get_registry().zero_config_agents()]

    violations = []
    for agent_name in zero_config_agents:
        agent_file = agents_dir / f"{agent_name}.py"
        if not agent_file.exists():
            continue
        content = agent_file.read_text()
        for match in re.finditer(r'add_argument\(\s*["\']([^-][^"\']*)["\']', content):
            arg_name = match.group(1)
            line_start = content.rfind("\n", 0, match.start()) + 1
            line_end = content.find("\n", match.end())
            line = content[line_start:line_end]
            if "default=" not in line and "nargs=" not in line:
                violations.append(f"{agent_name}: required positional arg '{arg_name}'")

    if not violations:
        results.append(
            CheckResult(
                name="axiom.ef_zero_config",
                group="axioms",
                status=Status.HEALTHY,
                message=f"All {len(zero_config_agents)} routine agents are zero-config runnable",
                duration_ms=_u._timed(t),
            )
        )
    else:
        results.append(
            CheckResult(
                name="axiom.ef_zero_config",
                group="axioms",
                status=Status.DEGRADED,
                message=f"ex-init-001 gap: {len(violations)} agent(s) require positional args",
                detail="; ".join(violations),
                remediation="Add defaults or make arguments optional with flags",
                duration_ms=_u._timed(t),
            )
        )

    return results


@check_group("axioms")
async def check_axiom_ef_automated_routines() -> list[CheckResult]:
    """Check that recurring agents have systemd timers (ex-routine-001/007)."""
    from agents._config import load_expected_timers

    results = []
    t = time.monotonic()

    expected_timers = load_expected_timers()
    rc, stdout, _ = await _u.run_cmd(
        ["systemctl", "--user", "list-timers", "--no-pager", "--plain"],
        timeout=5.0,
    )
    if rc != 0:
        results.append(
            CheckResult(
                name="axiom.ef_automated",
                group="axioms",
                status=Status.FAILED,
                message="Cannot check systemd timers",
                duration_ms=_u._timed(t),
            )
        )
        return results

    missing = []
    for agent_name, timer_name in expected_timers.items():
        if timer_name not in stdout:
            missing.append(f"{agent_name} ({timer_name})")

    if not missing:
        results.append(
            CheckResult(
                name="axiom.ef_automated",
                group="axioms",
                status=Status.HEALTHY,
                message=f"All {len(expected_timers)} recurring agents have active timers",
                duration_ms=_u._timed(t),
            )
        )
    else:
        results.append(
            CheckResult(
                name="axiom.ef_automated",
                group="axioms",
                status=Status.DEGRADED,
                message=f"ex-routine-001 gap: {len(missing)} agent(s) missing timers",
                detail="; ".join(missing),
                remediation="Enable timers: systemctl --user enable --now <timer>",
                duration_ms=_u._timed(t),
            )
        )

    return results


@check_group("axioms")
async def check_axiom_ef_notifications() -> list[CheckResult]:
    """Check alert infrastructure for proactive notification (ex-attention-001)."""
    results = []
    t = time.monotonic()

    notify_file = _c.AI_AGENTS_DIR / "shared" / "notify.py"
    if not notify_file.exists():
        results.append(
            CheckResult(
                name="axiom.ef_notifications",
                group="axioms",
                status=Status.FAILED,
                message="shared/notify.py not found \u2014 no proactive alert mechanism",
                duration_ms=_u._timed(t),
            )
        )
        return results

    status_code, _ = await _u.http_get("http://127.0.0.1:8090/v1/health", timeout=2.0)
    if status_code == 200:
        results.append(
            CheckResult(
                name="axiom.ef_notifications",
                group="axioms",
                status=Status.HEALTHY,
                message="Notification infrastructure operational (ntfy + notify.py)",
                duration_ms=_u._timed(t),
            )
        )
    else:
        results.append(
            CheckResult(
                name="axiom.ef_notifications",
                group="axioms",
                status=Status.DEGRADED,
                message="ntfy not reachable \u2014 proactive alerts degraded",
                detail=f"HTTP status: {status_code}",
                remediation="Check: docker compose -f ~/llm-stack/docker-compose.yml ps ntfy",
                duration_ms=_u._timed(t),
            )
        )

    return results
