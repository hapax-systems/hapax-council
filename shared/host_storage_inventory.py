"""host_storage_inventory — host-scoped storage identity receipts (logic).

Emits per-host storage receipts (JSON + a side-by-side Markdown rollup) so that
presence/absence/property claims are host-qualified and evidence-backed. The
2026-06-06 WD_BLACK SN7100 host-context-drift failure is made structurally hard:
every device row carries the host that produced it, absence is rendered per-host
(never bare "missing"), and a failed collector yields "not_witnessed", never
"absent".

Identity is anchored on machine-rooted, non-secret facts captured in the SAME
command stream as the device rows: hostname (uname -n) + the root-disk serial.
Kernel names (/dev/nvmeXnY) are recorded for humans but are never identity.

Read-only collectors. No secrets are read or printed (serials/UUIDs are device
identity, not secrets). Governed by host-storage-inventory-receipt-infra-20260606.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1
CACHE_DIR = Path.home() / ".cache" / "hapax" / "host-storage"
STATE_DIR = Path.home() / "hapax-state" / "storage"
ROLLUP_MD = STATE_DIR / "host-storage-rollup.md"

# Canonical machine-rooted anchors (root-disk serial), pinned per host.
# Source: host-storage-identity-contract-2026-06-06.md (canonicalized 2026-06-06).
PINNED_ROOT_SERIAL = {
    "hapax-podium": "S6WSNS0W406658B",
    "hapax-appendix": "TPBF2510310070101576",
}

HOST_ALIASES = {"hapax-appendix": "appendix", "hapax-podium": "podium"}
HOST_NORM = {"podium": "hapax-podium", "appendix": "hapax-appendix"}

# One command stream per host. Emits delimited sections so a single execution
# binds the witness (hostname + root serial) to the device rows.
PROBE = r"""
echo '===HOSTNAME==='; uname -n
echo '===LSBLK==='; lsblk -O -J 2>/dev/null || echo '{}'
echo '===BYID==='; ls -l /dev/disk/by-id 2>/dev/null | awk '{print $9, $11}' || true
echo '===PCINVME==='; (lspci -D -nn 2>/dev/null | grep -iE 'non-volatile|nvme') || true
echo '===EXIT==='
echo "lsblk=$(command -v lsblk >/dev/null && echo 0 || echo 127)"
echo "byid=$([ -d /dev/disk/by-id ] && echo 0 || echo 1)"
echo "lspci=$(command -v lspci >/dev/null && echo 0 || echo 127)"
echo '===END==='
"""


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_stream(target_host: str, transport: str, ssh_alias: str | None) -> tuple[str, int]:
    try:
        if transport == "local":
            r = subprocess.run(["bash", "-lc", PROBE], capture_output=True, text=True, timeout=60)
        else:
            r = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=10",
                    ssh_alias or target_host,
                    "bash -s",
                ],
                input=PROBE,
                capture_output=True,
                text=True,
                timeout=60,
            )
        return r.stdout, r.returncode
    except Exception as e:  # noqa: BLE001 — degrade to a receipt, never crash
        return f"===ERROR===\n{type(e).__name__}", 1


def split_sections(out: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    cur, buf = None, []
    for line in out.splitlines():
        if line.startswith("===") and line.endswith("==="):
            if cur is not None:
                sections[cur] = "\n".join(buf).strip()
            cur, buf = line.strip("="), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        sections[cur] = "\n".join(buf).strip()
    return sections


def parse_lsblk(raw: str) -> list[dict]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return []

    def fs_rows(node: dict) -> list[dict]:
        rows = []
        for ch in node.get("children", []):
            if ch.get("fstype"):
                mps = [m for m in (ch.get("mountpoints") or []) if m]
                rows.append(
                    {
                        "partition_kernel_dev": "/dev/" + ch.get("name", ""),
                        "fstype": ch.get("fstype"),
                        "label": ch.get("label"),
                        "uuid": ch.get("uuid"),
                        "partuuid": ch.get("partuuid"),
                        "mountpoints": mps,
                        "mountpoint": mps[0] if mps else None,
                    }
                )
        if node.get("fstype"):
            mps = [m for m in (node.get("mountpoints") or []) if m]
            rows.append(
                {
                    "partition_kernel_dev": "/dev/" + node.get("name", ""),
                    "fstype": node.get("fstype"),
                    "label": node.get("label"),
                    "uuid": node.get("uuid"),
                    "partuuid": node.get("partuuid"),
                    "mountpoints": mps,
                    "mountpoint": mps[0] if mps else None,
                }
            )
        return rows

    devices: list[dict] = []
    for top in data.get("blockdevices", []):
        if top.get("type") != "disk" or top.get("name", "").startswith("zram"):
            continue
        devices.append(
            {
                "presence": "present",
                "model": top.get("model"),
                "serial": top.get("serial"),
                "kernel_dev": "/dev/" + top.get("name", ""),
                "size": top.get("size"),
                "tran": top.get("tran"),
                "filesystems": fs_rows(top),
            }
        )
    return devices


def parse_byid(raw: str) -> dict[str, list[str]]:
    m: dict[str, list[str]] = {}
    for line in (raw or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and "../" in parts[-1]:
            kdev = "/dev/" + parts[-1].split("/")[-1]
            m.setdefault(kdev, []).append(parts[0])
    return m


def root_serial_from(devices: list[dict]) -> str | None:
    for d in devices:
        for fs in d.get("filesystems", []):
            if "/" in fs.get("mountpoints", []):
                return d.get("serial")
    return None


def build_receipt(
    intent_host: str, exec_host: str, transport: str, sections: dict[str, str], rc: int
) -> dict:
    evidence_host = (sections.get("HOSTNAME", "") or "").strip() or None
    devices = parse_lsblk(sections.get("LSBLK", ""))
    byid = parse_byid(sections.get("BYID", ""))
    for d in devices:
        d["by_id"] = byid.get(d.get("kernel_dev", ""), [])
    pci = [pl for pl in sections.get("PCINVME", "").splitlines() if pl.strip()]

    collectors: dict[str, dict] = {}
    for line in sections.get("EXIT", "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            collectors[k.strip()] = {"ran": v.strip() == "0", "exit_code": int(v.strip() or 127)}
    lsblk_ok = bool(collectors.get("lsblk", {}).get("ran")) and bool(devices)
    collectors.setdefault("lsblk", {})["row_count"] = len(devices)

    root_serial = root_serial_from(devices)
    pinned = PINNED_ROOT_SERIAL.get(intent_host)
    anchor_ok = evidence_host == intent_host and (pinned is None or root_serial == pinned)

    locality = "same_host" if transport == "local" else "cross_host_ssh"
    recency = "live" if lsblk_ok else "stale"
    evidence_class = (
        "live"
        if (recency == "live" and locality == "same_host")
        else ("recent" if recency == "live" else "stale")
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "receipt_kind": "host_storage_inventory",
        "host_provenance": {
            "intent_host": intent_host,
            "exec_host": exec_host,
            "evidence_host": evidence_host,
            "transport": transport,
        },
        "evidence_witness": {
            "hostname": evidence_host,
            "root_disk_serial": root_serial,
            "captured_in_same_command": True,
            "anchor_verified": bool(anchor_ok),
            "pinned_root_serial": pinned,
        },
        "hostname": evidence_host,
        "observed_at": now_iso(),
        "recency_class": recency,
        "locality_class": locality,
        "evidence_class": evidence_class,
        "generator": {"name": "hapax-host-storage-inventory", "version": "0.1.0"},
        "exit_code": rc,
        "collectors": collectors,
        "pci_nvme": pci,
        "devices": devices,
        "warnings": (
            []
            if anchor_ok
            else [
                f"anchor mismatch: evidence_host={evidence_host} root_serial={root_serial} "
                f"!= pinned {intent_host}/{pinned}"
            ]
        ),
    }


def query_serial(receipts: dict[str, dict], serial: str) -> dict[str, str]:
    """Three-state per host: present / absent / not_witnessed (never global)."""
    out: dict[str, str] = {}
    for host, r in receipts.items():
        if not (r["collectors"].get("lsblk", {}).get("ran") and r["devices"]):
            out[host] = "not_witnessed"
        else:
            out[host] = (
                "present" if any(d.get("serial") == serial for d in r["devices"]) else "absent"
            )
    return out


def render_rollup(receipts: dict[str, dict]) -> str:
    hosts = sorted(receipts)
    projects_mp = str(Path.home() / "projects")
    role_map = {
        "/": "root",
        "/store": "store",
        "/store-fast": "store-fast",
        "/data": "data",
        "/boot": "boot",
        projects_mp: "data",
    }
    out = [
        "# Host Storage Identity — Rollup",
        "",
        f"Generated `{now_iso()}` by `hapax-host-storage-inventory`. Absence is "
        "host-scoped: a blank cell where another host has content is a *per-host* "
        "absence, never global.",
        "",
    ]
    roles: dict[str, dict[str, str]] = {}
    for host, r in receipts.items():
        for d in r["devices"]:
            for fs in d.get("filesystems", []):
                for mp in fs.get("mountpoints", []):
                    if mp not in role_map:
                        continue
                    roles.setdefault(role_map[mp], {})[host] = (
                        f"{fs.get('fstype')} `{(fs.get('uuid') or '')[:13]}…` · "
                        f"{d.get('model') or ''} `{d.get('serial') or ''}` ({d.get('tran') or ''})"
                    )
    out.append("| role | " + " | ".join(f"`{h}`" for h in hosts) + " |")
    out.append("|---" * (len(hosts) + 1) + "|")
    for role in sorted(roles):
        cells = " | ".join(roles[role].get(h, "— *(not present on this host)*") for h in hosts)
        out.append(f"| `{role}` | {cells} |")
    out += ["", "## NVMe controllers (per host)", ""]
    for h in hosts:
        out.append(f"- **{h}**: {len(receipts[h].get('pci_nvme', []))} NVMe controller(s)")
    out += ["", "## Provenance", ""]
    for h in hosts:
        hp, ew, r = receipts[h]["host_provenance"], receipts[h]["evidence_witness"], receipts[h]
        out.append(
            f"- **{h}**: intent={hp['intent_host']} exec={hp['exec_host']} "
            f"evidence={hp['evidence_host']} transport={hp['transport']} "
            f"class={r['evidence_class']} anchor_ok={ew['anchor_verified']} "
            f"observed={r['observed_at']}"
        )
    return "\n".join(out) + "\n"


def collect(targets: list[str]) -> dict[str, dict]:
    local_host = subprocess.run(["uname", "-n"], capture_output=True, text=True).stdout.strip()
    receipts: dict[str, dict] = {}
    for spec in targets:
        host_id, _, alias = spec.partition(":")
        host_id = HOST_NORM.get(host_id, host_id)
        transport = "local" if host_id == local_host else "ssh"
        out, rc = run_stream(host_id, transport, alias or HOST_ALIASES.get(host_id))
        receipts[host_id] = build_receipt(host_id, local_host, transport, split_sections(out), rc)
    return receipts


def write_substrate(receipts: dict[str, dict]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for r in receipts.values():
        ts = r["observed_at"].replace(":", "").replace("-", "")
        (
            CACHE_DIR / f"{r['hostname'] or r['host_provenance']['intent_host']}-{ts}.json"
        ).write_text(json.dumps(r, indent=2))
    index = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now_iso(),
        "receipts": [
            {
                "intent_host": r["host_provenance"]["intent_host"],
                "evidence_host": r["host_provenance"]["evidence_host"],
                "evidence_class": r["evidence_class"],
                "observed_at": r["observed_at"],
                "serials": [d.get("serial") for d in r["devices"] if d.get("serial")],
            }
            for r in receipts.values()
        ],
    }
    (CACHE_DIR / "index.json").write_text(json.dumps(index, indent=2))
    rollup = render_rollup(receipts)
    ROLLUP_MD.write_text(rollup)
    (CACHE_DIR / "index.md").write_text(rollup)
    return ROLLUP_MD


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Host-scoped storage identity receipts")
    ap.add_argument("--host", action="append", default=[])
    ap.add_argument("--query-serial", default=None)
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args(argv)

    receipts = collect(args.host or ["podium", "appendix"])
    path = write_substrate(receipts)
    print(f"[rollup] {path}")
    for h, r in receipts.items():
        print(
            f"[receipt] {h}: class={r['evidence_class']} devices={len(r['devices'])} "
            f"anchor_ok={r['evidence_witness']['anchor_verified']}"
        )
    if args.query_serial:
        for h, st in query_serial(receipts, args.query_serial).items():
            print(f"{args.query_serial}: {st}_on {h}")
    if args.markdown:
        print(render_rollup(receipts))
    return 0
