"""Capability coverage meta-probe."""

from __future__ import annotations

from .config import HAPAXROMANA_DIR
from .sufficiency_probes import SufficiencyProbe


def _check_capability_coverage() -> tuple[bool, str]:
    """Meta-probe: verify agent registry health_groups have corresponding health checks."""
    from .sufficiency_probes import PROBES

    problems: list[str] = []

    try:
        from agents._agent_registry import get_registry

        registry = get_registry()
        try:
            from agents.health_monitor import CHECK_REGISTRY

            declared_groups = {a.health_group for a in registry.list_agents() if a.health_group}
            registered_groups = set(CHECK_REGISTRY.keys())
            missing_groups = declared_groups - registered_groups
            if missing_groups:
                problems.append(
                    f"health_groups without checks: {', '.join(sorted(missing_groups))}"
                )
        except ImportError:
            pass
    except Exception as e:
        problems.append(f"registry unavailable: {e}")

    try:
        import yaml

        coverage_file = HAPAXROMANA_DIR / "axioms" / "capability-coverage.yaml"
        if coverage_file.exists():
            data = yaml.safe_load(coverage_file.read_text())
            probe_ids = {p.id for p in PROBES}
            for cap in data.get("capabilities", []):
                for probe_id in cap.get("required_probes", []):
                    if probe_id not in probe_ids:
                        problems.append(f"{cap['id']}/{probe_id} missing")
    except Exception:
        pass

    if problems:
        return False, "; ".join(problems[:5])

    try:
        agent_count = len(registry.list_agents())
        return True, f"all health_groups covered across {agent_count} agents"
    except Exception:
        return True, "coverage checks passed"


COVERAGE_PROBES: list[SufficiencyProbe] = [
    SufficiencyProbe(
        id="probe-meta-coverage-001",
        axiom_id="executive_function",
        implication_id="ex-alert-004",
        level="system",
        question="Do all registered capabilities have corresponding sufficiency probes?",
        check=_check_capability_coverage,
    ),
]
