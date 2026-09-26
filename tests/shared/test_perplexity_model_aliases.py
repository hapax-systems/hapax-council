"""Sonar Chat Completions aliases are not model routes."""

from __future__ import annotations

import pytest

from shared.config import MODELS
from shared.grounding_adapters.perplexity import _MODEL_ALIAS_TO_ID

RETIRED_SONAR_ALIASES = ["web-scout", "web-research", "web-reason", "web-deep"]


@pytest.mark.parametrize("alias", RETIRED_SONAR_ALIASES)
def test_alias_is_not_registered(alias: str) -> None:
    assert alias not in MODELS


@pytest.mark.parametrize("alias", RETIRED_SONAR_ALIASES)
def test_alias_is_not_rewritten_to_sonar(alias: str) -> None:
    resolved = _MODEL_ALIAS_TO_ID.get(alias, alias)
    assert resolved == alias
    assert not resolved.startswith("sonar")


def test_no_registered_model_value_names_sonar() -> None:
    offenders = {alias: route for alias, route in MODELS.items() if "sonar" in route}
    assert offenders == {}
