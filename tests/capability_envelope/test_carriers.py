"""Source-only carrier conformance witnesses."""

import copy
import hashlib
import importlib
import json
import os
import shutil
import socket

import pytest

from shared.capability_envelope import EnvelopeCarrierError, EnvelopeRefusal, execute
from tests.capability_envelope.test_declaration_render import declaration

module = importlib.import_module("shared.capability_envelope.render")
parametrize = pytest.mark.parametrize
IDS = dict(oci_uid=100000, oci_gid=100000, oci_launcher_uid=1000, oci_launcher_gid=1000)
PROPERTIES = tuple(
    [
        "MemoryHigh=67108864",
        "MemoryMax=134217728",
        "MemorySwapMax=0",
        "OOMPolicy=kill",
        "RuntimeMaxSec=30",
        "Restart=no",
        "KillMode=control-group",
    ]
)
FLAGS = [
    "--unshare-pid",
    "--unshare-ipc",
    "--unshare-net",
    "--unshare-uts",
    "--unshare-cgroup-try",
    "--die-with-parent",
    "--new-session",
    "--clearenv",
]


@pytest.fixture(params=("t1", "t2", "t3"))
def carrier(request):
    return request.param


def job(root, carrier="t2", **updates):
    decl = declaration(**updates)
    return decl, module.render(decl, run_root=root / "run", carrier=carrier, **IDS)


def refuses(decl, out, **changes):
    with pytest.raises(EnvelopeRefusal, match="conformance"):
        module.check_conformance(decl, out.model_copy(update=changes))


def test_outputs(tmp_path, carrier):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    endpoint = tmp_path / "model.sock"
    with socket.socket(socket.AF_UNIX) as sock:
        sock.bind(str(endpoint))
        decl, out = job(
            tmp_path,
            carrier,
            channels=[
                dict(name="inbox", kind="mount", source=inbox),
                dict(name="model", kind="unix", source=endpoint),
            ],
        )
        assert module.check_conformance(decl, out) == out.channel_bytes
    surface = json.loads(out.channel_bytes)
    assert surface["mounts"][-2:] == [
        dict(kind="bind", source=str(inbox), target="/channels/inbox", access="ro"),
        dict(kind="bind", source=str(endpoint), target="/channels/model", access="ro"),
    ]
    assert surface["endpoints"] == ["unix:/channels/model"] and surface["egress"] == []
    assert all(m["source"] != "/var/run/docker.sock" for m in surface["mounts"])
    assert out.unit_properties == PROPERTIES
    payloads = {"channels": out.channel_bytes, "argv": "\0".join(out.argv).encode()}
    if carrier == "t1":
        assert out.argv[:13] == (
            *["systemd-run", "--user", "--wait", "--pipe", "--collect"],
            *(f"--property={p}" for p in PROPERTIES),
            "--",
        )
    if carrier != "t3":
        assert "--unshare-net" in out.argv
    else:
        raw = (out.run_root / "config.json").read_bytes()
        assert json.loads(raw) == out.oci_spec
        payloads["oci_spec"] = raw
        assert out.argv == ()
        assert out.oci_spec["process"]["user"] == {"uid": 1, "gid": 1}
        assert out.oci_spec["linux"]["uidMappings"][1]["hostID"] == 100000
        for m in out.oci_spec["mounts"]:
            if m["type"] == "bind" and "ro" in m["options"]:
                assert "rro" in m["options"]

    for name, data in payloads.items():
        assert out.facts[name + "_sha256"] == hashlib.sha256(data).hexdigest()


@parametrize("uid", [None, 0, -1, True, 2**32, 1000])
def test_ids(tmp_path, uid):
    with pytest.raises(EnvelopeRefusal, match="subordinate"):
        module.render(
            declaration(),
            run_root=tmp_path / "run",
            carrier="t3",
            **{**IDS, "oci_uid": uid},
        )
    assert not (tmp_path / "run").exists()


@parametrize("carrier", ["t1", "t3"])
def test_held(tmp_path, monkeypatch, carrier):
    def unexpected(*args, **kwargs):
        pytest.fail("source carrier attempted activation")

    monkeypatch.setattr(module.subprocess, "run", unexpected)
    _, out = job(tmp_path, carrier)
    with pytest.raises(EnvelopeCarrierError, match="governed"):
        execute(out, timeout=30)


@parametrize("change", ["mount", "access", "args", "env", "cwd", "unit"])
def test_surface(tmp_path, carrier, change):
    decl, out = job(tmp_path, carrier)
    if change == "unit":
        if carrier == "t1":
            refuses(decl, out, argv=("false", *out.argv[1:]))
        return refuses(decl, out, unit_properties=())
    if carrier == "t3":
        spec = copy.deepcopy(out.oci_spec)
        if change == "mount":
            spec["mounts"].append({**spec["mounts"][0], "source": "/undeclared"})
        elif change == "access":
            spec["mounts"][0]["options"] = ["rbind", "rprivate", "rw"]
        else:
            spec["process"][change] = "/bad" if change == "cwd" else ["bad"]
        refuses(decl, out, oci_spec=spec)
    else:
        a = list(out.argv)
        i = len(a) - len(decl.argv) - 1
        if change == "mount":
            a[i:i] = ["--ro-bind", "/undeclared", "/leak"]
        elif change == "access":
            a[a.index("--ro-bind")] = "--bind"
        elif change == "args":
            a[-1] = "bad"
        elif change == "env":
            a[a.index("--setenv") + 2] = "bad"
        else:
            a[a.index("--chdir") + 1] = "/bad"
        refuses(decl, out, argv=tuple(a))


@parametrize("carrier", ["t1", "t2"])
@parametrize("flag", FLAGS)
@parametrize("change", ["remove", "duplicate"])
def test_bwrap_isolation(tmp_path, carrier, flag, change):
    decl, out = job(tmp_path, carrier)
    a = list(out.argv)
    i = a.index(flag)
    a[i : i + 1] = [] if change == "remove" else [flag, flag]
    refuses(decl, out, argv=tuple(a))


@parametrize("carrier", ["t1", "t2"])
@parametrize(
    "change",
    ["hostname", "duplicate-hostname", "duplicate-chdir", "share-net", "clear-late", "remount"],
)
def test_bwrap_scaffold(tmp_path, carrier, change):
    work = tmp_path / "work"
    (work / ".claude").mkdir(parents=True)
    decl, out = job(tmp_path, carrier, workdir=work)
    a = list(out.argv)
    if change == "hostname":
        a[a.index("--hostname") + 1] = "host"
    elif change == "remount":
        i = a.index("--remount-ro")
        a[i:i] = a[i : i + 2]
    else:
        i = len(a) - len(decl.argv) - 1
        a[i:i] = {
            "duplicate-hostname": ["--hostname", "job"],
            "duplicate-chdir": ["--chdir", "/home/job"],
            "share-net": ["--share-net"],
            "clear-late": ["--clearenv"],
        }[change]
    refuses(decl, out, argv=tuple(a))


@parametrize("namespace", ["pid", "ipc", "uts", "mount", "user", "network", "cgroup"])
@parametrize("change", ["remove", "duplicate", "host-path", "extra-key"])
def test_oci_isolation(tmp_path, namespace, change):
    decl, out = job(tmp_path, "t3")
    spec = copy.deepcopy(out.oci_spec)
    entries = spec["linux"]["namespaces"]
    entry = next(n for n in entries if n["type"] == namespace)
    if change == "remove":
        entries.remove(entry)
    elif change == "duplicate":
        entries.append(dict(entry))
    else:
        entry["path" if change == "host-path" else "unexpected"] = "/proc/1/ns/" + namespace
    refuses(decl, out, oci_spec=spec)


@parametrize(
    "path,value",
    [
        (("root", "path"), "/"),
        (("hooks",), {"prestart": [{"path": "/bad"}]}),
        (("process", "user", "uid"), 0),
        (("linux", "uidMappings", 1, "hostID"), 0),
        (("linux", "extra"), []),
        (("mounts", 0, "uidMappings"), []),
        (("ociVersion",), "unsupported"),
        (("hostname",), "host"),
        (("process", "terminal"), True),
        (("process", "selinuxLabel"), "bad"),
        (("process", "capabilities", "extra"), []),
        (("process", "noNewPrivileges"), False),
    ],
)
def test_oci_scaffold(tmp_path, path, value):
    decl, out = job(tmp_path, "t3")
    spec = copy.deepcopy(out.oci_spec)
    target = spec
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    refuses(decl, out, oci_spec=spec)


@parametrize("harness", ["claude", "codex", "vibe"])
@parametrize("entry", ["file", "symlink", "directory", "nested", "home-symlink"])
def test_home_inventory(tmp_path, carrier, harness, entry):
    decl, out = job(tmp_path, carrier, harness=harness)
    home = out.run_root / "home"
    if entry == "file":
        (home / "CLAUDE.md").write_text("undeclared")
    elif entry == "symlink":
        (home / "AGENTS.md").symlink_to(tmp_path / "absent")
    elif entry == "directory":
        (home / "instructions").mkdir()
    elif entry == "nested":
        path = home / {"claude": ".claude", "codex": ".codex", "vibe": "private"}[harness]
        path.mkdir(exist_ok=True)
        (path / "AGENTS.md").write_text("undeclared")
    else:
        home.rename(out.run_root / "old-home")
        home.symlink_to(out.run_root / "old-home", target_is_directory=True)
    refuses(decl, out)


@parametrize(
    "change",
    [
        "missing",
        "symlink",
        "missing-dir",
        "extra-content",
        ".claude.json",
        ".claude/.claude.json",
        ".claude/settings.json",
    ],
)
def test_home_contents(tmp_path, carrier, change):
    decl, out = job(tmp_path, carrier)
    path = out.run_root / "home/.claude/settings.json"
    if change == "missing":
        path.unlink()
    elif change == "symlink":
        same = tmp_path / "same"
        same.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(same)
    elif change == "missing-dir":
        shutil.rmtree(path.parent)
    elif change == "extra-content":
        path.write_text(path.read_text() + " ")
    else:
        path = out.run_root / "home" / change
        value = json.loads(path.read_text())
        value["hooks" if "settings" in change else "mcpServers"] = {"extra": {"command": "leak"}}
        path.write_text(json.dumps(value))
    refuses(decl, out)


@parametrize("change", ["add", "replace-file", "replace-directory"])
def test_home_race(tmp_path, monkeypatch, carrier, change):
    decl, out = job(tmp_path, carrier)
    home = out.run_root / "home"
    config = home / ".claude"
    settings = config / "settings.json"
    original, raced = os.open, False

    def race(path, *args, **kwargs):
        nonlocal raced
        fd = original(path, *args, **kwargs)
        if str(path) == "settings.json" and not raced:
            raced = True
            if change == "add":
                (home / "CLAUDE.md").write_text("raced")
            elif change == "replace-file":
                settings.unlink()
                settings.write_text("{}")
            else:
                config.rename(home / "old-config")
                config.mkdir()
                settings.write_text("{}")
        return fd

    monkeypatch.setattr(os, "open", race)
    refuses(decl, out)
    assert raced


def test_imports(tmp_path, carrier):
    work = tmp_path / "work"
    (work / ".claude").mkdir(parents=True)
    for name in ("AGENTS.md", ".mcp.json"):
        (work / name).write_text("sentinel")
    auth = tmp_path / "auth"
    auth.mkdir()
    decl, out = job(
        tmp_path,
        carrier,
        workdir=work,
        declared_work_files=["AGENTS.md"],
        home_files=[dict(source=work / "AGENTS.md", target="declared/AGENTS.md")],
        credentials=[dict(source=auth, target="auth")],
    )
    assert set(out.masked) == {".claude", ".mcp.json"}
    mounts = {m["target"]: m for m in json.loads(out.channel_bytes)["mounts"]}
    assert mounts["/work/.claude"]["kind"] == "tmpfs"
    assert mounts["/work/.claude"]["access"] == "ro"
    assert mounts["/work/.mcp.json"]["source"].endswith("/empty")
    assert "/work/AGENTS.md" not in mounts
    changed = decl.model_copy(update={"spool": tmp_path})
    refuses(changed, out)
    if carrier == "t3":
        path = out.run_root / "rootfs/AGENTS.md"
        path.write_text("undeclared")
        refuses(decl, out)
        path.unlink()
    (out.run_root / "home/auth/private").write_text("undeclared placeholder data")
    refuses(decl, out)


@parametrize("fault", ["check", "mount"])
def test_publication(tmp_path, monkeypatch, fault):
    carriers = importlib.import_module("shared.capability_envelope.carriers")
    original = carriers.make_oci_spec

    def broken(*args, **kwargs):
        if fault == "check":
            raise EnvelopeRefusal("conformance injected discrepancy")
        spec = original(*args, **kwargs)
        spec["mounts"].append({**spec["mounts"][0], "source": "/undeclared"})
        return spec

    monkeypatch.setattr(
        module if fault == "check" else carriers,
        "check_conformance" if fault == "check" else "make_oci_spec",
        broken,
    )
    with pytest.raises(EnvelopeRefusal, match="conformance"):
        job(tmp_path, "t3")
    assert not (tmp_path / "run/config.json").exists()
