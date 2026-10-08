"""Render an envelope declaration into its host carrier (containment tier T2, bubblewrap).

Isolation is by construction, not by trusting harness flags:

- **The root is an allowlist.** ``/usr``, the ``/bin``-style links and a short list of ``/etc``
  files are bound read-only; nothing else from the host exists in the job. The host root and the
  operator's home are never bound whole, so no walk-up reaches an ancestor instruction file.
- **The job home is generated fresh per run** under a create-once run root. It holds only the
  declared files, credentials and the harness config rendered from the declaration (declared
  hooks, declared MCP servers). Nothing written during one run is visible to the next.
- **The checkout is masked by name.** Every file or directory in the workdir whose name is in
  ``MASKED_NAMES`` is covered — an empty read-only file, or an empty tmpfs for a directory —
  except the ones the declaration names. ``MASKED_NAMES`` is a fixed, measured list (see its own
  comment), not an enumeration of every name a harness might read: a name absent from it is not
  masked by this layer, and adding one is a measurement, never a guess. The list is applied
  wherever the walk meets such a name in the workdir, ``.git`` included.
- **The environment is cleared.** Only a fixed base, the harness config variables and the
  declared variables are set.

Harness flags are a second layer and never the only one. ``--bare`` is refused unless the
declaration names API billing: Claude's bare mode does not read ``CLAUDE_CODE_OAUTH_TOKEN``, so it
changes the billing surface, which must never happen implicitly.

Network namespaces are private. Declared Unix endpoints are mounted explicitly;
network egress requires the separately governed R9 gate and otherwise refuses.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from shared.capability_envelope.declaration import EnvelopeDeclaration

JOB_HOME = "/home/job"
JOB_WORK = "/work"
JOB_SPOOL = "/spool"
JOB_HOOKS = "/envelope/hooks"

# Instruction and harness config names masked in the checkout unless declared. Seeded from the
# measured imports of every CLI harness on appendix (ENCOUNTERED-MACHINERY M153, 2026-09-25) and
# the harness docs; extend it from measurement, never shrink it.
MASKED_NAMES: tuple[str, ...] = (
    "AGENTS.md",
    "AGENTS.override.md",
    "CLAUDE.md",
    "CLAUDE.local.md",
    "GEMINI.md",
    "copilot-instructions.md",
    ".agents",
    ".claude",
    ".codex",
    ".cursor",
    ".cursorrules",
    ".gemini",
    ".grok",
    ".kimi",
    ".kimi-code",
    ".mcp.json",
    ".opencode",
    ".vibe",
    ".windsurfrules",
    "opencode.json",
    "opencode.jsonc",
)

_ROOT_LINKS = ("/bin", "/sbin", "/lib", "/lib64")
_ETC_ALLOW = (
    "ca-certificates",
    "crypto-policies",
    "gai.conf",
    "group",
    "host.conf",
    "hosts",
    "ld.so.cache",
    "ld.so.conf",
    "ld.so.conf.d",
    "localtime",
    "mime.types",
    "nsswitch.conf",
    "os-release",
    "passwd",
    "pki",
    "protocols",
    "resolv.conf",
    "services",
    "ssl",
)
_BASE_PATH = ("/usr/local/bin", "/usr/bin", "/bin")
_SECRET_ENV_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE_KEY|ACCESS_KEY)", re.I
)


class EnvelopeRefusal(ValueError):
    """The declaration cannot be rendered safely. The message names the next action."""


@dataclass(frozen=True)
class _HarnessProfile:
    """Where a harness reads its config, and which declared imports this renderer can place."""

    config_env: tuple[tuple[str, str], ...] = ()
    renders_hooks: bool = False
    renders_mcp: bool = False


_PROFILES: dict[str, _HarnessProfile] = {
    "claude": _HarnessProfile(
        config_env=(("CLAUDE_CONFIG_DIR", ".claude"),), renders_hooks=True, renders_mcp=True
    ),
    "codex": _HarnessProfile(config_env=(("CODEX_HOME", ".codex"),)),
    "agy": _HarnessProfile(),
    "grok": _HarnessProfile(),
    "kimi": _HarnessProfile(),
    "vibe": _HarnessProfile(),
    "opencode": _HarnessProfile(),
    "muse": _HarnessProfile(),
}


class RenderedEnvelope(BaseModel):
    """The carrier argv for one run, plus the facts to record with the run."""

    model_config = ConfigDict(frozen=True)

    argv: tuple[str, ...]
    run_root: Path
    masked: tuple[str, ...]
    facts: dict[str, Any]
    carrier: Literal["t1", "t2", "t3"] = "t2"
    unit_properties: tuple[str, ...] = ()
    channel_bytes: bytes = b""
    oci_spec: dict[str, Any] | None = None
    oci_ids: tuple[int, int, int, int] | None = None


def _refuse(decl: EnvelopeDeclaration) -> None:
    profile = _PROFILES[decl.harness]
    billing_flags = {"--bare", "--api-key", "--api-key-file", "--api-key-helper"}
    if (
        any(arg.split("=", 1)[0] in billing_flags for arg in decl.argv)
        and decl.billing_surface != "api"
    ):
        raise EnvelopeRefusal(
            "--bare needs declared API billing: Claude's bare mode does not read "
            "CLAUDE_CODE_OAUTH_TOKEN, so it switches the billing surface; next action: set "
            "billing_surface='api' in the declaration, or drop --bare and rely on the envelope"
        )
    if decl.unit is None:
        raise EnvelopeRefusal("unit limits are required; next action: declare the unit section")
    if decl.unit.memory_high > decl.unit.memory_max:
        raise EnvelopeRefusal(
            "memory_high exceeds memory_max; next action: correct the unit limits"
        )
    names: set[str] = set()
    for channel in decl.channels:
        if channel.kind == "network":
            raise EnvelopeRefusal(
                "network egress has no admitted gate binding; next action: supply an admitted "
                "Unix endpoint or wait for the egress-gate work"
            )
        if channel.name in names or channel.source is None or channel.endpoint is not None:
            raise EnvelopeRefusal("invalid channel; next action: name a unique source binding")
        names.add(channel.name)
        if channel.kind == "unix" and not channel.source.is_socket():
            raise EnvelopeRefusal("Unix endpoint is not a socket; next action: correct its binding")
        if channel.source.resolve() in (Path("/"), Path.home()):
            raise EnvelopeRefusal(
                "channel binds a whole host root/home; next action: narrow its source"
            )
    for key in decl.env:
        if key in {
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
            "XDG_CACHE_HOME",
        } or key in dict(profile.config_env):
            raise EnvelopeRefusal("config environment override; next action: use declared imports")
        if _SECRET_ENV_RE.search(key):
            raise EnvelopeRefusal(
                f"env {key} looks like a credential, and env values appear in the carrier argv; "
                "next action: declare it as a CredentialBind file instead"
            )
    if decl.hooks and not profile.renders_hooks:
        raise EnvelopeRefusal(
            f"no hook renderer for harness {decl.harness}; next action: drop the hooks or add "
            "the harness's hook format to the envelope renderer with its unsafe-case tests"
        )
    if decl.mcp_servers and not profile.renders_mcp:
        raise EnvelopeRefusal(
            f"no MCP renderer for harness {decl.harness}; next action: drop the MCP servers or "
            "add the harness's MCP config format to the envelope renderer with its tests"
        )


def _masks(workdir: Path, declared: tuple[str, ...]) -> list[str]:
    """Checkout-relative paths to cover, in the order bwrap must mount them."""
    declared_set = set(declared)
    root = workdir.resolve()
    masked: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        for name in [*dirnames, *filenames]:
            if name not in MASKED_NAMES:
                continue
            path = base / name
            rel = path.relative_to(root).as_posix()
            if rel in declared_set:
                continue
            if path.is_symlink():
                target = path.resolve()
                try:
                    target_rel = target.relative_to(root).as_posix()
                except ValueError as exc:
                    # Inside the job it could resolve to any file the job can see (a bound
                    # credential, /etc), and a harness would import it as instructions.
                    raise EnvelopeRefusal(
                        f"checkout symlink {rel} points outside the checkout "
                        f"({os.readlink(path)}); next action: remove it from the checkout, or "
                        "declare it in declared_work_files if that file is meant to be read"
                    ) from exc
                if target_rel in declared_set:
                    continue
                # The RESOLVED TARGET is always named, never assumed to be covered by the walk:
                # a target inside a masked-name directory is pruned from the walk, and the walk
                # sees a chain only at its first link. `CLAUDE.md -> .git/CLAUDE.md` read the file
                # in full before this (review of #4784, gemini-1, 2026-09-28), which is why the
                # resolved target is named explicitly.
                #
                # The link path itself is deliberately NOT appended: bubblewrap refuses to mount
                # on a symlink destination ("bwrap: Can't mount on symlink destination
                # /work/CLAUDE.md", measured 2026-09-28), so covering the target is what closes
                # the leak — the link then resolves to the masked file. Appending the link would
                # trade a leak for a carrier that cannot start at all.
                rel = target_rel
            masked.append(rel)
        dirnames[:] = [d for d in dirnames if d not in MASKED_NAMES]
    # One mount per path: a target reachable both through a link and by the walk must not be
    # mounted twice, and the order of first appearance is the order bwrap must mount them in.
    return list(dict.fromkeys(masked))


def _claude_config(decl: EnvelopeDeclaration) -> tuple[dict[str, Any], dict[str, Any]]:
    settings: dict[str, Any] = {}
    if decl.hooks:
        events: dict[str, list[dict[str, Any]]] = {}
        for hook in decl.hooks:
            group: dict[str, Any] = {
                "hooks": [{"type": "command", "command": f"{JOB_HOOKS}/{hook.name}"}]
            }
            if hook.matcher:
                group["matcher"] = hook.matcher
            events.setdefault(hook.event, []).append(group)
        settings["hooks"] = events
    state: dict[str, Any] = {"hasCompletedOnboarding": True, "mcpServers": {}}
    for server in decl.mcp_servers:
        state["mcpServers"][server.name] = {
            "type": "stdio",
            "command": server.command[0],
            "args": list(server.command[1:]),
        }
    return settings, state


def _placeholder(run_home: Path, target: str, *, directory: bool) -> None:
    path = run_home / target
    path.parent.mkdir(parents=True, exist_ok=True)
    if directory:
        path.mkdir(exist_ok=True)
    else:
        path.touch()


def _environment(decl: EnvelopeDeclaration) -> dict[str, str]:
    """The fixed base plus explicitly declared variables; shared by render and readback."""
    env = {
        "HOME": JOB_HOME,
        "USER": os.environ.get("USER", "job"),
        "LOGNAME": os.environ.get("USER", "job"),
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
    }
    path_dirs = list(_BASE_PATH)
    for binary in decl.binaries:
        parent = str(binary.absolute().parent)
        if parent not in path_dirs:
            path_dirs.append(parent)
    for var, rel in _PROFILES[decl.harness].config_env:
        env[var] = f"{JOB_HOME}/{rel}"
    env["PATH"] = ":".join(path_dirs)
    env.update(decl.env)
    return env


def _render_bwrap(decl: EnvelopeDeclaration, *, run_root: Path) -> RenderedEnvelope:
    """Build the carrier argv for one run. ``run_root`` must not exist yet (create-once)."""
    profile = _PROFILES[decl.harness]
    try:
        run_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise EnvelopeRefusal(
            f"run root {run_root} already exists; a job home is never reused; next action: "
            "render into a fresh run root"
        ) from exc
    run_home = run_root / "home"
    run_home.mkdir()
    # Masked files read as empty, not as an error: /dev/null bound onto a nodev mount refuses the
    # open, and a harness may treat that differently from an absent or empty instruction file.
    empty = run_root / "empty"
    empty.touch()
    empty.chmod(0o444)

    a: list[str] = [
        "bwrap",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-net",
        "--unshare-uts",
        "--unshare-cgroup-try",
        "--hostname",
        "job",
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/usr",
        "/usr",
    ]
    for link in _ROOT_LINKS:
        if os.path.islink(link):
            a += ["--symlink", os.readlink(link), link]
        elif os.path.isdir(link):
            a += ["--ro-bind", link, link]
    for name in _ETC_ALLOW:
        if Path(f"/etc/{name}").exists():
            a += ["--ro-bind", f"/etc/{name}", f"/etc/{name}"]
    a += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    a += ["--ro-bind", str(run_home), JOB_HOME]

    env = _environment(decl)
    for binary in decl.binaries:
        resolved = binary.resolve()
        a += ["--ro-bind", str(resolved), str(resolved)]
        if binary.absolute() != resolved:
            a += ["--ro-bind", str(resolved), str(binary.absolute())]

    for _var, rel in profile.config_env:
        _placeholder(run_home, rel, directory=True)
    if decl.harness == "claude":
        settings, state = _claude_config(decl)
        config_dir = run_home / ".claude"
        (config_dir / "settings.json").write_text(json.dumps(settings, indent=1))
        # The global state file sits in $HOME or in CLAUDE_CONFIG_DIR depending on the CLI
        # version; both carry the same declared content.
        for state_path in (run_home / ".claude.json", config_dir / ".claude.json"):
            state_path.write_text(json.dumps(state, indent=1))
    for hook in decl.hooks:
        a += ["--ro-bind", str(hook.script.resolve()), f"{JOB_HOOKS}/{hook.name}"]
    for server in decl.mcp_servers:
        for bind in server.binds:
            a += ["--ro-bind", str(bind.resolve()), str(bind.absolute())]

    for item in decl.home_files:
        _placeholder(run_home, item.target, directory=False)
        a += ["--ro-bind", str(item.source.resolve()), f"{JOB_HOME}/{item.target}"]
    for cred in decl.credentials:
        _placeholder(run_home, cred.target, directory=cred.source.is_dir())
        mode = "--bind" if cred.writable else "--ro-bind"
        a += [mode, str(cred.source.resolve()), f"{JOB_HOME}/{cred.target}"]

    masked: list[str] = []
    if decl.workdir is not None:
        workdir = decl.workdir.resolve()
        a += ["--bind" if decl.workdir_writable else "--ro-bind", str(workdir), JOB_WORK]
        masked = _masks(workdir, decl.declared_work_files)
        for rel in masked:
            if (workdir / rel).is_dir():
                a += ["--tmpfs", f"{JOB_WORK}/{rel}", "--remount-ro", f"{JOB_WORK}/{rel}"]
            else:
                a += ["--ro-bind", str(empty), f"{JOB_WORK}/{rel}"]
    if decl.spool is not None:
        a += ["--bind", str(decl.spool.resolve()), JOB_SPOOL]
    for channel in decl.channels:
        a += ["--ro-bind", str(channel.source.resolve()), f"/channels/{channel.name}"]

    a += ["--clearenv"]
    for key, value in env.items():
        a += ["--setenv", key, value]
    a += ["--chdir", JOB_WORK if decl.workdir is not None else JOB_HOME, "--", *decl.argv]

    facts = {
        "carrier": "bwrap",
        "harness": decl.harness,
        "billing_surface": decl.billing_surface,
        "declaration_sha256": hashlib.sha256(decl.model_dump_json().encode()).hexdigest(),
        "argv_sha256": hashlib.sha256("\0".join(a).encode()).hexdigest(),
        "masked": masked,
        "hooks": [h.name for h in decl.hooks],
        "mcp_servers": [s.name for s in decl.mcp_servers],
    }
    return RenderedEnvelope(argv=tuple(a), run_root=run_root, masked=tuple(masked), facts=facts)


def render(
    decl: EnvelopeDeclaration,
    *,
    run_root: Path,
    carrier: Literal["t1", "t2", "t3"] = "t2",
    oci_uid: int | None = None,
    oci_gid: int | None = None,
    oci_launcher_uid: int | None = None,
    oci_launcher_gid: int | None = None,
) -> RenderedEnvelope:
    """Render, never launch, a declared envelope. T3 IDs are explicit enrolment bindings.

    T1 wraps the T2 filesystem carrier in a transient user service. T3 emits an OCI
    bundle plus the same required outer-unit properties; execution belongs to the
    separately admitted launcher. It is never implicitly run via a container daemon.
    """
    from shared.capability_envelope.carriers import make_oci_spec, unit_properties

    decl = EnvelopeDeclaration.model_validate(decl.model_dump())
    _refuse(decl)
    if carrier not in ("t1", "t2", "t3"):
        raise EnvelopeRefusal("unknown carrier; next action: select t1, t2 or t3")
    ids = (oci_uid, oci_gid, oci_launcher_uid, oci_launcher_gid)
    if carrier == "t3" and (
        any(type(value) is not int or not 0 < value < 2**32 - 1 for value in ids)
        or oci_uid == oci_launcher_uid
        or oci_gid == oci_launcher_gid
    ):
        raise EnvelopeRefusal(
            "OCI needs subordinate uid/gid bindings; next action: supply enrolled IDs"
        )
    run_root = run_root.absolute()
    rendered = _render_bwrap(decl, run_root=run_root)
    properties = unit_properties(decl)
    changes: dict[str, Any] = {"carrier": carrier, "unit_properties": properties}
    if carrier == "t1":
        changes["argv"] = (
            "systemd-run",
            "--user",
            "--wait",
            "--pipe",
            "--collect",
            *(f"--property={p}" for p in properties),
            "--",
            *rendered.argv,
        )
    elif carrier == "t3":
        changes["oci_spec"] = make_oci_spec(rendered, ids)
        changes["oci_ids"] = ids
        changes["argv"] = ()
    rendered = rendered.model_copy(update=changes)
    channel_bytes = check_conformance(decl, rendered)
    facts = {
        **rendered.facts,
        "carrier": carrier,
        "channels_sha256": hashlib.sha256(channel_bytes).hexdigest(),
        "unit_properties": properties,
        "argv_sha256": hashlib.sha256("\0".join(rendered.argv).encode()).hexdigest(),
    }
    if carrier == "t3":
        raw = (json.dumps(rendered.oci_spec, indent=2) + "\n").encode()
        (run_root / "config.json").write_bytes(raw)
        facts["oci_spec_sha256"] = hashlib.sha256(raw).hexdigest()
    return rendered.model_copy(update={"channel_bytes": channel_bytes, "facts": facts})


def check_conformance(decl: EnvelopeDeclaration, rendered: RenderedEnvelope) -> bytes:
    """Byte-compare the declaration's normalized channels with the actual carrier."""
    from shared.capability_envelope.carriers import check_surface

    _refuse(decl)
    return check_surface(decl, rendered)


class EnvelopeCarrierError(RuntimeError):
    """The carrier could not start the job. Never a reason to run the job unenveloped."""


def execute(
    rendered: RenderedEnvelope, *, stdin: str | None = None, timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run one rendered job. The caller keeps or discards ``rendered.run_root`` afterwards.

    Raises EnvelopeCarrierError when bubblewrap is not on the caller's PATH, or when bubblewrap
    itself fails (a nonzero exit whose stderr is bubblewrap's), for example without unprivileged
    user namespaces or when a declared binary is not inside the job.
    """
    if rendered.carrier != "t2":
        raise EnvelopeCarrierError(
            "execute only admits the existing T2 carrier; next action: use the governed "
            "launcher for unit/OCI activation after independent acceptance"
        )
    carrier = shutil.which(rendered.argv[0])
    if carrier is None:
        raise EnvelopeCarrierError(
            "bubblewrap not found on PATH; next action: install bubblewrap on this host, or "
            "route the job to a host that has it"
        )
    result = subprocess.run(
        [carrier, *rendered.argv[1:]],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={"PATH": ":".join(_BASE_PATH)},
    )
    if result.returncode != 0 and result.stderr.startswith("bwrap:"):
        first = result.stderr.splitlines()[0]
        raise EnvelopeCarrierError(
            f"the envelope carrier failed ({first}); next action: enable unprivileged user "
            "namespaces for bubblewrap on this host, or declare the missing binary"
        )
    return result
