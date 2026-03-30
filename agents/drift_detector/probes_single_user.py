"""Single-user axiom sufficiency probes."""

from __future__ import annotations

import re

from .config import AI_AGENTS_DIR
from .sufficiency_probes import SufficiencyProbe


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


SINGLE_USER_PROBES: list[SufficiencyProbe] = [
    SufficiencyProbe(
        id="probe-su-leverage-001",
        axiom_id="single_user",
        implication_id="su-decision-001",
        level="system",
        question="Is there no multi-user indirection in config paths?",
        check=_check_no_multiuser_indirection,
    ),
]
