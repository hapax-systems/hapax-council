"""Measure what hardware and devices exist on which host, across the whole estate.

Every existing inventory instrument on this estate is HOST-SCOPED: it reports the machine it
runs on. ``hapax-host-storage-inventory`` says so in its own docstring. Nothing enumerates the
estate, so every answer about "the system" is silently an answer about whichever host you
happened to be sitting on -- and it is presented, and read, as an estate answer.

That is not a hypothetical. Measured on 2026-08-11/12, all three of these were asserted
confidently and all three were wrong about the host rather than the fact:

* "the estate has no RTX 5090" -- it does, on podium; appendix has a 3090.
* "there are no video devices" -- there are eight, on podium; appendix has none.
* "the audio/perception stack is not loaded" -- not on appendix. Podium was never checked.

The correction is not a better document. Documents drift and they routinely omit the host, which
is the field that turned out to matter. The correction is a measurement that names the host on
every fact.

Two design rules, both learned expensively:

* **An unreachable host is a row, never an omission.** A collector that drops hosts it cannot
  reach returns a smaller, entirely consistent, entirely wrong inventory -- the same defect as
  ``importlib.metadata``'s ``skip_missing_files``, which silently filtered recorded-but-absent
  files out of a manifest that was then used as a completeness proof. Unreachability is a
  finding. It is recorded with its reason.
* **The host list is measured, not declared.** A hand-maintained roster is stale the first time
  a machine is added, and a machine missing from the roster is invisible rather than
  unreachable -- which is worse, because nothing reports it.

Read-only throughout: no remote command here mutates anything.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

#: Remote probes are short. A host that cannot answer this fast is a finding, not something to
#: wait on -- the collector must stay fast enough that people actually run it.
SSH_TIMEOUT_SECONDS = 12
TAILSCALE_TIMEOUT_SECONDS = 15

#: One shell pipeline per host. Every command is read-only. Fields are emitted as `key=value`
#: lines so a partial answer from a degraded host still parses -- an all-or-nothing payload
#: would turn one missing tool into a fully unknown host.
PROBE = r"""
echo "hostname=$(hostname 2>/dev/null)"
echo "product=$(cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null || cat /proc/device-tree/model 2>/dev/null | tr -d '\0')"
echo "cpus=$(nproc 2>/dev/null)"
echo "mem_gb=$(free -g 2>/dev/null | awk '/^Mem:/{print $2}')"
echo "kernel=$(uname -r 2>/dev/null)"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null \
    | sed 's/^/gpu=/'
fi
for d in /dev/video*; do [ -e "$d" ] && echo "video=$d"; done
echo "v4l_by_id=$(ls /dev/v4l/by-id/ 2>/dev/null | wc -l)"
echo "running_units=$(systemctl --user list-units --state=running --no-legend --no-pager 2>/dev/null | wc -l)"
echo "uptime_s=$(cut -d. -f1 /proc/uptime 2>/dev/null)"
for ip in $(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}'); do echo "ipv4=$ip"; done
"""


class InventoryUnavailable(RuntimeError):
    """The host roster itself could not be measured. Refuse rather than guess a roster."""


@dataclass
class HostFacts:
    """One host. ``reachable=False`` rows are kept: absence of data is the datum."""

    tailnet_name: str
    tailnet_ip: str = ""
    os: str = ""
    tags: list[str] = field(default_factory=list)
    tailnet_online: bool = False
    reachable: bool = False
    unreachable_reason: str = ""
    hostname: str = ""
    product: str = ""
    cpus: int = 0
    mem_gb: int = 0
    kernel: str = ""
    gpus: list[str] = field(default_factory=list)
    video_devices: list[str] = field(default_factory=list)
    v4l_by_id_count: int = 0
    running_units: int = 0
    uptime_seconds: int = 0
    ipv4: list[str] = field(default_factory=list)


def tailnet_hosts() -> list[dict[str, object]]:
    """The roster, measured from the tailnet.

    Refuses rather than falling back to a hardcoded list: a wrong roster produces an inventory
    that looks complete, which is the failure this module exists to prevent.
    """
    if shutil.which("tailscale") is None:
        raise InventoryUnavailable(
            "tailscale is not installed; the host roster cannot be measured. "
            "Refusing rather than assuming a roster -- an assumed roster silently omits hosts."
        )
    try:
        raw = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=TAILSCALE_TIMEOUT_SECONDS,
            check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        raise InventoryUnavailable(f"tailscale status failed: {exc}") from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise InventoryUnavailable(f"tailscale status returned unparseable JSON: {exc}") from exc

    rows: list[dict[str, object]] = []
    for node in [payload.get("Self") or {}, *(payload.get("Peer") or {}).values()]:
        name = node.get("HostName") or ""
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "ip": (node.get("TailscaleIPs") or [""])[0],
                "os": node.get("OS") or "",
                "tags": [t.replace("tag:", "") for t in (node.get("Tags") or [])],
                "online": bool(node.get("Online")),
            }
        )
    return sorted(rows, key=lambda r: str(r["name"]).lower())


def _parse_probe(text: str, facts: HostFacts) -> None:
    for line in text.splitlines():
        key, _, value = line.partition("=")
        value = value.strip()
        if not value:
            continue
        if key == "hostname":
            facts.hostname = value
        elif key == "product":
            facts.product = value
        elif key == "cpus" and value.isdigit():
            facts.cpus = int(value)
        elif key == "mem_gb" and value.isdigit():
            facts.mem_gb = int(value)
        elif key == "kernel":
            facts.kernel = value
        elif key == "gpu":
            facts.gpus.append(value)
        elif key == "video":
            facts.video_devices.append(value)
        elif key == "v4l_by_id" and value.isdigit():
            facts.v4l_by_id_count = int(value)
        elif key == "running_units" and value.isdigit():
            facts.running_units = int(value)
        elif key == "uptime_s" and value.isdigit():
            facts.uptime_seconds = int(value)
        elif key == "ipv4":
            facts.ipv4.append(value)


def probe_host(
    row: dict[str, object],
    *,
    runner: object = None,
    self_name: str = "",
) -> HostFacts:
    """Collect one host's facts. Never raises: an unreachable host is a populated row."""
    name = str(row["name"])
    facts = HostFacts(
        tailnet_name=name,
        tailnet_ip=str(row.get("ip") or ""),
        os=str(row.get("os") or ""),
        tags=list(row.get("tags") or []),
        tailnet_online=bool(row.get("online")),
    )

    if str(row.get("os") or "") != "linux":
        facts.unreachable_reason = f"not probed: os={row.get('os') or 'unknown'!s}"
        return facts

    target = name if name != self_name else ""
    argv = (
        ["bash", "-c", PROBE]
        if not target
        else [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={SSH_TIMEOUT_SECONDS // 2}",
            "-o",
            "StrictHostKeyChecking=accept-new",
            target,
            PROBE,
        ]
    )

    run = runner if callable(runner) else subprocess.run
    try:
        result = run(
            argv,
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        facts.unreachable_reason = f"{type(exc).__name__}: {exc}"
        return facts

    if result.returncode != 0 and not result.stdout.strip():
        detail = (result.stderr or "").strip().splitlines()
        facts.unreachable_reason = detail[-1][:160] if detail else f"exit {result.returncode}"
        return facts

    _parse_probe(result.stdout, facts)
    facts.reachable = bool(facts.hostname)
    if not facts.reachable and not facts.unreachable_reason:
        facts.unreachable_reason = "probe returned no hostname"
    return facts


def collect(*, runner: object = None, self_name: str = "") -> dict[str, object]:
    """Measure the whole estate. Unreachable hosts are present with a reason."""
    rows = tailnet_hosts()
    hosts = [probe_host(row, runner=runner, self_name=self_name) for row in rows]
    return {
        "schema": "hapax.estate_host_inventory.v1",
        "collected_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "collected_from": self_name,
        "host_count": len(hosts),
        "reachable_count": sum(1 for h in hosts if h.reachable),
        "unreachable": [h.tailnet_name for h in hosts if not h.reachable],
        "hosts": [asdict(h) for h in hosts],
    }


def _gpu_short(gpu: str) -> str:
    mib = re.search(r"(\d+)\s*MiB", gpu)
    name = re.sub(r"NVIDIA GeForce |NVIDIA ", "", gpu.split(",")[0]).strip()
    return f"{name} {int(mib.group(1)) // 1024}G" if mib else name


def render(inventory: dict[str, object]) -> str:
    """Human table. Unreachable hosts render as rows so they cannot be skimmed past."""
    lines = [
        f"estate host inventory — {inventory['collected_at']} "
        f"(from {inventory['collected_from'] or 'local'})",
        f"{inventory['reachable_count']}/{inventory['host_count']} reachable",
        "",
        f"{'HOST':<18} {'CPU':>4} {'RAM':>6} {'VID':>4} {'UNITS':>6}  GPUS / REASON",
    ]
    for host in inventory["hosts"]:  # type: ignore[index]
        if not host["reachable"]:
            lines.append(
                f"{host['tailnet_name']:<18} {'—':>4} {'—':>6} {'—':>4} {'—':>6}  "
                f"UNREACHABLE: {host['unreachable_reason'][:60]}"
            )
            continue
        gpus = ", ".join(_gpu_short(g) for g in host["gpus"]) or "—"
        lines.append(
            f"{host['tailnet_name']:<18} {host['cpus']:>4} {host['mem_gb']:>5}G "
            f"{len(host['video_devices']):>4} {host['running_units']:>6}  {gpus}"
        )
    return "\n".join(lines)


def find(inventory: dict[str, object], term: str) -> list[str]:
    """Answer "which host has X" — the question that keeps being answered wrong.

    Searches GPUs, product names and device paths. Unreachable hosts are reported as such
    rather than counted as absent, because "not found" and "not looked at" are different
    answers and conflating them is how this module's motivating errors happened.
    """
    needle = term.lower()
    hits: list[str] = []
    blind: list[str] = []
    for host in inventory["hosts"]:  # type: ignore[index]
        if not host["reachable"]:
            blind.append(str(host["tailnet_name"]))
            continue
        haystack = " ".join(
            [
                *host["gpus"],
                host["product"],
                host["hostname"],
                *host["video_devices"],
                host["kernel"],
            ]
        ).lower()
        if needle in haystack:
            hits.append(str(host["tailnet_name"]))
    if blind:
        hits.append(f"(not searched — unreachable: {', '.join(blind)})")
    return hits
