#!/usr/bin/env python3
"""Fail a PR diff that opens a provider-billing surface.

The provider_billing_sensitive release class's deterministic evidence
(RELEASE_MITIGATION_CHECKS, shared/sdlc_lifecycle.py): the ci.yml job
``billing-surface-scan`` runs this scan on every PR head, and the autoqueue
counts its SUCCESS as proof that the change cannot enable API or PAYG spend or
move work to another billing surface (the no-implicit-API/PAYG rule; memory
provider-spend-is-standing-authorized-not-api-spend).

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

Only added lines of non-doc files are scanned. Protective credential strips
(the governed launchers' ``os.environ.pop`` / ``del`` / ``unset`` of inherited
keys), clients bound to the governed LiteLLM proxy route (the estate's
quota-ledgered billing path), and lines carrying the visible
``billing-scan:allow`` marker never fail the scan; marker uses are printed as
``allowed`` so review sees every one. The scan is syntactic; the semantic
layer is the review-team quorum (the same trust split as the egress class).

Exit codes: 0 clean, 1 findings, 2 fail-closed (no usable diff input).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
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

_API_KEY_ROUTE_RES = (
    re.compile(r"\bapi_key\s*=\s*[^\s,)]"),
    re.compile(r"\bapiKey\s*[:=]\s*[^\s,)}]"),
    re.compile(r"[\"']?Authorization[\"']?\s*[:=]\s*[\"']?\s*Bearer\b"),
)

#: A client bound to the local LiteLLM proxy is the governed, quota-ledgered
#: route — not a new billing surface (its spend is metered by
#: shared/quota_spend_ledger.py).
_GOVERNED_PROXY_HINT = re.compile(r"litellm|127\.0\.0\.1|localhost", re.IGNORECASE)

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
    r"https?://(?:"
    + "|".join(re.escape(host) for host in _PROVIDER_API_HOSTS)
    + r")(?:[/\"'\s]|$)"
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


def _classify_line(content: str) -> tuple[str, ...]:
    kinds: list[str] = []
    protective = any(pattern.search(content) for pattern in _PROTECTIVE_RES)
    if not protective and any(
        pattern.search(content) for pattern in _CREDENTIAL_ENV_READ_RES
    ):
        kinds.append("credential-env-read")
    if _PROVIDER_HOST_RE.search(content) or _BARE_PROVIDER_SDK_RE.search(content):
        kinds.append("provider-api-endpoint")
    if not _GOVERNED_PROXY_HINT.search(content) and any(
        pattern.search(content) for pattern in _API_KEY_ROUTE_RES
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
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            path = None
            skip_file = True
            continue
        if raw.startswith("+++ "):
            candidate = raw[4:].strip()
            if candidate == "/dev/null":
                path = None
                skip_file = True
                continue
            path = candidate[2:] if candidate.startswith("b/") else candidate
            skip_file = _is_doc_path(path)
            if not skip_file:
                scanned.append(path)
            continue
        if skip_file or path is None:
            continue
        header = _HUNK_HEADER_RE.match(raw)
        if header:
            new_line = int(header.group(1))
            continue
        if raw.startswith("-"):
            continue
        if raw.startswith("+"):
            content = raw[1:]
            line_no = new_line
            new_line += 1
            for kind in _classify_line(content):
                finding = Finding(path=path, line=line_no, kind=kind, text=content.strip())
                if ALLOW_MARKER in content:
                    allowed.append(finding)
                else:
                    findings.append(finding)
            continue
        new_line += 1  # context line
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
            "mutation(s) in the diff"
        )
        return 1
    print(
        "billing-surface-scan: OK: no billing-surface mutation in "
        f"{len(result.scanned_files)} changed file(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
