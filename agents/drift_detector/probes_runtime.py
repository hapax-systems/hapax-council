"""Runtime behavioral sufficiency probes."""

from __future__ import annotations

from .sufficiency_probes import SufficiencyProbe


def _check_health_timer_fired() -> tuple[bool, str]:
    """health-monitor.timer fired within last 20 min."""
    import subprocess

    try:
        cmd = [
            "journalctl",
            "--user",
            "-u",
            "health-monitor.service",
            "--since",
            "20 min ago",
            "--no-pager",
            "-q",
            "--output=short",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
        if lines:
            return True, f"health-monitor.service ran in last 20 min ({len(lines)} log lines)"
        return False, "health-monitor.service has not run in last 20 min"
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f"journalctl check failed: {e}"


def _check_backup_fresh() -> tuple[bool, str]:
    """Last backup is <36h old."""
    import time as _time
    from pathlib import Path

    repo = Path("/data/backups/restic")
    candidates = [repo / "locks", repo / "snapshots", repo / "index"]
    latest: float | None = None
    for p in candidates:
        if p.exists():
            try:
                mtime = p.stat().st_mtime
                if latest is None or mtime > latest:
                    latest = mtime
            except OSError:
                continue

    if latest is None:
        return False, "restic repo not found"

    age_h = (_time.time() - latest) / 3600
    if age_h < 36:
        return True, f"backup {age_h:.1f}h old"
    return False, f"backup {age_h:.0f}h old (>36h)"


def _check_sync_fresh() -> tuple[bool, str]:
    """All sync state files are <24h old."""
    import time as _time
    from pathlib import Path

    try:
        from shared.agent_registry import AgentCategory, get_registry

        registry = get_registry()
        sync_agents = registry.agents_by_category(AgentCategory.SYNC)
        agents: dict[str, Path] = {}
        for agent in sync_agents:
            cache_name = agent.id.replace("_", "-")
            display = (
                cache_name.removesuffix("-sync") if cache_name.endswith("-sync") else cache_name
            )
            agents[display] = Path.home() / ".cache" / cache_name / "state.json"
    except ImportError:
        return True, "agent_registry not available (non-critical)"

    stale: list[str] = []
    missing: list[str] = []
    for name, state in agents.items():
        if not state.exists():
            missing.append(name)
            continue
        try:
            age_h = (_time.time() - state.stat().st_mtime) / 3600
            if age_h > 24:
                stale.append(f"{name}({age_h:.0f}h)")
        except OSError:
            missing.append(name)

    problems = stale + [f"{m}(missing)" for m in missing]
    if not problems:
        return True, f"all {len(agents)} sync agents fresh (<24h)"
    return False, f"stale/missing sync: {', '.join(problems)}"


def _check_no_error_spikes() -> tuple[bool, str]:
    """No agent produced >10 ERROR-level logs in last hour."""
    import json as _json
    import subprocess

    try:
        cmd = [
            "journalctl",
            "--user",
            "--priority=err",
            "--since",
            "1 hour ago",
            "--output=json",
            "--no-pager",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return True, "no error logs (journalctl returned no data)"

        counts: dict[str, int] = {}
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            try:
                entry = _json.loads(line)
                ident = entry.get("SYSLOG_IDENTIFIER", "unknown")
                counts[ident] = counts.get(ident, 0) + 1
            except _json.JSONDecodeError:
                continue

        spikes = {k: v for k, v in counts.items() if v > 10}
        if not spikes:
            total = sum(counts.values())
            return True, f"{total} errors in last hour, no agent >10"
        details = ", ".join(f"{k}={v}" for k, v in sorted(spikes.items(), key=lambda x: -x[1]))
        return False, f"error spikes: {details}"
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f"journalctl check failed: {e}"


def _check_prometheus_scraping() -> tuple[bool, str]:
    """Prometheus is scraping successfully."""
    import json as _json
    from urllib.error import URLError
    from urllib.request import urlopen

    try:
        with urlopen("http://localhost:9090/api/v1/targets", timeout=5) as resp:
            data = _json.loads(resp.read().decode())
        targets = data.get("data", {}).get("activeTargets", [])
        if not targets:
            return False, "prometheus has no active targets"
        up = sum(1 for t in targets if t.get("health") == "up")
        total = len(targets)
        if up == total:
            return True, f"all {total} prometheus targets up"
        down = [t.get("labels", {}).get("job", "?") for t in targets if t.get("health") != "up"]
        return False, f"{up}/{total} targets up, down: {', '.join(down)}"
    except (URLError, OSError, _json.JSONDecodeError) as e:
        return False, f"prometheus unreachable: {e}"


def _p(id: str, impl: str, q: str, fn) -> SufficiencyProbe:
    return SufficiencyProbe(
        id=id,
        axiom_id="executive_function",
        implication_id=impl,
        level="system",
        question=q,
        check=fn,
    )


RUNTIME_PROBES: list[SufficiencyProbe] = [
    _p(
        "probe-runtime-001",
        "ex-routine-007",
        "Has health-monitor.timer fired in last 20 min?",
        _check_health_timer_fired,
    ),
    _p("probe-runtime-002", "ex-alert-001", "Is the last backup <36h old?", _check_backup_fresh),
    _p(
        "probe-runtime-003",
        "ex-routine-007",
        "Are all sync state files <24h old?",
        _check_sync_fresh,
    ),
    _p(
        "probe-runtime-004",
        "ex-alert-001",
        "Are there no agent error spikes in the last hour?",
        _check_no_error_spikes,
    ),
    _p(
        "probe-runtime-005",
        "ex-alert-001",
        "Is Prometheus scraping successfully?",
        _check_prometheus_scraping,
    ),
]
