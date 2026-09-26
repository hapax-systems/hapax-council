"""Render an envelope declaration into its host carrier (containment tier T2, bubblewrap).

Isolation is by construction, not by trusting harness flags:

- **The root is an allowlist.** ``/usr``, the ``/bin``-style links and a short list of ``/etc``
  files are bound read-only; nothing else from the host exists in the job. The host root and the
  operator's home are never bound whole, so no walk-up reaches an ancestor instruction file.
- **The job home is generated fresh per run** under a create-once run root. It holds only the
  declared files, credentials and the harness config rendered from the declaration (declared
  hooks, declared MCP servers). Nothing written during one run is visible to the next.
- **The checkout is masked.** Every instruction or harness config file or directory in the
  workdir (``MASKED_NAMES``) is covered, except the ones the declaration names.
- **The environment is cleared.** Only a fixed base, the harness config variables and the
  declared variables are set.

Harness flags are a second layer and never the only one. ``--bare`` is refused unless the
declaration names API billing: Claude's bare mode does not read ``CLAUDE_CODE_OAUTH_TOKEN``, so it
changes the billing surface, which must never happen implicitly.

Egress is not narrowed here; network egress is the fabric's R9 gate.
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
from typing import Any

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


def _refuse(decl: EnvelopeDeclaration) -> None:
    profile = _PROFILES[decl.harness]
    if "--bare" in decl.argv and decl.billing_surface != "api":
        raise EnvelopeRefusal(
            "--bare needs declared API billing: Claude's bare mode does not read "
            "CLAUDE_CODE_OAUTH_TOKEN, so it switches the billing surface; next action: set "
            "billing_surface='api' in the declaration, or drop --bare and rely on the envelope"
        )
    for key in decl.env:
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
        dirnames[:] = [d for d in dirnames if d != ".git"]
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
                if target.name in MASKED_NAMES:
                    continue  # the target is masked on its own
                rel = target_rel
            masked.append(rel)
        dirnames[:] = [d for d in dirnames if d not in MASKED_NAMES]
    return masked


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


def render(decl: EnvelopeDeclaration, *, run_root: Path) -> RenderedEnvelope:
    """Build the carrier argv for one run. ``run_root`` must not exist yet (create-once)."""
    _refuse(decl)
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
        a += ["--ro-bind-try", f"/etc/{name}", f"/etc/{name}"]
    a += ["--ro-bind-try", "/run/systemd/resolve", "/run/systemd/resolve"]
    a += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    a += ["--bind", str(run_home), JOB_HOME]

    env: dict[str, str] = {
        "HOME": JOB_HOME,
        "USER": os.environ.get("USER", "job"),
        "LOGNAME": os.environ.get("USER", "job"),
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
    }
    path_dirs = list(_BASE_PATH)
    for binary in decl.binaries:
        resolved = binary.resolve()
        a += ["--ro-bind", str(resolved), str(resolved)]
        if binary.absolute() != resolved:
            a += ["--ro-bind", str(resolved), str(binary.absolute())]
        parent = str(binary.absolute().parent)
        if parent not in path_dirs:
            path_dirs.append(parent)

    for var, rel in profile.config_env:
        _placeholder(run_home, rel, directory=True)
        env[var] = f"{JOB_HOME}/{rel}"
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
        _placeholder(run_home, item.target, directory=item.source.is_dir())
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
                a += ["--tmpfs", f"{JOB_WORK}/{rel}"]
            else:
                a += ["--ro-bind", str(empty), f"{JOB_WORK}/{rel}"]
    if decl.spool is not None:
        a += ["--bind", str(decl.spool.resolve()), JOB_SPOOL]

    env["PATH"] = ":".join(path_dirs)
    env.update(decl.env)
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
