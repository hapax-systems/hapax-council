"""Single-user axiom sufficiency probes."""

from __future__ import annotations

import re

from .config import AI_AGENTS_DIR
from .sufficiency_probes import SufficiencyProbe

_USER_KEYED_PATH_PATTERNS = (
    r"os\.path\.join\([^)]*\buser_id\b",
    r"Path\([^)]*\buser_id\b",
    r"f[\"'][^\"']*\{user_id\}",
    r"f[\"'][^\"']*\{user\}",
    r"/users/\{",
)

_PROBE_SCAN_GLOBS = ("agents/**/*.py", "shared/**/*.py", "logos/**/*.py")


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


def _check_no_user_keyed_paths() -> tuple[bool, str]:
    """Enforces su-paths-001 (single_user axiom).

    File paths and database queries must not dynamically construct
    user-specific paths or apply user-based filters. Scans the
    project's Python source trees for path-construction patterns
    that key on `user_id` / `{user}` / `/users/{...}`.

    External-API client modules that query third-party endpoints
    are excluded (e.g. soundcloud_adapter resolves a third-party
    user, not an operator).
    """
    excluded_substrings = (
        "soundcloud_adapter",
        "liberapay_receiver",
        "drift_detector/probes_single_user",
        "drift_detector/_sufficiency_probes",
        "drift_detector/sufficiency_probes",
    )

    found: list[str] = []
    for glob in _PROBE_SCAN_GLOBS:
        for path in AI_AGENTS_DIR.glob(glob):
            if any(excl in str(path) for excl in excluded_substrings):
                continue
            try:
                content = path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for pattern in _USER_KEYED_PATH_PATTERNS:
                if re.search(pattern, content):
                    rel = path.relative_to(AI_AGENTS_DIR)
                    found.append(f"{rel}: {pattern}")
                    break

    if not found:
        return True, (
            "no user-keyed path construction in agents/**/*.py, "
            "shared/**/*.py, or logos/**/*.py (su-paths-001 sufficient)"
        )
    summary = "; ".join(found[:5])
    return False, f"user-keyed path patterns found ({len(found)} files): {summary}"


SINGLE_USER_PROBES: list[SufficiencyProbe] = [
    SufficiencyProbe(
        id="probe-su-leverage-001",
        axiom_id="single_user",
        implication_id="su-decision-001",
        level="system",
        question="Is there no multi-user indirection in config paths?",
        check=_check_no_multiuser_indirection,
    ),
    SufficiencyProbe(
        id="probe-su-paths-001",
        axiom_id="single_user",
        implication_id="su-paths-001",
        level="system",
        question=(
            "Is the project free of dynamic user-keyed path construction "
            "in agent / shared / logos source trees?"
        ),
        check=_check_no_user_keyed_paths,
    ),
]
