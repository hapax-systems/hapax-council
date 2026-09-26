#!/usr/bin/env python3
"""Fail a PR diff that opens a provider-billing surface.

The provider_billing_sensitive release class's deterministic evidence
(RELEASE_MITIGATION_CHECKS, shared/sdlc_lifecycle.py): the ci.yml job
``billing-surface-scan`` runs this scan on every PR head, and the autoqueue
counts its SUCCESS as one arm of that class's evidence (the no-implicit-API/PAYG
rule; memory provider-spend-is-standing-authorized-not-api-spend).

**What success proves, and what it does not.** Success proves exactly this: no
ADDED line matched this scan's line patterns, and — for Python — every parsed
``Call`` carrying a credential argument also binds its own route to a governed
proxy target. It is **not proof** that the change cannot enable API or PAYG
spend: a syntactic scan plus a per-call structural check cannot give that
guarantee, and no reader should take it from this check. The semantic layer —
whether the change routes spend or moves work to another billing surface in a
way neither the patterns nor the calls name — is the review-team quorum's, which
is why the class requires both arms. Findings are likewise a lower bound on
what the diff may do: text that cannot be matched, or a Python region that
cannot be parsed, is a limitation of the scan and, where it is
credential-bearing, a finding rather than a pass.

The scan reads a unified diff and flags any ADDED line that:

- reads or injects a provider credential environment variable
  (``credential-env-read``),
- constructs an API-key client route or Bearer authorization header
  (``api-key-route``),
- names a provider API endpoint literal or a zero-argument provider SDK
  constructor — the bare invocation path whose credential comes implicitly
  from the environment (``provider-api-endpoint``), or
- rebinds a capacity pool or plan type to the api_paid_spend (PAYG) class
  (``capacity-pool-payg``).

Only added lines of non-doc files are scanned, and the two file kinds are
decided differently:

- **Python** — each hunk's post-image region is parsed with ``ast``, and an
  ``api-key-route`` is reported per ``Call`` node: a call carrying an
  ``api_key``/``key``/``token`` argument with no governed proxy target of its
  own. The exemption requires that **same** Call to pass ``base_url`` /
  ``api_base`` / ``endpoint`` as a *literal* string resolving to a governed
  proxy host (``127.0.0.1``, ``localhost``, ``::1``, ``litellm``). A dynamic
  value is not a binding, and neither is a target belonging to a neighbouring,
  earlier or chained call. A call is reported only when an ADDED line falls
  inside it, so a pre-existing call in the context lines is not this change's
  surface.
- **Non-Python** — the line patterns apply and there is **no proxy exemption at
  all**: no structure can bind a target to the call that carries the credential,
  so an ``api_key`` route in such a file is always a finding.

These never fail the scan, and each is printed as ``allowed`` so review sees
every one: protective credential strips (the governed launchers'
``os.environ.pop`` / ``del`` / ``unset`` of inherited keys), a Python call
genuinely bound to the governed proxy as above, and lines carrying the visible
``billing-scan:allow`` marker. **A proxy name anywhere else never exempts a
line.**

Fail-closed paths, so the absence of a finding is never an accident: a Python
region that does not parse is never exempt (the line rules apply), and if it is
credential-bearing while those rules cannot match, it becomes a
``billing-scan-unusable-input`` finding. A file whose header arrives with no
hunk and no binary note is the same kind of finding, because its content was
never read.

Exit codes: 0 clean, 1 findings, 2 fail-closed (no usable diff input).
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

#: Inline exemption marker, in the gitleaks:allow tradition: visible in the
#: diff, reported by the scan, justified to the review team. For test fixtures
#: and pattern-definition source, never for production spend paths.
ALLOW_MARKER = "billing-scan:allow"

#: Provider credential environment variable shapes the estate strips from
#: governed lanes (scripts/hapax-codex, scripts/hapax-codex-headless).
_CREDENTIAL_NAME = (
    r"[A-Z][A-Z0-9_]*_(?:API_KEY|API_TOKEN|AUTH_TOKEN|SECRET_KEY|ACCESS_TOKEN|SESSION_TOKEN)"
)

#: Protective credential strips are the governed pattern, not a surface.
_PROTECTIVE_RES = (
    re.compile(r"\bos\.environ\.pop\s*\("),
    re.compile(r"\bdel\s+os\.environ\s*\["),
    re.compile(r"\benv\.pop\s*\("),
    re.compile(r"(?:^|[\s;])unset\s+"),
)

_CREDENTIAL_ENV_READ_RES = (
    re.compile(rf"\bos\.environ\s*\[\s*[\"']?{_CREDENTIAL_NAME}"),
    re.compile(rf"\bos\.environ\.(?:get|setdefault)\s*\(\s*[\"']?{_CREDENTIAL_NAME}"),
    re.compile(rf"\bos\.getenv\s*\(\s*[\"']?{_CREDENTIAL_NAME}"),
    re.compile(rf"\bprocess\.env(?:\.|\[\s*[\"']){_CREDENTIAL_NAME}"),
    re.compile(rf"(?:^|[\s;])(?:export\s+)?{_CREDENTIAL_NAME}\s*=[^=]"),
    re.compile(rf"^\s*-?\s*[\"']?{_CREDENTIAL_NAME}[\"']?\s*:"),
)

#: Credential *argument* text (``api_key=...``, ``apiKey: ...``). Used for non-Python
#: files and as the fail-closed fallback for Python text that could not be parsed.
_API_KEY_ARG_RES = (
    re.compile(r"\bapi_key\s*=\s*[^\s,)]"),
    re.compile(r"\bapiKey\s*[:=]\s*[^\s,)}]"),
)
#: Authorization-header text, in plain, subscript and f-string forms. A header is not
#: a Call, so this stays a line rule in every file type and is never exempted.
_BEARER_RES = (
    re.compile(r"[\"']?Authorization[\"']?\]?\s*[:=]\s*[\"']?\s*Bearer\b"),
    re.compile(r"[\"']?Authorization[\"']?\]?\s*[:=]\s*(?:f|rf|br|rb)[\"']\s*Bearer\b"),
)

#: A client bound to the local LiteLLM proxy is the governed, quota-ledgered
#: route — not a new billing surface (its spend is metered by
#: shared/quota_spend_ledger.py).
#:
#: The exemption is bound to the ROUTE TARGET, never to a substring of the line
#: (codex critical, review round 1, 2026-09-26): ``OpenAI(api_key=key)  #
#: localhost`` must be flagged, because a proxy's *name* in a comment, a
#: variable name or a neighbouring literal cannot bind the route. A target
#: counts only when it is an argument of the call being constructed.
_GOVERNED_PROXY_HOSTS = ("127.0.0.1", "localhost", "::1", "litellm")
_ROUTE_TARGET_RE = re.compile(
    r"\b(?:base_url|baseURL|api_base|apiBase|api_endpoint|endpoint|proxy)\b"
    r"\s*[:=]\s*(?P<q>[\"'])(?P<target>[^\"']+)(?P=q)",
    re.IGNORECASE,
)

#: The estate's paid provider API hosts (registry: config/platform-capability-
#: registry.json; clients: shared/tavily_client.py, shared/runway_gen3_client.py,
#: shared/quota_spend_ledger.py). A literal provider endpoint in added code is a
#: route around the governed proxy.
_PROVIDER_API_HOSTS = (
    "api.anthropic.com",
    "api.openai.com",
    "api.moonshot.ai",
    "api.moonshot.cn",
    "api.z.ai",
    "open.bigmodel.cn",
    "api.openrouter.ai",
    "openrouter.ai",
    "api.tavily.com",
    "api.perplexity.ai",
    "generativelanguage.googleapis.com",
    "api.x.ai",
    "api.runwayml.com",
)
_PROVIDER_HOST_RE = re.compile(
    r"https?://(?:" + "|".join(re.escape(host) for host in _PROVIDER_API_HOSTS) + r")(?:[/\"'\s]|$)"
)

#: Zero-argument provider SDK constructors read their credential from the
#: environment implicitly — the bare/API invocation path.
_BARE_PROVIDER_SDK_RE = re.compile(r"\b(?:Async)?(?:OpenAI|Anthropic|AzureOpenAI)\s*\(\s*\)")

#: Rebinding work to the PAYG billing class (registry JSON, python enum, or a
#: session plan-type flip; quota reader precedent: test_vibe_api_binding_and_
#: undeclared_routes in tests/shared/test_quota_headroom.py).
_CAPACITY_POOL_PAYG_RE = re.compile(
    r"\bcapacity_pool[\"']?\s*[:=]\s*[\"']?(?:api_paid_spend|CapacityPool\.API_PAID_SPEND)\b"
)
_PLAN_TYPE_API_RE = re.compile(r"\bplan_type[\"']?\s*[:=]\s*[\"']api[\"']")

_PY_SUFFIXES = (".py",)
_DOC_SUFFIXES = (".md", ".rst", ".txt")
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    text: str


@dataclass(frozen=True)
class ScanResult:
    findings: tuple[Finding, ...]
    allowed: tuple[Finding, ...]
    scanned_files: tuple[str, ...]


def _is_doc_path(path: str) -> bool:
    lowered = path.strip().lower()
    return lowered.endswith(_DOC_SUFFIXES) or lowered.startswith("docs/")


def _host_of(target: str) -> str:
    """Reduce a route target to its host, for governed-proxy comparison."""

    value = target.strip()
    if "//" in value:
        value = value.split("//", 1)[1]
    if "@" in value:
        value = value.rsplit("@", 1)[1]
    value = value.split("/", 1)[0]
    if value.startswith("["):  # bracketed IPv6, e.g. [::1]:4000
        return value.split("]", 1)[0].lstrip("[").strip().lower()
    return value.split(":", 1)[0].strip().lower()


#: Argument names that make a ``Call`` an API-key route.
_API_KEY_ARG_NAMES = frozenset({"api_key", "key", "token"})
#: Argument names that can bind a ``Call``'s route to a governed proxy.
_ROUTE_TARGET_ARG_NAMES = ("base_url", "api_base", "endpoint")
#: A loose probe for "this text may carry a credential binding", used only to decide
#: whether an UNPARSEABLE region must fail closed.
_KEY_BEARING_PROBE = re.compile(r"api[_-]?key|apikey|\btoken\b|\bkey\b", re.IGNORECASE)


def _call_api_key_args(call: ast.Call) -> list[ast.keyword]:
    """The keyword arguments of ``call`` that name a credential."""

    return [kw for kw in call.keywords if kw.arg in _API_KEY_ARG_NAMES]


def _call_is_proxy_bound(call: ast.Call) -> bool:
    """True only when THIS Call binds its own route to a governed proxy.

    Structure, not text (review round 2, 2026-09-26): the target must be a
    *literal string* argument of the same Call node. A dynamic value — a name, an
    attribute, a subscript, a call, an f-string — is **not** exempt, and neither
    is a proxy target belonging to a neighbouring or chained Call.
    """

    for kw in call.keywords:
        if kw.arg not in _ROUTE_TARGET_ARG_NAMES:
            continue
        value = kw.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        if _host_of(value.value) in _GOVERNED_PROXY_HOSTS:
            return True
    return False


def _region_api_key_route_findings(
    path: str,
    region: list[tuple[int, str, bool]],
) -> tuple[list[Finding], bool]:
    """AST findings for one hunk's post-image region.

    ``region`` is ``(new_line_no, text, is_added)`` in post-image order. Returns
    ``(findings, parsed)``. A Call is reported only when it carries a credential
    argument **and** no governed proxy target of its own **and** at least one
    ADDED line falls inside it — a pre-existing call in the context lines is not
    this change's billing surface.
    """

    source = "\n".join(text for _, text, _ in region)
    tree: ast.Module | None = None
    # A hunk's post-image is a fragment, not a module: an indented statement (or a
    # dedented block) must still be readable structurally, or the legitimate proxy
    # exemption would be lost for ordinary indented code. Try as-is, then dedented.
    for candidate in (source, textwrap.dedent(source)):
        try:
            tree = ast.parse(candidate)
            source = candidate
            break
        except (SyntaxError, ValueError):
            continue
    if tree is None:
        return [], False
    added_lines = {line_no for line_no, _, is_added in region if is_added}
    first_line = region[0][0] if region else 0
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _call_api_key_args(node):
            continue
        if _call_is_proxy_bound(node):
            continue
        start = first_line + (node.lineno or 1) - 1
        end = first_line + (getattr(node, "end_lineno", node.lineno) or node.lineno) - 1
        if not any(start <= line_no <= end for line_no in added_lines):
            continue
        segment = ast.get_source_segment(source, node) or ""
        text = (segment.splitlines() or [""])[0].strip()
        out.append(Finding(path=path, line=start, kind="api-key-route", text=text[:200]))
    return out, True


def _classify_line(
    content: str, *, api_key_args: bool = True, bearer: bool = True
) -> tuple[str, ...]:
    """The line-level classes. Grants NO proxy exemption — ever.

    The governed-proxy exemption is structural and lives in the AST path. For a
    non-Python file it does not exist at all (review round 2), and for a Python
    line that could not be parsed there is no structure to bind a target to, so
    the line rules apply with no exemption.
    """

    kinds: list[str] = []
    protective = any(pattern.search(content) for pattern in _PROTECTIVE_RES)
    if not protective and any(pattern.search(content) for pattern in _CREDENTIAL_ENV_READ_RES):
        kinds.append("credential-env-read")
    if _PROVIDER_HOST_RE.search(content) or _BARE_PROVIDER_SDK_RE.search(content):
        kinds.append("provider-api-endpoint")
    if (api_key_args and any(p.search(content) for p in _API_KEY_ARG_RES)) or (
        bearer and any(p.search(content) for p in _BEARER_RES)
    ):
        kinds.append("api-key-route")
    if _CAPACITY_POOL_PAYG_RE.search(content) or _PLAN_TYPE_API_RE.search(content):
        kinds.append("capacity-pool-payg")
    return tuple(kinds)


def scan_unified_diff(text: str) -> ScanResult:
    findings: list[Finding] = []
    allowed: list[Finding] = []
    scanned: list[str] = []
    path: str | None = None
    skip_file = True
    new_line = 0
    region: list[tuple[int, str, bool]] = []
    saw_hunk = False
    binary_section = False

    def flush() -> None:
        """Analyse one hunk's post-image region, then clear it."""

        nonlocal region, saw_hunk
        if not region or path is None:
            region = []
            return
        added = [(line_no, content) for line_no, content, is_added in region if is_added]
        if path.endswith(_PY_SUFFIXES):
            ast_findings, parsed = _region_api_key_route_findings(path, region)
        else:
            ast_findings, parsed = [], False
        if parsed:
            # Structure decided the api-key class; headers are still line rules.
            for finding in ast_findings:
                line_content = next((c for n, c, _ in region if n == finding.line), finding.text)
                if ALLOW_MARKER in line_content:
                    allowed.append(finding)
                else:
                    findings.append(finding)
            for line_no, content in added:
                for kind in _classify_line(content, api_key_args=False):
                    finding = Finding(path=path, line=line_no, kind=kind, text=content.strip())
                    (allowed if ALLOW_MARKER in content else findings).append(finding)
        else:
            # Unparsed Python, or any non-Python file: line rules, and NO exemption.
            # A proxy argument of any spelling cannot exempt here, because there is no
            # structure to bind it to the call that carries the credential.
            flagged = 0
            for line_no, content in added:
                for kind in _classify_line(content):
                    finding = Finding(path=path, line=line_no, kind=kind, text=content.strip())
                    if kind == "api-key-route":
                        flagged += 1
                    (allowed if ALLOW_MARKER in content else findings).append(finding)
            if (
                path.endswith(_PY_SUFFIXES)
                and not parsed
                and flagged == 0
                and any(
                    _KEY_BEARING_PROBE.search(content) and ALLOW_MARKER not in content
                    for _, content in added
                )
            ):
                # codex major, round 2: a post-image that cannot be parsed must not be
                # read as clean when it may carry a credential binding. This fires only
                # for key-bearing unparseable text, so an ordinary unparseable hunk (most
                # hunks) is not a finding: flagging every one would make this class
                # unarmable, which is the defect this entry exists to fix.
                first = added[0]
                findings.append(
                    Finding(
                        path=path,
                        line=first[0],
                        kind="billing-scan-unusable-input",
                        text=(
                            "this Python post-image region does not parse, and it carries "
                            f"credential-bearing text: {first[1].strip()[:120]!r}. "
                            "Next action: make the region parse (or scan the file at its "
                            "full head revision) so the structural check can decide; "
                            "unparseable credential-bearing text is never exempt."
                        ),
                    )
                )
        region = []

    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            flush()
            if path is not None and not skip_file and not saw_hunk and not binary_section:
                # codex major, round 2: a file header with no usable hunk and no binary
                # note means the file's content was never read — unusable input, not a
                # clean scan.
                findings.append(
                    Finding(
                        path=path,
                        line=0,
                        kind="billing-scan-unusable-input",
                        text=(
                            "the diff carries this file's header but no hunk and no binary "
                            "note, so no added line could be read. Next action: regenerate "
                            "the diff (the file's content must be present) or confirm the "
                            "change is binary."
                        ),
                    )
                )
            path = None
            skip_file = True
            saw_hunk = False
            binary_section = False
            continue
        if raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            binary_section = True
            continue
        if raw.startswith("index ") or raw.startswith("old mode") or raw.startswith("new mode"):
            continue
        if raw.startswith("+++ "):
            flush()
            candidate = raw[4:].strip()
            if candidate == "/dev/null":
                path = None
                skip_file = True
                continue
            path = candidate[2:] if candidate.startswith("b/") else candidate
            skip_file = _is_doc_path(path)
            saw_hunk = False
            if not skip_file:
                scanned.append(path)
            continue
        if skip_file or path is None:
            continue
        header = _HUNK_HEADER_RE.match(raw)
        if header:
            flush()
            saw_hunk = True
            new_line = int(header.group(1))
            continue
        if raw.startswith("-"):
            continue
        if raw.startswith("+"):
            region.append((new_line, raw[1:], True))
            new_line += 1
            continue
        region.append((new_line, raw[1:] if raw.startswith(" ") else raw, False))
        new_line += 1  # context line
    flush()
    if path is not None and not skip_file and not saw_hunk and not binary_section:
        findings.append(
            Finding(
                path=path,
                line=0,
                kind="billing-scan-unusable-input",
                text=(
                    "the diff ends with this file's header but no hunk and no binary "
                    "note, so no added line could be read. Next action: regenerate the "
                    "diff or confirm the change is binary."
                ),
            )
        )
    return ScanResult(
        findings=tuple(findings),
        allowed=tuple(allowed),
        scanned_files=tuple(scanned),
    )


def _read_diff(args: argparse.Namespace) -> str | None:
    if args.diff_file:
        try:
            return Path(args.diff_file).read_text(encoding="utf-8")
        except OSError as exc:
            print(
                f"billing-surface-scan: FAIL-CLOSED: cannot read diff file: {exc}",
                file=sys.stderr,
            )
            return None
    if args.base and args.head:
        proc = subprocess.run(
            ["git", "diff", "--find-renames", "--unified=0", f"{args.base}...{args.head}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            print(
                "billing-surface-scan: FAIL-CLOSED: git diff "
                f"{args.base}...{args.head}: {proc.stderr.strip()}",
                file=sys.stderr,
            )
            return None
        return proc.stdout
    print(
        "billing-surface-scan: FAIL-CLOSED: provide --diff-file or --base/--head",
        file=sys.stderr,
    )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--base", help="base revision (three-dot diff against --head)")
    parser.add_argument("--head", help="head revision")
    parser.add_argument("--diff-file", help="read a unified diff from a file instead of git")
    args = parser.parse_args(argv)
    text = _read_diff(args)
    if text is None:
        return 2
    # Fail CLOSED on unusable input (codex major, review round 1, 2026-09-26): an
    # empty or structureless diff is not evidence that the change is clean, and
    # reporting success on it would let a gate bless a diff it never read.
    #
    # ONE guard, two messages. Emptiness is a *kind* of structurelessness — both
    # mean no added line could be read — so the predicate is the structure, not
    # two separate conditions. (An empty-only guard beside a structural one is
    # dead code: the structural guard already fails empty input closed. That
    # redundancy was measured, not assumed: with the empty guard disabled the
    # whole case-2 set still passed.)
    if not text.strip() or ("diff --git " not in text and "+++ " not in text):
        if not text.strip():
            print(
                "billing-surface-scan: FAIL-CLOSED: empty diff input is not evidence. "
                "Next action: pass the PR diff (--base/--head) or a non-empty "
                "(--diff-file); a PR that genuinely changes no file is covered by the "
                "merge-group duplicate sentinel, not by this scan reporting success.",
                file=sys.stderr,
            )
        else:
            print(
                "billing-surface-scan: FAIL-CLOSED: input has no unified-diff structure "
                "(no 'diff --git' and no '+++ ' file header), so no added line could be "
                "read. Next action: confirm the diff command and rerun; a truncated or "
                "prose input must never read as a clean scan.",
                file=sys.stderr,
            )
        return 2
    result = scan_unified_diff(text)
    for finding in result.allowed:
        print(
            f"allowed {finding.path}:{finding.line}: {finding.kind} "
            f"({ALLOW_MARKER}): {finding.text}"
        )
    if result.findings:
        for finding in result.findings:
            print(f"{finding.path}:{finding.line}: {finding.kind}: {finding.text}")
        print(
            f"billing-surface-scan: FAIL: {len(result.findings)} billing-surface "
            "mutation(s) in the diff. Next action: remove the added billing surface "
            "or route the client through the governed LiteLLM proxy, then rerun; if "
            "the line is a scan fixture or a pattern definition, mark it visibly with "
            f"{ALLOW_MARKER} so review sees the exemption. If a finding is wrong, fix "
            "the scan in the same PR rather than exempting the line."
        )
        return 1
    print(
        "billing-surface-scan: OK: no billing-surface mutation in "
        f"{len(result.scanned_files)} changed file(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
