#!/usr/bin/env python
"""Generate the GitHub public-surface live-state drift report."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import yaml

from shared.github_public_surface import (
    INTENDED_PUBLIC_REPOS,
    PROFILE_REPO_CANDIDATES,
    REQUIRED_FILE_PATHS,
    CommunityProfileState,
    GitHubDocsEvidence,
    LocalPublicSurfaceEvidence,
    PackageSurface,
    PagesState,
    ReleaseTagState,
    RepoFilePresence,
    RepoLiveState,
    build_report,
    missing_required_categories,
    report_json_schema,
    report_to_markdown,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "docs/repo-pres/github-public-surface-live-state-reconcile.json"
MARKDOWN_PATH = REPO_ROOT / "docs/research/2026-04-30-github-public-surface-live-state-reconcile.md"
SCHEMA_PATH = REPO_ROOT / "schemas/github-public-surface-live-state-report.schema.json"
VAULT_MARKDOWN_PATH = (
    Path.home()
    / "Documents"
    / "Personal"
    / "20-projects"
    / "hapax-research"
    / "audits"
    / "2026-04-30-github-public-surface-live-state-reconcile.md"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--markdown", type=Path, default=MARKDOWN_PATH)
    parser.add_argument("--vault-markdown", type=Path, default=VAULT_MARKDOWN_PATH)
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    parser.add_argument("--generated-at", default=_now_iso())
    parser.add_argument("--skip-live", action="store_true", help="Use only local evidence.")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    live_repos = (
        [_missing_repo(repo_id, "live collection skipped") for repo_id in INTENDED_PUBLIC_REPOS]
        if args.skip_live
        else [_collect_repo(repo_id) for repo_id in INTENDED_PUBLIC_REPOS]
    )
    profile_repos = (
        [_missing_repo(repo_id, "live collection skipped") for repo_id in PROFILE_REPO_CANDIDATES]
        if args.skip_live
        else [_collect_repo(repo_id) for repo_id in PROFILE_REPO_CANDIDATES]
    )
    local = _local_evidence(repo_root)
    report = build_report(
        generated_at=args.generated_at,
        generated_by="scripts/github-public-surface-reconcile.py",
        source_refs=(
            "gh api repos/*",
            "gh api repos/*/contents/*",
            "gh api repos/*/community/profile",
            "gh api repos/*/pages",
            "docs/repo-pres/repo-registry.yaml",
            "CLAUDE.md",
        ),
        live_repos=live_repos,
        profile_repo_candidates=profile_repos,
        local_evidence=local,
        docs_evidence=_docs_evidence(),
    )
    missing_categories = missing_required_categories(report)
    if missing_categories:
        raise SystemExit(
            f"report missing required drift categories: {', '.join(missing_categories)}"
        )

    _write_json(args.output, report.model_dump(mode="json"))
    _write_json(args.schema, report_json_schema())
    markdown = report_to_markdown(report)
    _write_text(args.markdown, markdown)
    _write_text(args.vault_markdown, markdown)
    print(f"wrote {args.output}")
    print(f"wrote {args.schema}")
    print(f"wrote {args.markdown}")
    print(f"wrote {args.vault_markdown}")
    return 0


def _collect_repo(repo_id: str) -> RepoLiveState:
    owner, name = repo_id.split("/", 1)
    repo_payload, repo_error = _gh_json(f"repos/{owner}/{name}")
    if not isinstance(repo_payload, dict):
        return _missing_repo(repo_id, repo_error or "repo API returned no object")

    visibility = _string_or_none(repo_payload.get("visibility"))
    private = bool(repo_payload.get("private"))
    if private or visibility != "public":
        return RepoLiveState(
            repo_id=repo_id,
            owner=owner,
            name=name,
            exists=True,
            private=private,
            visibility=visibility or "non_public",
            archived=_bool_or_none(repo_payload.get("archived")),
            html_url=_string_or_none(repo_payload.get("html_url")),
            api_error="repo is not public; authenticated-only details redacted",
        )

    default_branch = _string_or_none(repo_payload.get("default_branch"))
    branch_sha = _branch_sha(owner, name, default_branch)
    topics = _repo_topics(owner, name)
    files = _file_presence(owner, name, default_branch)
    return RepoLiveState(
        repo_id=repo_id,
        owner=owner,
        name=name,
        exists=True,
        private=bool(repo_payload.get("private")),
        visibility=_string_or_none(repo_payload.get("visibility")),
        archived=_bool_or_none(repo_payload.get("archived")),
        default_branch=default_branch,
        default_branch_sha=branch_sha,
        description=_string_or_none(repo_payload.get("description")),
        homepage=_string_or_none(repo_payload.get("homepage")),
        topics=tuple(sorted(topics)),
        license_spdx=_license_field(repo_payload, "spdx_id"),
        license_name=_license_field(repo_payload, "name"),
        has_issues=_bool_or_none(repo_payload.get("has_issues")),
        has_discussions=_bool_or_none(repo_payload.get("has_discussions")),
        has_wiki=_bool_or_none(repo_payload.get("has_wiki")),
        has_projects=_bool_or_none(repo_payload.get("has_projects")),
        pushed_at=_string_or_none(repo_payload.get("pushed_at")),
        html_url=_string_or_none(repo_payload.get("html_url")),
        files=files,
        pages=_pages_state(owner, name),
        releases=_release_state(owner, name),
        tags=_tag_state(owner, name),
        community=_community_profile(owner, name),
    )


def _missing_repo(repo_id: str, error: str) -> RepoLiveState:
    owner, name = repo_id.split("/", 1)
    return RepoLiveState(
        repo_id=repo_id,
        owner=owner,
        name=name,
        exists=False,
        visibility="missing_or_private",
        api_error=error,
    )


def _gh_json(endpoint: str) -> tuple[Any | None, str | None]:
    result = subprocess.run(
        ["gh", "api", endpoint],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None, _first_line(result.stderr) or f"gh api {endpoint} failed"
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"gh api {endpoint} returned malformed JSON: {exc}"


def _branch_sha(owner: str, name: str, default_branch: str | None) -> str | None:
    if not default_branch:
        return None
    payload, _error = _gh_json(f"repos/{owner}/{name}/branches/{quote(default_branch, safe='')}")
    if not isinstance(payload, dict):
        return None
    commit = payload.get("commit")
    if isinstance(commit, dict):
        return _string_or_none(commit.get("sha"))
    return None


def _repo_topics(owner: str, name: str) -> tuple[str, ...]:
    payload, _error = _gh_json(f"repos/{owner}/{name}/topics")
    if not isinstance(payload, dict):
        return ()
    names = payload.get("names")
    if not isinstance(names, list):
        return ()
    return tuple(str(name) for name in names if isinstance(name, str))


def _file_presence(
    owner: str, name: str, default_branch: str | None
) -> dict[str, RepoFilePresence]:
    files: dict[str, RepoFilePresence] = {}
    ref_suffix = f"?ref={quote(default_branch, safe='')}" if default_branch else ""
    for path in REQUIRED_FILE_PATHS:
        endpoint = f"repos/{owner}/{name}/contents/{quote(path, safe='/')}{ref_suffix}"
        payload, _error = _gh_json(endpoint)
        if isinstance(payload, dict):
            files[path] = RepoFilePresence(
                path=path,
                exists=True,
                sha=_string_or_none(payload.get("sha")),
                size=_int_or_none(payload.get("size")),
                html_url=_string_or_none(payload.get("html_url")),
            )
        else:
            files[path] = RepoFilePresence(path=path, exists=False)
    return files


def _pages_state(owner: str, name: str) -> PagesState:
    payload, error = _gh_json(f"repos/{owner}/{name}/pages")
    if not isinstance(payload, dict):
        return PagesState(exists=False, error=error)
    source = payload.get("source")
    source_branch = None
    source_path = None
    if isinstance(source, dict):
        source_branch = _string_or_none(source.get("branch"))
        source_path = _string_or_none(source.get("path"))
    return PagesState(
        exists=True,
        status=_string_or_none(payload.get("status")),
        html_url=_string_or_none(payload.get("html_url")),
        cname=_string_or_none(payload.get("cname")),
        source_branch=source_branch,
        source_path=source_path,
    )


def _release_state(owner: str, name: str) -> ReleaseTagState:
    payload, error = _gh_json(f"repos/{owner}/{name}/releases?per_page=100")
    if not isinstance(payload, list):
        return ReleaseTagState(count=0, error=error)
    latest = payload[0] if payload and isinstance(payload[0], dict) else {}
    return ReleaseTagState(
        count=len(payload),
        latest_name=_string_or_none(latest.get("name")) if isinstance(latest, dict) else None,
        latest_tag_name=_string_or_none(latest.get("tag_name"))
        if isinstance(latest, dict)
        else None,
        latest_published_at=(
            _string_or_none(latest.get("published_at")) if isinstance(latest, dict) else None
        ),
    )


def _tag_state(owner: str, name: str) -> ReleaseTagState:
    payload, error = _gh_json(f"repos/{owner}/{name}/tags?per_page=100")
    if not isinstance(payload, list):
        return ReleaseTagState(count=0, error=error)
    latest = payload[0] if payload and isinstance(payload[0], dict) else {}
    return ReleaseTagState(
        count=len(payload),
        latest_name=_string_or_none(latest.get("name")) if isinstance(latest, dict) else None,
        latest_tag_name=_string_or_none(latest.get("name")) if isinstance(latest, dict) else None,
    )


def _community_profile(owner: str, name: str) -> CommunityProfileState:
    payload, error = _gh_json(f"repos/{owner}/{name}/community/profile")
    if not isinstance(payload, dict):
        return CommunityProfileState(error=error)
    files_payload = payload.get("files")
    files: dict[str, bool] = {}
    if isinstance(files_payload, dict):
        files = {str(key): value is not None for key, value in files_payload.items()}
    return CommunityProfileState(
        health_percentage=_int_or_none(payload.get("health_percentage")),
        description=_string_or_none(payload.get("description")),
        files=files,
    )


def _local_evidence(repo_root: Path) -> LocalPublicSurfaceEvidence:
    registry = _registry(repo_root)
    notice_links = _notice_links(repo_root / "NOTICE.md")
    package_surfaces = _package_surfaces(repo_root / "packages")
    return LocalPublicSurfaceEvidence(
        repo_head=_git_head(repo_root),
        registry_license_by_repo=registry["license_by_repo"],
        registry_assets_policy=registry["assets_policy"],
        root_file_sha256=_root_hashes(repo_root),
        notice_links=tuple(notice_links),
        notice_missing_links=tuple(
            link
            for link in notice_links
            if _is_local_link(link) and not (repo_root / link).exists()
        ),
        package_surfaces=tuple(package_surfaces),
    )


def _registry(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "docs/repo-pres/repo-registry.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    repos = payload.get("repos", []) if isinstance(payload, dict) else []
    license_by_repo = {
        str(item["name"]): str(item["license"])
        for item in repos
        if isinstance(item, dict) and "name" in item and "license" in item
    }
    assets_policy = None
    assets = payload.get("assets_repos", []) if isinstance(payload, dict) else []
    for item in assets:
        if isinstance(item, dict) and item.get("name") == "hapax-assets":
            assets_policy = str(item.get("license_policy"))
    return {"license_by_repo": license_by_repo, "assets_policy": assets_policy}


def _notice_links(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    if "CONTRIBUTING.md" in text and "CONTRIBUTING.md" not in links:
        links.append("CONTRIBUTING.md")
    return sorted({link for link in links if link})


def _is_local_link(link: str) -> bool:
    return not (
        link.startswith("http://")
        or link.startswith("https://")
        or link.startswith("#")
        or link.startswith("mailto:")
    )


def _package_surfaces(packages_root: Path) -> list[PackageSurface]:
    surfaces: list[PackageSurface] = []
    if not packages_root.exists():
        return surfaces
    for package_dir in sorted(path for path in packages_root.iterdir() if path.is_dir()):
        readme = package_dir / "README.md"
        citation = package_dir / "CITATION.cff"
        pyproject = package_dir / "pyproject.toml"
        readme_text = readme.read_text(encoding="utf-8") if readme.exists() else ""
        mentions_issues = bool(re.search(r"\b(issue|issues|github issues)\b", readme_text, re.I))
        mentions_support = bool(re.search(r"\b(support|help|contact)\b", readme_text, re.I))
        status: Literal["needs_claim_discipline", "evidence_only", "not_public_package"]
        status = (
            "needs_claim_discipline" if mentions_issues or mentions_support else "evidence_only"
        )
        surfaces.append(
            PackageSurface(
                path=str(readme.relative_to(REPO_ROOT)) if readme.exists() else str(package_dir),
                package_name=package_dir.name,
                has_readme=readme.exists(),
                has_citation=citation.exists(),
                has_pyproject=pyproject.exists(),
                readme_mentions_issues=mentions_issues,
                readme_mentions_support=mentions_support,
                claim_status=status,
                evidence_refs=tuple(
                    str(path.relative_to(REPO_ROOT))
                    for path in (readme, citation, pyproject)
                    if path.exists()
                ),
            )
        )
    return surfaces


def _root_hashes(repo_root: Path) -> dict[str, str]:
    paths = (
        "README.md",
        "LICENSE",
        "NOTICE.md",
        "SECURITY.md",
        "CITATION.cff",
        "codemeta.json",
        ".zenodo.json",
        "CLAUDE.md",
    )
    hashes: dict[str, str] = {}
    for rel in paths:
        path = repo_root / rel
        if path.exists():
            hashes[rel] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _docs_evidence() -> GitHubDocsEvidence:
    return GitHubDocsEvidence(
        user_profile_readme_url=(
            "https://docs.github.com/en/account-and-profile/how-tos/"
            "profile-customization/managing-your-profile-readme"
        ),
        organization_profile_readme_url=(
            "https://docs.github.com/en/organizations/collaborating-with-groups-in-"
            "organizations/customizing-your-organizations-profile"
        ),
        user_profile_requirement=(
            "A user profile README requires a public repository whose name matches the "
            "GitHub username and contains a non-empty root README.md."
        ),
        organization_profile_requirement=(
            "An organization profile README uses a public .github repository with "
            "profile/README.md."
        ),
        profile_readme_decision="user_repo_named_ryanklee_required",
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _license_field(payload: dict[str, Any], key: str) -> str | None:
    license_payload = payload.get("license")
    if isinstance(license_payload, dict):
        return _string_or_none(license_payload.get(key))
    return None


def _bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
