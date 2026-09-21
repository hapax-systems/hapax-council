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
import shlex
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
        if name not in bindings:
            raise ValueError(
                f"unknown --binding {name!r}; next action: choose from "
                + ", ".join(sorted(bindings))
            )
        binding = bindings[name]
        body = common
        if binding.get("fragment"):
            body += "\n" + (config / binding["fragment"]).read_text()
        body = (
            "<!-- Generated from Council config/agent-instructions; edit the source. -->\n\n" + body
        )
        payload = body.encode()
        if len(body) > binding.get("max_chars", sys.maxsize):
            raise ValueError(
                f"{name}: instruction character limit exceeded "
                f"({len(body)} characters, limit {binding['max_chars']}); reduce shared/native content "
                "or move domain guidance to a scoped reference, then retry"
            )
        if len(payload) > binding.get("max_bytes", sys.maxsize):
            raise ValueError(
                f"{name}: instruction byte limit exceeded "
                f"({len(payload)} bytes, limit {binding['max_bytes']}); reduce shared/native content "
                "or move domain guidance to a scoped reference, then retry"
            )
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
        try:
            before = tomllib.loads(body)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(
                f"invalid native TOML in {target}; next action: repair its TOML syntax "
                "before retrying instruction installation"
            ) from exc
        expected = copy.deepcopy(before)
        compat = expected.setdefault("compat", {})
        if not isinstance(compat, dict) or not isinstance(compat.get("claude", {}), dict):
            raise ValueError(
                f"invalid native TOML structure in {target}: compat and compat.claude must be "
                "TOML tables; next action: repair these tables while preserving other settings, "
                "then retry instruction installation"
            )
        compat.setdefault("claude", {})["agents"] = False
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
        try:
            preserved = tomllib.loads(body) == expected
        except tomllib.TOMLDecodeError:
            preserved = False
        if not preserved:
            raise ValueError(
                f"cannot preserve native TOML in {target} while setting compat.claude.agents; "
                "next action: express this setting under a standalone [compat.claude] table "
                "with an agents = true/false line, preserving other settings, then retry"
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
                # A failed rename must not leave a deterministic temporary
                # link name that blocks the next recovery attempt.
                with tempfile.TemporaryDirectory(
                    prefix=f".{path.name}.restore-", dir=path.parent
                ) as temporary:
                    temp = Path(temporary) / "link"
                    temp.symlink_to(item["target"])
                    os.replace(temp, path)
            else:
                path.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    if errors:
        raise OSError(f"rollback incomplete; retained backup {backup}: {'; '.join(errors)}")


def recovery_command(home: Path, backup: Path) -> str:
    return shlex.join(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--home",
            str(home),
            "--restore-backup",
            str(backup),
        ]
    )


def recover_pending(state: Path, backup: Path) -> None:
    """Recover only this unresolved transaction's preimages or known postimages.

    The pending record is written before publication. A failed first install,
    upgrade or rollback remains recoverable even if current.json was restored.
    All destinations are checked before any restore; foreign edits narrow the
    action to manual reconciliation. Installers refuse successors while pending.
    """
    pending = json.loads((state / "pending.json").read_text())
    if Path(pending["backup"]).resolve() != backup.resolve():
        raise ValueError("backup is not the pending transaction; recover that transaction first")
    originals = json.loads((backup / "preimages.json").read_text())
    for index, (item, post) in enumerate(zip(originals, pending["postimages"], strict=True)):
        path = Path(item["path"])
        if matches_preimage(path, item, backup, index):
            continue
        if preimage(path) != {"kind": "file", "mode": 0o600} or digest(path.read_bytes()) != post:
            raise ValueError(
                f"transaction output changed; reconcile against retained preimage before recovery: {path}"
            )
    restore(backup)
    (state / "pending.json").unlink()


def parse_current_receipt(body: bytes, path: Path) -> dict:
    current = json.loads(body)
    if not isinstance(current, dict):
        raise ValueError(
            f"{path}: receipt must be a JSON object; "
            "next action: reconcile the receipt with the retained install backup before retrying"
        )
    return current


def check_bindings(receipt: dict, home: Path) -> dict:
    """Read-only comparison with rendered expectations, never a loading claim."""
    result = copy.deepcopy(receipt)
    result["observation"] = "filesystem_drift_check"
    for item in result["files"]:
        path = Path(item["path"])
        observed = digest(path.read_bytes()) if path.is_file() else None
        item["observed_sha256"] = observed
        item["matches"] = not path.is_symlink() and observed == item["sha256"]
    state = home / ".config/hapax/agent-instructions"
    current_path = state / "current.json"
    current = (
        parse_current_receipt(current_path.read_bytes(), current_path)
        if current_path.is_file()
        else {}
    )
    result["receipt_matches"] = (
        current.get("source_revision") == receipt["source_revision"]
        and current.get("files") == receipt["files"]
    )
    result["pending_transaction"] = os.path.lexists(state / "pending.json")
    result["matches"] = (
        all(item["matches"] for item in result["files"])
        and result["receipt_matches"]
        and not result["pending_transaction"]
    )
    return result


def verified_current_installation(
    receipt: dict, outputs: list[tuple[str, Path, bytes]], state: Path
) -> dict | None:
    """Reuse only a complete receipt with unchanged regular 0600 postimages."""
    try:
        current_path = state / "current.json"
        if preimage(current_path) != {"kind": "file", "mode": 0o600}:
            return None
        current = json.loads(current_path.read_bytes())
        if not isinstance(current, dict):
            return None
        rollback = current.get("rollback")
        if not isinstance(rollback, str) or not rollback or "\0" in rollback:
            return None
        # Exact equality validates the supported receipt shape and the complete
        # binding/path/hash/byte-count selection, including its source revision.
        if current != {**receipt, "rollback": rollback}:
            return None
        for _, path, body in outputs:
            # check_bindings does not check mode; publication and pending
            # recovery both require regular files with mode 0600.
            if preimage(path) != {"kind": "file", "mode": 0o600}:
                return None
            if path.read_bytes() != body:
                return None
    except (OSError, ValueError):
        # Missing, malformed or unreadable evidence cannot justify preserving
        # a success receipt. Normal publication retains its preimages.
        return None
    return current


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
            if os.path.lexists(shadow) and (not shadow.is_file() or shadow.read_bytes().strip()):
                raise ValueError(f"{name}: {shadow} shadows the global binding; reconcile it first")
        outputs.append((name, path, payload))
        setting = instruction_setting(name, binding, path)
        if setting is not None:
            target, body, prior = setting
            outputs.append((f"{name}-instruction-setting", target, body))
            settings_before[target] = prior
    # Resolve parent directories, but not the final component: publishing
    # intentionally replaces an old file symlink rather than its target.
    destinations: dict[Path, tuple[str, Path]] = {}
    for name, path, _ in outputs:
        resolved = path.parent.resolve() / path.name
        if resolved in destinations:
            prior_name, prior_path = destinations[resolved]
            raise ValueError(
                f"native instruction destinations overlap: {prior_name} ({prior_path}) and "
                f"{name} ({path}) both resolve to {resolved}; next action: reconcile native-home "
                "overrides or directory aliases before retrying"
            )
        destinations[resolved] = (name, path)
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
        if os.path.lexists(state / "pending.json"):
            pending = json.loads((state / "pending.json").read_text())
            raise ValueError(
                "unresolved instruction transaction; next action: "
                + recovery_command(home, Path(pending["backup"]))
            )
        for path, prior in settings_before.items():
            if (path.read_bytes() if path.exists() else None) != prior:
                raise OSError(f"native settings changed during preparation; retry: {path}")
        # Keep both transaction guards ahead of reuse. An identical retry must
        # retain the original rollback boundary instead of backing up itself.
        current = verified_current_installation(receipt, outputs, state)
        if current is not None:
            return current
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
        receipt_body = json.dumps(receipt, indent=2).encode() + b"\n"
        atomic_write(
            state / "pending.json",
            json.dumps(
                {
                    "backup": str(backup),
                    "postimages": [digest(body) for _, _, body in outputs] + [digest(receipt_body)],
                },
                indent=2,
            ).encode(),
        )

        def publish_guarded(index: int, path: Path, body: bytes) -> None:
            if not matches_preimage(path, originals[index], backup, index):
                raise OSError(f"instruction destination changed during installation: {path}")
            atomic_write(path, body)

        try:
            for index, (_, path, body) in enumerate(outputs):
                publish_guarded(index, path, body)
            for _, path, body in outputs:
                if path.is_symlink() or path.read_bytes() != body:
                    raise OSError(f"instruction readback failed: {path}")
            publish_guarded(len(outputs), state / "current.json", receipt_body)
            current_path = state / "current.json"
            if current_path.is_symlink() or current_path.read_bytes() != receipt_body:
                raise OSError(f"instruction receipt readback failed: {current_path}")
        except BaseException as exc:
            try:
                # Automatic recovery has the same ownership boundary as the
                # CLI: unknown intervening bytes are never ours to overwrite.
                # Keep pending state and preimages when reconciliation is needed.
                recover_pending(state, backup)
            except (OSError, ValueError) as rollback_error:
                raise OSError(
                    f"installation failed: {exc}; {rollback_error}; next action: "
                    + recovery_command(home, backup)
                ) from exc
            raise
        (state / "pending.json").unlink()
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--source-revision")
    parser.add_argument("--restore-backup", type=Path)
    parser.add_argument("--binding", action="append")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare rendered bindings and current receipt without writes",
    )
    parser.add_argument("--use-native-home-env", action="store_true")
    args = parser.parse_args()
    if args.check and (args.apply or args.restore_backup):
        parser.error("--check cannot be combined with --apply or --restore-backup")
    try:
        if args.restore_backup is not None:
            state = args.home / ".config/hapax/agent-instructions"
            with (state / "install.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if os.path.lexists(state / "pending.json"):
                    recover_pending(state, args.restore_backup)
                    print("Recovered the pending instruction transaction.")
                    return 0
                current_path = state / "current.json"
                current_body = current_path.read_bytes()
                current = parse_current_receipt(current_body, current_path)
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
                # Retain a recoverable transaction if manual rollback itself
                # fails after restoring current.json or any earlier output.
                # Expected postimages come from the validated receipt snapshot,
                # never a later read that could adopt somebody else's edit.
                approved = {item["path"]: item["sha256"] for item in current["files"]}
                approved[str(current_path)] = digest(current_body)
                originals = json.loads((args.restore_backup / "preimages.json").read_text())
                original_paths = [item["path"] for item in originals]
                if len(original_paths) != len(approved) or set(original_paths) != set(approved):
                    raise ValueError(
                        "backup targets differ from the current installation; "
                        "inspect the receipt and backup before rollback"
                    )
                atomic_write(
                    state / "pending.json",
                    json.dumps(
                        {
                            "backup": str(args.restore_backup),
                            "postimages": [approved[path] for path in original_paths],
                        },
                        indent=2,
                    ).encode(),
                )
                recover_pending(state, args.restore_backup)
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
        if args.check:
            receipt = check_bindings(receipt, args.home)
    except (OSError, ValueError, KeyError) as exc:
        print(f"instruction binding failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2))
    return 0 if receipt.get("matches", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
