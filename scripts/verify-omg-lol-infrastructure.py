#!/usr/bin/env python3
"""Validate the omg.lol infrastructure evidence envelope.

This is intentionally a static verifier. Live omg.lol checks remain manual
or operator-run because they depend on bearer-token availability and can expose
private account details if printed carelessly.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "config" / "omg-lol.yaml"

REQUIRED_ACCEPTANCE_SECTIONS = (
    "directory_listing",
    "address_verification",
    "settings_surfaces",
    "dns",
    "pgp",
)
VALID_PGP_STATUSES = {"uploaded", "deferred"}
SECRET_KEY_FRAGMENTS = ("api_key", "apikey", "bearer", "password", "secret", "token")
REQUIRED_PUBLICATION_FRONTMATTER_POLICY_FIELDS = (
    "status",
    "publication_allowed_without_bus",
    "direct_public_egress_allowed",
    "review_required",
    "claim_ceiling",
)
REQUIRED_PUBLICATION_FRONTMATTER_GATES = {
    "source_artifact_public_safe",
    "rights_privacy_redaction_pass",
    "target_surface_allowlist_pass",
    "claim_review_current",
}


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return loaded


def _walk_mapping(value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            yield path + (key_text,), child
            yield from _walk_mapping(child, path + (key_text,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_mapping(child, path + (str(index),))


def _has_secret_key_name(path: tuple[str, ...]) -> bool:
    joined = ".".join(path).lower().replace("-", "_")
    return any(fragment in joined for fragment in SECRET_KEY_FRAGMENTS)


def validate_config(config: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []

    if config.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if config.get("service") != "omg.lol":
        errors.append("service must be omg.lol")
    if config.get("address") != "hapax":
        errors.append("address must be hapax")

    acceptance = config.get("acceptance")
    if not isinstance(acceptance, Mapping):
        errors.append("acceptance must be a mapping")
        acceptance = {}

    for section in REQUIRED_ACCEPTANCE_SECTIONS:
        if section not in acceptance:
            errors.append(f"acceptance.{section} is required")

    settings = acceptance.get("settings_surfaces")
    if isinstance(settings, Mapping):
        if settings.get("audited") is not True:
            errors.append("acceptance.settings_surfaces.audited must be true")
        if settings.get("no_undocumented_writes") is not True:
            errors.append("acceptance.settings_surfaces.no_undocumented_writes must be true")
    elif "settings_surfaces" in acceptance:
        errors.append("acceptance.settings_surfaces must be a mapping")

    dns = acceptance.get("dns")
    if isinstance(dns, Mapping):
        custom_records = dns.get("custom_records")
        if not isinstance(custom_records, list):
            errors.append("acceptance.dns.custom_records must be a list")
    elif "dns" in acceptance:
        errors.append("acceptance.dns must be a mapping")

    pgp = acceptance.get("pgp")
    if isinstance(pgp, Mapping):
        status = pgp.get("status")
        if status not in VALID_PGP_STATUSES:
            errors.append("acceptance.pgp.status must be uploaded or deferred")
        if status == "deferred" and not pgp.get("reason"):
            errors.append("acceptance.pgp.reason is required when status is deferred")
    elif "pgp" in acceptance:
        errors.append("acceptance.pgp must be a mapping")

    configured_settings = config.get("configured_settings")
    if not isinstance(configured_settings, Mapping):
        errors.append("configured_settings must be a mapping")

    blockers = config.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        errors.append("blockers must be a non-empty list while live acceptance is unmet")

    policy = config.get("publication_frontmatter_policy")
    if not isinstance(policy, Mapping):
        errors.append("publication_frontmatter_policy must be a mapping")
        policy = {}
    for field in REQUIRED_PUBLICATION_FRONTMATTER_POLICY_FIELDS:
        if field not in policy:
            errors.append(f"publication_frontmatter_policy.{field} is required")
    if policy.get("publication_allowed_without_bus") is not False:
        errors.append(
            "publication_frontmatter_policy.publication_allowed_without_bus must be false"
        )
    if policy.get("direct_public_egress_allowed") is not False:
        errors.append("publication_frontmatter_policy.direct_public_egress_allowed must be false")
    if policy.get("review_required") != "Claim Verification Council":
        errors.append(
            "publication_frontmatter_policy.review_required must be Claim Verification Council"
        )
    policy_text = str(policy.get("claim_ceiling") or "").lower()
    for required in ("source refs", "rights", "privacy", "redaction", "target surfaces"):
        if required not in policy_text:
            errors.append(f"publication_frontmatter_policy.claim_ceiling missing {required!r}")
    required_gates = set(policy.get("required_gates") or ())
    if required_gates:
        missing = sorted(REQUIRED_PUBLICATION_FRONTMATTER_GATES - required_gates)
        if missing:
            errors.append(
                "publication_frontmatter_policy.required_gates missing: " + ", ".join(missing)
            )

    for path, value in _walk_mapping(config):
        if _has_secret_key_name(path):
            errors.append(f"secret-like key is not allowed in config: {'.'.join(path)}")
        if isinstance(value, str) and "Bearer " in value:
            errors.append(f"bearer-looking value is not allowed in config: {'.'.join(path)}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"omg-lol infrastructure config failed to load: {exc}", file=sys.stderr)
        return 2

    errors = validate_config(config)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"OK: {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
