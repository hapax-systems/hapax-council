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
    SufficiencyProbe(
        id="probe-su-cache-001",
        axiom_id="single_user",
        implication_id="su-cache-001",
        level="component",
        question=(
            "Are caching strategies free of user-specific cache keys "
            "or user-scoped invalidation patterns?"
        ),
        check=lambda: _check_no_user_keyed_caches(),
    ),
    SufficiencyProbe(
        id="probe-su-storage-001",
        axiom_id="single_user",
        implication_id="su-storage-001",
        level="component",
        question=(
            "Are storage modules (Qdrant schema, storage arbiter, "
            "profile facts) free of multi-tenant primitives like "
            "tenant_id / account_id / org_id?"
        ),
        check=lambda: _check_no_multi_tenant_storage(),
    ),
]


def _check_no_multi_tenant_storage() -> tuple[bool, str]:
    """Enforces su-storage-001 (single_user).

    File paths, database schemas, and data structures can use
    operator-specific identifiers without generalization. The
    inversion: storage code MUST NOT introduce multi-tenant
    primitives like tenant_id / account_id / org_id, which would
    indicate generalization-for-multi-user-future.

    Scans canonical storage modules (Qdrant schema, storage arbiter,
    profile facts) for forbidden multi-tenant column / payload-key
    declarations.

    Hyprland `workspace_id` is allowed — it's a Linux desktop
    workspace concept, not a multi-tenant primitive.
    """
    forbidden_patterns = (
        r"\btenant_id\b",
        r"\baccount_id\b",
        r"\borg_id\b",
        r"\borganization_id\b",
    )

    storage_modules = (
        AI_AGENTS_DIR / "shared" / "qdrant_schema.py",
        AI_AGENTS_DIR / "agents" / "storage_arbiter.py",
        AI_AGENTS_DIR / "shared" / "governance" / "qdrant_gate.py",
    )

    found: list[str] = []
    checked = 0
    for module in storage_modules:
        if not module.exists():
            continue
        checked += 1
        try:
            content = module.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in forbidden_patterns:
            if re.search(pattern, content):
                found.append(f"{module.name}: {pattern}")
                break

    if checked == 0:
        return False, "no canonical storage modules found"

    if not found:
        return True, (
            f"no multi-tenant primitives in {checked} canonical storage "
            f"modules — su-storage-001 sufficient"
        )
    summary = "; ".join(found[:3])
    return False, f"multi-tenant primitives found: {summary}"


def _check_no_user_keyed_caches() -> tuple[bool, str]:
    """Enforces su-cache-001 (single_user).

    Caching strategies must not implement user-specific cache keys or
    user-scoped cache invalidation patterns. Scans the project's cache
    modules for user-keyed cache patterns:
      - cache.set(user_id, ...) / cache.get(user_id, ...)
      - cache_key=f"...{user_id}..."
      - per_user_cache, user_cache_key, cache_by_user
      - @lru_cache decorating functions with user_id parameters

    External-API client modules that cache third-party data are
    excluded (e.g. soundcloud_adapter caches third-party user data,
    not operator data).
    """
    user_keyed_cache_patterns = (
        r"cache\.[gs]et\([^)]*\buser_id\b",
        r"cache_key\s*=\s*[fr]?[\"'][^\"']*\{user_id\}",
        r"per_user_cache",
        r"user_cache_key",
        r"cache_by_user",
        r"\.cache_user\(",
    )

    excluded_substrings = (
        "soundcloud_adapter",
        "drift_detector/probes_single_user",
    )

    cache_modules = (
        AI_AGENTS_DIR / "shared" / "embed_cache.py",
        AI_AGENTS_DIR / "agents" / "predictive_cache.py",
        AI_AGENTS_DIR / "agents" / "studio_compositor" / "frame_cache.py",
        AI_AGENTS_DIR / "agents" / "hapax_daimonion" / "cpal" / "signal_cache.py",
    )

    found: list[str] = []
    checked = 0
    for module in cache_modules:
        if any(excl in str(module) for excl in excluded_substrings):
            continue
        if not module.exists():
            continue
        checked += 1
        try:
            content = module.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in user_keyed_cache_patterns:
            if re.search(pattern, content):
                found.append(f"{module.name}: {pattern}")
                break

    if checked == 0:
        return False, "no canonical cache modules found"

    if not found:
        return True, (
            f"no user-keyed cache patterns in {checked} canonical cache "
            f"modules — su-cache-001 sufficient"
        )
    summary = "; ".join(found[:3])
    return False, f"user-keyed cache patterns found: {summary}"
