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
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

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
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


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
            out.append(Finding(path=path, line=line_no, kind="api-key-route", text=snippet(node)))
        if _node_credential_env_read(node):
            if id(node) in strip_targets:
                continue  # the strip's target itself; recorded above
            out.append(
                Finding(path=path, line=line_no, kind="credential-env-read", text=snippet(node))
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


class GitUnavailable(RuntimeError):
    """git itself is missing: this scanner cannot validate its input without it."""


class UnusableInput(RuntimeError):
    """The input is not a diff git will apply to the base. Nothing is scanned."""


#: Lines git emits around a section (never a body line). ``+++ b/<path>`` names the post-image path;
#: ``--- a/<path>`` is consumed and ignored.
_SECTION_META_PREFIXES: tuple[str, ...] = (
    "index ",
    "new file mode ",
    "deleted file mode ",
    "old mode ",
    "new mode ",
    "similarity index ",
    "dissimilarity index ",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
)


def _run_git(
    args: list[str],
    *,
    repo: Path,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo),
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:  # git absent, or not executable
        raise GitUnavailable(str(exc)) from exc


def _git_out(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stderr or proc.stdout or "").strip()


def _resolve_base(base: str, *, repo: Path) -> str:
    proc = _run_git(["rev-parse", "--verify", f"{base}^{{commit}}"], repo=repo)
    if proc.returncode != 0:
        raise UnusableInput(
            f"~base '{base}' is not a commit git can resolve here ({_git_out(proc)}). Next action: "
            "pass --base as the PR's base revision (or a commit sha) in this repository"
        )
    return proc.stdout.strip()


def materialise_post_image(diff_text: str, *, repo: Path, base: str) -> tuple[Path, dict[str, str]]:
    """The temporary index git builds from ``base`` + the input diff, or UnusableInput.

    GIT VALIDATES THE INPUT HERE. ``git apply --check`` proves the input is a well-formed diff
    that applies to the resolved base; ``git apply --cached`` then materialises the post-image in
    an index seeded from the base's tree. A shape git will not apply is billing-scan-unusable-input
    with a next action — there is no permissive parse of raw diff text to leak.
    """
    resolved = _resolve_base(base, repo=repo)
    index_dir = Path(tempfile.mkdtemp(prefix="billing-scan-index-"))
    index_path = index_dir / "index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
    read = _run_git(["read-tree", resolved], repo=repo, env=env)
    if read.returncode != 0:
        raise UnusableInput(
            f"git could not seed a temporary index from {resolved[:12]}: {_git_out(read)}. Next "
            "action: run this scanner inside the repository whose base it names"
        )
    # VALIDATE AGAINST THE BASE TREE, not the worktree: --cached checks the diff against the tree
    # the temporary index holds. (A plain `git apply --check` reads the worktree, which is the
    # post-image on a PR head, so a correct diff would look unapplicable.)
    check = _run_git(
        ["apply", "--cached", "--check", "--whitespace=nowarn", "-"],
        repo=repo,
        env=env,
        stdin=diff_text,
    )
    if check.returncode != 0:
        raise UnusableInput(
            f"git will not apply this input to {resolved[:12]}: {_git_out(check)}. Next action: "
            "regenerate the diff with `git diff <base>...HEAD` in this repository (or fix the "
            "input); a diff git cannot apply is billing-scan-unusable-input and is never scanned"
        )
    applied = _run_git(
        ["apply", "--cached", "--whitespace=nowarn", "-"], repo=repo, env=env, stdin=diff_text
    )
    if applied.returncode != 0:
        raise UnusableInput(
            f"git accepted the input with --check but could not apply it to the index: "
            f"{_git_out(applied)}. Next action: regenerate the diff from the same repository state "
            "and rerun"
        )
    return index_path, env


def parse_git_added_lines(text: str) -> tuple[dict[str, dict[int, str]], str | None]:
    """Added lines per post-image path from git's OWN ``--unified=0`` output.

    A CLOSED grammar over the lines git emits for a text diff: section metadata, ``---``/``+++``
    headers, a ``Binary files … differ`` note, hunk headers, body lines and the
    ``\\ No newline at end of file`` marker. **The default is REJECT**: a line this grammar does not
    know refuses the input (with its own next action) rather than being skipped, so an
    unanticipated shape can never scan clean.
    """
    files: dict[str, dict[int, str]] = {}
    pending_path: str | None = None
    path: str | None = None
    new_line = 0
    in_hunk = False
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            pending_path = None
            path = None
            in_hunk = False
            continue
        if raw.startswith(_SECTION_META_PREFIXES):
            continue
        if raw.startswith("--- ") or raw.startswith("+++ "):
            candidate = raw[4:].strip()
            if raw.startswith("--- "):
                continue
            if candidate == "/dev/null":
                pending_path = None
            elif candidate.startswith("b/"):
                pending_path = candidate[2:]
            else:
                return {}, f"a '+++ ' header git would not emit: {raw!r}"
            continue
        if raw.startswith(("Binary files ", "GIT binary patch")):
            # A declared-binary section's payload is opaque: git shows no added lines for it.
            pending_path = None
            in_hunk = False
            continue
        header = _HUNK_HEADER_RE.match(raw)
        if header is not None:
            if pending_path is None:
                return {}, "a hunk header arrived before any '+++ b/<path>' header"
            path = pending_path
            new_line = int(header.group(3))
            in_hunk = True
            continue
        if raw.startswith("\\"):
            # `\ No newline at end of file` is hunk metadata, never an added line.
            continue
        if in_hunk and raw.startswith("+"):
            if path is None:
                return {}, "an added line arrived with no post-image path"
            files.setdefault(path, {})[new_line] = raw[1:]
            new_line += 1
            continue
        if in_hunk and raw.startswith(("-", " ")):
            if raw.startswith(" "):
                # A context line cannot occur under --unified=0; accepting the shape is not a
                # fail-open because a context line is never scanned as added.
                new_line += 1
            continue
        return {}, f"an unrecognised line in git's own diff output: {raw!r}"
    return files, None


def post_image_blob(path: str, *, repo: Path, env: dict[str, str]) -> str | None:
    """git's own post-image text for ``path``, or None when git cannot hand it over as text.

    None is a LIMITATION, never a pass: the caller then judges the added lines by the text
    patterns, which grant no structural exemption.
    """
    try:
        proc = subprocess.run(
            ["git", "show", f":{path}"], cwd=str(repo), env=env, capture_output=True, check=False
        )
    except OSError as exc:
        raise GitUnavailable(str(exc)) from exc
    if proc.returncode != 0 or not proc.stdout:
        return None
    if b"\x00" in proc.stdout[:8192]:  # binary blob: opaque, and never parsed as text
        return None
    return proc.stdout.decode("utf-8", errors="replace")


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
    index_path, env = materialise_post_image(diff_text, repo=repo, base=base)
    del index_path
    regenerated = _run_git(
        ["diff", "--cached", "--no-color", "--no-ext-diff", "--unified=0", f"{base}^{{commit}}"],
        repo=repo,
        env=env,
    )
    if regenerated.returncode != 0:
        return None, (
            f"FAIL-CLOSED: git could not regenerate the diff from the validated index: "
            f"{_git_out(regenerated)}. Next action: rerun in the repository whose base it names"
        )
    files, error = parse_git_added_lines(regenerated.stdout)
    if error is not None:
        return None, (
            f"FAIL-CLOSED: {error}. Next action: this shape is not one git emits for a text diff, "
            "so nothing is scanned; regenerate the input with `git diff <base>...HEAD` and rerun"
        )

    findings: list[Finding] = []
    allowed: list[Finding] = []
    scanned: list[str] = []

    def emit(
        path: str, line_no: int, kinds: tuple[str, ...], content: str, text: str | None = None
    ) -> None:
        """Record one added line's kinds, applying the marker decision.

        The marker is honoured only on an allowlisted path. Anywhere else it does NOT exempt the
        line (the underlying findings stand) and it is itself a finding — never a silent ignore.
        **This is the ONE place a finding's exemption is decided**, and it is decided from the
        finding's OWN line: ``line_no``/``content`` must be the line the finding is about, so a
        neighbour's marker can never speak for it (the r3 marker leak).
        """
        marked = ALLOW_MARKER in content
        if not kinds and not marked:
            return
        marker_ok = marked and _marker_is_allowed_on(path)
        if marked and not marker_ok:
            findings.append(_marker_outside_fixtures_finding(path, line_no, content))
        for kind in kinds:
            finding = Finding(
                path=path,
                line=line_no,
                kind=kind,
                text=text if text is not None else content.strip()[:200],
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
                emit(path, finding.line, (finding.kind,), line_content, text=finding.text)
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
    return (
        ScanResult(
            findings=tuple(findings),
            allowed=tuple(allowed),
            scanned_files=tuple(scanned),
        ),
        None,
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
