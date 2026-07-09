#!/usr/bin/env python3
"""Check hook/runtime gate wiring against hooks/gate-manifest.yaml."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "hooks" / "gate-manifest.yaml"
DEFAULT_CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"


def _as_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"malformed YAML at {path}: {exc}") from exc
    return _as_mapping(data, str(path))


def _hook_basename(command: str) -> str:
    text = command.strip()
    if not text:
        return command
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    hook_names = [Path(token).name for token in tokens if Path(token).name.endswith(".sh")]
    if hook_names:
        return hook_names[-1]
    return Path(tokens[0]).name


def _literal_list(value: Any, label: str) -> list[str]:
    return [str(item) for item in _as_list(value, label)]


def _phase_entries_from_claude_settings(settings_path: Path) -> dict[str, list[dict[str, Any]]]:
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = _as_mapping(data.get("hooks"), f"{settings_path}: hooks")
    phases: dict[str, list[dict[str, Any]]] = {}
    for phase, entries_raw in hooks.items():
        entries: list[dict[str, Any]] = []
        for index, entry_raw in enumerate(_as_list(entries_raw, f"{settings_path}: hooks.{phase}")):
            entry = _as_mapping(entry_raw, f"{settings_path}: hooks.{phase}[{index}]")
            hook_names: list[str] = []
            for hook_raw in _as_list(
                entry.get("hooks"), f"{settings_path}: hooks.{phase}[{index}].hooks"
            ):
                hook = _as_mapping(hook_raw, f"{settings_path}: hook command")
                if hook.get("type") != "command":
                    continue
                command = hook.get("command")
                if not isinstance(command, str):
                    raise ValueError(f"{settings_path}: hook command is not a string")
                hook_names.append(_hook_basename(command))
            entries.append({"matcher": str(entry.get("matcher", "")), "hooks": hook_names})
        phases[str(phase)] = entries
    return phases


def _manifest_claude_phases(runtime: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    phases = _as_mapping(runtime.get("phases"), "manifest claude.phases")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for phase, entries_raw in phases.items():
        entries: list[dict[str, Any]] = []
        for index, entry_raw in enumerate(_as_list(entries_raw, f"manifest claude.{phase}")):
            entry = _as_mapping(entry_raw, f"manifest claude.{phase}[{index}]")
            entries.append(
                {
                    "matcher": str(entry.get("matcher", "")),
                    "hooks": _literal_list(entry.get("hooks"), f"manifest claude.{phase}.hooks"),
                }
            )
        normalized[str(phase)] = entries
    return normalized


def check_claude_settings(
    runtime: dict[str, Any],
    *,
    settings_path: Path | None,
    require_settings: bool,
    skip: bool,
) -> list[str]:
    if skip:
        return []
    path = settings_path or Path(
        os.environ.get("HAPAX_CLAUDE_SETTINGS_FILE", DEFAULT_CLAUDE_SETTINGS)
    )
    if not path.exists():
        if require_settings:
            return [f"claude settings missing: {path}"]
        print(f"SKIP claude live settings not found: {path}")
        return []
    expected = _manifest_claude_phases(runtime)
    actual = _phase_entries_from_claude_settings(path)
    errors: list[str] = []
    if actual != expected:
        expected_phases = set(expected)
        actual_phases = set(actual)
        for phase in sorted(expected_phases | actual_phases):
            if actual.get(phase) != expected.get(phase):
                errors.append(
                    f"claude {phase} drift: expected {expected.get(phase)!r}, got {actual.get(phase)!r}"
                )
    return errors


def _extract_hook_array(text: str, function_name: str) -> list[str]:
    pattern = (
        rf"^{re.escape(function_name)}\(\)\s*\{{.*?"
        r"local hooks=\(\s*(?P<body>.*?)\s*\)\s*local hook"
    )
    match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
    if match is None:
        raise ValueError(f"could not locate hook array in {function_name}")
    return re.findall(r"([A-Za-z0-9_.-]+\.sh)", match.group("body"))


def _extract_for_hook_list(text: str, function_name: str) -> list[str]:
    pattern = rf"^{re.escape(function_name)}\(\)\s*\{{.*?for hook in (?P<body>[^;]+); do"
    match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
    if match is None:
        raise ValueError(f"could not locate hook loop in {function_name}")
    return re.findall(r"([A-Za-z0-9_.-]+\.sh)", match.group("body"))


def collect_codex_adapter(adapter_path: Path) -> dict[str, Any]:
    text = adapter_path.read_text(encoding="utf-8")
    return {
        "SessionStart": _extract_for_hook_list(text, "run_session_start"),
        "PreToolUse": {
            "shell": _extract_hook_array(text, "run_pre_shell"),
            "mutation": _extract_hook_array(text, "run_pre_mutation_event"),
        },
        "PostToolUse": {
            "shell": _extract_hook_array(text, "run_post_shell"),
            "mutation": _extract_hook_array(text, "run_post_mutation_event"),
        },
        "Stop": _extract_for_hook_list(text, "run_stop"),
    }


def _check_codex_config(
    runtime: dict[str, Any],
    *,
    launcher_path: Path,
    config_path: Path,
) -> list[str]:
    errors: list[str] = []
    adapter_name = str(runtime.get("hook_adapter"))
    config_phases = _literal_list(runtime.get("config_phases"), "manifest codex.config_phases")

    launcher_text = launcher_path.read_text(encoding="utf-8")
    for phase in config_phases:
        if f"hooks.{phase}=" not in launcher_text:
            errors.append(f"codex launcher missing hooks.{phase} override")
    if adapter_name not in launcher_text:
        errors.append(f"codex launcher missing adapter marker {adapter_name}")

    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    hooks = _as_mapping(config.get("hooks"), f"{config_path}: hooks")
    for phase in config_phases:
        entries = _as_list(hooks.get(phase), f"{config_path}: hooks.{phase}")
        commands = [
            _hook_basename(str(entry.get("command", "")))
            for entry in entries
            if isinstance(entry, dict)
        ]
        if commands != [adapter_name]:
            errors.append(
                f"codex config {phase} drift: expected {[adapter_name]!r}, got {commands!r}"
            )
    return errors


def check_codex(
    runtime: dict[str, Any],
    *,
    adapter_path: Path,
    launcher_path: Path,
    config_path: Path,
) -> list[str]:
    expected = _as_mapping(runtime.get("adapter_phases"), "manifest codex.adapter_phases")
    actual = collect_codex_adapter(adapter_path)
    errors: list[str] = []
    if actual != expected:
        for phase in sorted(set(expected) | set(actual)):
            if actual.get(phase) != expected.get(phase):
                errors.append(
                    f"codex adapter {phase} drift: expected {expected.get(phase)!r}, got {actual.get(phase)!r}"
                )
    errors.extend(
        _check_codex_config(runtime, launcher_path=launcher_path, config_path=config_path)
    )
    return errors


def _check_marker_file(runtime_name: str, label: str, path: Path, markers: list[str]) -> list[str]:
    if not path.exists():
        return [f"{runtime_name} {label} missing: {path}"]
    text = path.read_text(encoding="utf-8")
    missing = [marker for marker in markers if marker not in text]
    if not missing:
        return []
    return [f"{runtime_name} {label} marker drift in {path}: missing {missing!r}"]


def check_marker_runtime(
    runtime_name: str, runtime: dict[str, Any], *, repo_root: Path, script_path: Path
) -> list[str]:
    errors = _check_marker_file(
        runtime_name,
        "capability",
        script_path,
        _literal_list(
            runtime.get("capability_markers"), f"manifest {runtime_name}.capability_markers"
        ),
    )
    adapter_raw = runtime.get("hook_adapter")
    if adapter_raw:
        adapter_path = Path(str(adapter_raw))
        if not adapter_path.is_absolute():
            adapter_path = repo_root / adapter_path
        errors.extend(
            _check_marker_file(
                runtime_name,
                "adapter",
                adapter_path,
                _literal_list(
                    runtime.get("adapter_markers"), f"manifest {runtime_name}.adapter_markers"
                ),
            )
        )
        if adapter_path.exists() and not os.access(adapter_path, os.X_OK):
            errors.append(f"{runtime_name} adapter not executable: {adapter_path}")
    return errors


def check_ci(runtime: dict[str, Any], *, workflow_path: Path) -> list[str]:
    text = workflow_path.read_text(encoding="utf-8")
    data = _load_yaml(workflow_path)
    jobs = _as_mapping(data.get("jobs"), f"{workflow_path}: jobs")
    expected_jobs = _literal_list(runtime.get("jobs"), "manifest ci.jobs")
    actual_jobs = [str(name) for name in jobs]
    errors: list[str] = []
    if actual_jobs != expected_jobs:
        errors.append(f"ci jobs drift: expected {expected_jobs!r}, got {actual_jobs!r}")

    missing_markers = [
        marker
        for marker in _literal_list(runtime.get("run_markers"), "manifest ci.run_markers")
        if marker not in text
    ]
    if missing_markers:
        errors.append(f"ci run marker drift in {workflow_path}: missing {missing_markers!r}")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--claude-settings", type=Path)
    parser.add_argument("--require-claude-settings", action="store_true")
    parser.add_argument("--skip-claude-settings", action="store_true")
    parser.add_argument("--codex-adapter", type=Path)
    parser.add_argument("--codex-launcher", type=Path)
    parser.add_argument("--codex-config", type=Path)
    parser.add_argument("--vibe-launcher", type=Path)
    parser.add_argument("--ci-workflow", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    manifest_path = args.manifest if args.manifest.is_absolute() else repo_root / args.manifest
    manifest = _load_yaml(manifest_path)
    runtimes = _as_mapping(manifest.get("runtimes"), "manifest runtimes")

    def path_from_arg(override: Path | None, default: str) -> Path:
        path = override or Path(default)
        return path if path.is_absolute() else repo_root / path

    errors: list[str] = []
    errors.extend(
        check_claude_settings(
            _as_mapping(runtimes.get("claude"), "manifest runtimes.claude"),
            settings_path=args.claude_settings,
            require_settings=args.require_claude_settings,
            skip=args.skip_claude_settings,
        )
    )
    errors.extend(
        check_codex(
            _as_mapping(runtimes.get("codex"), "manifest runtimes.codex"),
            adapter_path=path_from_arg(args.codex_adapter, "hooks/scripts/codex-hook-adapter.sh"),
            launcher_path=path_from_arg(args.codex_launcher, "scripts/hapax-codex"),
            config_path=path_from_arg(args.codex_config, "config/codex/config.toml"),
        )
    )
    for runtime_name, arg_name in (("vibe", "vibe_launcher"),):
        runtime = _as_mapping(runtimes.get(runtime_name), f"manifest runtimes.{runtime_name}")
        default_script = str(runtime.get("script"))
        override = getattr(args, arg_name)
        errors.extend(
            check_marker_runtime(
                runtime_name,
                runtime,
                repo_root=repo_root,
                script_path=path_from_arg(override, default_script),
            )
        )
    errors.extend(
        check_ci(
            _as_mapping(runtimes.get("ci"), "manifest runtimes.ci"),
            workflow_path=path_from_arg(
                args.ci_workflow,
                str(_as_mapping(runtimes.get("ci"), "manifest runtimes.ci").get("workflow")),
            ),
        )
    )

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"gate-manifest-check: OK ({manifest_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
