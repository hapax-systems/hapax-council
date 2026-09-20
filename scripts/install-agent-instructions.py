#!/usr/bin/env python3
"""Render/install native global instructions; invoked by post-merge deployment.

Writes Markdown, Grok's named-instruction setting, and rollback artifacts.
Trust, hooks, authentication and running processes are not changed. Use a
staged, commit-addressed source tree for deployment; a checkout is useful for
isolated verification. Filesystem readback is not a native loading receipt.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import tomllib
from pathlib import Path


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def render(source: Path, names: list[str] | None = None) -> dict[str, tuple[dict, bytes]]:
    config = source / "config/agent-instructions"
    bindings = json.loads((config / "bindings.json").read_text())
    common = (config / "AGENTS.md").read_text()
    rendered = {}
    for name in names or bindings:
        binding = bindings[name]
        body = common
        if binding.get("fragment"):
            body += "\n" + (config / binding["fragment"]).read_text()
        body = (
            "<!-- Generated from Council config/agent-instructions; edit the source. -->\n\n" + body
        )
        payload = body.encode()
        if len(body) > binding.get("max_chars", sys.maxsize):
            raise ValueError(f"{name}: instruction character limit exceeded")
        if len(payload) > binding.get("max_bytes", sys.maxsize):
            raise ValueError(f"{name}: instruction byte limit exceeded")
        rendered[name] = (binding, payload)
    return rendered


def destination(binding: dict, home: Path, env: dict[str, str]) -> Path:
    if binding.get("home_env") and env.get(binding["home_env"]):
        return Path(env[binding["home_env"]]).expanduser() / binding["filename"]
    if binding.get("xdg") and env.get("XDG_CONFIG_HOME"):
        return Path(env["XDG_CONFIG_HOME"]) / binding["xdg"]
    return home / binding["path"]


def instruction_setting(
    name: str, binding: dict, path: Path
) -> tuple[Path, bytes, bytes | None] | None:
    """Preserve native settings while preventing duplicate personal instructions.

    Grok calls named Claude instruction discovery `agents`; `rules` is a
    separate rule-directory surface. This does not disable skills, MCP or hooks.
    """
    if name == "grok" and binding.get("claude_named_instructions") is False:
        target = path.with_name("config.toml")
        prior = target.read_bytes() if target.exists() else None
        body = prior.decode() if prior is not None else ""
        before = tomllib.loads(body)
        expected = copy.deepcopy(before)
        expected.setdefault("compat", {}).setdefault("claude", {})["agents"] = False
        section = re.search(r"(?m)^\[compat\.claude\][ \t]*(?:#[^\n]*)?\n", body)
        if section:
            next_section = re.search(r"(?m)^\[", body[section.end() :])
            end = section.end() + next_section.start() if next_section else len(body)
            contents = body[section.end() : end]
            key = re.compile(r"(?m)^(agents[ \t]*=[ \t]*)(?:true|false)([ \t]*(?:#[^\n]*)?)$")
            if key.search(contents):
                contents = key.sub(r"\g<1>false\g<2>", contents)
            else:
                contents += "\nagents = false\n"
            body = body[: section.end()] + contents + body[end:]
        else:
            body += "\n[compat.claude]\nagents = false\n"
        # Unsupported TOML layouts refuse before any publication instead of
        # rewriting or losing unrelated settings.
        if tomllib.loads(body) != expected:
            raise ValueError(
                f"cannot preserve native TOML while setting {target}: compat.claude.agents"
            )
        return target, body.encode(), prior
    return None


def atomic_write(path: Path, body: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)


def preimage(path: Path) -> dict:
    if path.is_symlink():
        return {"kind": "symlink", "target": str(path.readlink())}
    if not path.exists():
        return {"kind": "absent"}
    if not path.is_file():
        raise ValueError(f"instruction destination is not a file: {path}")
    return {"kind": "file", "mode": stat.S_IMODE(path.stat().st_mode)}


def matches_preimage(path: Path, item: dict, backup: Path, index: int) -> bool:
    if preimage(path) != {k: v for k, v in item.items() if k != "path"}:
        return False
    return item["kind"] != "file" or path.read_bytes() == (backup / str(index)).read_bytes()


def restore(backup: Path, indexes: list[int] | None = None) -> None:
    receipt = json.loads((backup / "preimages.json").read_text())
    errors = []
    for index, item in reversed(list(enumerate(receipt))):
        if indexes is not None and index not in indexes:
            continue
        path = Path(item["path"])
        try:
            if matches_preimage(path, item, backup, index):
                continue
            if item["kind"] == "file":
                atomic_write(path, (backup / str(index)).read_bytes(), item["mode"])
            elif item["kind"] == "symlink":
                temp = path.with_name(f".{path.name}.restore-{backup.name}")
                temp.symlink_to(item["target"])
                os.replace(temp, path)
            else:
                path.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    if errors:
        raise OSError(f"rollback incomplete; retained backup {backup}: {'; '.join(errors)}")


def install(
    source: Path,
    home: Path,
    *,
    revision: str,
    names: list[str] | None = None,
    env: dict[str, str] | None = None,
    apply: bool = False,
) -> dict:
    env = {} if env is None else env
    rendered = render(source, names)
    state = home / ".config/hapax/agent-instructions"
    outputs = [
        (
            "shared",
            state / "AGENTS.md",
            (source / "config/agent-instructions/AGENTS.md").read_bytes(),
        )
    ]
    settings_before: dict[Path, bytes | None] = {}
    for name, (binding, payload) in rendered.items():
        path = destination(binding, home, env)
        if binding.get("shadow"):
            shadow = path.with_name(binding["shadow"])
            if shadow.exists() and shadow.read_bytes().strip():
                raise ValueError(f"{name}: {shadow} shadows the global binding; reconcile it first")
        outputs.append((name, path, payload))
        setting = instruction_setting(name, binding, path)
        if setting is not None:
            target, body, prior = setting
            outputs.append((f"{name}-instruction-setting", target, body))
            settings_before[target] = prior
    # Resolve parent directories, but not the final component: publishing
    # intentionally replaces an old file symlink rather than its target.
    paths = [p.parent.resolve() / p.name for _, p, _ in outputs]
    if len(set(paths)) != len(paths):
        raise ValueError("native instruction destinations overlap")
    receipt = {
        "source_revision": revision,
        "observation": "filesystem_readback" if apply else "render_only",
        "native_loading": "unobserved",
        "files": [
            {"binding": name, "path": str(path), "sha256": digest(body), "bytes": len(body)}
            for name, path, body in outputs
        ],
    }
    if not apply:
        return receipt
    state.mkdir(parents=True, exist_ok=True)
    with (state / "install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for path, prior in settings_before.items():
            if (path.read_bytes() if path.exists() else None) != prior:
                raise OSError(f"native settings changed during preparation; retry: {path}")
        # Save every original before publishing any payload. Include the current
        # receipt so rollback restores the reported state as well as Markdown.
        targets = [p for _, p, _ in outputs] + [state / "current.json"]
        originals = [{"path": str(p), **preimage(p)} for p in targets]
        backups = state / "backups"
        backups.mkdir(exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix="install-", dir=backups))
        for index, (path, original) in enumerate(zip(targets, originals, strict=True)):
            if original["kind"] == "file":
                atomic_write(backup / str(index), path.read_bytes())
        atomic_write(backup / "preimages.json", json.dumps(originals, indent=2).encode())
        receipt["rollback"] = str(backup)
        attempted: list[int] = []
        try:
            for index, (_, path, body) in enumerate(outputs):
                if not matches_preimage(path, originals[index], backup, index):
                    raise OSError(f"instruction destination changed during installation: {path}")
                attempted.append(index)
                atomic_write(path, body)
            for _, path, body in outputs:
                if path.is_symlink() or path.read_bytes() != body:
                    raise OSError(f"instruction readback failed: {path}")
            attempted.append(len(outputs))
            atomic_write(state / "current.json", json.dumps(receipt, indent=2).encode() + b"\n")
        except BaseException as exc:
            try:
                restore(backup, attempted)
            except OSError as rollback_error:
                raise OSError(f"installation failed: {exc}; {rollback_error}") from exc
            raise
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--source-revision")
    parser.add_argument("--restore-backup", type=Path)
    parser.add_argument("--binding", action="append")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--use-native-home-env", action="store_true")
    args = parser.parse_args()
    try:
        if args.restore_backup is not None:
            state = args.home / ".config/hapax/agent-instructions"
            with (state / "install.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                current = json.loads((state / "current.json").read_text())
                if Path(current["rollback"]).resolve() != args.restore_backup.resolve():
                    raise ValueError(
                        "backup is not the current install; inspect the successor first"
                    )
                for item in current["files"]:
                    path = Path(item["path"])
                    if path.is_symlink() or digest(path.read_bytes()) != item["sha256"]:
                        raise ValueError(
                            f"installed output changed; reconcile before rollback: {path}"
                        )
                restore(args.restore_backup)
            print("Restored the previous instruction bindings and install receipt.")
            return 0
        if not args.source_revision:
            parser.error("--source-revision is required for rendering or installation")
        receipt = install(
            args.source,
            args.home,
            revision=args.source_revision,
            names=args.binding,
            env=dict(os.environ) if args.use_native_home_env else {},
            apply=args.apply,
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"instruction binding failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
