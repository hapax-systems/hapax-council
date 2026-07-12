from __future__ import annotations

import pytest

from shared.sdlc_owner_identity import (
    canonical_task_owner,
    inferred_task_owner_platform,
    owner_matches,
    parse_task_owner,
)


def test_bare_owner_remains_legacy_compatible() -> None:
    assert owner_matches("cx-red", "cx-red", "codex")


@pytest.mark.parametrize(
    ("owner", "role", "expected_platform", "wrong_platform"),
    [
        ("cx-red", "cx-red", "codex", "claude"),
        ("eta", "eta", "claude", "codex"),
        ("cc-zai", "cc-zai", "claude", "codex"),
        ("vbe-1", "vbe-1", "vibe", "claude"),
    ],
)
def test_known_bare_owner_never_authorizes_another_platform(
    owner: str,
    role: str,
    expected_platform: str,
    wrong_platform: str,
) -> None:
    assert inferred_task_owner_platform(role) == expected_platform
    assert owner_matches(owner, role, expected_platform)
    assert not owner_matches(owner, role, wrong_platform)


def test_unknown_bare_owner_keeps_explicit_legacy_compatibility() -> None:
    assert owner_matches("legacy-special", "legacy-special", "codex")
    assert not owner_matches(
        "legacy-special",
        "legacy-special",
        "codex",
        allow_unqualified=False,
    )


def test_canonical_owner_preserves_known_platform() -> None:
    assert canonical_task_owner("cx-red", "Codex") == "codex/cx-red"
    assert canonical_task_owner("legacy-special", None) == "legacy-special"


def test_qualified_owner_requires_exact_platform_and_role() -> None:
    assert owner_matches("codex/cx-red", "cx-red", "codex")
    assert not owner_matches("codex/cx-red", "cx-red", "claude")
    assert not owner_matches("codex/cx-red", "cx-blue", "codex")


@pytest.mark.parametrize(
    ("owner", "role", "platform"),
    [
        ("claude/cx-red", "cx-red", "claude"),
        ("codex/vbe-1", "vbe-1", "codex"),
        ("vibe/alpha", "alpha", "vibe"),
    ],
)
def test_known_role_shape_rejects_contradictory_qualified_platform(
    owner: str,
    role: str,
    platform: str,
) -> None:
    with pytest.raises(ValueError, match="contradicts"):
        parse_task_owner(owner)
    with pytest.raises(ValueError, match="contradicts"):
        canonical_task_owner(role, platform)
    assert not owner_matches(owner, role, platform)


@pytest.mark.parametrize("owner", ["other/cx-red", "codex/", "codex/cx/red", "cx red"])
def test_malformed_owner_is_not_silently_normalized(owner: str) -> None:
    with pytest.raises(ValueError):
        parse_task_owner(owner)
