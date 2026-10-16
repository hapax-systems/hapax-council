#!/usr/bin/env python3
"""Git-validated provider-billing surface scan.

Exits 0 clean, 1 on findings, 2 on unusable input; ``--report-only`` records redacted
findings without blocking. Git applies the diff to an index seeded from the merge base;
only Git's added lines and post-image are scanned. Findings are a lower bound.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
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


def scan_git_validated(
    diff_text: str, *, repo: Path, base: str
) -> tuple[ScanResult | None, str | None]:
    """Scan the added lines git derives from the validated input: ``(result, error)``.

    ``error`` (exit 2) means git refused the input; ``result`` is then None, so unusable
    input never scans clean.
    """
    if not diff_text.strip():
        return None, (
            "FAIL-CLOSED: empty diff input is not evidence. Next action: pass the PR diff "
            "(--diff-file) or --base/--head; a PR that genuinely changes no file is covered by the "
            "merge-group duplicate sentinel, not by this scan reporting success."
        )
    with materialise_post_image(diff_text, repo=repo, base=base) as (_index_path, env):
        files, error = regenerated_added_lines(repo=repo, base=base, env=env)
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
        f"billing-surface-scan: FAIL-CLOSED: git is unavailable ({exc}), and this scanner "
        "validates its input with git before scanning anything. Next action: install git or "
        "run this scan where git is available",
        file=sys.stderr,
    )
    return 2


def _strict_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0] or None)
    parser.add_argument("--base", required=False, help="base revision the input diff applies to")
    parser.add_argument("--head", help="head revision (used only to generate the input diff)")
    parser.add_argument(
        "--diff-file",
        help="read the input diff from a file instead of generating it with git diff",
    )
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
        try:
            diff_text = Path(args.diff_file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(
                f"billing-surface-scan: FAIL-CLOSED: cannot read the diff file: {exc}. Next action: "
                "pass a readable --diff-file, or omit it and let git generate the diff",
                file=sys.stderr,
            )
            return 2
    else:
        if not args.base or not args.head:
            print(
                "billing-surface-scan: FAIL-CLOSED: provide --diff-file, or --base and --head so "
                "git can generate the input diff. Next action: rerun with "
                "`--base <base> --head <head>` (or --diff-file <path>)",
                file=sys.stderr,
            )
            return 2
        # ONE base for diff and index seed: a moved base can misplace zero-context hunks.
        try:
            merge_base = _run_git(["merge-base", args.base, args.head], repo=repo)
        except GitUnavailable as exc:
            return _git_unavailable(exc)
        if merge_base.returncode != 0:
            print(
                f"billing-surface-scan: FAIL-CLOSED: git merge-base {args.base} {args.head}: "
                f"{_git_out(merge_base)}. Next action: fetch both revisions and rerun",
                file=sys.stderr,
            )
            return 2
        args.base = merge_base.stdout.strip()
        try:
            generated = _run_git(
                ["diff", "--find-renames", "--unified=0", f"{args.base}..{args.head}"],
                repo=repo,
            )
        except GitUnavailable as exc:
            return _git_unavailable(exc)
        if generated.returncode != 0:
            print(
                f"billing-surface-scan: FAIL-CLOSED: git diff {args.base}...{args.head}: "
                f"{_git_out(generated)}. Next action: confirm both revisions exist in this "
                "repository and rerun",
                file=sys.stderr,
            )
            return 2
        diff_text = generated.stdout

    if not args.base:
        print(
            "billing-surface-scan: FAIL-CLOSED: --base is required: git validates the input against "
            "it, and without that the scan would parse raw diff text on its own authority. Next "
            "action: pass --base (the PR's base revision)",
            file=sys.stderr,
        )
        return 2
    try:
        result, error = scan_git_validated(diff_text, repo=repo, base=args.base)
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
            "diff. Next action: remove the added billing surface or route the client through the "
            "governed LiteLLM proxy, then rerun; if the line is a scan fixture or a pattern "
            f"definition, mark it visibly with {ALLOW_MARKER} so review sees the exemption. If a "
            "finding is wrong, fix the scan in the same PR rather than exempting the line."
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


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--report-only" not in args:
        return _strict_main(args)
    args.remove("--report-only")
    output = io.StringIO()
    error_type = ""
    with redirect_stdout(output), redirect_stderr(output):
        try:
            status = _strict_main(args)
        except SystemExit:
            status = 2
        except Exception as exc:
            status = 3
            error_type = type(exc).__name__
    for line in output.getvalue().splitlines():
        match = re.match(r"^(allowed )?(.+?:\d+: [a-z][a-z0-9-]*):", line)
        if match:
            print(f"{match.group(1) or ''}{match.group(2)}")
    label = {0: "clean", 1: "findings", 2: "unusable-input", 3: "process-error"}[status]
    print(f"billing-surface-scan: REPORT-ONLY: {label}{f' ({error_type})' if error_type else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
