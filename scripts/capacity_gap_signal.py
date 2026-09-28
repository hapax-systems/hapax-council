"""Read-only capacity discovery and gap judgement; one state file and lanebus mail.

V1 consumes the installed capacity observer and live, zero-spend probes. It does not
claim that a free GPU is an idle service: only a request counter window does that.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

OBSERVER_PERIOD = timedelta(minutes=20)
CYCLE = timedelta(minutes=15)
STALE_AFTER = OBSERVER_PERIOD * 2
REQUEST_WINDOW = timedelta(minutes=15)
PORT_RE = re.compile(r"(?<!\d)(?:--port[= ]|localhost:|127\.0\.0\.1:|['\"])(\d{4,5})(?!\d)")
RUNTIME_PORT_RE = re.compile(r"(?:--port[= ]|:[ ]?|^)(\d{4,5})(?:/tcp|\b)")
ROUTE_ENDPOINT_RE = re.compile(r"https?://[A-Za-z0-9.-]+:(\d{4,5})")
PARALLEL_RE = re.compile(r"(?:--tensor-parallel-size[= ]|VLLM_TENSOR_PARALLEL_SIZE[^\d]*)(\d+)")
MODEL_RE = re.compile(r"(?:/models/|--model[= ])([A-Za-z0-9_.-]+)")
HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,99}")
METRIC_RE = re.compile(r"^vllm:request_success_total(?:\{[^}]*\})?\s+([\d.]+)$")
GPU_MEMORY_RE = re.compile(r"(?im)^.*(?:nvidia|geforce|rtx).*?,\s*(\d+) MiB,\s*(\d+) MiB\s*$")
FUGU_RESET_RE = re.compile(
    r"Try again at ([A-Za-z]{3}) (\d+)(?:st|nd|rd|th), (\d{4}) (\d{1,2}):(\d{2}) (AM|PM)"
)
OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
FEATHERLESS_MODELS = "https://api.featherless.ai/v1/models"


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def stamp(now: datetime) -> str:
    return now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_observations(path: Path, now: datetime) -> list[dict[str, Any]]:
    """Read the recent tail; malformed lines cannot turn stale input into healthy input."""
    if not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            try:
                row = json.loads(line)
                if isinstance(row, dict) and isinstance(row.get("ts"), str):
                    at = instant(row["ts"])
                    if now - timedelta(hours=2) <= at <= now + timedelta(minutes=2):
                        rows.append(row)
            except (ValueError, TypeError):
                continue
    return rows[-8:]


def observer_stale(observations: list[dict[str, Any]], now: datetime) -> bool:
    return not observations or now - instant(observations[-1]["ts"]) > STALE_AFTER


@dataclass
class Inventory:
    ports: set[int] = field(default_factory=set)
    sources: list[str] = field(default_factory=list)
    parallel_sizes: dict[str, int] = field(default_factory=dict)


def inventory_repo(root: Path) -> Inventory:
    """Scan the whole source tree for unit/compose endpoint declarations each run."""
    inventory = Inventory()
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = [
            name for name in subdirs if not name.startswith(".") and name != "node_modules"
        ]
        for name in files:
            path = Path(directory) / name
            if path.suffix not in {".service", ".yaml", ".yml"}:
                continue
            if "systemd" not in path.parts and "compose" not in name:
                continue
            try:
                raw = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            ports = {int(m) for m in PORT_RE.findall(raw) if 1024 <= int(m) <= 65535}
            if not ports and not PARALLEL_RE.search(raw):
                continue
            inventory.sources.append(str(path.relative_to(root)))
            inventory.ports.update(ports)
            size = PARALLEL_RE.search(raw)
            if size:
                service = path.stem
                if "compose" in name:
                    match = re.search(r"(?m)^\s{2}([A-Za-z0-9_-]+):\s*$", raw)
                    if match:
                        service = match.group(1)
                inventory.parallel_sizes[service] = int(size.group(1))
    return inventory


def run(command: list[str], timeout: int = 8) -> str:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def tailnet_devices() -> tuple[set[str], set[str]]:
    raw = run(["tailscale", "status", "--json"], 8)
    if not raw:
        return set(), set()
    try:
        record = json.loads(raw)
    except ValueError:
        return set(), set()
    online, all_hosts = set(), set()
    for item in [record.get("Self", {}), *record.get("Peer", {}).values()]:
        host = str(item.get("HostName") or "").lower()
        if not HOST_RE.fullmatch(host):
            continue
        all_hosts.add(host)
        if item.get("Online", True):
            online.add(host)
    return online, all_hosts


def host_runtime(host: str) -> str:
    """Inspect units, containers and processes; no mutation and no model invocation."""
    if not HOST_RE.fullmatch(host):
        return ""
    command = (
        "systemctl --user list-units --type=service --state=running --no-legend 2>/dev/null; "
        "docker ps --format '{{.Names}} {{.Image}} {{.Ports}} {{.Command}}' 2>/dev/null; "
        "ps -eo args 2>/dev/null | grep -E 'vllm|llama-server|ray::|torchrun' | grep -v grep; "
        "nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader 2>/dev/null; "
        "cat /proc/device-tree/model 2>/dev/null; true"
    )
    return run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", host, command], 9)


def runtime_membership(runtime: dict[str, str], answering: set[str]) -> dict[str, set[str]]:
    """Join hosts on a process/model signature; never infer a member is its own API."""
    signatures: dict[str, set[str]] = defaultdict(set)
    for host, output in runtime.items():
        for model in MODEL_RE.findall(output):
            signatures[model.lower()].add(host)
    members: dict[str, set[str]] = {}
    for endpoint in answering:
        host = endpoint.split(":", 1)[0]
        owners = {host}
        host_signatures = set(MODEL_RE.findall(runtime.get(host, "")))
        for signature in host_signatures:
            owners.update(signatures[signature.lower()])
        members[endpoint] = owners
    return members


def probe_endpoint(host: str, port: int) -> tuple[str, dict[str, Any]]:
    key = f"{host}:{port}"
    try:
        with urllib.request.urlopen(f"http://{key}/v1/models", timeout=2) as response:
            payload = json.load(response)
        models = [
            str(item["id"])
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
        if not models:
            return key, {"answering": False, "models": [], "requests": []}
        counter = None
        try:
            with urllib.request.urlopen(f"http://{key}/metrics", timeout=2) as response:
                metrics = response.read(2_000_000).decode("utf-8", "replace")
            values = [
                float(m.group(1)) for line in metrics.splitlines() if (m := METRIC_RE.match(line))
            ]
            if values:
                counter = sum(values)
        except (OSError, ValueError, urllib.error.URLError):
            pass
        return key, {"answering": True, "models": models, "counter": counter, "requests": []}
    except (OSError, ValueError, urllib.error.URLError):
        return key, {"answering": False, "models": [], "requests": []}


def classify_local(
    observations: list[dict[str, Any]],
    members: dict[str, set[str]],
    endpoints: dict[str, dict[str, Any]],
    now: datetime,
) -> dict[str, str]:
    """Request deltas decide idleness; GPU samples only describe resource headroom."""
    del observations, members
    states = {}
    for key, endpoint in endpoints.items():
        if not endpoint.get("answering"):
            states[key] = "lost"
            continue
        requests = endpoint.get("requests") or []
        if len(requests) < 2:
            states[key] = "unknown"
            continue
        first_at, first_count = requests[0]
        last_at, last_count = requests[-1]
        if last_at - first_at < REQUEST_WINDOW or now - last_at > CYCLE * 2:
            states[key] = "unknown"
        elif last_count > first_count:
            states[key] = "busy"
        elif last_count == first_count:
            states[key] = "idle"
        else:
            states[key] = "unknown"  # restarted counter
    return states


def unserved_metal(
    observations: list[dict[str, Any]],
    runtime: dict[str, str],
    members: dict[str, set[str]],
    now: datetime,
) -> set[str]:
    """Two fresh observations and no serving process identify an unserved GPU host."""
    if len(observations) < 2:
        return set()
    first, last = observations[0], observations[-1]
    if (
        now - instant(last["ts"]) > STALE_AFTER
        or instant(last["ts"]) - instant(first["ts"]) < REQUEST_WINDOW
    ):
        return set()
    present = set(first.get("fleet_memory") or {}) & set(last.get("fleet_memory") or {})
    serving_hosts = set().union(*members.values()) if members else set()

    def has_headroom(host: str) -> bool:
        memory = GPU_MEMORY_RE.search(runtime.get(host, ""))
        return bool(
            memory
            and int(memory.group(1)) > 0
            and int(memory.group(2)) / int(memory.group(1)) < 0.2
        )

    return {
        host
        for host in present - serving_hosts
        if first["fleet_memory"].get(host)
        and last["fleet_memory"].get(host)
        and has_headroom(host)
        and not re.search(r"(?i)vllm|llama-server|torchrun|ray::", runtime.get(host, ""))
    }


@dataclass
class Demand:
    waiting_rows: list[str] = field(default_factory=list)
    walled_rows: dict[str, list[str]] = field(default_factory=dict)
    review_queue: int = 0
    writer_queue: int = 0
    appliance_queue: int = 0


def waiting_demand(rows: list[dict[str, Any]], walled_families: set[str]) -> Demand:
    demand = Demand()
    for row in rows:
        task_id = str(row.get("task_id") or "")
        if not task_id:
            continue
        status = str(row.get("status") or "")
        assigned = str(row.get("assigned_to") or "").lower()
        if status == "offered" or (
            assigned not in {"", "unassigned", "none"} and status in {"assigned", "offered"}
        ):
            demand.waiting_rows.append(task_id)
        for family in walled_families:
            if family in assigned and status not in {"done", "closed", "cancelled", "abandoned"}:
                demand.walled_rows.setdefault(family, []).append(task_id)
    return demand


def read_tasks(active: Path) -> list[dict[str, Any]]:
    rows = []
    for path in active.glob("*.md"):
        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.startswith("---\n"):
                continue
            block = raw.split("\n---", 1)[0][4:]
            data = yaml.safe_load(block)
            if isinstance(data, dict) and data.get("type") == "cc-task":
                rows.append(data)
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
    return rows


def registration_gaps(discovered: set[str], registered: set[str], answering: set[str]) -> set[str]:
    return {f"UNREGISTERED:{name}" for name in discovered - registered if name in answering}


def judge_gaps(states: dict[str, str], demand: Demand, registered: set[str]) -> set[str]:
    del registered
    gaps = set()
    count = (
        len(demand.waiting_rows)
        + demand.review_queue
        + demand.writer_queue
        + demand.appliance_queue
    )
    for key, state in states.items():
        if state == "idle" and count:
            gaps.add(f"IDLE_WITH_DEMAND:{key}:waiting={count}:fit=unmeasured")
        elif state == "unserved" and count:
            gaps.add(f"UNSERVED_METAL_WITH_DEMAND:{key}:waiting={count}:fit=unmeasured")
        elif state == "lost":
            gaps.add(f"LOST:{key}")
        elif state == "walled" and demand.walled_rows.get(key):
            gaps.add(f"WALLED_WITH_DEMAND:{key}:rows={len(demand.walled_rows[key])}")
    return gaps


def _state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as out:
        json.dump(state, out, sort_keys=True)
        out.write("\n")
        temp = Path(out.name)
    os.replace(temp, path)


def deliver(
    gaps: set[str],
    state_path: Path,
    inbox: Path,
    now: datetime,
    detail: str = "",
    recipient: str = "dev1-seat",
) -> bool:
    """Mail changed gaps or a persistent set every 30 min; never mail a clear set."""
    state = _state(state_path)
    previous = set(state.get("gaps") or [])
    last = instant(state["last_mail_at"]) if state.get("last_mail_at") else None
    should_mail = bool(gaps) and (
        gaps != previous or last is None or now - last >= timedelta(minutes=30)
    )
    if should_mail:
        inbox.mkdir(parents=True, exist_ok=True)
        name = now.strftime("%Y%m%dT%H%M%SZ") + "-capacity-gap-signal.md"
        path = inbox / name
        with path.open("x", encoding="utf-8") as mail:
            mail.write(
                f"---\nfrom: capacity-gap-signal\nto: {recipient}\ncreated_at: {stamp(now)}\nthread: capacity-gap-signal\nack: false\n---\n\n# Capacity gaps\n\n"
            )
            for item in sorted(gaps):
                mail.write(f"- {item}\n")
            if detail:
                mail.write(f"\n{detail}\n")
        state["last_mail_at"] = stamp(now)
    state["gaps"] = sorted(gaps)
    state["status_line"] = f"capacity-gap {stamp(now)} gaps={len(gaps)} " + (
        ", ".join(sorted(gaps)[:3]) if gaps else "clear"
    )
    _write_state(state_path, state)
    print(state["status_line"])
    return should_mail


def _subscribed_state(ledger_path: Path, now: datetime) -> dict[str, str]:
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        if now - instant(ledger["captured_at"]) > CYCLE * 2:
            return {}
    except (OSError, ValueError, KeyError):
        return {}
    states = {}
    for item in ledger.get("quota_snapshots") or []:
        route = str(item.get("route_id") or "")
        value = str(item.get("subscription_quota_state") or "unknown")
        until = item.get("fresh_until")
        if until:
            try:
                if instant(str(until)) < now:
                    value = "unknown"
            except ValueError:
                value = "unknown"
        states[route.split(".", 1)[0]] = (
            "walled"
            if value in {"exhausted", "walled"}
            else "unknown"
            if value == "unknown"
            else "available"
        )
    return states


def codex_headroom(sessions_root: Path, now: datetime) -> tuple[str, str]:
    """Read the newest transcript quota event, with no model invocation."""
    paths = sorted(
        sessions_root.glob("*/*/*/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for path in paths[:8]:
        if now.timestamp() - path.stat().st_mtime > 3600:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines[-1000:]):
            try:
                event = json.loads(line)
                limits = event.get("payload", {}).get("rate_limits") or {}
                primary = limits.get("primary") or {}
                used = float(primary["used_percent"])
                reset = datetime.fromtimestamp(int(primary["resets_at"]), UTC)
            except (ValueError, TypeError, KeyError, OverflowError):
                continue
            wall = limits.get("rate_limit_reached_type") or used >= 100
            return (
                "walled" if wall else "available",
                f"codex headroom={max(0, 100 - used):.1f}% reset={stamp(reset)}",
            )
    return "unknown", "codex headroom=unknown"


def fetch_catalogue(url: str) -> dict[str, Any] | None:
    """GET metadata only. No completion endpoint or credential is used."""
    request = urllib.request.Request(url, headers={"User-Agent": "hapax-capacity-gap-signal/1"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read(16_000_000))
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def catalogue_capabilities(catalogues: dict[str, dict[str, Any] | None]) -> dict[str, str]:
    states = {"space-bunny": "unknown", "featherless": "unknown"}
    openrouter = catalogues.get(OPENROUTER_MODELS) or {}
    for item in openrouter.get("data") or []:
        if not isinstance(item, dict) or item.get("id") != "stealth/space-bunny-alpha":
            continue
        pricing = item.get("pricing") or {}
        try:
            states["space-bunny"] = (
                "price0"
                if Decimal(str(pricing["prompt"])) == 0 and Decimal(str(pricing["completion"])) == 0
                else "priced"
            )
        except (KeyError, InvalidOperation, TypeError):
            states["space-bunny"] = "unknown"
        break
    featherless = catalogues.get(FEATHERLESS_MODELS) or {}
    models = featherless.get("data") or []
    if isinstance(models, list) and models:
        states["featherless"] = f"available:{len(models)}"
    return states


def fugu_panes() -> dict[str, str]:
    names = run(["tmux", "ls", "-F", "#{session_name}"], 5).splitlines()
    return {
        name: run(["tmux", "capture-pane", "-pt", name, "-S", "-40"], 5)
        for name in names
        if name.startswith("hapax-fugu-")
    }


def fugu_wall(panes: dict[str, str], now: datetime) -> tuple[str, str | None]:
    resets = []
    for pane in panes.values():
        if "usage limit" not in pane.lower():
            continue
        match = FUGU_RESET_RE.search(pane)
        if not match:
            continue
        month, day, year, hour, minute, ampm = match.groups()
        try:
            local = datetime.strptime(
                f"{month} {day} {year} {hour}:{minute} {ampm}", "%b %d %Y %I:%M %p"
            )
            reset = local.replace(
                tzinfo=ZoneInfo(os.environ.get("HAPAX_CAPACITY_PANE_TZ", "America/Chicago"))
            ).astimezone(UTC)
        except ValueError:
            continue
        if reset > now:
            resets.append(reset)
    return ("walled", stamp(max(resets))) if resets else ("unknown", None)


def _claude_pace(repo: Path) -> tuple[str, str] | None:
    raw = run(["python", str(repo / "scripts/hapax-claude-pool-pace"), "status", "--json"], 25)
    try:
        data = json.loads(raw)
        if data.get("over_line") and data.get("weekly_used_percent") is not None:
            return (
                "OVER_PACE:claude",
                f"Claude weekly used={data['weekly_used_percent']}%, pacing line={data['line_percent']}%, reset={data.get('weekly_resets_at', 'unknown')}",
            )
    except (ValueError, KeyError):
        pass
    return None


def _pr_demand() -> tuple[int, int]:
    raw = run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            "hapax-systems/hapax-council",
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,isDraft,reviewDecision,mergeStateStatus",
        ],
        12,
    )
    try:
        prs = json.loads(raw)
        review = sum(not pr.get("isDraft") and pr.get("reviewDecision") != "APPROVED" for pr in prs)
        writer = sum(pr.get("mergeStateStatus") == "DIRTY" for pr in prs)
        return review, writer
    except (ValueError, TypeError):
        return 0, 0


def _appliance_demand(bus: Path) -> int:
    kit = bus / "mimo-talus/kit"
    manifest = kit / "MANIFEST-v2.json"
    ledger = kit / "LEDGER-v2.md"
    if manifest.is_file() and ledger.is_file():
        try:
            total = int(json.loads(manifest.read_text(encoding="utf-8"))["count"])
            done = {
                fields[0]
                for line in ledger.read_text(encoding="utf-8").splitlines()
                if (fields := [field.strip() for field in line.strip("|").split("|")])
                and len(fields) >= 2
                and fields[0].isdigit()
                and fields[1] == "DONE"
            }
            return max(0, total - len(done))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    inbox = bus / "mimo"
    return sum(not (inbox / "read" / path.name).exists() for path in inbox.glob("*.md"))


def seat_role(seat_document: Path) -> tuple[str, str]:
    """Resolve §0 at send time; refuse an unreadable or ambiguous seat."""
    raw = seat_document.read_text(encoding="utf-8")
    section = raw.split("## 0. Incumbent and lease", 1)[1].split("## 1.", 1)[0]
    match = re.search(r"(?m)^\| incumbent \|[^\n]*?role `([^`]+)`", section)
    if not match:
        raise ValueError(f"seat incumbent role missing in {seat_document}")
    role = match.group(1)
    if not HOST_RE.fullmatch(role):
        raise ValueError(f"invalid seat role in {seat_document}")
    return role, role.removesuffix("-seat")


def cycle(args: argparse.Namespace, now: datetime) -> set[str]:
    state = _state(args.state)
    observations = load_observations(args.observer, now)
    stale = observer_stale(observations, now)
    repo_inventory = inventory_repo(args.repo)
    online, tailnet = tailnet_devices()
    ports = set(repo_inventory.ports)
    if args.routing.is_file():
        ports.update(
            int(port)
            for port in ROUTE_ENDPOINT_RE.findall(args.routing.read_text(encoding="utf-8"))
        )
    for row in observations[-1:]:
        ports.update(int(p) for p in row.get("local_endpoints", {}) if str(p).isdigit())
    ports = {p for p in ports if 1024 <= p <= 65535}
    hosts = online | {str(h) for row in observations[-1:] for h in row.get("fleet_memory", {})}
    hosts = {host for host in hosts if HOST_RE.fullmatch(host)}
    with ThreadPoolExecutor(max_workers=12) as pool:
        runtime_values = list(pool.map(host_runtime, sorted(hosts)))
    runtime = dict(zip(sorted(hosts), runtime_values, strict=True))
    for output in runtime.values():
        ports.update(int(port) for port in RUNTIME_PORT_RE.findall(output))
    ports = {port for port in ports if 1024 <= port <= 65535}
    with ThreadPoolExecutor(max_workers=12) as pool:
        probes = list(
            pool.map(
                lambda hp: probe_endpoint(*hp),
                [(h, p) for h in sorted(online) for p in sorted(ports)],
            )
        )
    endpoints = dict(probes)
    answering = {key for key, item in endpoints.items() if item.get("answering")}
    members = runtime_membership(runtime, answering)
    last_counters = state.get("request_counters") or {}
    request_counters = {}
    for key, item in endpoints.items():
        count = item.get("counter")
        if count is None:
            continue
        older = last_counters.get(key)
        if isinstance(older, list) and len(older) == 2:
            try:
                item["requests"] = [(instant(older[0]), float(older[1])), (now, count)]
            except (ValueError, TypeError):
                pass
        request_counters[key] = [stamp(now), count]
    states = classify_local(observations, members, endpoints, now)
    states.update(
        {host: "unserved" for host in unserved_metal(observations, runtime, members, now)}
    )
    known = set(state.get("known_endpoints") or [])
    states = {key: value for key, value in states.items() if value != "lost" or key in known}
    quota = _subscribed_state(args.quota_ledger, now)
    codex_state, codex_detail = codex_headroom(args.codex_sessions, now)
    quota["codex"] = codex_state
    fugu_state, fugu_reset = fugu_wall(fugu_panes(), now)
    quota["fugu"] = fugu_state
    states.update(quota)
    rows = read_tasks(args.tasks)
    walled = {key for key, value in quota.items() if value == "walled"}
    outage = observations[-1].get("family_outage", {}) if observations else {}
    for name, value in outage.items():
        if not isinstance(value, dict) or name == "error":
            continue
        try:
            if now - instant(value["observed_at"]) <= STALE_AFTER:
                walled.add(name)
        except (KeyError, ValueError, TypeError):
            continue
    demand = waiting_demand(rows, walled)
    demand.review_queue, demand.writer_queue = _pr_demand()
    demand.appliance_queue = _appliance_demand(args.lanebus)
    registered_text = args.routing.read_text(encoding="utf-8") if args.routing.is_file() else ""
    registered = {name for name in tailnet if name in registered_text}
    discovered = {
        host
        for host in online
        if any(key.startswith(f"{host}:") for key in answering)
        or re.search(r"(?i)nvidia|jetson|vllm|llama-server|/models/", runtime.get(host, ""))
    }
    gaps = judge_gaps(states, demand, registered)
    gaps |= registration_gaps(discovered, registered, answering=discovered)
    with ThreadPoolExecutor(max_workers=2) as pool:
        catalogues = dict(
            zip(
                (OPENROUTER_MODELS, FEATHERLESS_MODELS),
                pool.map(fetch_catalogue, (OPENROUTER_MODELS, FEATHERLESS_MODELS)),
                strict=True,
            )
        )
    catalogue_states = catalogue_capabilities(catalogues)
    if (
        catalogue_states["space-bunny"] == "price0"
        and "stealth/space-bunny-alpha" not in registered_text
    ):
        gaps.add("UNREGISTERED:openrouter:stealth/space-bunny-alpha")
    elif catalogue_states["space-bunny"] == "priced":
        gaps.add("PRICE_CHANGED:openrouter:stealth/space-bunny-alpha")
    if (
        catalogue_states["featherless"].startswith("available")
        and "featherless" not in registered_text.lower()
    ):
        gaps.add("UNREGISTERED:featherless")
    if "unknown" in catalogue_states.values():
        state["catalogue_failures"] = int(state.get("catalogue_failures") or 0) + 1
        if state["catalogue_failures"] >= 2:
            gaps.add("INPUT_STALE:provider-catalogues")
    else:
        state["catalogue_failures"] = 0
    for endpoint in answering:
        if endpoint in registered_text:
            continue
        models = endpoints[endpoint].get("models") or []
        if any(model not in registered_text for model in models):
            gaps.add(f"UNREGISTERED:{endpoint}:{','.join(sorted(models))}")
    for key in known - answering:
        if key.split(":", 1)[0] in online:
            gaps.add(f"LOST:{key}")
    if stale:
        gaps.add("INPUT_STALE:capacity-observer")
    if not tailnet:
        failures = int(state.get("tailnet_failures") or 0) + 1
        state["tailnet_failures"] = failures
        if failures >= 2:
            gaps.add("INPUT_STALE:tailnet")
    else:
        state["tailnet_failures"] = 0
    pace = _claude_pace(args.repo)
    if pace:
        gaps.add(pace[0])
    for family in walled:
        if demand.walled_rows.get(family):
            gaps.add(f"WALLED_WITH_DEMAND:{family}:rows={len(demand.walled_rows[family])}")
    state["request_counters"] = request_counters
    state["known_endpoints"] = sorted(known | answering)
    _write_state(args.state, state)
    detail = f"Waiting rows: {len(demand.waiting_rows)}; review queue: {demand.review_queue}; writer queue: {demand.writer_queue}; MiMo queued work: {demand.appliance_queue}. {codex_detail}. Fugu={fugu_state}, reset={fugu_reset or 'unknown'}; Featherless={catalogue_states['featherless']}; Space Bunny={catalogue_states['space-bunny']}. {pace[1] if pace else 'Claude pace=within line or unknown'}. Endpoint fit remains unmeasured unless a work-spec profile supplies it. TP membership: {json.dumps({key: sorted(value) for key, value in members.items()}, sort_keys=True)}"
    recipient, inbox_name = seat_role(args.seat_document)
    deliver(gaps, args.state, args.lanebus / inbox_name, now, detail, recipient=recipient)
    return gaps


def main() -> int:
    home = Path.home()
    vault = home / "Documents/Personal"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--observer", type=Path, default=home / ".cache/hapax/capacity-observations.jsonl"
    )
    parser.add_argument(
        "--state", type=Path, default=home / ".cache/hapax/capacity-gap-signal-state.json"
    )
    parser.add_argument(
        "--quota-ledger",
        type=Path,
        default=home / ".cache/hapax/orchestration/quota-spend-ledger-live.json",
    )
    parser.add_argument("--codex-sessions", type=Path, default=home / ".codex/sessions")
    parser.add_argument("--tasks", type=Path, default=vault / "20-projects/hapax-cc-tasks/active")
    parser.add_argument(
        "--routing", type=Path, default=vault / "30-areas/hapax/frame/CAPABILITY-ROUTING-TABLE.md"
    )
    parser.add_argument("--lanebus", type=Path, default=vault / "30-areas/hapax/lanebus")
    parser.add_argument(
        "--seat-document", type=Path, default=vault / "30-areas/hapax/frame/COORDINATOR-SEAT.md"
    )
    args = parser.parse_args()
    cycle(args, datetime.now(UTC))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
