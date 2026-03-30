"""Skill syntax health checks."""

from __future__ import annotations

import time

from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("skills")
async def check_skill_syntax() -> list[CheckResult]:
    """Validate Claude Code skill definitions are syntactically valid."""
    t = time.monotonic()
    try:
        from agents._sufficiency_probes import _check_skill_syntax

        met, evidence = _check_skill_syntax()
        status = Status.HEALTHY if met else Status.DEGRADED
        return [
            CheckResult(
                name="skills.syntax",
                group="skills",
                status=status,
                message=evidence,
                remediation="Fix skill YAML frontmatter or embedded Python syntax"
                if not met
                else None,
                duration_ms=_u._timed(t),
            )
        ]
    except Exception as e:
        return [
            CheckResult(
                name="skills.syntax",
                group="skills",
                status=Status.FAILED,
                message=f"Skill syntax check error: {e}",
                duration_ms=_u._timed(t),
            )
        ]
