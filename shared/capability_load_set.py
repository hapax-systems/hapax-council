"""Observe declared native inputs without mistaking host presence for loading.

The declaration lives on PlatformCapabilityRoute. Results belong in existing
launch/measurement receipts; this module creates no ledger and grants no authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from shared.platform_capability_registry import NativeLoadSet


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def observe_load_set(
    declaration: NativeLoadSet | None,
    *,
    home: Path,
    project: Path,
    env: Mapping[str, str],
    native_receipts: Sequence[Mapping[str, str]] | None = None,
) -> dict:
    """Join filesystem bytes and optional native path/hash receipts to declaration.

    A native receipt must describe bytes witnessed at the loading boundary,
    not an agent's assertion or a later filesystem read. Callers retain the raw
    evidence separately. Missing native observations stay unobserved.
    """
    if declaration is None:
        return {"declaration": "unobserved", "native_loading": "unobserved", "may_authorize": False}
    native_home = home / declaration.native_home
    if declaration.home_env and env.get(declaration.home_env):
        native_home = Path(env[declaration.home_env]).expanduser()
    roots = {"native_home": native_home.resolve(), "project": project.resolve()}
    files = []
    declared: dict[str, str | None] = {}
    problems = []
    for item in declaration.files:
        path = roots[item.root] / item.path
        key = str(path.resolve())
        if key in declared and declared[key] != item.sha256:
            raise ValueError(
                f"conflicting native load declarations for {key}; next action: reconcile "
                "native-home/project aliases or declared digests before observing this load set"
            )
        declared[key] = item.sha256
        try:
            body = path.read_bytes()
            observed = _sha(body)
            state = "match" if item.sha256 == observed else "unobserved_digest"
            if item.sha256 is not None and observed != item.sha256:
                state = "digest_mismatch"
                problems.append(f"digest_mismatch:{item.root}:{item.path}")
        except FileNotFoundError:
            observed = None
            state = "missing" if item.required else "absent_optional"
            if item.required:
                problems.append(f"missing:{item.root}:{item.path}")
        except OSError as exc:
            observed = None
            state = "unreadable"
            problems.append(f"unreadable:{item.root}:{item.path}:{type(exc).__name__}")
        files.append(
            {
                "root": item.root,
                "path": item.path,
                "observed_path": key,
                "state": state,
                "sha256": observed,
            }
        )

    # Presence is only a discovery hazard. Do not call these unexpected_load
    # until the native loader actually reports consuming the bytes.
    candidates = {
        native_home / name
        for name in ("AGENTS.override.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "SYSTEM.md")
    }
    cwd = project.resolve()
    candidates.update(
        cwd / name
        for name in ("AGENTS.override.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "SYSTEM.md")
    )
    unexpected_present = sorted(
        str(p) for p in candidates if p.is_file() and str(p.resolve()) not in declared
    )
    unexpected_load = []
    observed_keys: set[str] = set()
    for receipt in native_receipts or ():
        key = str(Path(receipt["path"]).resolve())
        expected = declared.get(key)
        if key not in declared or (expected is not None and expected != receipt.get("sha256")):
            unexpected_load.append({"path": receipt["path"], "sha256": receipt.get("sha256")})
        elif expected is not None and expected == receipt.get("sha256"):
            observed_keys.add(key)
    required_keys = {
        str((roots[item.root] / item.path).resolve())
        for item in declaration.files
        if item.required and item.kind == "instructions"
    }
    native_loading = "unobserved"
    if native_receipts is not None:
        native_loading = "unexpected_load" if unexpected_load else "incomplete"
        if not unexpected_load and required_keys and required_keys <= observed_keys:
            native_loading = "observed"
    return {
        "declaration": "present",
        "declaration_sha256": _sha(
            json.dumps(
                declaration.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ),
        "source_refs": list(declaration.source_refs),
        "resolved_roots": {name: str(path) for name, path in roots.items()},
        "files": files,
        "problems": problems,
        "unexpected_present": unexpected_present,
        "unexpected_load": unexpected_load,
        "native_loading": native_loading,
        "extensions": {
            name: getattr(declaration, name) for name in ("plugins", "skills", "hooks", "mcp")
        },
        "memory_scope": declaration.memory_scope,
        "loading_flags": declaration.loading_flags,
        "boundary": "host_observation",
        "may_authorize": False,
    }
