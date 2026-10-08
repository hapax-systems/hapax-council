"""Carrier bindings and independent readback of the declaration's channel surface.

The fixed Linux runtime scaffold is distinguished from declared imports, but included
in the comparison: an extra mount anywhere is a discrepancy. There is no network
allowlist fiction here: network namespaces are private and egress is empty until
the separately governed gate can provide an enforceable binding.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shared.capability_envelope.declaration import EnvelopeDeclaration
    from shared.capability_envelope.render import RenderedEnvelope


def unit_properties(decl: EnvelopeDeclaration) -> tuple[str, ...]:
    unit = decl.unit
    return (
        f"MemoryHigh={unit.memory_high}",
        f"MemoryMax={unit.memory_max}",
        f"MemorySwapMax={unit.memory_swap_max}",
        f"OOMPolicy={unit.oom_policy}",
        f"RuntimeMaxSec={unit.runtime_max_sec}",
        f"Restart={unit.restart}",
        "KillMode=control-group",
    )


def _mount(kind: str, source: str, target: str, access: str = "ro") -> dict[str, str]:
    return {"kind": kind, "source": source, "target": target, "access": access}


def _declared_surface(decl: EnvelopeDeclaration, root: Path) -> dict[str, Any]:
    """Read expected mounts from typed declaration fields, never the emitted carrier."""
    from shared.capability_envelope.render import (
        _ETC_ALLOW,
        _ROOT_LINKS,
        JOB_HOME,
        JOB_HOOKS,
        JOB_SPOOL,
        JOB_WORK,
        _masks,
    )

    mounts = [_mount("bind", "/usr", "/usr")]
    links = []
    for link in _ROOT_LINKS:
        if Path(link).is_symlink():
            links.append([os.readlink(link), link])
        elif Path(link).is_dir():
            mounts.append(_mount("bind", link, link))
    mounts.extend(
        _mount("bind", f"/etc/{name}", f"/etc/{name}")
        for name in _ETC_ALLOW
        if Path(f"/etc/{name}").exists()
    )
    mounts.extend(
        [
            _mount("proc", "proc", "/proc", "rw"),
            _mount("dev", "dev", "/dev", "rw"),
            _mount("tmpfs", "tmpfs", "/tmp", "rw"),
            _mount("bind", str(root / "home"), JOB_HOME),
        ]
    )
    for binary in decl.binaries:
        mounts.append(_mount("bind", str(binary.resolve()), str(binary.resolve())))
        if binary.absolute() != binary.resolve():
            mounts.append(_mount("bind", str(binary.resolve()), str(binary.absolute())))
    mounts.extend(
        _mount("bind", str(h.script.resolve()), f"{JOB_HOOKS}/{h.name}") for h in decl.hooks
    )
    for server in decl.mcp_servers:
        mounts.extend(_mount("bind", str(b.resolve()), str(b.absolute())) for b in server.binds)
    mounts.extend(
        _mount("bind", str(f.source.resolve()), f"{JOB_HOME}/{f.target}") for f in decl.home_files
    )
    mounts.extend(
        _mount(
            "bind", str(c.source.resolve()), f"{JOB_HOME}/{c.target}", "rw" if c.writable else "ro"
        )
        for c in decl.credentials
    )
    if decl.workdir is not None:
        work = decl.workdir.resolve()
        mounts.append(_mount("bind", str(work), JOB_WORK, "rw" if decl.workdir_writable else "ro"))
        for rel in _masks(work, decl.declared_work_files):
            directory = (work / rel).is_dir()
            mounts.append(
                _mount(
                    "tmpfs" if directory else "bind",
                    "tmpfs" if directory else str(root / "empty"),
                    f"{JOB_WORK}/{rel}",
                )
            )
    if decl.spool is not None:
        mounts.append(_mount("bind", str(decl.spool.resolve()), JOB_SPOOL, "rw"))
    mounts.extend(
        _mount("bind", str(c.source.resolve()), f"/channels/{c.name}") for c in decl.channels
    )
    endpoints = [f"unix:/channels/{c.name}" for c in decl.channels if c.kind == "unix"]
    endpoints.extend(
        {"stdio": server.name, "command": list(server.command)} for server in decl.mcp_servers
    )
    return {"mounts": mounts, "links": links, "endpoints": endpoints, "egress": []}


def _bwrap_parts(argv: tuple[str, ...]) -> dict[str, Any]:
    from shared.capability_envelope.render import EnvelopeRefusal

    a = list(argv)
    if not a or a.pop(0) != "bwrap":
        raise EnvelopeRefusal("conformance: missing bwrap carrier; next action: re-render")
    mounts, links, env = [], [], []
    network = False
    cleared = False
    seen: dict[str, int] = {}
    cwd = None
    i = 0
    flags = {
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup-try",
        "--die-with-parent",
        "--new-session",
        "--unshare-net",
        "--clearenv",
    }
    required = flags | {"--hostname", "--chdir"}
    while i < len(a):
        op = a[i]
        if op == "--":
            if any(seen.get(flag) != 1 for flag in required):
                raise EnvelopeRefusal(
                    "conformance: incomplete isolation scaffold; next action: re-render"
                )
            if not cleared:
                raise EnvelopeRefusal(
                    "conformance: environment not cleared; next action: re-render"
                )
            return {
                "mounts": mounts,
                "links": links,
                "env": env,
                "cwd": cwd,
                "args": a[i + 1 :],
                "network": network,
            }
        if op in required:
            seen[op] = seen.get(op, 0) + 1
        if op in ("--ro-bind", "--bind"):
            mounts.append(_mount("bind", a[i + 1], a[i + 2], "ro" if op == "--ro-bind" else "rw"))
            i += 3
        elif op in ("--proc", "--dev", "--tmpfs"):
            mounts.append(_mount(op[2:], op[2:], a[i + 1], "rw"))
            i += 2
        elif op == "--remount-ro":
            if not mounts or mounts[-1]["target"] != a[i + 1] or mounts[-1]["access"] == "ro":
                raise EnvelopeRefusal("conformance: unexpected remount; next action: re-render")
            mounts[-1]["access"] = "ro"
            i += 2
        elif op == "--symlink":
            links.append(a[i + 1 : i + 3])
            i += 3
        elif op == "--setenv":
            env.append(f"{a[i + 1]}={a[i + 2]}")
            i += 3
        elif op in ("--hostname", "--chdir"):
            if op == "--hostname" and a[i + 1] != "job":
                raise EnvelopeRefusal("conformance: hostname differs; next action: re-render")
            if op == "--chdir":
                cwd = a[i + 1]
            i += 2
        elif op == "--unshare-net":
            network = True
            i += 1
        elif op == "--clearenv":
            cleared = True
            env.clear()
            i += 1
        elif op in flags:
            i += 1
        else:
            raise EnvelopeRefusal(f"conformance: unexpected {op}; next action: re-render")
    raise EnvelopeRefusal("conformance: missing command; next action: re-render")


def make_oci_spec(rendered: RenderedEnvelope, ids: tuple[int, int, int, int]) -> dict[str, Any]:
    """OCI 1.2.1 bundle using the scrub carrier's allowlisted runtime filesystem.

    No image imports, hooks or network setup are inferred. Image production, subordinate
    ID admission and mount ownership are separate enrolment/activation obligations.
    """
    parts = _bwrap_parts(rendered.argv)
    uid, gid, launcher_uid, launcher_gid = ids
    rootfs = rendered.run_root / "rootfs"
    rootfs.mkdir()
    for source, target in parts["links"]:
        (rootfs / target.lstrip("/")).symlink_to(source)
    mounts = []
    for mount in parts["mounts"]:
        kind = mount["kind"]
        mounts.append(
            {
                "destination": mount["target"],
                "type": "tmpfs" if kind == "dev" else kind,
                "source": "tmpfs" if kind == "dev" else mount["source"],
                "options": (
                    ["rbind", "rprivate"]
                    if kind == "bind"
                    else ["nosuid"]
                    if kind == "dev"
                    else ["nosuid", "nodev"]
                )
                + [mount["access"]]
                + (["rro"] if kind == "bind" and mount["access"] == "ro" else []),
            }
        )
    return {
        "ociVersion": "1.2.1",
        "root": {"path": "rootfs", "readonly": True},
        "hostname": "job",
        "process": {
            "terminal": False,
            "user": {"uid": 1, "gid": 1},
            "args": parts["args"],
            "env": parts["env"],
            "cwd": parts["cwd"],
            "noNewPrivileges": True,
            "capabilities": {
                k: [] for k in ("bounding", "effective", "inheritable", "permitted", "ambient")
            },
        },
        "mounts": mounts,
        "linux": {
            "namespaces": [
                {"type": n} for n in ("pid", "ipc", "uts", "mount", "user", "network", "cgroup")
            ],
            "uidMappings": [
                {"containerID": 0, "hostID": launcher_uid, "size": 1},
                {"containerID": 1, "hostID": uid, "size": 1},
            ],
            "gidMappings": [
                {"containerID": 0, "hostID": launcher_gid, "size": 1},
                {"containerID": 1, "hostID": gid, "size": 1},
            ],
            # Ceilings belong to the outer non-delegated T1 unit. No competing OCI cgroup.
        },
    }


def _oci_surface(rendered: RenderedEnvelope) -> dict[str, Any]:
    from shared.capability_envelope.render import EnvelopeRefusal

    spec = rendered.oci_spec
    if set(spec) != {"ociVersion", "root", "hostname", "process", "mounts", "linux"} or spec[
        "root"
    ] != {"path": "rootfs", "readonly": True}:
        raise EnvelopeRefusal("conformance: OCI root or imports changed; next action: re-render")
    if (
        spec["ociVersion"] != "1.2.1"
        or spec["hostname"] != "job"
        or set(spec["process"])
        != {"terminal", "user", "args", "env", "cwd", "noNewPrivileges", "capabilities"}
        or spec["process"]["terminal"] is not False
        or set(spec["process"]["capabilities"])
        != {"bounding", "effective", "inheritable", "permitted", "ambient"}
        or spec["process"]["user"] != {"uid": 1, "gid": 1}
        or spec["process"]["noNewPrivileges"] is not True
        or any(spec["process"]["capabilities"].values())
    ):
        raise EnvelopeRefusal("conformance: OCI privilege differs; next action: re-render")
    if set(spec["linux"]) != {"namespaces", "uidMappings", "gidMappings"}:
        raise EnvelopeRefusal("conformance: extra OCI Linux bindings; next action: re-render")
    uid, gid, launcher_uid, launcher_gid = rendered.oci_ids
    for key, host, sub in (("uidMappings", launcher_uid, uid), ("gidMappings", launcher_gid, gid)):
        if spec["linux"][key] != [
            {"containerID": 0, "hostID": host, "size": 1},
            {"containerID": 1, "hostID": sub, "size": 1},
        ]:
            raise EnvelopeRefusal(
                "conformance: OCI identity binding differs; next action: re-render"
            )
    namespaces = spec["linux"]["namespaces"]
    if namespaces != [
        {"type": name} for name in ("pid", "ipc", "uts", "mount", "user", "network", "cgroup")
    ]:
        raise EnvelopeRefusal("conformance: OCI isolation scaffold differs; next action: re-render")
    mounts = []
    for mount in spec["mounts"]:
        if set(mount) != {"destination", "type", "source", "options"}:
            raise EnvelopeRefusal("conformance: extra mount bindings; next action: re-render")
        kind = mount["type"]
        if kind == "tmpfs" and mount["destination"] == "/dev":
            kind = "dev"
        options = mount["options"]
        access = "ro" if "ro" in options and "rw" not in options else "rw"
        expected_options = (
            (
                ["rbind", "rprivate"]
                if kind == "bind"
                else ["nosuid"]
                if kind == "dev"
                else ["nosuid", "nodev"]
            )
            + [access]
            + (["rro"] if kind == "bind" and access == "ro" else [])
        )
        if options != expected_options:
            raise EnvelopeRefusal("conformance: unexpected mount options; next action: re-render")
        mounts.append(
            _mount(kind, "dev" if kind == "dev" else mount["source"], mount["destination"], access)
        )
    rootfs = rendered.run_root / "rootfs"
    if any(not p.is_symlink() for p in rootfs.iterdir()):
        raise EnvelopeRefusal("conformance: undeclared OCI rootfs import; next action: re-render")
    links = [[os.readlink(p), "/" + p.name] for p in rootfs.iterdir() if p.is_symlink()]
    return {"mounts": mounts, "links": sorted(links), "egress": []}


def _home_inventory(decl: EnvelopeDeclaration) -> dict[str, bytes | None]:
    """Exact generated files and empty mountpoints, derived from admitted imports."""
    from shared.capability_envelope.render import _PROFILES, _claude_config

    expected: dict[str, bytes | None] = {}

    def add(relative: str, content: bytes | None) -> None:
        path = Path(relative)
        for parent in path.parents:
            if parent != Path("."):
                expected.setdefault(str(parent), None)
        expected.setdefault(str(path), content)

    for _, relative in _PROFILES[decl.harness].config_env:
        add(relative, None)
    if decl.harness == "claude":
        settings, state = _claude_config(decl)
        for relative, value in (
            (".claude/settings.json", settings),
            (".claude.json", state),
            (".claude/.claude.json", state),
        ):
            add(relative, json.dumps(value, indent=1).encode())
    for item in decl.home_files:
        add(item.target, b"")
    for credential in decl.credentials:
        add(credential.target, None if credential.source.is_dir() else b"")
    return expected


def _check_generated_home(decl: EnvelopeDeclaration, root: Path) -> None:
    """Anchored, no-follow readback; reject concurrent entry/content/identity changes.

    This observes the pre-dispatch filesystem. It does not claim host files remain
    immutable after return; carrier activation still needs custody of the bundle.
    No unadmitted file is opened and no symlink is followed, including directories.
    """
    from shared.capability_envelope.render import EnvelopeRefusal

    expected = _home_inventory(decl)
    observed: set[str] = set()

    def refuse() -> None:
        raise EnvelopeRefusal(
            "conformance: generated home inventory or contents changed; next action: "
            "render a fresh home from the declaration and retain exclusive bundle custody"
        )

    def signature(info: os.stat_result) -> tuple[int, ...]:
        return (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_nlink,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    def visit(parent_fd: int, name: str, relative: str, *, directory: bool) -> None:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not (stat.S_ISDIR(before.st_mode) if directory else stat.S_ISREG(before.st_mode)):
            refuse()
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if directory:
            flags |= os.O_DIRECTORY
        fd = os.open(name, flags, dir_fd=parent_fd)
        try:
            if signature(os.fstat(fd)) != signature(before):
                refuse()
            if directory:
                for child in sorted(os.listdir(fd)):
                    rel = f"{relative}/{child}" if relative else child
                    if rel not in expected:
                        refuse()
                    observed.add(rel)
                    visit(fd, child, rel, directory=expected[rel] is None)
            else:
                content = expected[relative]
                # Bounded read detects appended data without importing private contents.
                if os.read(fd, len(content) + 1) != content:
                    refuse()
            if signature(os.fstat(fd)) != signature(before) or signature(
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            ) != signature(before):
                refuse()
        finally:
            os.close(fd)

    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root_before = os.fstat(root_fd)
        visit(root_fd, "home", "", directory=True)
        if observed != set(expected):
            refuse()
        if signature(os.fstat(root_fd)) != signature(root_before) or signature(
            root.lstat()
        ) != signature(root_before):
            refuse()
    finally:
        os.close(root_fd)


def _bytes(surface: dict[str, Any]) -> bytes:
    return json.dumps(surface, sort_keys=True, separators=(",", ":")).encode()


def check_surface(decl: EnvelopeDeclaration, rendered: RenderedEnvelope) -> bytes:
    from shared.capability_envelope.render import (
        JOB_HOME,
        JOB_WORK,
        EnvelopeRefusal,
        _claude_config,
        _environment,
    )

    expected = _declared_surface(decl, rendered.run_root)
    expected["links"] = sorted(expected["links"])
    if rendered.unit_properties != unit_properties(decl):
        raise EnvelopeRefusal("conformance: unit properties differ; next action: re-render")
    try:
        if rendered.carrier == "t3":
            actual = _oci_surface(rendered)
            process = rendered.oci_spec["process"]
        else:
            argv = rendered.argv
            if rendered.carrier == "t1":
                prefix = (
                    "systemd-run",
                    "--user",
                    "--wait",
                    "--pipe",
                    "--collect",
                    *(f"--property={p}" for p in unit_properties(decl)),
                    "--",
                )
                if argv[: len(prefix)] != prefix:
                    raise EnvelopeRefusal(
                        "conformance: systemd properties differ; next action: re-render"
                    )
                argv = argv[len(prefix) :]
            parts = _bwrap_parts(argv)
            if not parts["network"]:
                raise EnvelopeRefusal("conformance: host network exposed; next action: re-render")
            actual = {"mounts": parts["mounts"], "links": sorted(parts["links"]), "egress": []}
            process = parts
        if (
            process["args"] != list(decl.argv)
            or process["env"] != [f"{k}={v}" for k, v in _environment(decl).items()]
            or process["cwd"] != (JOB_WORK if decl.workdir is not None else JOB_HOME)
        ):
            raise EnvelopeRefusal(
                "conformance: command/environment differs; next action: re-render"
            )
        actual["endpoints"] = [
            f"unix:{m['target']}"
            for m in actual["mounts"]
            if m["kind"] == "bind" and Path(m["source"]).is_socket()
        ]
        _check_generated_home(decl, rendered.run_root)
        if decl.harness == "claude":
            _, state = _claude_config(decl)
            actual["endpoints"].extend(
                {"stdio": name, "command": [value["command"], *value["args"]]}
                for name, value in state["mcpServers"].items()
            )
        if _bytes(actual) != _bytes(expected):
            raise EnvelopeRefusal(
                "conformance: channel bytes differ; next action: correct the carrier"
            )
    except (KeyError, IndexError, TypeError, OSError, json.JSONDecodeError) as exc:
        raise EnvelopeRefusal("conformance: malformed carrier; next action: re-render") from exc
    return _bytes(expected)
