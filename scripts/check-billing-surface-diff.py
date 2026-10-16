#!/usr/bin/env python3
"""Git-validated provider-billing surface scan.

Exits 0 clean, 1 on findings, 2 on unusable input. The gate reads only the diff it has git
generate from --base/--head, drivers off; a supplied --diff-file is untrusted and refused.
Git applies the diff to an index seeded from the merge base; only Git's added lines and
post-image are scanned. Findings are a lower bound.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.billing_surface_detector import (  # noqa: E402
    _PY_SUFFIXES,
    ALLOW_MARKER,
    Finding,
    ScanResult,
    _has_bearer_header,
    _is_doc_path,
    _marker_is_allowed_on,
    _marker_outside_fixtures_finding,
    _node_findings_for_postimage,
    _pattern_only_classes,
    _text_classes,
)
from scripts.billing_surface_input import (  # noqa: E402
    GitUnavailable,
    UnusableInput,
    _git_out,
    _run_git,
    materialise_post_image,
    post_image_blob,
    regenerated_added_lines,
)


def scan_git_validated(*, repo: Path, base: str, head: str) -> tuple[ScanResult | None, str | None]:
    """Scan what git applies of the merge-base..head diff it generates: ``(result, error)``.

    An ``error`` (exit 2) has ``result`` None, so unusable input never scans clean."""
    # GIT_ATTR_SOURCE (below) is ignored by git < 2.40: refuse rather than silently lose it.
    version = re.match(r"git version (\d+)\.(\d+)", _run_git(["--version"], repo=repo).stdout)
    if version is None or (int(version[1]), int(version[2])) < (2, 40):
        return None, (
            "FAIL-CLOSED: git >= 2.40 is required for attribute-source hardening. Next action: "
            "upgrade git or run on a host with git >= 2.40"
        )
    # ONE base for diff and index seed: a moved base can misplace zero-context hunks.
    merge_base = _run_git(["merge-base", base, head], repo=repo)
    if merge_base.returncode != 0:
        return None, (
            f"FAIL-CLOSED: git merge-base {base} {head}: {_git_out(merge_base)}. Next action: "
            "fetch both revisions and rerun"
        )
    base = merge_base.stdout.strip()
    # Drivers or textconv could substitute a clean patch, and the PR's `.gitattributes` a binary
    # stub git apply skips: both diffs take attributes from the base tree.
    attrs = {"GIT_ATTR_SOURCE": base}
    generated = _run_git(
        ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--find-renames"]
        + ["--unified=0", f"{base}..{head}"],
        repo=repo,
        env={**os.environ, **attrs},
    )
    if generated.returncode != 0:
        return None, (
            f"FAIL-CLOSED: git diff {base}..{head}: {_git_out(generated)}. Next action: confirm "
            "both revisions exist in this repository and rerun"
        )
    if not generated.stdout.strip():
        return None, (
            "FAIL-CLOSED: an empty diff is not evidence. Next action: pass the PR's --base/--head"
        )
    with materialise_post_image(generated.stdout, repo=repo, base=base) as (_index_path, env):
        files, error = regenerated_added_lines(repo=repo, base=base, env={**env, **attrs})
        if error is not None:
            return None, error
        return _scan_validated_files(files, repo=repo, env=env), None


def _scan_validated_files(
    files: dict[str, dict[int, str]], *, repo: Path, env: dict[str, str]
) -> ScanResult:
    """Judge only Git-regenerated added lines while the validated index exists."""
    findings: list[Finding] = []
    allowed: list[Finding] = []
    scanned: list[str] = []

    def emit(
        path: str,
        line_no: int,
        kinds: tuple[str, ...],
        content: str,
        text: str | None = None,
        *,
        covers: tuple[int, ...] = (),
    ) -> None:
        """Record one added line's kinds: the ONE place an exemption is decided.

        A marker exempts only on an allowlisted path (elsewhere it is itself a finding), and only
        when every added line the finding covers carries it; empty ``covers`` means this line.
        """
        covered_texts = [added[line] for line in covers if line in added] or [content]
        marked = all(ALLOW_MARKER in text_of_line for text_of_line in covered_texts)
        if not kinds and not marked:
            return
        marker_ok = marked and _marker_is_allowed_on(path)
        if marked and not marker_ok:
            for line in covers or (line_no,):
                if line in added:
                    findings.append(_marker_outside_fixtures_finding(path, line, added[line]))
        for kind in kinds:
            finding = Finding(
                path=path,
                line=line_no,
                kind=kind,
                text=text if text is not None else content.strip()[:200],
                covers=covers,
            )
            (allowed if marker_ok else findings).append(finding)

    for path in sorted(files):
        if _is_doc_path(path):
            continue
        added = files[path]
        scanned.append(path)
        content = post_image_blob(path, repo=repo, env=env)
        node_findings: list[Finding] = []
        node_allowed: list[Finding] = []
        parsed = False
        if path.endswith(_PY_SUFFIXES) and content is not None:
            node_findings, node_allowed, parsed = _node_findings_for_postimage(
                path, content, set(added)
            )
        allowed.extend(node_allowed)
        if parsed:
            for finding in node_findings:
                line_content = added.get(finding.line, finding.text)
                emit(
                    path,
                    finding.line,
                    (finding.kind,),
                    line_content,
                    text=finding.text,
                    covers=finding.covers,
                )
            for line_no, text in sorted(added.items()):
                line_kinds: tuple[str, ...] = _pattern_only_classes(text)
                if _has_bearer_header(text):
                    line_kinds += ("api-key-route",)
                emit(path, line_no, line_kinds, text)
            continue
        # `unparseable-python` goes straight to the findings: no marker exempts it.
        findings.extend(node_findings)
        for line_no, text in sorted(added.items()):
            emit(path, line_no, _text_classes(text), text)
    return ScanResult(
        findings=tuple(findings), allowed=tuple(allowed), scanned_files=tuple(scanned)
    )


def _git_unavailable(exc: GitUnavailable) -> int:
    print(
        f"billing-surface-scan: FAIL-CLOSED: git is unavailable ({exc}). Next action: install "
        "git or run this scan where git is available",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0] or None)
    parser.add_argument("--base", required=False, help="base revision the input diff applies to")
    parser.add_argument("--head", help="head revision (used only to generate the input diff)")
    parser.add_argument("--diff-file", help="refused: untrusted text")
    parser.add_argument("--repo", help="repository to validate and scan in (default: cwd)")
    args = parser.parse_args(argv)
    repo = Path(args.repo).expanduser() if args.repo else Path.cwd()
    if not repo.is_dir():
        print(
            f"billing-surface-scan: FAIL-CLOSED: --repo {repo} is not a directory. Next action: "
            "pass the repository to scan",
            file=sys.stderr,
        )
        return 2

    if args.diff_file:
        print(
            "billing-surface-scan: FAIL-CLOSED: --diff-file is unusable for a gate: it is "
            "untrusted text. Next action: rerun with `--base <base> --head <head>`",
            file=sys.stderr,
        )
        return 2
    if not args.base or not args.head:
        print(
            "billing-surface-scan: FAIL-CLOSED: provide --base and --head so git can generate the "
            "input diff. Next action: rerun with `--base <base> --head <head>`",
            file=sys.stderr,
        )
        return 2
    try:
        result, error = scan_git_validated(repo=repo, base=args.base, head=args.head)
    except GitUnavailable as exc:
        return _git_unavailable(exc)
    except UnusableInput as exc:
        print(f"billing-surface-scan: FAIL-CLOSED: {exc}", file=sys.stderr)
        return 2
    if error is not None or result is None:
        print(f"billing-surface-scan: {error}", file=sys.stderr)
        return 2

    for finding in result.allowed:
        print(f"allowed {finding.path}:{finding.line}: {finding.kind}: {finding.text}")
    if result.findings:
        for finding in result.findings:
            print(f"{finding.path}:{finding.line}: {finding.kind}: {finding.text}")
        print(
            f"billing-surface-scan: FAIL: {len(result.findings)} billing-surface mutation(s) in the "
            "diff. Next action: remove it or route the client through the governed LiteLLM "
            f"proxy; mark a scan fixture or pattern definition visibly with {ALLOW_MARKER}; fix "
            "a wrong finding in the scan, not by exempting the line."
        )
        return 1
    print(
        "billing-surface-scan: OK: no billing-surface mutation in "
        f"{len(result.scanned_files)} changed file(s) (input applied by git)"
    )
    if result.allowed:
        print(
            f"billing-surface-scan: exempted {len(result.allowed)} site(s) by structure or the "
            "fixture allowlist ("
            + ", ".join(sorted({f"{f.path}:{f.line}" for f in result.allowed}))
            + ")"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
