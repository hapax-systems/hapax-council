#!/usr/bin/env python3
"""Audit Hapax GitHub repositories for the required CI/app baseline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass

DEFAULT_OWNER = "hapax-systems"
REQUIRED_RULESET_NAME = "hapax-default-branch-ci-cd"
PRIVATE_SECURITY_CONFIG_NAME = "Hapax dependency baseline"
PUBLIC_SECURITY_CONFIG_NAME = "GitHub recommended"
REQUIRED_ORG_SECRETS = ("CODECOV_TOKEN", "SEMGREP_APP_TOKEN")
REQUIRED_ACTION_PATTERNS = (
    "actions-rust-lang/audit@*",
    "anthropics/claude-code-action@*",
    "astral-sh/ruff-action@*",
    "astral-sh/setup-uv@*",
    "codecov/codecov-action@*",
    "dependabot/fetch-metadata@*",
    "docker://rhysd/actionlint:*",
    "dorny/paths-filter@*",
    "dtolnay/rust-toolchain@*",
    "github/codeql-action/upload-sarif@*",
    "ossf/scorecard-action@*",
    "oven-sh/setup-bun@*",
    "pnpm/action-setup@*",
    "pypa/gh-action-pypi-publish@*",
    "quarto-dev/quarto-actions/setup@*",
    "android-actions/setup-android@*",
    "gradle/actions/setup-gradle@*",
)
REQUIRED_FILES = (
    "AGENTS.md",
    ".coderabbit.yaml",
    "codecov.yml",
    ".github/dependabot.yml",
    ".github/workflows/semgrep.yml",
)
CI_WORKFLOW = ".github/workflows/ci.yml"


@dataclass(frozen=True)
class Finding:
    repo: str
    message: str


def gh_json(*args: str) -> object:
    proc = subprocess.run(["gh", *args], check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout or "null")


def gh_ok(*args: str) -> bool:
    proc = subprocess.run(
        ["gh", *args], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return proc.returncode == 0


def list_repos(owner: str) -> list[str]:
    data = gh_json(
        "repo",
        "list",
        owner,
        "--limit",
        "300",
        "--json",
        "nameWithOwner,isArchived",
    )
    if not isinstance(data, list):
        raise RuntimeError("gh repo list did not return a list")
    repos: list[str] = []
    for item in data:
        if isinstance(item, dict) and not item.get("isArchived"):
            repos.append(str(item["nameWithOwner"]))
    return sorted(repos)


def audit_org(owner: str) -> list[Finding]:
    findings: list[Finding] = []
    repo = f"{owner}/<org>"
    org = gh_json("api", f"/orgs/{owner}")
    if not isinstance(org, dict):
        raise RuntimeError("gh api /orgs did not return an object")

    forbidden_true = (
        "members_can_create_repositories",
        "members_can_create_public_repositories",
        "members_can_create_private_repositories",
        "members_can_create_internal_repositories",
    )
    for field in forbidden_true:
        if org.get(field) is not False:
            findings.append(Finding(repo, f"org setting {field} must be false"))

    required_true = (
        "dependency_graph_enabled_for_new_repositories",
        "dependabot_alerts_enabled_for_new_repositories",
        "dependabot_security_updates_enabled_for_new_repositories",
        "secret_scanning_enabled_for_new_repositories",
        "secret_scanning_push_protection_enabled_for_new_repositories",
    )
    for field in required_true:
        if org.get(field) is not True:
            findings.append(Finding(repo, f"org setting {field} must be true"))

    actions = gh_json("api", f"/orgs/{owner}/actions/permissions")
    if isinstance(actions, dict):
        if actions.get("enabled_repositories") != "all":
            findings.append(Finding(repo, "Actions must be enabled for all org repositories"))
        if actions.get("allowed_actions") != "selected":
            findings.append(Finding(repo, "Actions allowed_actions must be selected"))
        if actions.get("sha_pinning_required") is not False:
            findings.append(
                Finding(repo, "sha_pinning_required must remain false until refs are pinned")
            )
    else:
        findings.append(Finding(repo, "could not read org Actions permissions"))

    selected = gh_json("api", f"/orgs/{owner}/actions/permissions/selected-actions")
    if isinstance(selected, dict):
        if selected.get("github_owned_allowed") is not True:
            findings.append(Finding(repo, "GitHub-owned actions must be allowed"))
        if selected.get("verified_allowed") is not False:
            findings.append(
                Finding(repo, "verified marketplace actions must not be blanket-allowed")
            )
        allowed = set(str(item) for item in selected.get("patterns_allowed", []))
        for pattern in REQUIRED_ACTION_PATTERNS:
            if pattern not in allowed:
                findings.append(Finding(repo, f"Actions allowlist missing {pattern}"))
    else:
        findings.append(Finding(repo, "could not read selected Actions allowlist"))

    workflow = gh_json("api", f"/orgs/{owner}/actions/permissions/workflow")
    if isinstance(workflow, dict):
        if workflow.get("default_workflow_permissions") != "read":
            findings.append(Finding(repo, "default workflow permissions must be read"))
        if workflow.get("can_approve_pull_request_reviews") is not False:
            findings.append(Finding(repo, "Actions must not approve pull request reviews"))
    else:
        findings.append(Finding(repo, "could not read workflow permissions"))

    secrets = gh_json("secret", "list", "--org", owner, "--json", "name,visibility")
    if isinstance(secrets, list):
        names = {str(item.get("name")) for item in secrets if isinstance(item, dict)}
        for secret in REQUIRED_ORG_SECRETS:
            if secret not in names:
                findings.append(Finding(repo, f"missing org Actions secret {secret}"))
    else:
        findings.append(Finding(repo, "could not read org Actions secrets"))

    rulesets = gh_json("api", f"/orgs/{owner}/rulesets")
    if isinstance(rulesets, list):
        if not any(
            isinstance(item, dict)
            and item.get("name") == REQUIRED_RULESET_NAME
            and item.get("enforcement") == "active"
            for item in rulesets
        ):
            findings.append(Finding(repo, f"missing active org ruleset {REQUIRED_RULESET_NAME}"))
    else:
        findings.append(Finding(repo, "could not read org rulesets"))

    defaults = gh_json("api", f"/orgs/{owner}/code-security/configurations/defaults")
    if isinstance(defaults, list):
        default_names = {
            str(item.get("default_for_new_repos")): str(
                (item.get("configuration") or {}).get("name")
            )
            for item in defaults
            if isinstance(item, dict)
        }
        if default_names.get("public") != PUBLIC_SECURITY_CONFIG_NAME:
            findings.append(
                Finding(repo, f"public code-security default must be {PUBLIC_SECURITY_CONFIG_NAME}")
            )
        if default_names.get("private_and_internal") != PRIVATE_SECURITY_CONFIG_NAME:
            findings.append(
                Finding(
                    repo,
                    f"private/internal code-security default must be {PRIVATE_SECURITY_CONFIG_NAME}",
                )
            )
    else:
        findings.append(Finding(repo, "could not read code-security configuration defaults"))

    return findings


def read_file(repo: str, path: str) -> str | None:
    proc = subprocess.run(
        ["gh", "api", f"repos/{repo}/contents/{path}", "--jq", ".content"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    decode = subprocess.run(
        ["base64", "-d"],
        input=proc.stdout,
        check=False,
        capture_output=True,
        text=True,
    )
    if decode.returncode != 0:
        return None
    return decode.stdout


def audit_repo(repo: str) -> list[Finding]:
    owner = repo.split("/", 1)[0]
    findings: list[Finding] = []
    if owner != DEFAULT_OWNER:
        findings.append(Finding(repo, f"owner must be {DEFAULT_OWNER}, got {owner}"))
    if owner == "ryanklee":
        findings.append(Finding(repo, "personal-account owner ryanklee is forbidden"))

    for path in REQUIRED_FILES:
        if not gh_ok("api", f"repos/{repo}/contents/{path}"):
            findings.append(Finding(repo, f"missing required file {path}"))

    ci = read_file(repo, CI_WORKFLOW)
    if ci is None:
        findings.append(Finding(repo, f"missing required file {CI_WORKFLOW}"))
    elif "all-green" not in ci:
        findings.append(Finding(repo, f"{CI_WORKFLOW} does not define all-green aggregate"))
    elif "codecov/codecov-action" in ci:
        if "use_oidc: true" not in ci:
            findings.append(Finding(repo, "Codecov uploads must use OIDC"))
        if "id-token: write" not in ci:
            findings.append(Finding(repo, "Codecov OIDC workflow must grant id-token: write"))

    coderabbit = read_file(repo, ".coderabbit.yaml")
    if coderabbit is not None and "request_changes_workflow: false" not in coderabbit:
        findings.append(Finding(repo, ".coderabbit.yaml must keep request_changes_workflow: false"))

    semgrep = read_file(repo, ".github/workflows/semgrep.yml")
    if semgrep is not None and "SEMGREP_APP_TOKEN" not in semgrep:
        findings.append(Finding(repo, "Semgrep workflow must use SEMGREP_APP_TOKEN"))

    return findings


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument(
        "--repo", action="append", help="Repo as owner/name. May be passed multiple times."
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    if args.owner == "ryanklee":
        print("refusing owner ryanklee; Hapax repos must live under hapax-systems", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    if args.owner == DEFAULT_OWNER:
        findings.extend(audit_org(args.owner))

    repos = args.repo or list_repos(args.owner)
    for repo in repos:
        findings.extend(audit_repo(repo))

    if findings:
        for finding in findings:
            print(f"{finding.repo}: {finding.message}", file=sys.stderr)
        return 1

    print(f"repo standards audit passed: {len(repos)} repo(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
