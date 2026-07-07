from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify-omg-lol-infrastructure.py"
CONFIG_PATH = REPO_ROOT / "config" / "omg-lol.yaml"
FANOUT_CONFIG_PATH = REPO_ROOT / "config" / "omg-lol-fanout.yaml"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("verify_omg_lol_infrastructure", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repo_omg_lol_config_validates() -> None:
    module = _load_module()
    config = module.load_config(CONFIG_PATH)
    assert module.validate_config(config) == []


def test_validation_requires_acceptance_sections() -> None:
    module = _load_module()
    errors = module.validate_config(
        {
            "schema_version": 1,
            "service": "omg.lol",
            "address": "hapax",
            "publication_frontmatter_policy": {
                "status": "guarded_public_channel",
                "publication_allowed_without_bus": False,
                "direct_public_egress_allowed": False,
                "review_required": "Claim Verification Council",
                "claim_ceiling": (
                    "source refs, rights gate, privacy gate, redaction posture, and target surfaces"
                ),
            },
            "configured_settings": {},
            "acceptance": {},
            "blockers": [{"id": "x", "owner": "operator", "reason": "pending"}],
        }
    )
    assert "acceptance.directory_listing is required" in errors
    assert "acceptance.address_verification is required" in errors
    assert "acceptance.settings_surfaces is required" in errors
    assert "acceptance.dns is required" in errors
    assert "acceptance.pgp is required" in errors


def test_validation_rejects_unknown_pgp_status() -> None:
    module = _load_module()
    config = module.load_config(CONFIG_PATH)
    config["acceptance"]["pgp"]["status"] = "guessed"
    assert "acceptance.pgp.status must be uploaded or deferred" in module.validate_config(config)


def test_validation_rejects_secret_shaped_keys() -> None:
    module = _load_module()
    config = module.load_config(CONFIG_PATH)
    config["configured_settings"]["api_key"] = "redacted"
    errors = module.validate_config(config)
    assert "secret-like key is not allowed in config: configured_settings.api_key" in errors


def test_validation_requires_publication_frontmatter_policy() -> None:
    module = _load_module()
    config = module.load_config(CONFIG_PATH)
    config.pop("publication_frontmatter_policy")
    errors = module.validate_config(config)
    assert "publication_frontmatter_policy must be a mapping" in errors
    assert "publication_frontmatter_policy.review_required is required" in errors


def test_validation_rejects_direct_public_egress_policy() -> None:
    module = _load_module()
    config = module.load_config(CONFIG_PATH)
    config["publication_frontmatter_policy"]["direct_public_egress_allowed"] = True
    errors = module.validate_config(config)
    assert "publication_frontmatter_policy.direct_public_egress_allowed must be false" in errors


def test_validation_rejects_publication_without_bus_policy() -> None:
    module = _load_module()
    config = module.load_config(CONFIG_PATH)
    config["publication_frontmatter_policy"]["publication_allowed_without_bus"] = True
    errors = module.validate_config(config)
    assert "publication_frontmatter_policy.publication_allowed_without_bus must be false" in errors


def test_validation_rejects_non_council_review_policy() -> None:
    module = _load_module()
    config = module.load_config(CONFIG_PATH)
    config["publication_frontmatter_policy"]["review_required"] = "informal review"
    errors = module.validate_config(config)
    assert (
        "publication_frontmatter_policy.review_required must be Claim Verification Council"
        in errors
    )


def test_validation_rejects_incomplete_claim_ceiling() -> None:
    module = _load_module()
    config = module.load_config(CONFIG_PATH)
    config["publication_frontmatter_policy"]["claim_ceiling"] = "source refs only"
    errors = module.validate_config(config)
    assert "publication_frontmatter_policy.claim_ceiling missing 'rights'" in errors
    assert "publication_frontmatter_policy.claim_ceiling missing 'target surfaces'" in errors


def test_validation_rejects_incomplete_required_gates() -> None:
    module = _load_module()
    config = module.load_config(CONFIG_PATH)
    config["publication_frontmatter_policy"]["required_gates"] = ["source_artifact_public_safe"]
    errors = module.validate_config(config)
    assert (
        "publication_frontmatter_policy.required_gates missing: "
        "claim_review_current, no_direct_public_egress, rights_privacy_redaction_pass, "
        "source_refs_present, target_surface_allowlist_pass"
    ) in errors


def test_validation_rejects_missing_required_gates() -> None:
    module = _load_module()
    config = module.load_config(CONFIG_PATH)
    config["publication_frontmatter_policy"].pop("required_gates")
    errors = module.validate_config(config)
    assert "publication_frontmatter_policy.required_gates is required" in errors
    assert "publication_frontmatter_policy.required_gates must be a non-empty list" in errors


def test_validation_rejects_incomplete_target_surfaces() -> None:
    module = _load_module()
    config = module.load_config(CONFIG_PATH)
    config["publication_frontmatter_policy"]["target_surfaces"] = ["omg-weblog"]
    errors = module.validate_config(config)
    assert "publication_frontmatter_policy.target_surfaces missing: " in "\n".join(errors)
    assert "mastodon-post" in "\n".join(errors)
    assert "zenodo-doi" in "\n".join(errors)


def test_primary_config_pins_publication_frontmatter_policy_gates_and_targets() -> None:
    module = _load_module()
    policy = module.load_config(CONFIG_PATH)["publication_frontmatter_policy"]

    assert policy["publication_allowed_without_bus"] is False
    assert policy["direct_public_egress_allowed"] is False
    assert policy["review_required"] == "Claim Verification Council"
    assert set(policy["required_gates"]) == module.REQUIRED_PUBLICATION_FRONTMATTER_GATES
    assert set(policy["target_surfaces"]) == module.REQUIRED_PUBLICATION_TARGET_SURFACES


def test_fanout_config_pins_publication_frontmatter_policy_gates() -> None:
    import yaml

    config = yaml.safe_load(FANOUT_CONFIG_PATH.read_text(encoding="utf-8"))
    policy = config["publication_frontmatter_policy"]
    assert policy["publication_allowed_without_bus"] is False
    assert policy["direct_public_egress_allowed"] is False
    assert policy["review_required"] == "Claim Verification Council"
    assert set(policy["required_gates"]) == {
        "source_artifact_public_safe",
        "rights_privacy_redaction_pass",
        "target_surface_allowlist_pass",
        "fanout_loop_prevention_present",
        "claim_review_current",
    }
    claim_ceiling = policy["claim_ceiling"].lower()
    assert "already-approved public artifacts" in claim_ceiling
    assert "comparative claims" in claim_ceiling
