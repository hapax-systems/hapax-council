"""Construct execution identity from the registry, never from harness defaults.

This is identity resolution, not route admission or model selection. The caller
must already have selected a governed route (or an explicit descriptor leaf).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from shared.platform_capability_registry import (
    PLATFORM_CAPABILITY_REGISTRY,
    ExecutionDescriptor,
    ModelId,
    PlatformCapabilityRegistryError,
    load_platform_capability_registry_for_dispatch,
    materialize_descriptor_leaves,
)


class ExecutionIdentityError(ValueError):
    """A launch cannot prove its declared execution identity."""


def resolve_execution_descriptor(
    route_id: str, *, registry_path: Path | None = None
) -> ExecutionDescriptor:
    path = registry_path or Path(
        os.environ.get("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(PLATFORM_CAPABILITY_REGISTRY))
    )
    try:
        registry, _ = load_platform_capability_registry_for_dispatch(path, apply_receipts=False)
        descriptor = materialize_descriptor_leaves(registry)[route_id]
        if descriptor.model_id == ModelId.UNKNOWN:
            raise ValueError("model identity is unknown")
        return descriptor
    except (KeyError, ValueError, PlatformCapabilityRegistryError) as exc:
        raise ExecutionIdentityError(
            f"refusing execution of {route_id!r}: missing or invalid ExecutionDescriptor; "
            f"remedy: declare the route's model and effort in {path} and retry ({exc})"
        ) from exc


def codex_execution_args(descriptor: ExecutionDescriptor) -> list[str]:
    # Unimplemented axes must not silently inherit host settings or get dropped.
    if (
        descriptor.effort == "none"
        or descriptor.context_mode != "standard"
        or descriptor.fast_mode != "off"
        or descriptor.quantization != "none"
    ):
        raise ExecutionIdentityError(
            "refusing unsupported Codex ExecutionDescriptor; remedy: add a governed "
            "invocation mapping for its declared axes before launching"
        )
    return [
        "-c",
        f"model={json.dumps(descriptor.model_id)}",
        "-c",
        f"model_reasoning_effort={json.dumps(descriptor.effort)}",
    ]


def reject_codex_identity_overrides(args: list[str]) -> None:
    for index, arg in enumerate(args):
        # Both long/short CLI forms and quoted/dotted TOML keys can override identity.
        if arg in {"--model", "--profile", "--oss", "--local-provider"} or arg.startswith(
            ("--model=", "--profile=", "--local-provider=", "-m", "-p")
        ):
            raise ExecutionIdentityError(
                "refusing execution identity override; remedy: select --execution-route "
                "with the required registry descriptor"
            )
        config = None
        if arg in {"-c", "--config"} and index + 1 < len(args):
            config = args[index + 1]
        elif arg.startswith("--config="):
            config = arg.partition("=")[2]
        elif arg.startswith("-c") and arg != "-c":
            config = arg[2:].removeprefix("=")
        if config is not None:
            key = re.sub(r"[\s\"']", "", config.partition("=")[0])
            if any(
                part in {"model", "model_reasoning_effort", "model_provider", "profile"}
                for part in key.split(".")
            ):
                raise ExecutionIdentityError(
                    "refusing execution identity config override; remedy: edit the governed "
                    "ExecutionDescriptor instead"
                )


def claude_execution_binding(descriptor: ExecutionDescriptor) -> dict:
    """Bind request controls; native execution observation remains separate.

    Claude's effort environment variable takes precedence over --effort. Both
    must come from this same frozen descriptor rather than the caller's settings.
    """
    if (
        not descriptor.model_id.startswith("claude-")
        or descriptor.effort not in {"low", "medium", "high", "xhigh", "max"}
        or descriptor.context_mode != "standard"
        or descriptor.fast_mode != "off"
        or descriptor.quantization != "none"
    ):
        raise ExecutionIdentityError(
            "refusing unsupported Claude ExecutionDescriptor; remedy: add a governed "
            "invocation mapping for its declared axes before launching"
        )
    return {
        "argv": ["--model", str(descriptor.model_id), "--effort", str(descriptor.effort)],
        "env": {
            "CLAUDE_CODE_EFFORT_LEVEL": str(descriptor.effort),
            "CLAUDE_CODE_DISABLE_FAST_MODE": "1",
        },
        "descriptor": descriptor.model_dump(mode="json"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", required=True)
    parser.add_argument("--with-descriptor", action="store_true")
    parser.add_argument("--harness", choices=("codex", "claude"), default="codex")
    parser.add_argument("extra", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.harness == "claude":
            if not args.route.startswith("claude.") or args.extra:
                raise ExecutionIdentityError(
                    "refusing non-Claude route or extra identity arguments; remedy: "
                    "select the declared Claude route without overrides"
                )
            descriptor = resolve_execution_descriptor(args.route)
            print(json.dumps(claude_execution_binding(descriptor)))
            return 0
        if not args.route.startswith("codex."):
            raise ExecutionIdentityError("refusing non-Codex route in Codex launcher")
        reject_codex_identity_overrides(args.extra)
        descriptor = resolve_execution_descriptor(args.route)
        argv = codex_execution_args(descriptor)
        print(
            json.dumps(
                {"argv": argv, "descriptor": descriptor.model_dump(mode="json")}
                if args.with_descriptor
                else argv
            )
        )
    except ExecutionIdentityError as exc:
        print(str(exc), file=sys.stderr)
        return 9
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
