"""Canonical task-owner identity parsing and platform-aware matching."""

from __future__ import annotations

from dataclasses import dataclass

UNASSIGNED_TASK_OWNERS = frozenset({"", "null", "none", "~", "unassigned"})
TASK_OWNER_PLATFORMS = frozenset({"claude", "codex", "vibe"})
CLAUDE_LEGACY_ROLES = frozenset(
    {"alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"}
)


@dataclass(frozen=True)
class TaskOwnerIdentity:
    role: str
    platform: str | None = None

    @property
    def reservation_key(self) -> str:
        return f"{self.platform}/{self.role}" if self.platform else self.role


def task_owner_is_unassigned(owner: str) -> bool:
    return owner.strip().lower() in UNASSIGNED_TASK_OWNERS


def inferred_task_owner_platform(role: str) -> str | None:
    """Return the platform encoded by a known legacy bare-role shape."""

    normalized = role.strip()
    if normalized.startswith("cx-"):
        return "codex"
    if normalized.startswith("vbe-"):
        return "vibe"
    if normalized in CLAUDE_LEGACY_ROLES or normalized.startswith("cc-"):
        return "claude"
    return None


def canonical_task_owner(role: str, platform: str | None) -> str:
    """Format an owner without discarding a known caller platform."""

    normalized_role = role.strip()
    if (
        not normalized_role
        or task_owner_is_unassigned(normalized_role)
        or "/" in normalized_role
        or any(char.isspace() for char in normalized_role)
    ):
        raise ValueError("task owner role is not a non-empty bare identity")
    if platform is None or not platform.strip():
        return normalized_role
    normalized_platform = platform.strip().lower()
    if normalized_platform not in TASK_OWNER_PLATFORMS:
        raise ValueError("task owner platform is not supported")
    inferred_platform = inferred_task_owner_platform(normalized_role)
    if inferred_platform is not None and inferred_platform != normalized_platform:
        raise ValueError("task owner platform contradicts the role identity")
    return f"{normalized_platform}/{normalized_role}"


def parse_task_owner(owner: str) -> TaskOwnerIdentity | None:
    """Parse a bare legacy role or an exact ``platform/role`` owner.

    Canonical unassigned spellings return ``None``. Any other malformed identity
    raises ``ValueError`` so admission callers can HOLD rather than erase it.
    """

    normalized = owner.strip()
    if task_owner_is_unassigned(normalized):
        return None
    if "/" not in normalized:
        if any(char.isspace() for char in normalized):
            raise ValueError("bare task owner contains whitespace")
        return TaskOwnerIdentity(
            role=normalized,
            platform=inferred_task_owner_platform(normalized),
        )

    platform, separator, role = normalized.partition("/")
    platform = platform.strip().lower()
    role = role.strip()
    if (
        not separator
        or platform not in TASK_OWNER_PLATFORMS
        or not role
        or task_owner_is_unassigned(role)
        or "/" in role
        or any(char.isspace() for char in role)
    ):
        raise ValueError("task owner is not a supported platform/role identity")
    inferred_platform = inferred_task_owner_platform(role)
    if inferred_platform is not None and inferred_platform != platform:
        raise ValueError("task owner platform contradicts the role identity")
    return TaskOwnerIdentity(role=role, platform=platform)


def owner_matches(
    owner: str,
    role: str,
    platform: str | None,
    *,
    allow_unqualified: bool = True,
) -> bool:
    """Return whether ``owner`` authorizes this exact capability identity."""

    try:
        identity = parse_task_owner(owner)
    except ValueError:
        return False
    if identity is None or identity.role != role.strip():
        return False
    if identity.platform is None:
        return allow_unqualified
    return bool(platform) and identity.platform == platform.strip().lower()
