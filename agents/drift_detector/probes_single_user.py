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
    SufficiencyProbe(
        id="probe-su-config-001",
        axiom_id="single_user",
        implication_id="su-config-001",
        level="component",
        question=(
            "Does shared/config.py hardcode the operator's preferences "
            "rather than requiring caller-supplied config?"
        ),
        check=lambda: _check_config_hardcodes_operator_prefs(),
    ),
    SufficiencyProbe(
        id="probe-su-feature-001",
        axiom_id="single_user",
        implication_id="su-feature-001",
        level="component",
        question=(
            "Is the project free of multi-user collaboration features "
            "(invite_user_to / add_team_member / share_with_user / etc.)?"
        ),
        check=lambda: _check_no_collab_features(),
    ),
    SufficiencyProbe(
        id="probe-su-admin-001",
        axiom_id="single_user",
        implication_id="su-admin-001",
        level="component",
        question=(
            "Is the project free of administrative interfaces, user "
            "management UIs, or role assignment systems?"
        ),
        check=lambda: _check_no_admin_ui(),
    ),
    SufficiencyProbe(
        id="probe-su-agents-001",
        axiom_id="single_user",
        implication_id="su-agents-001",
        level="component",
        question=(
            "Are AI agents free of user-context-switching / permission-"
            "checking / user-specific behavior customization?"
        ),
        check=lambda: _check_no_user_context_switching(),
    ),
    SufficiencyProbe(
        id="probe-su-data-001",
        axiom_id="single_user",
        implication_id="su-data-001",
        level="component",
        question=(
            "Are data storage paths free of access-control / permissions / "
            "data-isolation primitives?"
        ),
        check=lambda: _check_no_data_access_control(),
    ),
    SufficiencyProbe(
        id="probe-su-api-001",
        axiom_id="single_user",
        implication_id="su-api-001",
        level="component",
        question=(
            "Are API endpoints free of user-verification / quota / abuse-prevention primitives?"
        ),
        check=lambda: _check_no_api_user_verification(),
    ),
]


def _join(*parts: str) -> str:
    return "".join(parts)


_AGENTS_FORBIDDEN = "|".join(
    [
        "def " + _join("set_current_", "user"),
        "def " + _join("switch_context_for_", "user"),
        "def " + _join("user_permission_", "check"),
        "def " + _join("check_user_", "permission"),
        "def " + _join("customize_for_", "user"),
    ]
)

_DATA_FORBIDDEN = "|".join(
    [
        "def " + _join("check_data_", "ownership"),
        "def " + _join("verify_user_can_", "access"),
        "def " + _join("enforce_", "isolation"),
        "def " + _join("require_", "permission"),
        "class " + _join("AccessControl", "List"),
        "class " + _join("Data", "Permission"),
    ]
)

_API_FORBIDDEN = "|".join(
    [
        "def " + _join("authenticate_", "request"),
        "def " + _join("verify_", "user"),
        "def " + _join("check_", "quota"),
        "def " + _join("rate_limit_", "user"),
        "def " + _join("detect_", "abuse"),
        "class " + _join("Rate", "Limiter"),
        "class " + _join("Quota", "Enforcer"),
        "class " + _join("Abuse", "Detector"),
    ]
)


def _scan_for_forbidden(pattern_re: re.Pattern[str]) -> list[str]:
    found: list[str] = []
    for glob in _PROBE_SCAN_GLOBS:
        for py_file in AI_AGENTS_DIR.glob(glob):
            try:
                content = py_file.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if pattern_re.search(content):
                rel = py_file.relative_to(AI_AGENTS_DIR)
                found.append(str(rel))
    return found


def _check_no_user_context_switching() -> tuple[bool, str]:
    """Enforces su-agents-001 (single_user, T1, absence pattern)."""
    found = _scan_for_forbidden(re.compile(_AGENTS_FORBIDDEN))
    if not found:
        return True, (
            "no user-context-switching / permission-checking patterns "
            "in agents - su-agents-001 sufficient"
        )
    return False, f"forbidden patterns: {', '.join(found[:3])}"


def _check_no_data_access_control() -> tuple[bool, str]:
    """Enforces su-data-001 (single_user, T1, absence pattern)."""
    found = _scan_for_forbidden(re.compile(_DATA_FORBIDDEN))
    if not found:
        return True, (
            "no access-control / permission / isolation primitives "
            "in storage paths - su-data-001 sufficient"
        )
    return False, f"forbidden patterns: {', '.join(found[:3])}"


def _check_no_api_user_verification() -> tuple[bool, str]:
    """Enforces su-api-001 (single_user, T1, absence pattern)."""
    found = _scan_for_forbidden(re.compile(_API_FORBIDDEN))
    if not found:
        return True, (
            "no user-verification / quota / abuse-prevention primitives "
            "on API endpoints - su-api-001 sufficient"
        )
    return False, f"forbidden patterns: {', '.join(found[:3])}"


def _check_no_collab_features() -> tuple[bool, str]:
    """Enforces su-feature-001 (single_user, T0/block, absurdity).

    Features for user collaboration, sharing between users, or
    multi-user coordination must not be developed. Verifies absence
    of SaaS-style collab patterns:
      - def invite_user_to* / add_team_member / share_with_user
      - class TeamWorkspace / OrgChannel / UserGroup
      - bcrypt.hashpw, jwt.encode (multi-user auth primitives)
    """
    forbidden_patterns = (
        r"def invite_user_to|def add_team_member|def share_with_user|"
        r"class TeamWorkspace|class OrgChannel|class UserGroup|"
        r"bcrypt\.hashpw|jwt\.encode"
    )
    pattern = re.compile(forbidden_patterns)

    found: list[str] = []
    for glob in _PROBE_SCAN_GLOBS:
        for py_file in AI_AGENTS_DIR.glob(glob):
            try:
                content = py_file.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if pattern.search(content):
                rel = py_file.relative_to(AI_AGENTS_DIR)
                found.append(str(rel))

    if not found:
        return True, (
            "no multi-user collaboration features anywhere in agents / "
            "shared / logos source trees - su-feature-001 sufficient"
        )
    return False, f"collab feature patterns found: {', '.join(found[:3])}"


def _check_no_admin_ui() -> tuple[bool, str]:
    """Enforces su-admin-001 (single_user, T0/block, absurdity).

    Administrative interfaces, user management UIs, or role assignment
    systems must not exist since the single user is the admin by
    default. Verifies absence of admin/role/permission patterns:
      - def admin_panel / def manage_users / def assign_role
      - class UserManagement / class AdminUI / class RoleAssignment
      - permission.grant / role.assign / user.deactivate
    """
    forbidden_patterns = (
        r"def admin_panel|def manage_users|def assign_role|"
        r"class UserManagement|class AdminUI|class RoleAssignment|"
        r"\.permission\.grant|\.role\.assign|\.user\.deactivate"
    )
    pattern = re.compile(forbidden_patterns)

    found: list[str] = []
    for glob in _PROBE_SCAN_GLOBS:
        for py_file in AI_AGENTS_DIR.glob(glob):
            try:
                content = py_file.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if pattern.search(content):
                rel = py_file.relative_to(AI_AGENTS_DIR)
                found.append(str(rel))

    if not found:
        return True, (
            "no administrative interfaces / user-management UIs / "
            "role-assignment systems - su-admin-001 sufficient"
        )
    return False, f"admin UI patterns found: {', '.join(found[:3])}"


def _check_config_hardcodes_operator_prefs() -> tuple[bool, str]:
    """Enforces su-config-001 (single_user).

    Configuration files should hardcode the operator's preferences
    rather than providing generic defaults or multi-user options.
    Verifies shared/config.py:
      - Has >=10 hardcoded operator-specific tokens (Path.home(),
        model name strings, hapax-prefixed identifiers, etc.)
      - Most os.environ.get() calls have non-empty default args
        (caller config is optional, defaults are operator-specific)
    """
    config_file = AI_AGENTS_DIR / "shared" / "config.py"
    if not config_file.exists():
        return False, "shared/config.py not found"

    content = config_file.read_text()

    hardcoded_patterns = (
        r"Path\.home\(\)",
        r'"claude-(?:sonnet|opus|haiku)',
        r'"gemini-(?:flash|pro)',
        r'"local-(?:fast|coding|reasoning)',
        r'"hapax-',
    )
    hardcoded_count = 0
    for pattern in hardcoded_patterns:
        hardcoded_count += len(re.findall(pattern, content))

    with_defaults = len(re.findall(r"os\.environ\.get\([^)]*,\s*\S", content))
    no_defaults = len(re.findall(r"os\.environ\[", content))
    total_env = with_defaults + no_defaults

    if hardcoded_count < 10:
        return False, (
            f"only {hardcoded_count} hardcoded operator-specific tokens in "
            f"shared/config.py (need >=10) - su-config-001 insufficient"
        )

    if total_env > 0 and (with_defaults / total_env) < 0.8:
        return False, (
            f"only {with_defaults}/{total_env} os.environ reads have "
            f"hardcoded defaults - su-config-001 insufficient"
        )

    return True, (
        f"{hardcoded_count} hardcoded operator-specific tokens + "
        f"{with_defaults}/{total_env} os.environ reads with defaults "
        f"- su-config-001 sufficient"
    )


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
