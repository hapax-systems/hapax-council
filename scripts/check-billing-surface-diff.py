#!/usr/bin/env python3
"""Fail a PR diff that opens a provider-billing surface — git-validated input.

The provider_billing_sensitive class's deterministic arm (RELEASE_MITIGATION_CHECKS): the ci.yml
job ``billing-surface-scan`` runs this scan on every PR head and the autoqueue counts its SUCCESS.
**None of that wiring is in this file's PR** — the entry, the job and the autoqueue read land in
**#4805**; this half is the scanner they invoke.

**GIT VALIDATES THE INPUT; THIS SCANNER NEVER PARSES RAW DIFF TEXT ON ITS OWN AUTHORITY.** Six
rounds across #4795 and #4808 each found a new malformed shape that a hand-rolled diff parser read
clean: truncation at any prefix, header-less hunks, ``+++`` without ``diff --git``, a marker
leaking across lines, a ``Binary files … differ`` note after a hunk. The fix is structural:

1. the input is applied BY GIT to the base (``git apply --check``, then ``git apply --cached`` into
   a temporary index seeded from the base). Anything git will not apply is
   ``billing-scan-unusable-input`` and exits 2 with a next action — there is no permissive parse to
   leak;
2. the added lines come from **git's own output**: a diff git regenerates from that index
   (``git diff --cached --unified=0``), read by a CLOSED grammar whose default is REJECT, so an
   unrecognised line refuses rather than scans;
3. the post-image the AST layer parses comes from **git's own object store** (``git show :<path>``
   against the same index), so no region is reconstructed from diff text at all.

**What success proves:** no ADDED line matched the line patterns, and for Python every parsed
``Call`` with a credential argument also binds its own route to a governed proxy. It is **not
proof** that the change cannot spend: the semantic layer is the review quorum's, which is why the
class needs both arms. Findings are a lower bound too: text that cannot be matched, or a blob that
cannot be parsed, is a limitation and — where credential-bearing — a finding, never a pass.

Flagged on ADDED lines of non-doc files: ``credential-env-read`` (a credential env read or
injection), ``api-key-route`` (an API-key client route or Bearer header), ``provider-api-endpoint``
(a provider endpoint literal or a bare provider SDK constructor — the implicit-credential path),
``capacity-pool-payg`` (a capacity_pool/plan_type rebinding to api_paid_spend).

**Python** is decided per ``ast`` node **on the post-image git materialised**: a ``Call`` carrying
``api_key``/``key``/``token`` is a route unless that **same** Call binds its own route to a governed
proxy host (``127.0.0.1``, ``localhost``, ``::1``, ``litellm``) through a *literal*
``base_url``/``api_base``/``endpoint``. A dynamic value is not a binding, nor is a
neighbouring/earlier/chained call's target. A node counts only when an ADDED line falls inside it.
**Non-Python** gets **no structural exemption**; the marker on an allowlisted path is the one
exemption any file kind can carry. **Every exemption granted is printed** as ``allowed``.

Exit codes: 0 clean, 1 findings, 2 fail-closed (no usable diff input).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.billing_surface_detector import (  # noqa: E402
    _KEY_BEARING_PROBE,
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
    """Scan the added lines GIT derives from the validated input.

    Returns ``(result, error)``. ``error`` is a fail-closed message with a next action (exit 2):
    git will not apply the input, git could not regenerate the diff, or git's own output carried a
    line the closed grammar refuses. ``result`` is None whenever ``error`` is set — there is no
    path from an unusable input to a clean scan.
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
        """Record one added line's kinds, applying the marker decision.

        The marker is honoured only on an allowlisted path. Anywhere else it does NOT exempt the
        line (the underlying findings stand) and it is itself a finding — never a silent ignore.
        **This is the ONE place a finding's exemption is decided.** It is decided from the ADDED
        lines the finding COVERS: for a line-level class that is the line itself, and for a
        node-decided finding it is every added line inside the node (`covers`). A marker on an
        unchanged line therefore cannot exempt a newly added line — codex's r1 critical on #4844,
        where a marker on a call's unchanged opening line exempted an added ``api_key=`` argument
        further down. An empty ``covers`` falls back to the line's own text only.
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
        flagged = 0
        for line_no, text in sorted(added.items()):
            kinds = _text_classes(text)
            if "api-key-route" in kinds:
                flagged += 1
            emit(path, line_no, kinds, text)
        if (
            path.endswith(_PY_SUFFIXES)
            and content is not None
            and not parsed
            and flagged == 0
            and any(_KEY_BEARING_PROBE.search(text) for text in added.values())
        ):
            # ONE FINDING PER KEY-BEARING LINE, each with its own line's text: attributing a
            # region's damage to its first line let a marker on that line move the finding to
            # `allowed` while a later unmarked key-bearing line was never judged (dev21's r2
            # reproduction). The marker's contract is exactly the marked line.
            for line_no, text in sorted(added.items()):
                if _KEY_BEARING_PROBE.search(text):
                    emit(
                        path,
                        line_no,
                        ("billing-scan-unusable-input",),
                        text,
                        text=(
                            "this Python post-image does not parse and this added line carries "
                            f"credential-bearing text: {text.strip()[:120]!r}. Next action: make "
                            "the file parse at the head revision it names, or scan it whole; "
                            "unparseable credential-bearing text is never exempt."
                        ),
                    )
    return ScanResult(
        findings=tuple(findings), allowed=tuple(allowed), scanned_files=tuple(scanned)
    )


def main(argv: list[str] | None = None) -> int:
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

    if args.diff_file:
        try:
            diff_text = Path(args.diff_file).read_text(encoding="utf-8")
        except OSError as exc:
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
        generated = _run_git(
            ["diff", "--find-renames", "--unified=0", f"{args.base}...{args.head}"],
            repo=repo,
        )
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
        print(
            f"billing-surface-scan: FAIL-CLOSED: git is unavailable ({exc}), and this scanner "
            "validates its input with git before scanning anything. Next action: install git or "
            "run this scan where git is available",
            file=sys.stderr,
        )
        return 2
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


if __name__ == "__main__":
    raise SystemExit(main())
