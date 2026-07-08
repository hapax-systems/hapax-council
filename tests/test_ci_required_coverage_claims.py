import os
import re
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_BRANCH_PROTECTION_JOBS = (
    "lint",
    "capability-surface-delta",
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


def _assert_uses_pinned_action(block: str, action: str) -> None:
    assert re.search(rf"{re.escape(action)}@[0-9a-f]{{40}}\b", block), action


def _workflow_shell_function(workflow_text: str, function_name: str) -> str:
    match = re.search(
        rf"^ {{10}}{re.escape(function_name)}\(\) \{{\n(?P<body>.*?^ {{10}}\}})",
        workflow_text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, f"missing shell function {function_name}"
    return textwrap.dedent(match.group(0))


def _workflow_docs_filter_decision_block(workflow_text: str) -> str:
    match = re.search(
        r'^ {10}docs_only=true\n.*?^ {10}echo "python_prod_dependency_witness=\$python_prod_dependency_witness" >> "\$GITHUB_OUTPUT"',
        workflow_text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "missing docs_only_filter decision block"
    return textwrap.dedent(match.group(0))


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


def test_auto_fix_workflow_escalates_without_privileged_pr_checkout() -> None:
    workflow_text = _read(".github/workflows/auto-fix.yml")
    auto_fix_job = _workflow_job_block(workflow_text, "auto-fix")

    assert "contents: read" in workflow_text
    assert "issues: write" in workflow_text
    assert "actions/checkout" not in auto_fix_job
    assert "anthropics/claude-code-action" not in auto_fix_job
    assert "ANTHROPIC_API_KEY" not in workflow_text
    assert "HEAD_BRANCH: ${{ github.event.workflow_run.head_branch }}" in auto_fix_job
    assert 'BRANCH="${{ github.event.workflow_run.head_branch }}"' not in auto_fix_job
    assert "Privileged workflow auto-mutation is disabled" in auto_fix_job
    assert 'gh run view "$RUN_ID"' in auto_fix_job


def test_github_workflows_do_not_use_escaped_model_providers() -> None:
    for workflow in (REPO_ROOT / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        assert "anthropics/claude-code-action" not in text, workflow
        assert "ANTHROPIC_API_KEY" not in text, workflow
        assert "OPENROUTER_API_KEY" not in text, workflow
        assert "claude-sonnet-4-6" not in text, workflow


def test_model_watchdogs_use_central_secret_boundary() -> None:
    watchdog_dir = REPO_ROOT / "systemd" / "watchdogs"
    for watchdog in watchdog_dir.glob("*-watchdog"):
        text = watchdog.read_text(encoding="utf-8")
        if "LITELLM_API_KEY" not in text:
            continue
        assert "changeme" not in text, watchdog
        assert "pass show litellm/master-key" not in text, watchdog
        assert "hapax-secrets.env" in text, watchdog
        assert ': "${LITELLM_API_KEY:?' in text, watchdog


def test_sdlc_implement_shell_uses_validated_issue_env_not_inline_payload() -> None:
    workflow_text = _read(".github/workflows/sdlc-implement.yml")
    plan_job = _workflow_job_block(workflow_text, "plan-and-implement")

    assert "ISSUE_NUMBER: ${{ github.event.client_payload.issue_number }}" in plan_job
    assert 'case "$ISSUE_NUMBER"' in plan_job
    assert "gh issue edit ${{ github.event.client_payload.issue_number }}" not in plan_job
    assert "--issue-number ${{ github.event.client_payload.issue_number }}" not in plan_job
    assert "ISSUE=${{ github.event.client_payload.issue_number }}" not in plan_job
    assert 'printf \'BRANCH=%s\\n\' "$BRANCH" >> "$GITHUB_ENV"' in plan_job
    assert 'echo "BRANCH=$BRANCH" >> "$GITHUB_ENV"' not in plan_job


def test_sdlc_fix_round_guards_agent_branch_before_checkout() -> None:
    workflow_text = _read(".github/workflows/sdlc-implement.yml")
    fix_job = _workflow_job_block(workflow_text, "fix-round")

    assert "Validate agent-authored PR source" in fix_job
    assert "HEAD_REPOSITORY: ${{ github.event.pull_request.head.repo.full_name }}" in fix_job
    assert '[[ "$HEAD_REF" == agent/issue-* ]]' in fix_job
    assert "if: steps.review_pr.outputs.safe == 'true'" in fix_job
    assert "persist-credentials: false" in fix_job
    assert "printf '%s\\n' \"$REVIEW_BODY\" > /tmp/review-body.txt" in fix_job
    assert 'git push origin "HEAD:${HEAD_REF}"' in fix_job


def test_auto_fix_keeps_real_failure_remediation_but_skips_auto_fix_recursion() -> None:
    workflow_text = _read(".github/workflows/auto-fix.yml")
    auto_fix_job = _workflow_job_block(workflow_text, "auto-fix")

    assert "github.event.workflow_run.conclusion == 'failure'" in auto_fix_job
    assert "github.event.workflow_run.head_branch != 'main'" in auto_fix_job
    assert (
        "!contains(github.event.workflow_run.head_commit.message || '', '[auto-fix]')"
        in auto_fix_job
    )
    assert "real CI failures route to governed remediation" in auto_fix_job
    assert "recursively trigger the privileged classifier" in auto_fix_job


def test_readme_typecheck_commands_match_ci_and_safety_net() -> None:
    readme_text = _read("README.md")

    assert "uv run --no-project --with pyrefly==0.64.1 pyrefly check" in readme_text
    assert "CI typecheck" in readme_text
    assert "uv run pyright" in readme_text
    assert "weekly typecheck safety net" in readme_text


def test_pyrefly_config_keeps_optional_dependency_override_noise_suppressed() -> None:
    config_text = _read("pyrefly.toml")

    assert "bad-override = false" in config_text


def test_ci_typecheck_uses_minimal_pyrefly_fast_path() -> None:
    ci_text = _read(".github/workflows/ci.yml")
    typecheck_block = _workflow_job_block(ci_text, "typecheck")

    _assert_uses_pinned_action(typecheck_block, "astral-sh/setup-uv")
    assert "enable-cache: true" in typecheck_block
    assert "uv run --no-project --with pyrefly==0.64.1 pyrefly check" in typecheck_block
    assert "apt-get" not in typecheck_block
    assert "uv sync --extra ci" not in typecheck_block
    assert "actions/cache@v4" not in typecheck_block
    assert "~/.cache/pyrefly" not in typecheck_block


def test_ci_capability_surface_delta_gate_is_required() -> None:
    ci_text = _read(".github/workflows/ci.yml")
    gate_block = _workflow_job_block(ci_text, "capability-surface-delta")
    all_green_block = _workflow_job_block(ci_text, "all-green")

    _assert_uses_pinned_action(gate_block, "actions/checkout")
    _assert_uses_pinned_action(gate_block, "astral-sh/setup-uv")
    assert "scripts/hapax-capability-surface-delta-gate" in gate_block
    assert (
        "uv run --no-project --with pydantic==2.13.4 "
        "--with pyyaml==6.0.3 "
        "python scripts/hapax-capability-surface-delta-gate"
    ) in gate_block
    assert "uv run --frozen python scripts/hapax-capability-surface-delta-gate" not in gate_block
    assert "Post-merge duplicate required-check sentinel" in gate_block
    assert "Docs-only required-check sentinel" in gate_block
    assert "capability-surface-delta" in all_green_block


def test_ci_runs_python_prod_optional_dependency_witness_for_dependency_changes() -> None:
    ci_text = _read(".github/workflows/ci.yml")
    docs_filter_block = _workflow_job_block(ci_text, "docs_only_filter")
    test_full_shard_block = _workflow_job_block(ci_text, "test-full-shard")
    test_block = _workflow_job_block(ci_text, "test")

    assert "python_prod_dependency_witness:" in docs_filter_block
    assert "python_prod_dependency_witness=false" in docs_filter_block
    assert "python_prod_dependency_witness=true" in docs_filter_block
    assert "tests/test_python_prod_dependency_constraints.py" in docs_filter_block

    witness_command = (
        "uv run --frozen \\\n"
        "            --extra ci --extra audio --extra tui --extra studio --extra rerank \\\n"
        "            pytest tests/test_python_prod_dependency_constraints.py -q -rs"
    )
    assert "Run python-prod optional dependency witness" in test_full_shard_block
    assert "matrix.shard == 1" in test_full_shard_block
    assert "needs.docs_only_filter.outputs.python_prod_dependency_witness == 'true'" in (
        test_full_shard_block
    )
    assert witness_command in test_full_shard_block

    assert "Install python-prod optional witness system deps" in test_block
    assert "ffmpeg" in test_block
    assert "portaudio19-dev" in test_block
    assert "portaudio19-dev" in test_full_shard_block
    assert test_block.count("Run python-prod optional dependency witness") == 2
    assert witness_command in test_block


def test_ci_docs_only_filter_executes_python_prod_witness_decision(tmp_path: Path) -> None:
    ci_text = _read(".github/workflows/ci.yml")
    script = "\n\n".join(
        _workflow_shell_function(ci_text, function_name)
        for function_name in (
            "is_audio_authority_path",
            "is_system_dynamics_map_authority_path",
            "docs_only_path",
        )
    )
    script += textwrap.dedent(
        """

        changed_files="$CHANGED_FILES"
        changed_count="$CHANGED_COUNT"
        """
    )
    script += "\n" + _workflow_docs_filter_decision_block(ci_text)

    def run_filter(paths: list[str]) -> dict[str, str]:
        changed_files = tmp_path / "changed-files.txt"
        github_output = tmp_path / "github-output.txt"
        changed_files.write_text(
            "".join(f"{path}\n" for path in paths),
            encoding="utf-8",
        )
        github_output.write_text("", encoding="utf-8")
        env = {
            **os.environ,
            "CHANGED_FILES": str(changed_files),
            "CHANGED_COUNT": str(len(paths)),
            "GITHUB_OUTPUT": str(github_output),
        }
        result = subprocess.run(
            ["bash", "-c", "set -euo pipefail\n" + script],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        return dict(
            line.split("=", 1) for line in github_output.read_text(encoding="utf-8").splitlines()
        )

    assert run_filter(["pyproject.toml"]) == {
        "docs_only": "false",
        "changed_count": "1",
        "python_prod_dependency_witness": "true",
    }
    assert run_filter(["uv.lock"])["python_prod_dependency_witness"] == "true"
    assert (
        run_filter(["tests/test_python_prod_dependency_constraints.py"])[
            "python_prod_dependency_witness"
        ]
        == "true"
    )
    assert run_filter(["docs/research/dependency-note.md"]) == {
        "docs_only": "true",
        "changed_count": "1",
        "python_prod_dependency_witness": "false",
    }
    assert run_filter(["shared/runtime.py"]) == {
        "docs_only": "false",
        "changed_count": "1",
        "python_prod_dependency_witness": "false",
    }


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
    assert "is_system_dynamics_map_authority_path()" in ci_text
    assert "docs/architecture/system-dynamics-map*" in ci_text
    assert "docs/architecture/vendor/cytoscape-*.js" in ci_text
    assert (
        'is_audio_authority_path "$path" || is_system_dynamics_map_authority_path "$path"'
    ) in ci_text

    for job_name in REQUIRED_BRANCH_PROTECTION_JOBS:
        job_block = _workflow_job_block(ci_text, job_name)
        if job_name == "test":
            assert (
                "needs: [docs_only_filter, post_merge_duplicate_filter, test-full-shard, "
                "test-title-cards]" in job_block
            )
        else:
            assert "needs: [docs_only_filter, post_merge_duplicate_filter]" in job_block
        assert "Docs-only required-check sentinel" in job_block
        assert "needs.docs_only_filter.outputs.docs_only == 'true'" in job_block
        assert "needs.docs_only_filter.outputs.docs_only != 'true'" in job_block


def test_ci_docs_only_filter_executes_system_dynamics_map_carveout() -> None:
    ci_text = _read(".github/workflows/ci.yml")
    script = "\n\n".join(
        _workflow_shell_function(ci_text, function_name)
        for function_name in (
            "is_audio_authority_path",
            "is_system_dynamics_map_authority_path",
            "docs_only_path",
        )
    )
    script += textwrap.dedent(
        """

        assert_docs_only_result() {
          local expected="$1"
          local path="$2"
          set +e
          docs_only_path "$path"
          local actual="$?"
          set -e
          if [ "$actual" -ne "$expected" ]; then
            echo "$path expected $expected, got $actual" >&2
            exit 1
          fi
        }

        assert_docs_only_result 1 docs/architecture/system-dynamics-map-viewer.html
        assert_docs_only_result 1 docs/architecture/system-dynamics-map.canonical.trig
        assert_docs_only_result 1 docs/architecture/vendor/cytoscape-3.34.0.min.js
        assert_docs_only_result 0 docs/architecture/ordinary-note.md
        assert_docs_only_result 1 shared/runtime.py
        """
    )

    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


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
    assert "merge_group:" not in security_text
    assert "rhysd/actionlint:1.7.12" in actionlint_block
    assert "if: github.event_name == 'schedule'" in rust_audit_block
    assert "if: github.event_name == 'schedule'" in scorecard_block
    _assert_uses_pinned_action(scorecard_block, "ossf/scorecard-action")


def test_required_frontend_build_jobs_are_path_gated_without_absent_checks() -> None:
    ci_text = _read(".github/workflows/ci.yml")
    web_block = _workflow_job_block(ci_text, "web-build")
    vscode_block = _workflow_job_block(ci_text, "vscode-build")

    assert "pull-requests: read" in ci_text

    assert "Detect web-build input changes" in web_block
    _assert_uses_pinned_action(web_block, "dorny/paths-filter")
    assert "web_build:" in web_block
    assert "'hapax-logos/**'" in web_block
    assert "Non-web required-check sentinel" in web_block
    assert "steps.filter.outputs.web_build != 'true'" in web_block
    assert "steps.filter.outputs.web_build == 'true'" in web_block
    assert "No web-build inputs changed; web-build reports success" in web_block

    assert "Detect vscode-build input changes" in vscode_block
    _assert_uses_pinned_action(vscode_block, "dorny/paths-filter")
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
    assert "No-escape review hold" in review_job
    assert (
        "External Claude review is disabled until a no-escape route receipt exists." in review_job
    )
    assert "review_ready=false" in review_job
    assert "steps.claude.outputs.review_ready == 'true'" in review_job
    assert "steps.docs.outputs.docs_only != 'true'" in review_job


def test_claude_review_auto_fix_debounce_uses_pr_head_commit_lookup() -> None:
    review_text = _read(".github/workflows/claude-review.yml")
    review_job = _workflow_job_block(review_text, "review")

    assert "github.event.head_commit.message" not in review_job
    assert "Detect auto-fix head commit" in review_job
    assert "pull_request.synchronize is not a push payload" in review_job
    assert "HEAD_SHA: ${{ github.event.pull_request.head.sha }}" in review_job
    assert "HEAD_REPOSITORY: ${{ github.event.pull_request.head.repo.full_name }}" in review_job
    assert 'gh api "repos/$HEAD_REPOSITORY/commits/$HEAD_SHA"' in review_job
    assert 'if ! message="$(gh api "repos/$HEAD_REPOSITORY/commits/$HEAD_SHA"' in review_job
    assert "failing closed by skipping Claude review" in review_job
    assert "grep -Fq '[auto-fix]'" in review_job
    assert "Auto-fix review sentinel" in review_job
    assert "steps.auto_fix.outputs.skip == 'true'" in review_job
    assert "steps.auto_fix.outputs.skip != 'true'" in review_job


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


AUDIO_SAFETY_SLICE_PATHS = (
    "shared/audio_routing_policy.py",
    "shared/audio_control_plane.py",
    "shared/audio_restart_proof_gate.py",
    "shared/audio_topology*.py",
    "shared/audio_canary*.py",
    "config/audio-topology.yaml",
    "config/audio-routing.yaml",
    "config/wireplumber/**",
    "config/hapax/audio-*.conf",
    "config/pipewire/**",
    "scripts/hapax-wireplumber-*",
    "docs/audio-topology-reference.md",
)

AUDIO_SAFETY_SLICE_TESTS = (
    "tests/shared/test_audio_routing_policy.py",
    "tests/scripts/test_hapax_audio_routing_check.py",
    "tests/shared/test_canonical_audio_topology.py",
    "tests/shared/test_audio_topology_inspector.py",
    "tests/docs/test_audio_current_capsule.py",
)


def test_audio_graph_validate_workflow_triggers_on_audio_authority_paths() -> None:
    workflow_text = _read(".github/workflows/audio-graph-validate.yml")

    for path_pattern in AUDIO_SAFETY_SLICE_PATHS:
        assert path_pattern in workflow_text, (
            f"audio-graph-validate.yml missing path trigger: {path_pattern}"
        )


def test_audio_graph_validate_workflow_runs_safety_slice_tests() -> None:
    workflow_text = _read(".github/workflows/audio-graph-validate.yml")

    for test_path in AUDIO_SAFETY_SLICE_TESTS:
        assert test_path in workflow_text, (
            f"audio-graph-validate.yml missing safety slice test: {test_path}"
        )


def test_audio_graph_validate_runs_generator_freshness_check() -> None:
    workflow_text = _read(".github/workflows/audio-graph-validate.yml")

    assert "generate-pipewire-audio-confs.py" in workflow_text
    assert "--check" in workflow_text
    assert "--check-route-maps" in workflow_text
    assert "--check-wireplumber-deny-policy" in workflow_text


def test_audio_graph_validate_triggers_on_pull_request_and_merge_group() -> None:
    workflow_text = _read(".github/workflows/audio-graph-validate.yml")

    assert "pull_request:" in workflow_text
    assert "merge_group:" in workflow_text
