"""shared/axiom_enforcer.py — Output enforcement for LLM-generated text.

Intercepts agent output before write, checks for axiom violations, and either
blocks (T0) or logs (T1/T2) depending on tier and enforcement mode.

Reads enforcement-exceptions.yaml to skip enforcement for approved paths.

Usage:
    from shared.axiom_enforcer import enforce_output, EnforcementResult

    result = enforce_output(text, agent_id="briefing", output_path=briefing_file)
    if result.allowed:
        output_path.write_text(text)
    else:
        print(f"BLOCKED: {result.violations}")
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from shared.axiom_pattern_checker import PatternViolation, check_output

log = logging.getLogger(__name__)

EXCEPTIONS_PATH = Path(__file__).resolve().parent.parent / "axioms" / "enforcement-exceptions.yaml"
QUARANTINE_DIR = Path(__file__).resolve().parent.parent / "profiles" / ".quarantine"
AUDIT_LOG = Path(__file__).resolve().parent.parent / "profiles" / ".enforcement-audit.jsonl"


@dataclass
class EnforcementResult:
    """Result of an enforcement check."""

    allowed: bool
    violations: list[PatternViolation] = field(default_factory=list)
    quarantine_path: Path | None = None
    audit_only: bool = False  # True during tuning period


# ── Enforcement mode ─────────────────────────────────────────────────────────
# Start in audit-only mode. Set AXIOM_ENFORCE_BLOCK=1 to enable T0 blocking.
import os

_BLOCK_ENABLED = os.environ.get("AXIOM_ENFORCE_BLOCK", "0") == "1"


def _load_exceptions() -> dict[str, dict]:
    """Load enforcement exceptions keyed by component path."""
    if not EXCEPTIONS_PATH.exists():
        return {}
    try:
        data = yaml.safe_load(EXCEPTIONS_PATH.read_text())
    except Exception:
        return {}
    result: dict[str, dict] = {}
    for exc in data.get("exceptions", []):
        component = exc.get("component", "")
        if component:
            result[component] = exc
    return result


def _is_excepted(agent_id: str, output_path: str | Path) -> bool:
    """Check if this agent/path combination has an enforcement exception."""
    exceptions = _load_exceptions()
    output_str = str(output_path)
    for component, _exc in exceptions.items():
        if component in output_str or agent_id in component:
            return True
    return False


def _quarantine(text: str, agent_id: str, violations: list[PatternViolation]) -> Path:
    """Write blocked output to quarantine for operator review."""
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    quarantine_file = QUARANTINE_DIR / f"{agent_id}-{ts}.md"

    violation_summary = "\n".join(
        f"- [{v.tier}] {v.pattern_id}: '{v.matched_text}' — {v.description}"
        for v in violations
    )

    quarantine_file.write_text(
        f"# Quarantined Output — {agent_id}\n"
        f"Quarantined at: {ts}\n"
        f"Agent: {agent_id}\n\n"
        f"## Violations\n{violation_summary}\n\n"
        f"## Original Output\n{text}\n"
    )

    log.warning("Output quarantined: %s (%d violations)", quarantine_file, len(violations))
    return quarantine_file


def _audit_log(
    agent_id: str,
    output_path: str | Path,
    violations: list[PatternViolation],
    *,
    allowed: bool,
    audit_only: bool,
    source_text: str = "",
) -> None:
    """Append enforcement event to audit log."""
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        violation_entries = []
        for v in violations:
            entry_v: dict = {
                "pattern_id": v.pattern_id,
                "tier": v.tier,
                "matched_text": v.matched_text,
                "axiom_id": v.axiom_id,
            }
            # Include surrounding context for labeling
            if source_text:
                start = max(0, v.match_start - 80)
                end = min(len(source_text), v.match_end + 80)
                entry_v["context"] = source_text[start:end].replace("\n", " ").strip()
            violation_entries.append(entry_v)

        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "agent_id": agent_id,
            "output_path": str(output_path),
            "allowed": allowed,
            "audit_only": audit_only,
            "source": "live",
            "violations": violation_entries,
        }
        with AUDIT_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        log.debug("Failed to write audit log: %s", e)


def enforce_output(
    text: str,
    agent_id: str,
    output_path: str | Path,
    *,
    block_enabled: bool | None = None,
) -> EnforcementResult:
    """Enforce axiom patterns on LLM-generated output.

    Args:
        text: The output text to check.
        agent_id: Identifier of the producing agent.
        output_path: Where the output would be written.
        block_enabled: Override for blocking mode. None uses env var.

    Returns:
        EnforcementResult with allowed=True if output should proceed.
    """
    should_block = block_enabled if block_enabled is not None else _BLOCK_ENABLED

    # Check for exceptions
    if _is_excepted(agent_id, output_path):
        log.debug("Enforcement exception for %s at %s", agent_id, output_path)
        return EnforcementResult(allowed=True)

    # Check patterns
    violations = check_output(text)

    if not violations:
        return EnforcementResult(allowed=True)

    t0_violations = [v for v in violations if v.tier == "T0"]
    t1_violations = [v for v in violations if v.tier == "T1"]

    # Always log
    _audit_log(
        agent_id,
        output_path,
        violations,
        allowed=not (t0_violations and should_block),
        audit_only=not should_block,
        source_text=text,
    )

    # T0 violations: block (if enabled) + quarantine
    if t0_violations and should_block:
        quarantine_path = _quarantine(text, agent_id, t0_violations)
        return EnforcementResult(
            allowed=False,
            violations=violations,
            quarantine_path=quarantine_path,
        )

    # Audit-only mode: allow but flag
    if t0_violations and not should_block:
        log.warning(
            "AUDIT: %d T0 violation(s) in %s output (blocking disabled): %s",
            len(t0_violations),
            agent_id,
            ", ".join(v.pattern_id for v in t0_violations),
        )
        return EnforcementResult(
            allowed=True,
            violations=violations,
            audit_only=True,
        )

    # T1/T2 only: allow + audit
    if t1_violations:
        log.info(
            "T1 violation(s) in %s output: %s",
            agent_id,
            ", ".join(v.pattern_id for v in t1_violations),
        )

    return EnforcementResult(
        allowed=True,
        violations=violations,
    )
