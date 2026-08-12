"""The resolver's two sources, and the two distinct kinds of absence."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.cc_task_root import (
    OVERRIDE_ENV,
    CcTaskRootSource,
    CcTaskRootUnavailable,
    cc_task_root,
    require_cc_task_root,
    resolve_cc_task_root,
)


def test_the_override_wins_when_it_names_a_real_directory(tmp_path, monkeypatch) -> None:
    root = tmp_path / "elsewhere"
    root.mkdir()
    monkeypatch.setenv(OVERRIDE_ENV, str(root))
    monkeypatch.setenv("PERSONAL_VAULT_PATH", str(tmp_path / "vault"))

    resolved = resolve_cc_task_root()

    assert resolved.path == root
    assert resolved.source is CcTaskRootSource.OVERRIDE
    assert resolved.exists


def test_an_override_naming_nothing_refuses_and_does_not_fall_back(tmp_path, monkeypatch) -> None:
    """The failure this module exists to prevent.

    Falling back to the vault default here would write cc-tasks into a different SSOT than the
    one the operator configured, and every write would succeed — the split would be invisible
    from inside the process that caused it.
    """
    vault = tmp_path / "vault" / "20-projects" / "hapax-cc-tasks"
    vault.mkdir(parents=True)
    monkeypatch.setenv(OVERRIDE_ENV, str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("PERSONAL_VAULT_PATH", str(tmp_path / "vault"))

    with pytest.raises(CcTaskRootUnavailable) as exc:
        resolve_cc_task_root()

    assert "Refusing rather than falling back" in str(exc.value)
    assert "Next:" in str(exc.value)
    assert str(vault) not in str(exc.value), (
        "the refusal must not advertise the path it refused to use"
    )


def test_an_override_pointing_at_a_file_is_not_a_root(tmp_path, monkeypatch) -> None:
    """`-d`, not `-e`. A file at that path is a misconfiguration, not a vault."""
    target = tmp_path / "notes.md"
    target.write_text("not a vault\n", encoding="utf-8")
    monkeypatch.setenv(OVERRIDE_ENV, str(target))

    with pytest.raises(CcTaskRootUnavailable):
        resolve_cc_task_root()


def test_an_empty_override_is_not_an_override(tmp_path, monkeypatch) -> None:
    """An unset knob and a knob set to whitespace mean the same thing: not configured."""
    vault = tmp_path / "vault"
    (vault / "20-projects" / "hapax-cc-tasks").mkdir(parents=True)
    monkeypatch.setenv(OVERRIDE_ENV, "   ")
    monkeypatch.setenv("PERSONAL_VAULT_PATH", str(vault))

    resolved = resolve_cc_task_root()

    assert resolved.source is CcTaskRootSource.PERSONAL_VAULT
    assert resolved.exists


def test_the_personal_vault_knob_is_honoured(tmp_path, monkeypatch) -> None:
    vault = tmp_path / "somewhere-else"
    (vault / "20-projects" / "hapax-cc-tasks").mkdir(parents=True)
    monkeypatch.delenv(OVERRIDE_ENV, raising=False)
    monkeypatch.setenv("PERSONAL_VAULT_PATH", str(vault))

    assert cc_task_root() == vault / "20-projects" / "hapax-cc-tasks"


def test_an_absent_default_is_genesis_not_an_error(tmp_path, monkeypatch) -> None:
    """R4.1's third clause is that first-init CREATES the task vault, so the pre-creation state
    is legitimate. A resolver that raised here could not be called by the thing that creates it."""
    monkeypatch.delenv(OVERRIDE_ENV, raising=False)
    monkeypatch.setenv("PERSONAL_VAULT_PATH", str(tmp_path / "not-yet"))

    resolved = resolve_cc_task_root()

    assert not resolved.exists
    assert resolved.source is CcTaskRootSource.PERSONAL_VAULT
    assert resolved.path == tmp_path / "not-yet" / "20-projects" / "hapax-cc-tasks"


def test_require_refuses_the_genesis_state_and_says_what_it_is(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(OVERRIDE_ENV, raising=False)
    monkeypatch.setenv("PERSONAL_VAULT_PATH", str(tmp_path / "not-yet"))

    with pytest.raises(CcTaskRootUnavailable) as exc:
        require_cc_task_root()

    assert "pre-first-init" in str(exc.value), (
        "a caller reading this must be able to tell genesis from a broken install"
    )
    assert "Next:" in str(exc.value)


def test_require_returns_the_path_when_the_vault_is_there(tmp_path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    tasks = vault / "20-projects" / "hapax-cc-tasks"
    tasks.mkdir(parents=True)
    monkeypatch.delenv(OVERRIDE_ENV, raising=False)
    monkeypatch.setenv("PERSONAL_VAULT_PATH", str(vault))

    assert require_cc_task_root() == tasks


def test_active_and_closed_hang_off_the_resolved_root(tmp_path, monkeypatch) -> None:
    root = tmp_path / "r"
    root.mkdir()
    monkeypatch.setenv(OVERRIDE_ENV, str(root))

    resolved = resolve_cc_task_root()

    assert resolved.active == root / "active"
    assert resolved.closed == root / "closed"


def test_todays_environment_resolves_to_todays_hardcoded_path(monkeypatch) -> None:
    """The adoption safety property. If this ever differs, migrating a call site MOVES the SSOT.

    Asserted against the literal every consumer currently carries, not against the resolver's own
    parts — a test built from the same constants as the code would agree with a typo.
    """
    monkeypatch.delenv(OVERRIDE_ENV, raising=False)
    monkeypatch.delenv("PERSONAL_VAULT_PATH", raising=False)

    assert cc_task_root() == Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"


def test_the_vault_knob_is_read_at_call_time_not_at_import(tmp_path, monkeypatch) -> None:
    """`shared.config` snapshots PERSONAL_VAULT_PATH at import, which would make the knob
    unchangeable for the life of the process — wrong for first-init, and untestable."""
    first = tmp_path / "one"
    second = tmp_path / "two"
    monkeypatch.delenv(OVERRIDE_ENV, raising=False)

    monkeypatch.setenv("PERSONAL_VAULT_PATH", str(first))
    before = cc_task_root()
    monkeypatch.setenv("PERSONAL_VAULT_PATH", str(second))
    after = cc_task_root()

    assert before != after
    assert after == second / "20-projects" / "hapax-cc-tasks"
