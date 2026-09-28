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
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.billing_surface_input import (  # noqa: E402
    GitUnavailable,
    UnusableInput,
    _git_out,
    _run_git,
    materialise_post_image,
    post_image_blob,
    regenerated_added_lines,
)

#: Inline exemption marker, in the gitleaks:allow tradition: visible in the
#: diff, reported by the scan, justified to the review team. For test fixtures
#: and pattern-definition source, never for production spend paths.
ALLOW_MARKER = "billing-scan:allow"

ALLOW_MARKER_PATH_ALLOWLIST = (
    "tests/",
    "scripts/check-billing-surface-diff.py",
)
#: Pattern-definition modules that legitimately carry the marker. Named one by one:
#: a glob here would re-open the hole the allowlist exists to close. Empty today —
#: the scanner's own path above is the named pattern source.
ALLOW_MARKER_PATTERN_MODULES: tuple[str, ...] = ()


def _marker_is_allowed_on(path: str) -> bool:
    """True only on an allowlisted fixture or pattern-definition path.

    **A path entry that names a FILE matches that file exactly; only an entry that ends in
    ``/`` is a directory prefix.** The old ``startswith`` over both kinds admitted
    ``scripts/check-billing-surface-diff.py_helper.py`` — a production file that merely
    begins with an allowlisted file's name bought the self-exemption the allowlist exists to
    deny (codex major, round 5).
    """

    candidate = path.strip()
    if candidate in ALLOW_MARKER_PATTERN_MODULES:
        return True
    for entry in ALLOW_MARKER_PATH_ALLOWLIST:
        if entry.endswith("/"):
            # A directory entry matches at the repo root only: `tests/x.py` yes,
            # `notests/x.py` no (the entry keeps its trailing slash), `pkg/tests/x.py` no.
            if candidate.startswith(entry):
                return True
        elif candidate == entry:
            return True
    return False


def _marker_outside_fixtures_finding(path: str, line_no: int, text: str) -> Finding:
    return Finding(
        path=path,
        line=line_no,
        kind="billing-scan-allow-outside-fixtures",
        text=(
            f"{ALLOW_MARKER} on a non-fixture path cannot self-exempt: {text.strip()[:120]!r}. "
            "Next action: remove the marker; a production spend path cannot suppress this "
            "scan — route the client through the governed LiteLLM proxy, or get a seat "
            "ruling recorded on the row."
        ),
    )


#: Provider credential environment variable shapes the estate strips from
#: governed lanes (scripts/hapax-codex, scripts/hapax-codex-headless).
_CREDENTIAL_NAME = (
    r"[A-Z][A-Z0-9_]*_(?:API_KEY|API_TOKEN|AUTH_TOKEN|SECRET_KEY|ACCESS_TOKEN|SESSION_TOKEN)"
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

_GOVERNED_PROXY_HOSTS = ("127.0.0.1", "localhost", "::1", "litellm")

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


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    text: str
    #: Added post-image lines this finding covers, when it is decided on a NODE. The marker decision
    #: reads these, so a marker on an unchanged line can never exempt a newly added line inside the
    #: node (codex's r1 critical on #4844).
    covers: tuple[int, ...] = ()


@dataclass(frozen=True)
class ScanResult:
    findings: tuple[Finding, ...]
    allowed: tuple[Finding, ...]
    scanned_files: tuple[str, ...]


def _is_doc_path(path: str) -> bool:
    lowered = path.strip().lower()
    return lowered.endswith(_DOC_SUFFIXES) or lowered.startswith("docs/")


_EMPTY_BLOB_SHORT = "e69de29"


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


EXEMPTION_SITES: dict[str, str] = {
    "proxy": "per ast.Call: that call's own literal base_url/api_base/endpoint target",
    "protective_strip": "per ast node: ONLY the target node of os.environ.pop(<literal>[, default]) or del os.environ[<literal>]; every other child, the default argument included, is scanned",
    "allow_marker": "path-allowlisted comment (tests/**, the scanner's own source); applies to the marked line's nodes only",
    "text_path_non_python": "none: non-Python files, and Python text that did not parse, grant no structural exemption (the marker site is the only one they can carry)",
}
#: The functions that implement the AST-decided sites. The guard test
#: (`tests/scripts/test_check_billing_surface_diff.py::test_no_exemption_is_decided_from_line_content`)
#: parses this scanner's own source and fails if any of them takes line text as an input.
NODE_EXEMPTION_FUNCTIONS: tuple[str, ...] = ("_call_is_proxy_bound", "_strip_target_node")
#: “Line text” carriers the guard refuses to see inside an exemption function.
_LINE_TEXT_NAMES = frozenset({"content", "line", "raw", "text", "source"})


def _credential_name_matches(value: str) -> bool:
    """True when a literal names a credential environment variable."""

    return re.search(_CREDENTIAL_NAME, value) is not None


def _is_os_environ(node: ast.AST) -> bool:
    """True for ``os.environ`` (attribute) or a bare ``environ`` name."""

    if isinstance(node, ast.Attribute):
        return node.attr == "environ" and isinstance(node.value, ast.Name) and node.value.id == "os"
    return isinstance(node, ast.Name) and node.id == "environ"


def _literal_str(node: ast.AST) -> str | None:
    """The value of a literal string node, else None (a dynamic value is not a literal)."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _strip_target_node(node: ast.AST) -> ast.AST | None:
    """The ONE child a recognised protective strip exempts: the credential it strips.

    Recognised forms are exactly ``os.environ.pop(<literal>[, default])`` and
    ``del os.environ[<literal>]``; the exempt node is the **target literal** (for
    ``del``, the subscript that names it). **Every other child node is scanned as
    ordinary code — the default argument included** (codex-1's round-4 critical:
    ``os.environ.pop("OLD_API_KEY", os.environ["OPENAI_API_KEY"])`` was passing
    because the exemption covered the whole subtree, so the added read in the
    default argument was never reported).

    ``env.pop(...)`` and shell ``unset`` are **not recognised as strips at all** —
    not here and not on the text path — because they are not the governed launcher
    pattern, and exempting whatever object happens to be named ``env`` is how this
    hole kept re-opening. There is no path on which they are exempt: the text path
    grants no exemption whatsoever (see ``EXEMPTION_SITES``).
    """

    if isinstance(node, ast.Delete) and len(node.targets) == 1:
        target = node.targets[0]
        if (
            isinstance(target, ast.Subscript)
            and _is_os_environ(target.value)
            and _literal_str(target.slice) is not None
        ):
            return target
        return None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "pop"
        and _is_os_environ(node.func.value)
        and bool(node.args)
        and _literal_str(node.args[0]) is not None
    ):
        return node.args[0]
    return None


def _node_credential_env_read(node: ast.AST) -> bool:
    """True for a credential env READ or INJECTION, per node.

    ``os.environ["X"]`` (read or assignment target), ``os.environ.get("X")``,
    ``os.getenv("X")``, ``os.environ.setdefault("X", ...)`` — matched only on a
    LITERAL credential name. Named non-literals are left to review; a literal that
    is not a credential name is not this class.
    """

    if isinstance(node, ast.Subscript) and _is_os_environ(node.value):
        name = _literal_str(node.slice)
        return name is not None and _credential_name_matches(name)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        attr = node.func.attr
        if attr in {"get", "setdefault"} and _is_os_environ(node.func.value):
            name = _literal_str(node.args[0]) if node.args else None
            return name is not None and _credential_name_matches(name)
        if (
            attr == "getenv"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        ):
            name = _literal_str(node.args[0]) if node.args else None
            return name is not None and _credential_name_matches(name)
    return False


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


def _node_findings_for_postimage(
    path: str, content: str, added_lines: set[int]
) -> tuple[list[Finding], list[Finding], bool]:
    """Per-node findings for the post-image blob GIT materialised (Python).

    ``content`` is git's own post-image for ``path`` (``git show :<path>`` against the index the
    input diff was applied to), so positions are absolute file lines and nothing is reconstructed
    from diff text. Returns ``(findings, allowed, parsed)`` — ``allowed`` names every exemption this
    blob granted, with its path and line, so the report shows what the gate let through.

    **Every exemption is decided on a NODE, never on a line** (round-3 contract):

    - ``protective_strip`` exempts only the strip's **target** node, so a credential read elsewhere
      on the same line is still counted (the round-3 case,
      ``os.environ.pop("OLD_API_KEY", None); key = os.environ["OPENAI_API_KEY"]``) **and so is a
      read in the strip's own default argument** (the round-4 case,
      ``os.environ.pop("OLD_API_KEY", os.environ["OPENAI_API_KEY"])``);
    - ``proxy`` exempts only a ``Call`` whose own route target is a governed proxy;
    - a node is reported only when an ADDED line falls inside it, so pre-existing code is not this
      change's surface.

    The blob is parsed as-is: it is a whole file, so a dedent fallback would move every line.
    """
    try:
        tree: ast.Module | None = ast.parse(content)
    except (SyntaxError, ValueError):
        tree = None
    if tree is None:
        return [], [], False
    source = content

    def node_is_added(node: ast.AST) -> bool:
        # ``ast.walk`` yields nodes with no position (Module, operator singletons, ...). They are
        # not operations and cannot carry a surface.
        if getattr(node, "lineno", None) is None:
            return False
        start = node.lineno or 1
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        return any(start <= line_no <= end for line_no in added_lines)

    def snippet(node: ast.AST) -> str:
        segment = ast.get_source_segment(source, node) or ""
        return (segment.splitlines() or [""])[0].strip()[:200]

    out: list[Finding] = []
    allowed_out: list[Finding] = []

    def covered(node: ast.AST) -> tuple[int, ...]:
        """The ADDED lines the node spans, in order: the marker decision reads these and only these."""
        start = node.lineno or 1
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        return tuple(line for line in sorted(added_lines) if start <= line <= end)

    # ONLY the strip's target node is exempt. Its other children — the default argument above all —
    # are scanned like any other code (codex-1's round-4 critical).
    strip_targets: set[int] = set()
    for node in ast.walk(tree):
        if not node_is_added(node):
            continue
        target = _strip_target_node(node)
        if target is None:
            continue
        strip_targets.add(id(target))
        allowed_out.append(
            Finding(
                path=path,
                line=node.lineno or 1,
                kind="protective-strip",
                text=snippet(node),
                covers=covered(node),
            )
        )

    for node in ast.walk(tree):
        if not node_is_added(node):
            continue
        line_no = node.lineno or 1
        if isinstance(node, ast.Call) and _call_api_key_args(node):
            if _call_is_proxy_bound(node):
                allowed_out.append(
                    Finding(
                        path=path, line=line_no, kind="governed-proxy-route", text=snippet(node)
                    )
                )
                continue
            out.append(
                Finding(
                    path=path,
                    line=line_no,
                    kind="api-key-route",
                    text=snippet(node),
                    covers=covered(node),
                )
            )
        if _node_credential_env_read(node):
            if id(node) in strip_targets:
                continue  # the strip's target itself; recorded above
            out.append(
                Finding(
                    path=path,
                    line=line_no,
                    kind="credential-env-read",
                    text=snippet(node),
                    covers=covered(node),
                )
            )
    return out, allowed_out, True


def _pattern_only_classes(content: str) -> tuple[str, ...]:
    """The two classes decided by patterns alone, in every file kind.

    They carry **no exemption**, so a line rule cannot hide a different operation
    on the same line — which is the whole round-3 lesson. (A provider host literal
    or a PAYG rebinding has no legitimate per-node exemption to grant.)
    """

    kinds: list[str] = []
    if _PROVIDER_HOST_RE.search(content) or _BARE_PROVIDER_SDK_RE.search(content):
        kinds.append("provider-api-endpoint")
    if _CAPACITY_POOL_PAYG_RE.search(content) or _PLAN_TYPE_API_RE.search(content):
        kinds.append("capacity-pool-payg")
    return tuple(kinds)


def _text_classes(content: str) -> tuple[str, ...]:
    """The full line-class set, with **no exemptions of any kind**.

    Used for non-Python files and for Python text that could not be parsed: without
    structure there is nothing to bind an exemption to, so every pattern hit is a
    finding. The header rules are here too — a Bearer header is not a Call, so it is
    line-level in every file kind and is never exempted.
    """

    kinds: list[str] = []
    if any(pattern.search(content) for pattern in _CREDENTIAL_ENV_READ_RES):
        kinds.append("credential-env-read")
    if any(pattern.search(content) for pattern in _API_KEY_ARG_RES) or any(
        pattern.search(content) for pattern in _BEARER_RES
    ):
        kinds.append("api-key-route")
    kinds.extend(_pattern_only_classes(content))
    return tuple(kinds)


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
                if any(pattern.search(text) for pattern in _BEARER_RES):
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
