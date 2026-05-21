"""Tests verifying Perplexity model aliases resolve in the model registry."""

from __future__ import annotations

import pytest

from shared.config import MODELS

PERPLEXITY_ALIASES = ["web-scout", "web-research", "web-reason", "web-deep"]


@pytest.mark.parametrize("alias", PERPLEXITY_ALIASES)
def test_alias_registered(alias: str) -> None:
    assert alias in MODELS, f"Perplexity alias {alias!r} missing from MODELS"


@pytest.mark.parametrize("alias", PERPLEXITY_ALIASES)
def test_alias_resolves_to_nonempty_string(alias: str) -> None:
    resolved = MODELS[alias]
    assert isinstance(resolved, str)
    assert len(resolved) > 0


def test_all_four_aliases_present() -> None:
    for alias in PERPLEXITY_ALIASES:
        assert alias in MODELS
