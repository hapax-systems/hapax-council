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
REQUIRED_FILES = (
    "AGENTS.md",
    ".coderabbit.yaml",
    "codecov.yml",
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

    repos = args.repo or list_repos(args.owner)
    findings: list[Finding] = []
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
