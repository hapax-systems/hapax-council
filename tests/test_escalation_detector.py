"""Tests for shared.escalation_detector — recording privilege escalation from existing logs.

A lane that can escalate can reach any credential on the host, so escalation is recorded
(it cannot be prevented here). Each test pins one escalation shape: sudo, su, pkexec and
ksu in the journal, and containers that are privileged, have added capabilities,
bind-mount host paths, or are exec'd into.
"""

from __future__ import annotations

from shared import escalation_detector as ed


def _journal(identifier: str, message: str, ts: str = "1790310000000000") -> dict[str, str]:
    return {"SYSLOG_IDENTIFIER": identifier, "MESSAGE": message, "__REALTIME_TIMESTAMP": ts}


def _inspect(
    *,
    privileged: bool = False,
    cap_add: list[str] | None = None,
    mounts: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "HostConfig": {"Privileged": privileged, "CapAdd": cap_add},
        "Mounts": mounts or [],
    }


def _event(action: str, cid: str = "c1") -> dict[str, object]:
    return {"Type": "container", "Action": action, "Actor": {"ID": cid}, "timeNano": 1}


# Journal: sudo, su, pkexec, ksu ------------------------------------------------------------------


def test_sudo_command_is_recorded():
    entries = [_journal("sudo", "lane : TTY=pts/3 ; PWD=/tmp ; USER=root ; COMMAND=/usr/bin/true")]
    findings = ed.journal_findings(entries)
    assert [(f.kind, f.subject) for f in findings] == [("sudo", "root")]
    assert findings[0].sensitive is False


def test_sudo_touching_a_sensitive_path_is_marked_sensitive():
    entries = [
        _journal(
            "sudo",
            "lane : TTY=pts/3 ; PWD=/tmp ; USER=root ; COMMAND=/usr/bin/rm /etc/claude-code/x.json",
        )
    ]
    assert ed.journal_findings(entries)[0].sensitive is True


def test_sudo_session_closed_lines_are_not_findings():
    entries = [_journal("sudo", "pam_unix(sudo:session): session closed for user root")]
    assert ed.journal_findings(entries) == []


def test_pkexec_without_any_sudo_line_is_recorded():
    entries = [
        _journal(
            "pkexec",
            "lane: Executing command [USER=root] [TTY=unknown] [CWD=/tmp] [COMMAND=/usr/bin/id]",
        )
    ]
    assert [(f.kind, f.subject) for f in ed.journal_findings(entries)] == [("pkexec", "root")]


def test_su_to_root_is_recorded():
    entries = [
        _journal(
            "su", "pam_unix(su:session): session opened for user root(uid=0) by lane(uid=1000)"
        )
    ]
    assert [(f.kind, f.subject) for f in ed.journal_findings(entries)] == [("su", "root")]


def test_su_session_closed_is_not_a_finding():
    entries = [_journal("su", "pam_unix(su:session): session closed for user root")]
    assert ed.journal_findings(entries) == []


def test_ksu_is_recorded():
    entries = [_journal("ksu", "'ksu root' authenticated lane for root on /dev/pts/1")]
    assert [f.kind for f in ed.journal_findings(entries)] == ["ksu"]


def test_unrelated_journal_lines_are_ignored():
    assert ed.journal_findings([_journal("systemd", "Started foo.service.")]) == []


# Containers: privileged, added capabilities, host bind mounts, exec ------------------------------


def test_host_root_bind_mount_is_a_risk():
    risk = ed.container_risk(
        _inspect(mounts=[{"Type": "bind", "Source": "/", "Destination": "/host"}])
    )
    assert risk == ["host-mount:/"]


def test_privileged_container_is_a_risk():
    assert ed.container_risk(_inspect(privileged=True)) == ["privileged"]


def test_cap_add_without_privileged_is_a_risk():
    assert ed.container_risk(_inspect(cap_add=["SYS_ADMIN"])) == ["cap-add:SYS_ADMIN"]


def test_ordinary_container_is_not_a_risk():
    mounts = [
        {"Type": "volume", "Source": "/var/lib/docker/volumes/x/_data", "Destination": "/data"}
    ]
    assert ed.container_risk(_inspect(mounts=mounts)) == []


def test_bind_mount_of_a_non_sensitive_host_directory_is_not_a_risk():
    mounts = [{"Type": "bind", "Source": "/srv/cache", "Destination": "/cache"}]
    assert ed.container_risk(_inspect(mounts=mounts)) == []


def test_creating_an_escalated_container_is_recorded():
    inspect = {"c1": _inspect(privileged=True)}
    findings = ed.docker_findings([_event("create")], inspect)
    assert [(f.kind, f.subject) for f in findings] == [("container_escalated", "c1")]


def test_exec_into_a_privileged_container_is_recorded():
    inspect = {"c1": _inspect(privileged=True)}
    findings = ed.docker_findings([_event("exec_start: sh")], inspect)
    assert [f.kind for f in findings] == ["exec_into_escalated_container"]


def test_exec_into_a_host_mounted_container_is_recorded():
    inspect = {"c1": _inspect(mounts=[{"Type": "bind", "Source": "/etc", "Destination": "/e"}])}
    findings = ed.docker_findings([_event("exec_create: sh")], inspect)
    assert [f.kind for f in findings] == ["exec_into_escalated_container"]
    assert findings[0].sensitive is True


def test_exec_into_an_ordinary_container_is_not_recorded():
    assert ed.docker_findings([_event("exec_start: sh")], {"c1": _inspect()}) == []


def _with_healthcheck(test: list[str]) -> dict[str, object]:
    inspect = _inspect(mounts=[{"Type": "bind", "Source": "/etc", "Destination": "/e"}])
    inspect["Config"] = {"Healthcheck": {"Test": test}}
    return inspect


def test_the_containers_own_shell_healthcheck_is_not_recorded():
    inspect = {"c1": _with_healthcheck(["CMD-SHELL", "pg_isready -U postgres"])}
    events = [_event("exec_create: /bin/sh -c pg_isready -U postgres")]
    events.append(_event("exec_start: /bin/sh -c pg_isready -U postgres"))
    assert ed.docker_findings(events, inspect) == []


def test_the_containers_own_exec_form_healthcheck_is_not_recorded():
    inspect = {"c1": _with_healthcheck(["CMD", "curl", "-f", "http://localhost/health"])}
    events = [_event("exec_start: curl -f http://localhost/health")]
    assert ed.docker_findings(events, inspect) == []


def test_an_exec_that_only_contains_the_healthcheck_command_is_recorded():
    inspect = {"c1": _with_healthcheck(["CMD-SHELL", "pg_isready -U postgres"])}
    events = [_event("exec_start: /bin/sh -c pg_isready -U postgres; id")]
    assert [f.kind for f in ed.docker_findings(events, inspect)] == [
        "exec_into_escalated_container"
    ]


def test_a_healthcheck_command_run_in_another_container_is_recorded():
    inspect = {
        "c1": _with_healthcheck(["CMD-SHELL", "pg_isready -U postgres"]),
        "c2": _inspect(privileged=True),
    }
    events = [_event("exec_start: /bin/sh -c pg_isready -U postgres", cid="c2")]
    assert [f.subject for f in ed.docker_findings(events, inspect)] == ["c2"]


def test_container_without_inspect_data_is_recorded_as_unknown_not_skipped():
    findings = ed.docker_findings([_event("create", cid="gone")], {})
    assert [(f.kind, f.subject) for f in findings] == [("container_uninspectable", "gone")]
