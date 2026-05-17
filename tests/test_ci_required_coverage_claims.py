import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_BRANCH_PROTECTION_JOBS = (
    "lint",
    "typecheck",
    "test",
    "web-build",
    "vscode-build",
)


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _workflow_job_block(workflow_text: str, job_name: str) -> str:
    match = re.search(
        rf"\n  {re.escape(job_name)}:\n(?P<body>.*?)(?=\n  [A-Za-z0-9_-]+:\n|\Z)",
        workflow_text,
        re.DOTALL,
    )
    assert match is not None, f"missing workflow job {job_name}"
    return match.group(0)


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


def test_ci_docs_only_prs_trigger_required_jobs_with_sentinels() -> None:
    ci_text = _read(".github/workflows/ci.yml")

    assert "paths-ignore:" not in ci_text
    assert "\n  docs_only_filter:" in ci_text
    assert "docs_only_path()" in ci_text
    assert "docs|docs/*|lab-journal|lab-journal/*|research|research/*" in ci_text
    assert '[[ "$path" == *.md && "$path" != */* ]]' in ci_text
    assert '[[ "$path" == axioms/*.md ]]' in ci_text

    for job_name in REQUIRED_BRANCH_PROTECTION_JOBS:
        job_block = _workflow_job_block(ci_text, job_name)
        assert "needs: [docs_only_filter, post_merge_duplicate_filter]" in job_block
        assert "Docs-only required-check sentinel" in job_block
        assert "needs.docs_only_filter.outputs.docs_only == 'true'" in job_block
        assert "needs.docs_only_filter.outputs.docs_only != 'true'" in job_block


def test_ci_merge_group_docs_only_filter_has_stable_base_sha() -> None:
    ci_text = _read(".github/workflows/ci.yml")
    docs_filter_block = _workflow_job_block(ci_text, "docs_only_filter")

    assert "GITHUB_EVENT_NAME: ${{ github.event_name }}" in docs_filter_block
    assert "GITHUB_REF_NAME: ${{ github.ref_name }}" in docs_filter_block
    assert 'if [ "$GITHUB_EVENT_NAME" = "merge_group" ]; then' in docs_filter_block
    assert "merge_group_base_sha" in docs_filter_block
    assert "sed -n 's/.*-\\([0-9a-f]\\{40\\}\\)$/\\1/p'" in docs_filter_block
    assert 'git diff --name-only "$merge_group_base_sha"..HEAD' in docs_filter_block


def test_ci_post_merge_pushes_reuse_successful_merge_group_validation() -> None:
    ci_text = _read(".github/workflows/ci.yml")
    duplicate_filter = _workflow_job_block(ci_text, "post_merge_duplicate_filter")

    assert "actions: read" in ci_text
    assert "actions/workflows/ci.yml/runs" in duplicate_filter
    assert "head_sha=$GITHUB_SHA" in duplicate_filter
    assert "event=merge_group" in duplicate_filter
    assert "status=success" in duplicate_filter
    assert "duplicate_merge_group=true" in duplicate_filter

    for job_name in REQUIRED_BRANCH_PROTECTION_JOBS:
        job_block = _workflow_job_block(ci_text, job_name)
        assert "Post-merge duplicate required-check sentinel" in job_block
        assert (
            "needs.post_merge_duplicate_filter.outputs.duplicate_merge_group == 'true'" in job_block
        )
        assert (
            "needs.post_merge_duplicate_filter.outputs.duplicate_merge_group != 'true'" in job_block
        )


def test_ci_non_required_jobs_skip_duplicate_post_merge_push_work() -> None:
    ci_text = _read(".github/workflows/ci.yml")

    for job_name in (
        "homage-visual-regression",
        "rust-check",
        "secrets-scan",
        "security",
    ):
        job_block = _workflow_job_block(ci_text, job_name)
        assert "needs: post_merge_duplicate_filter" in job_block
        assert (
            "github.event_name != 'push' || "
            "needs.post_merge_duplicate_filter.outputs.duplicate_merge_group != 'true'"
        ) in job_block

    secrets_block = _workflow_job_block(ci_text, "secrets-scan")
    assert "PUSH_BEFORE_SHA: ${{ github.event.before }}" in secrets_block
    assert "GITHUB_SHA: ${{ github.sha }}" in secrets_block
    assert 'log_opts="$PUSH_BEFORE_SHA..$GITHUB_SHA"' in secrets_block


def test_security_extras_push_keeps_only_lightweight_actionlint() -> None:
    security_text = _read(".github/workflows/security-extras.yml")
    actionlint_block = _workflow_job_block(security_text, "actionlint")
    rust_audit_block = _workflow_job_block(security_text, "rust-audit")
    scorecard_block = _workflow_job_block(security_text, "scorecard")

    assert "push:" in security_text
    assert "rhysd/actionlint:1.7.12" in actionlint_block
    assert "if: github.event_name == 'schedule'" in rust_audit_block
    assert "if: github.event_name == 'schedule'" in scorecard_block
    assert "ossf/scorecard-action@v2.4.3" in scorecard_block


def test_required_frontend_build_jobs_are_path_gated_without_absent_checks() -> None:
    ci_text = _read(".github/workflows/ci.yml")
    web_block = _workflow_job_block(ci_text, "web-build")
    vscode_block = _workflow_job_block(ci_text, "vscode-build")

    assert "pull-requests: read" in ci_text

    assert "Detect web-build input changes" in web_block
    assert "dorny/paths-filter@v3" in web_block
    assert "web_build:" in web_block
    assert "'hapax-logos/**'" in web_block
    assert "Non-web required-check sentinel" in web_block
    assert "steps.filter.outputs.web_build != 'true'" in web_block
    assert "steps.filter.outputs.web_build == 'true'" in web_block
    assert "No web-build inputs changed; web-build reports success" in web_block

    assert "Detect vscode-build input changes" in vscode_block
    assert "dorny/paths-filter@v3" in vscode_block
    assert "vscode_build:" in vscode_block
    assert "'vscode/**'" in vscode_block
    assert "Non-vscode required-check sentinel" in vscode_block
    assert "steps.filter.outputs.vscode_build != 'true'" in vscode_block
    assert "steps.filter.outputs.vscode_build == 'true'" in vscode_block
    assert "No vscode-build inputs changed; vscode-build reports success" in vscode_block


def test_claude_review_docs_only_prs_trigger_review_sentinel() -> None:
    review_text = _read(".github/workflows/claude-review.yml")
    review_job = _workflow_job_block(review_text, "review")

    assert "paths-ignore:" not in review_text
    assert "Detect docs-only review change set" in review_job
    assert "Docs-only review sentinel" in review_job
    assert "steps.docs.outputs.docs_only == 'true'" in review_job
    assert (
        "env.CLAUDE_REVIEW_CONFIGURED == 'true' && steps.docs.outputs.docs_only != 'true'"
    ) in review_job


def test_docs_only_warning_no_longer_recommends_carrier_workaround() -> None:
    current_guidance = "\n".join(
        _read(path)
        for path in (
            "hooks/scripts/docs-only-pr-warn.sh",
            "hooks/scripts/README.md",
            "tooling/claude-agents/INSTALL.md",
            "CLAUDE.md",
        )
    )

    stale_guidance = (
        "branch protection will block",
        "Workaround: bundle",
        "carrier bundle",
        "bundle a non-markdown",
        "bundle a non-md",
    )
    for phrase in stale_guidance:
        assert phrase not in current_guidance

    assert "no carrier file is required" in current_guidance
    assert "required-check sentinels" in current_guidance
