"""Credential-expiry probes for the cred monitor.

Detects credentials that are approaching expiry or have already died, and routes a
governed P0 (via scripts/hapax-p0-incident-intake) so a dying token becomes a desktop
alert + coalesced P0 task DAYS before it silently breaks something -- e.g. the gdrive
OAuth refresh token that staled the offsite backup for ~11 days before anyone noticed.

Single-user, max-longevity posture: most credentials never expire (service-account keys,
the GPG master key, static provider API keys), so this probes only the few that genuinely
can die -- the Tailscale node key and rclone OAuth remotes -- with an injectable runner so
the threshold ladder + routing are deterministically testable. The intake coalesces by
fingerprint, so even a 5-min tick against a dead credential yields ONE task, not a storm.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

WARN_DAYS = 14
P0_DAYS = 7
_REPO_ROOT = Path(__file__).resolve().parents[2]
_INTAKE = _REPO_ROOT / "scripts" / "hapax-p0-incident-intake"

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class CredentialExpiry:
    name: str
    healthy: bool
    days_remaining: int | None  # None when liveness-only (no date)
    severity: str  # "ok" | "warn" | "p0"
    title: str
    message: str


def _default_run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), capture_output=True, text=True, check=False, timeout=25)


def _severity(*, healthy: bool, days: int | None) -> str:
    if not healthy:
        return "p0"
    if days is None:
        return "ok"
    if days <= P0_DAYS:
        return "p0"
    if days <= WARN_DAYS:
        return "warn"
    return "ok"


def probe_tailscale_node_key(
    *, now: datetime | None = None, run: Runner | None = None
) -> CredentialExpiry | None:
    """Return the node-key expiry status, or None if Tailscale is absent or key expiry is
    disabled (the desired max-longevity state -- nothing to alert)."""
    run = run or _default_run
    now = now or datetime.now(UTC)
    try:
        proc = run(["tailscale", "status", "--json"])
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        expiry = json.loads(proc.stdout).get("Self", {}).get("KeyExpiry")
    except (json.JSONDecodeError, AttributeError):
        return None
    if not expiry:  # key expiry disabled -> never expires -> good, nothing to alert
        return None
    try:
        exp = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
    except ValueError:
        return None
    days = (exp - now).days
    healthy = days > 0
    return CredentialExpiry(
        name="tailscale/node-key",
        healthy=healthy,
        days_remaining=days,
        severity=_severity(healthy=healthy, days=days),
        title="Tailscale node key expiring",
        message=(
            f"Tailscale node key expires in {days}d ({expiry}). Durable fix: admin console "
            "-> Machines -> this device -> Disable key expiry (single-user box). Otherwise the "
            "cross-rig LiteLLM/Tailscale transport drops when it fires."
        ),
    )


def probe_rclone_remote(remote: str, *, run: Runner | None = None) -> CredentialExpiry:
    """Liveness-probe an rclone remote; an OAuth refresh-token death (invalid_grant) is the
    canonical silent-failure this watchdog exists to catch before the backup goes stale."""
    run = run or _default_run
    try:
        proc = run(["rclone", "about", f"{remote}:"])
    except (OSError, subprocess.TimeoutExpired):
        return CredentialExpiry(
            name=f"rclone/{remote}",
            healthy=False,
            days_remaining=None,
            severity="p0",
            title=f"rclone {remote} probe failed",
            message=f"rclone {remote}: liveness probe could not run.",
        )
    if proc.returncode == 0:
        return CredentialExpiry(
            name=f"rclone/{remote}",
            healthy=True,
            days_remaining=None,
            severity="ok",
            title=f"rclone {remote} reachable",
            message=f"rclone {remote}: reachable.",
        )
    err = (proc.stderr or "").lower()
    auth_dead = any(s in err for s in ("invalid_grant", "token expired", "config reconnect"))
    if auth_dead:
        message = (
            f"rclone {remote}: OAuth token DEAD (invalid_grant). Immediate: "
            f"`rclone config reconnect {remote}:`. Durable: publish the OAuth consent screen "
            "to Production, or switch the remote to a service account (never expires)."
        )
    else:
        message = f"rclone {remote}: FAILED — {(proc.stderr or '').strip()[:200]}"
    return CredentialExpiry(
        name=f"rclone/{remote}",
        healthy=False,
        days_remaining=None,
        severity="p0",
        title=f"rclone {remote} credential failure",
        message=message,
    )


def collect_expiry_statuses(
    *,
    rclone_remotes: Sequence[str] = ("gdrive",),
    now: datetime | None = None,
    run: Runner | None = None,
) -> list[CredentialExpiry]:
    statuses: list[CredentialExpiry] = []
    ts = probe_tailscale_node_key(now=now, run=run)
    if ts is not None:
        statuses.append(ts)
    for remote in rclone_remotes:
        statuses.append(probe_rclone_remote(remote, run=run))
    return statuses


def route_expiry_alerts(
    statuses: Sequence[CredentialExpiry], *, intake_run: Runner | None = None
) -> list[str]:
    """Route warn/p0 statuses through the governed P0 intake (coalesced, one task per
    credential). Returns the names routed. Best-effort -- a routing failure never raises."""
    intake_run = intake_run or _default_run
    routed: list[str] = []
    for status in statuses:
        if status.severity == "ok":
            continue
        priority = "urgent" if status.severity == "p0" else "high"
        try:
            proc = intake_run(
                [
                    str(_INTAKE),
                    "notification",
                    "--title",
                    status.title,
                    "--message",
                    status.message,
                    "--technical",
                    "--priority",
                    priority,
                    "--tag",
                    "key",
                    # emit a visible desktop bubble too, not just the coalesced P0 task --
                    # a dying credential should be SEEN, not only filed.
                    "--desktop-confirmation",
                ]
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        # Only count as routed when the intake actually SUCCEEDED; a nonzero exit means
        # the alert did not land, so it must not be reported as routed.
        if getattr(proc, "returncode", 1) == 0:
            routed.append(status.name)
    return routed
