"""Tests for the Meta Muse review-seat wrapper.

These pin four fail-closed properties. Each is a privacy or billing control, not a style choice:

* the wrapper always passes one pinned model, so muse's own default (a ``-contributor`` id) is
  never what runs;
* every run passes ``--contributor-mode off``. On a Muse Code subscription the training mode is
  an account setting, independent of the model id, and it defaults to Contributor; the per-run
  flag is what keeps a run out of Contributor mode, so the pin alone is not enough;
* any override toward a ``-contributor`` id, or toward any id that is not the pin, is refused
  before muse is launched;
* ``META_API_KEY`` (which muse prefers over the account login) never reaches the child
  process, so a present API key cannot silently switch the seat onto API billing.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "hapax-muse-reviewer"
PROMPT = "Review this small diff.\n"
FAKE_META_API_KEY = "fake-meta-api-key-for-tests-0123456789"  # pragma: allowlist secret


def _load_wrapper():
    loader = importlib.machinery.SourceFileLoader("hapax_muse_reviewer", str(WRAPPER))
    spec = importlib.util.spec_from_loader("hapax_muse_reviewer", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _fake_muse(tmp_path: Path) -> tuple[Path, Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_file = tmp_path / "argv.txt"
    env_file = tmp_path / "meta-api-key.txt"
    fake = bin_dir / "muse"
    fake.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\0' "$@" > {argv_file}
printf '%s\\n' "${{META_API_KEY:-unset}}" > {env_file}
printf 'verdict: accept\\n'
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake, argv_file, env_file


def _run(tmp_path: Path, fake: Path, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in {"META_API_KEY", "HAPAX_MUSE_MODEL"}}
    env.update({"HAPAX_MUSE_BIN": str(fake), "HOME": str(tmp_path / "home")})
    env.update(extra_env)
    return subprocess.run(
        [str(WRAPPER)],
        input=PROMPT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )


def _argv(argv_file: Path) -> list[str]:
    return [a for a in argv_file.read_text(encoding="utf-8").split("\0") if a]


def test_pinned_model_is_a_standard_id_not_contributor() -> None:
    wrapper = _load_wrapper()
    assert wrapper.PINNED_REVIEW_MODEL
    assert not wrapper.PINNED_REVIEW_MODEL.endswith("-contributor")


def test_wrapper_passes_the_pinned_model(tmp_path: Path) -> None:
    fake, argv_file, _ = _fake_muse(tmp_path)
    result = _run(tmp_path, fake, {})
    assert result.returncode == 0, result.stderr
    argv = _argv(argv_file)
    assert "--model" in argv, "an unpinned run would use muse's contributor default"
    assert argv[argv.index("--model") + 1] == _load_wrapper().PINNED_REVIEW_MODEL


def _contributor_mode_values(argv: list[str]) -> list[str]:
    values = []
    for i, arg in enumerate(argv):
        if arg == "--contributor-mode":
            values.append(argv[i + 1] if i + 1 < len(argv) else "")
        elif arg.startswith("--contributor-mode="):
            values.append(arg.split("=", 1)[1])
    return values


def test_command_always_carries_contributor_mode_off() -> None:
    wrapper = _load_wrapper()
    argv = wrapper.command("muse", Path("/tmp/prompt.md"), Path("/tmp/ws"))
    assert _contributor_mode_values(argv) == ["off"], "every run must force Contributor mode off"


@pytest.mark.parametrize("override", [None, "pin"])
def test_wrapper_runs_with_contributor_mode_off(tmp_path: Path, override: str | None) -> None:
    fake, argv_file, _ = _fake_muse(tmp_path)
    extra = {} if override is None else {"HAPAX_MUSE_MODEL": _load_wrapper().PINNED_REVIEW_MODEL}
    result = _run(tmp_path, fake, extra)
    assert result.returncode == 0, result.stderr
    assert _contributor_mode_values(_argv(argv_file)) == ["off"], (
        "the account default is Contributor mode; without the per-run flag a run may be trained on"
    )


def test_wrapper_refuses_a_contributor_model_override(tmp_path: Path) -> None:
    fake, argv_file, _ = _fake_muse(tmp_path)
    result = _run(tmp_path, fake, {"HAPAX_MUSE_MODEL": "muse-spark-1.3-contributor"})
    assert result.returncode != 0
    assert "is a contributor id" in result.stderr, "the contributor branch itself must refuse"
    assert not argv_file.exists(), "muse must not be launched"


def test_wrapper_refuses_any_unpinned_model_override(tmp_path: Path) -> None:
    fake, argv_file, _ = _fake_muse(tmp_path)
    result = _run(tmp_path, fake, {"HAPAX_MUSE_MODEL": "muse-spark-1.3"})
    assert result.returncode != 0
    assert not argv_file.exists(), "muse must not be launched"


def test_wrapper_accepts_the_pin_as_an_explicit_override(tmp_path: Path) -> None:
    fake, argv_file, _ = _fake_muse(tmp_path)
    pin = _load_wrapper().PINNED_REVIEW_MODEL
    result = _run(tmp_path, fake, {"HAPAX_MUSE_MODEL": pin})
    assert result.returncode == 0, result.stderr
    assert _argv(argv_file)[_argv(argv_file).index("--model") + 1] == pin


def test_wrapper_scrubs_meta_api_key(tmp_path: Path) -> None:
    fake, _, env_file = _fake_muse(tmp_path)
    result = _run(tmp_path, fake, {"META_API_KEY": FAKE_META_API_KEY})
    assert result.returncode == 0, result.stderr
    assert env_file.read_text(encoding="utf-8").strip() == "unset"
    assert "fake-meta-api-key-for-tests" not in result.stdout + result.stderr
