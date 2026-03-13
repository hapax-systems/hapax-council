"""Fix capabilities — structured fix evaluation and execution for health monitor."""

from shared.fix_capabilities.base import Capability

_REGISTRY: dict[str, Capability] = {}


def register_capability(cap: Capability) -> None:
    """Register a capability, mapping all its check_groups."""
    for group in cap.check_groups:
        _REGISTRY[group] = cap


def get_capability_for_group(group: str) -> Capability | None:
    """Return the capability registered for a check group, or None."""
    return _REGISTRY.get(group)


def get_all_capabilities() -> list[Capability]:
    """Return all unique registered capabilities."""
    seen: set[str] = set()
    result: list[Capability] = []
    for cap in _REGISTRY.values():
        if cap.name not in seen:
            seen.add(cap.name)
            result.append(cap)
    return result


def load_builtin_capabilities() -> None:
    """Register all built-in capability modules."""
    from shared.fix_capabilities.docker_cap import DockerCapability
    from shared.fix_capabilities.filesystem_cap import FilesystemCapability
    from shared.fix_capabilities.ollama_cap import OllamaCapability
    from shared.fix_capabilities.profiles_cap import ProfilesCapability
    from shared.fix_capabilities.queues_cap import QueuesCapability
    from shared.fix_capabilities.systemd_cap import SystemdCapability

    register_capability(OllamaCapability())
    register_capability(DockerCapability())
    register_capability(SystemdCapability())
    register_capability(FilesystemCapability())
    register_capability(ProfilesCapability())
    register_capability(QueuesCapability())
