from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify-omg-lol-infrastructure.py"
CONFIG_PATH = REPO_ROOT / "config" / "omg-lol.yaml"


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
