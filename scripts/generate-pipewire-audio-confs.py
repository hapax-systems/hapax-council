#!/usr/bin/env python3
"""Dry-run Phase 6 audio route policy generator discipline.

This bootstrap intentionally writes only the route-policy manifest. It does
not rewrite live PipeWire or WirePlumber confs, and it never reloads services.
Future generator parity work can add conf emission after golden output and
round-trip checks are in place.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from shared.audio_routing_policy import (
    DEFAULT_FORBIDDEN_LINKS_PATH,
    DEFAULT_LINK_MAP_PATH,
    DEFAULT_POLICY_PATH,
    DEFAULT_TOPOLOGY_PATH,
    DEFAULT_WIREPLUMBER_DENY_CONF_PATH,
    DEFAULT_WIREPLUMBER_DENY_SCRIPT_PATH,
    audio_routing_manifest_json,
    generated_route_map_texts,
    generated_wireplumber_deny_policy_texts,
    load_audio_routing_policy,
    load_audio_topology_descriptor,
)
from shared.perception_conf_gen import generated_contact_mic_conf_text
from shared.perception_registry import load_default_registry

CONTACT_MIC_CONF_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "pipewire" / "hapax-contact-mic.conf"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--topology", type=Path, default=DEFAULT_TOPOLOGY_PATH)
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--write-route-maps", action="store_true")
    parser.add_argument("--write-wireplumber-deny-policy", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-route-maps", action="store_true")
    parser.add_argument("--check-wireplumber-deny-policy", action="store_true")
    parser.add_argument("--check-installed-route-maps", action="store_true")
    parser.add_argument(
        "--installed-hapax-dir",
        type=Path,
        default=Path.home() / ".config" / "hapax",
    )
    parser.add_argument("--write-source-confs", action="store_true")
    parser.add_argument("--check-source-confs", action="store_true")
    args = parser.parse_args()

    policy = load_audio_routing_policy(args.policy)
    manifest_text = audio_routing_manifest_json(policy)
    manifest_path = Path(policy.generated_output.manifest_path)

    if args.write_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(manifest_text, encoding="utf-8")

    if args.check:
        existing = manifest_path.read_text(encoding="utf-8")
        if existing != manifest_text:
            raise SystemExit(
                f"{manifest_path} is stale; rerun scripts/generate-pipewire-audio-confs.py "
                "--write-manifest"
            )

    if args.write_route_maps or args.check_route_maps or args.check_installed_route_maps:
        topology = load_audio_topology_descriptor(args.topology)
        desired_text, forbidden_text = generated_route_map_texts(topology, policy)
        if args.write_route_maps:
            DEFAULT_LINK_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
            DEFAULT_LINK_MAP_PATH.write_text(desired_text, encoding="utf-8")
            DEFAULT_FORBIDDEN_LINKS_PATH.write_text(forbidden_text, encoding="utf-8")
        if args.check_route_maps:
            expected = {
                DEFAULT_LINK_MAP_PATH: desired_text,
                DEFAULT_FORBIDDEN_LINKS_PATH: forbidden_text,
            }
            stale = [
                path
                for path, text in expected.items()
                if not path.exists() or path.read_text(encoding="utf-8") != text
            ]
            if stale:
                raise SystemExit(
                    "route map artifact(s) stale: "
                    + ", ".join(str(path) for path in stale)
                    + "; rerun scripts/generate-pipewire-audio-confs.py --write-route-maps"
                )
        if args.check_installed_route_maps:
            installed = {
                args.installed_hapax_dir / "audio-link-map.conf": desired_text,
                args.installed_hapax_dir / "audio-forbidden-links.conf": forbidden_text,
            }
            stale = [
                path
                for path, text in installed.items()
                if not path.exists() or path.read_text(encoding="utf-8") != text
            ]
            if stale:
                raise SystemExit(
                    "installed route map(s) differ from generated repo policy: "
                    + ", ".join(str(path) for path in stale)
                )

    if args.write_wireplumber_deny_policy or args.check_wireplumber_deny_policy:
        deny_conf_text, deny_script_text = generated_wireplumber_deny_policy_texts()
        expected = {
            DEFAULT_WIREPLUMBER_DENY_CONF_PATH: deny_conf_text,
            DEFAULT_WIREPLUMBER_DENY_SCRIPT_PATH: deny_script_text,
        }
        if args.write_wireplumber_deny_policy:
            for path, text in expected.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        if args.check_wireplumber_deny_policy:
            stale = [
                path
                for path, text in expected.items()
                if not path.exists() or path.read_text(encoding="utf-8") != text
            ]
            if stale:
                raise SystemExit(
                    "WirePlumber deny policy artifact(s) stale: "
                    + ", ".join(str(path) for path in stale)
                    + "; rerun scripts/generate-pipewire-audio-confs.py "
                    "--write-wireplumber-deny-policy"
                )

    if args.write_source_confs or args.check_source_confs:
        # Pipewire SOURCE confs generated from the perception registry's typed
        # hw_source — the contact-mic conf was the eavesdrop class (hand-typed
        # node.target drifted to the retired L-12). The generator is the sole
        # writer; deployed bytes are byte-diff-gated (REQ-20260616 Phase 1).
        contact_mic_text = generated_contact_mic_conf_text(load_default_registry())
        if args.write_source_confs:
            CONTACT_MIC_CONF_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONTACT_MIC_CONF_PATH.write_text(contact_mic_text, encoding="utf-8")
        if args.check_source_confs:
            if (
                not CONTACT_MIC_CONF_PATH.exists()
                or CONTACT_MIC_CONF_PATH.read_text(encoding="utf-8") != contact_mic_text
            ):
                raise SystemExit(
                    f"{CONTACT_MIC_CONF_PATH} differs from the registry-generated text; "
                    "rerun scripts/generate-pipewire-audio-confs.py --write-source-confs"
                )

    if not args.write_manifest and not args.check:
        if (
            args.write_route_maps
            or args.check_route_maps
            or args.check_installed_route_maps
            or args.write_wireplumber_deny_policy
            or args.check_wireplumber_deny_policy
            or args.write_source_confs
            or args.check_source_confs
        ):
            return 0
        print(manifest_text, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
