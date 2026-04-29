from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_homage_visual_regression_nightly_workflow_exists_for_ci_claim() -> None:
    ci_text = _read(".github/workflows/ci.yml")
    nightly_text = _read(".github/workflows/homage-vr-nightly.yml")

    assert ".github/workflows/homage-vr-nightly.yml" in ci_text
    assert "schedule:" in nightly_text
    assert "workflow_dispatch:" in nightly_text
    assert "tests/studio_compositor/test_visual_regression_homage.py" in nightly_text
    assert "homage-visual-regression-nightly-diffs" in nightly_text


def test_pyright_safety_net_workflow_exists_for_pyproject_claim() -> None:
    pyproject_text = _read("pyproject.toml")
    workflow_text = _read(".github/workflows/pyright-safety-net.yml")

    assert ".github/workflows/pyright-safety-net.yml" in pyproject_text
    assert '"pyright>=1.1.400"' in pyproject_text
    assert "schedule:" in workflow_text
    assert "workflow_dispatch:" in workflow_text
    assert "uv sync --extra ci --group dev" in workflow_text
    assert "uv run pyright" in workflow_text


def test_auto_fix_typecheck_guidance_matches_pyrefly_and_pyright_split() -> None:
    workflow_text = _read(".github/workflows/auto-fix.yml")

    assert "(pyrefly|pyright)" in workflow_text
    assert (
        "If PR typecheck failed: `uv run --no-project --with pyrefly==0.62.0 pyrefly check`"
    ) in workflow_text
    assert "If pyright safety-net failed: `uv run pyright`" in workflow_text


def test_readme_typecheck_commands_match_ci_and_safety_net() -> None:
    readme_text = _read("README.md")

    assert "uv run --no-project --with pyrefly==0.62.0 pyrefly check" in readme_text
    assert "CI typecheck" in readme_text
    assert "uv run pyright" in readme_text
    assert "weekly typecheck safety net" in readme_text


def test_pyrefly_config_keeps_optional_dependency_override_noise_suppressed() -> None:
    config_text = _read("pyrefly.toml")

    assert "bad-override = false" in config_text


def test_ci_typecheck_uses_minimal_pyrefly_fast_path() -> None:
    ci_text = _read(".github/workflows/ci.yml")
    typecheck_start = ci_text.index("\n  typecheck:")
    test_start = ci_text.index("\n  test:", typecheck_start)
    typecheck_block = ci_text[typecheck_start:test_start]

    assert "astral-sh/setup-uv@v7" in typecheck_block
    assert "enable-cache: true" in typecheck_block
    assert "uv run --no-project --with pyrefly==0.62.0 pyrefly check" in typecheck_block
    assert "apt-get" not in typecheck_block
    assert "uv sync --extra ci" not in typecheck_block
    assert "actions/cache@v4" not in typecheck_block
    assert "~/.cache/pyrefly" not in typecheck_block


def test_cargo_hook_advisory_has_matching_path_gated_ci_job() -> None:
    ci_text = _read(".github/workflows/ci.yml")
    hook_text = _read("hooks/scripts/cargo-check-rust.sh")

    assert "rust-check:" in ci_text
    assert "hapax-logos/crates/**" in ci_text
    assert 'cargo check -p "$crate"' in ci_text
    assert "CI rust-check runs matching crate checks on PR/push" in hook_text
