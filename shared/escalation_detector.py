"""Escalation detector: record privilege escalation seen in existing logs.

On a host where the processes that send outbound messages can gain root, no local check
can stop a deliberate escalation from reaching a credential. What can be done is to record
every escalation, so it is visible after the fact. This module turns journal entries and
container records into findings. It is pure: callers supply the entries (for example from
``journalctl -o json``, ``docker events`` and ``docker inspect``) and decide where the
findings go. It changes nothing on the host.

Recorded:

- journal: ``sudo`` commands, ``su`` sessions opened for another user, ``pkexec``
  executions, ``ksu`` use;
- containers: created privileged, with added capabilities, or with a bind mount of a
  sensitive host path; and any ``exec`` into such a container;
- a container that cannot be inspected is recorded as ``container_uninspectable``, never
  skipped.

A finding is ``sensitive`` when its command or mount touches a path where credentials or
permission policy live.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

SENSITIVE_PATHS: tuple[str, ...] = (
    "/etc/claude-code",
    "/etc/credstore",
    "/etc/credstore.encrypted",
    "/run/credentials",
    "/etc/sudoers",
    "/etc/sudoers.d",
    "/var/run/docker.sock",
    "/run/docker.sock",
)
# Host paths whose bind mount alone gives a container reach over the host.
SENSITIVE_MOUNT_ROOTS: tuple[str, ...] = (
    "/",
    "/etc",
    "/root",
    "/home",
    "/run",
    "/var/run",
    *SENSITIVE_PATHS,
)

_SUDO_COMMAND = re.compile(r"USER=(?P<user>\S+) ; COMMAND=(?P<command>.*)$")
_SESSION_OPENED = re.compile(r"session opened for user (?P<user>[^\s(]+)")
_PKEXEC = re.compile(
    r"Executing command \[USER=(?P<user>[^\]]+)\].*\[COMMAND=(?P<command>[^\]]*)\]"
)
_EXEC_ACTION = ("exec_create", "exec_start")


@dataclass(frozen=True)
class Finding:
    kind: str
    source: str
    subject: str
    detail: str
    sensitive: bool
    at: str


def _touches_sensitive(text: str) -> bool:
    return any(path in text for path in SENSITIVE_PATHS)


def journal_findings(entries: Iterable[Mapping[str, Any]]) -> list[Finding]:
    """Escalations by sudo, su, pkexec and ksu, from ``journalctl -o json`` entries."""
    findings: list[Finding] = []
    for entry in entries:
        ident = str(entry.get("SYSLOG_IDENTIFIER", ""))
        message = str(entry.get("MESSAGE", ""))
        at = str(entry.get("__REALTIME_TIMESTAMP", ""))
        if ident == "sudo":
            m = _SUDO_COMMAND.search(message)
            if m:
                command = m.group("command")
                findings.append(
                    Finding(
                        "sudo", "journal", m.group("user"), command, _touches_sensitive(command), at
                    )
                )
        elif ident == "su":
            m = _SESSION_OPENED.search(message)
            if m:
                findings.append(Finding("su", "journal", m.group("user"), message, False, at))
        elif ident == "pkexec":
            m = _PKEXEC.search(message)
            if m:
                command = m.group("command")
                findings.append(
                    Finding(
                        "pkexec",
                        "journal",
                        m.group("user"),
                        command,
                        _touches_sensitive(command),
                        at,
                    )
                )
        elif ident == "ksu":
            findings.append(Finding("ksu", "journal", "", message, False, at))
    return findings


def _mount_is_sensitive(source: str) -> bool:
    """The host root itself, or any path at or under one of the sensitive roots."""
    if source == "/":
        return True
    return any(
        source == root or source.startswith(root + "/")
        for root in SENSITIVE_MOUNT_ROOTS
        if root != "/"
    )


def container_risk(inspect: Mapping[str, Any]) -> list[str]:
    """Why a container (``docker inspect``) can reach the host: privileged, caps, host mounts."""
    host = inspect.get("HostConfig") or {}
    risks: list[str] = []
    if host.get("Privileged"):
        risks.append("privileged")
    risks.extend(f"cap-add:{cap}" for cap in host.get("CapAdd") or [])
    for mount in inspect.get("Mounts") or []:
        source = str(mount.get("Source", ""))
        if mount.get("Type") == "bind" and _mount_is_sensitive(source):
            risks.append(f"host-mount:{source}")
    return risks


def _is_own_healthcheck(action: str, inspect: Mapping[str, Any]) -> bool:
    """True when an exec runs exactly the container's configured healthcheck.

    Docker runs a healthcheck as an exec every interval. Its command was fixed when the container
    was created, and that creation is itself recorded, so only an exact match is excluded; an
    exec that merely contains the healthcheck command is still recorded.
    """
    test = ((inspect.get("Config") or {}).get("Healthcheck") or {}).get("Test") or []
    command = action.partition(": ")[2]
    if len(test) == 2 and test[0] == "CMD-SHELL":
        return command == f"/bin/sh -c {test[1]}"
    if len(test) >= 2 and test[0] == "CMD":
        return command == " ".join(test[1:])
    return False


def docker_findings(
    events: Iterable[Mapping[str, Any]], inspect_by_id: Mapping[str, Mapping[str, Any]]
) -> list[Finding]:
    """Container creations and execs with escalation risk (``docker events`` + ``inspect``)."""
    findings: list[Finding] = []
    for event in events:
        if event.get("Type") != "container":
            continue
        action = str(event.get("Action", ""))
        cid = str((event.get("Actor") or {}).get("ID", ""))
        at = str(event.get("timeNano", ""))
        is_exec = action.startswith(_EXEC_ACTION)
        if action != "create" and not is_exec:
            continue
        inspect = inspect_by_id.get(cid)
        if inspect is None:
            findings.append(Finding("container_uninspectable", "docker", cid, action, False, at))
            continue
        risks = container_risk(inspect)
        if not risks or (is_exec and _is_own_healthcheck(action, inspect)):
            continue
        sensitive = any(r.startswith("host-mount:") or r == "privileged" for r in risks)
        kind = "exec_into_escalated_container" if is_exec else "container_escalated"
        findings.append(Finding(kind, "docker", cid, ", ".join(risks), sensitive, at))
    return findings
