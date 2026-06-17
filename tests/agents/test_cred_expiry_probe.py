"""Deterministic coverage of the credential-expiry probes + their P0 routing."""

from __future__ import annotations

import json
import types
from datetime import UTC, datetime

from agents.hapax_cred_monitor import expiry_probe as ep


def _proc(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


_NOW = datetime(2026, 6, 17, tzinfo=UTC)


def _ts_run(days_out: int):
    from datetime import timedelta

    iso = (_NOW + timedelta(days=days_out)).isoformat().replace("+00:00", "Z")
    return lambda argv: _proc(stdout=json.dumps({"Self": {"KeyExpiry": iso}}))


def test_tailscale_key_expiry_disabled_yields_no_alert():
    # KeyExpiry null == expiry disabled in admin (the desired state) -> no alert
    assert (
        ep.probe_tailscale_node_key(
            now=_NOW, run=lambda argv: _proc(stdout=json.dumps({"Self": {"KeyExpiry": None}}))
        )
        is None
    )


def test_tailscale_key_far_out_is_ok():
    s = ep.probe_tailscale_node_key(now=_NOW, run=_ts_run(82))
    assert s is not None and s.severity == "ok" and s.days_remaining == 82


def test_tailscale_key_two_weeks_is_warn():
    s = ep.probe_tailscale_node_key(now=_NOW, run=_ts_run(10))
    assert s.severity == "warn"


def test_tailscale_key_one_week_is_p0():
    s = ep.probe_tailscale_node_key(now=_NOW, run=_ts_run(5))
    assert s.severity == "p0"


def test_tailscale_key_expired_is_p0_and_unhealthy():
    s = ep.probe_tailscale_node_key(now=_NOW, run=_ts_run(-3))
    assert s.severity == "p0" and s.healthy is False


def test_tailscale_absent_yields_none():
    assert ep.probe_tailscale_node_key(now=_NOW, run=lambda a: _proc(returncode=1)) is None


def test_rclone_healthy_is_ok():
    s = ep.probe_rclone_remote("gdrive", run=lambda a: _proc(returncode=0, stdout="Total: 1"))
    assert s.severity == "ok" and s.healthy is True


def test_rclone_invalid_grant_is_p0_with_reconnect_guidance():
    s = ep.probe_rclone_remote(
        "gdrive",
        run=lambda a: _proc(
            returncode=1, stderr="couldn't fetch token: invalid_grant: token expired"
        ),
    )
    assert s.severity == "p0" and s.healthy is False
    assert "config reconnect" in s.message and "service account" in s.message


def test_rclone_other_failure_is_p0():
    s = ep.probe_rclone_remote("gdrive", run=lambda a: _proc(returncode=1, stderr="quota exceeded"))
    assert s.severity == "p0" and "quota exceeded" in s.message


def test_route_expiry_alerts_routes_only_non_ok_with_right_priority():
    statuses = [
        ep.CredentialExpiry("ok-cred", True, 99, "ok", "t", "m"),
        ep.CredentialExpiry("warn-cred", True, 10, "warn", "t", "m"),
        ep.CredentialExpiry("dead-cred", False, None, "p0", "t", "m"),
    ]
    calls = []
    ep.route_expiry_alerts(statuses, intake_run=lambda argv: calls.append(list(argv)) or _proc())
    # ok not routed; warn -> high; p0 -> urgent
    assert len(calls) == 2
    prios = sorted(c[c.index("--priority") + 1] for c in calls)
    assert prios == ["high", "urgent"]
    assert all("--technical" in c for c in calls)


def test_route_expiry_alerts_survives_intake_failure():
    def boom(argv):
        raise OSError("intake missing")

    routed = ep.route_expiry_alerts(
        [ep.CredentialExpiry("dead", False, None, "p0", "t", "m")], intake_run=boom
    )
    assert routed == []


def test_collect_runs_tailscale_and_each_rclone_remote():
    def run(argv):
        if argv[0] == "tailscale":
            return _proc(stdout='{"Self": {"KeyExpiry": null}}')  # disabled -> no status
        return _proc(returncode=0)  # rclone healthy

    statuses = ep.collect_expiry_statuses(rclone_remotes=("gdrive", "b2"), now=_NOW, run=run)
    names = {s.name for s in statuses}
    assert names == {"rclone/gdrive", "rclone/b2"}  # tailscale disabled -> omitted
