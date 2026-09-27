#!/usr/bin/env python3
"""Fail a PR diff that opens a provider-billing surface.

The provider_billing_sensitive release class's deterministic evidence
(RELEASE_MITIGATION_CHECKS, shared/sdlc_lifecycle.py): the ci.yml job
``billing-surface-scan`` runs this scan on every PR head, and the autoqueue
counts its SUCCESS as one arm of that class's evidence (the no-implicit-API/PAYG
rule; memory provider-spend-is-standing-authorized-not-api-spend).

**None of that wiring is in this file's PR.** The `RELEASE_MITIGATION_CHECKS`
entry, the `ci.yml` job and the autoqueue's evidence read land in **#4805**
(the second half of the #4795 split); this half is the scanner the wiring will
invoke, so nothing here is wired to anything yet.

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
- **Non-Python** — the line patterns apply and there is **no structural
  exemption**: nothing there can bind an exemption to the operation that carries
  the credential, so every pattern hit in such a file is a finding, per line and
  per statement alike. The visible marker on an **allowlisted path** is the only
  exemption a non-Python file can carry, and it is shared with every file kind.

Every exemption the scan grants is printed as ``allowed`` with its path and line,
so review sees each one: a Python ``Call`` genuinely bound to the governed proxy,
the **target node alone** of a Python protective strip
(``os.environ.pop(<literal>[, default])`` or ``del os.environ[<literal>]`` — never a
read elsewhere on the line, and never the strip's own default argument), and a line
carrying the visible ``billing-scan:allow`` marker on an allowlisted path. **A proxy
name anywhere else never exempts a line, a strip's other children are scanned as
ordinary code, and no non-Python file is granted a structural exemption — the
marker on an allowlisted fixture path is the only kind it can carry.**

Fail-closed paths, so the absence of a finding is never an accident: a Python
region that does not parse is never exempt (the line rules apply), and if it is
credential-bearing while those rules cannot match, it becomes a
``billing-scan-unusable-input`` finding. An **incomplete section** is the same kind
of finding, because its content was never read, and completeness is judged from the
input rather than from the file's class: a section is whole when it shows a binary
note, a mode-only change, a pure rename, an empty-file ``index``, or a hunk **whose
body delivered the counts its header declares** (a hunk that ends short was cut
inside). An ``index``-only header is a truncated content change, never a clean scan.

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

#: Paths on which the visible ``billing-scan:allow`` marker is HONOURED. Everywhere
#: else the marker is itself a finding (``billing-scan-allow-outside-fixtures``).
#:
#: Why this exists (dev21's recommendation, 2026-09-26): the marker was a
#: self-exemption hole — one added comment on a production API-key route made the
#: scan pass, and the scan's pass is what the billing mitigation gate treats as
#: evidence. Review is the wrong single control for a billing gate (today's own
#: measurements: 12–22 % diff coverage on large diffs, refuted criticals re-fed,
#: three rounds to catch the paren-window bypass). The gitleaks tradition works
#: because secrets have a second net — rotation and monitoring; this gate's second
#: net is PAYG spend. So the marker is honoured on fixture paths only, and the
#: pattern-definition modules are named file by file rather than by glob.
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

#: NOTE: the protective strip is NOT a line pattern and NOT a subtree. It was a pattern
#: over the whole line, so `os.environ.pop("OLD_API_KEY", None); key = os.environ["OPENAI_API_KEY"]`
#: passed (round-3 critical); it was then the whole strip subtree, so
#: `os.environ.pop("OLD_API_KEY", os.environ["OPENAI_API_KEY"])` passed (round-4 critical).
#: It is now decided per node by `_strip_target_node`, which returns the **one** node a
#: recognised strip exempts — the credential it strips. Exactly two forms are recognised,
#: `os.environ.pop(<literal>[, default])` and `del os.environ[<literal>]`; **every other
#: child of the strip, the default argument included, is scanned as ordinary code**.
#: `env.pop(...)` and shell `unset` are not recognised at all, on any path. Keeping the
#: deleted line-pattern constant deleted is deliberate: a dead line-pattern here would
#: invite the next reader to re-wire a whole-line exemption.

#: THE TEXT PATH GRANTS NO EXEMPTION AT ALL — not per line, and not per statement.
#:
#: Rounds 1, 2 and 3 of review each found the same class: an exemption decided from line
#: content (a proxy substring, a paren window, a protective strip). The text path —
#: non-Python files, and Python text that could not be parsed — has no structure to bind
#: an exemption to the operation carrying the credential, so the only defensible rule
#: there is the seat's: **grant no exemptions.**
#:
#: An earlier revision of this file granted a statement-level strip exemption here. It is
#: deleted, because a "statement" there was a `;`-delimited fragment of ONE line
#: (measured: `del os.environ["ANTHROPIC_API_KEY"]` in a .sh file was exempted by it) and
#: a line-content exemption is exactly the class this file exists to end.
#:
#: Measured, not assumed, for the estate's own launchers: every strip spelling
#: `scripts/hapax-codex`, `-headless`, `-send`, `-mcp-config-scrub` and
#: `install-codex-config.sh` actually use (`unset X_API_KEY`, chained `env.pop(...)` /
#: `os.environ.pop(...)` inside embedded Python, `os.environ.update`) matches NO
#: read/injection pattern, so refusing text-path exemptions flags **0** of their lines
#: (`_text_classes` run over every line of each file). The only spelling that WOULD newly
#: be flagged in a non-Python file is `del os.environ["X_API_KEY"]`, which no script in
#: this repo contains; if one appears it is meant to be a finding (review routes it, or
#: the launcher gets structural handling) rather than a line exemption.


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
# NOTE: an earlier round carried a `_ROUTE_TARGET_RE` line regex here. It is deleted:
# the proxy binding is decided per `ast.Call` (see `_call_is_proxy_bound`), and a line
# regex describing an exemption the live path does not implement is worse than dead
# code — it invites the next reader to re-wire a whole-line exemption (round 3 review,
# claude minor).

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
#: A hunk header, with BOTH line counts captured: ``@@ -<old_start>[,<old_count>] +<new_start>[,<new_count>] @@``.
#: The counts are the hunk's inventory, and the hunk is only whole when its body delivers
#: exactly that many lines on each side (codex-1's round-6 critical: capturing only the
#: new-side start let input cut off right after ``@@``, or mid-hunk, scan clean). An absent
#: count means one line, per the diff format.
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


#: The short form of git's empty blob (its short hash is ``e69de29``; the full hash is
#: git's, not this file's to write down). An
#: ``index`` line that names it on one side and the all-zero object on the other is how git
#: describes a file that is empty on one side — a COMPLETE section with no content, not a
#: truncated one.
_EMPTY_BLOB_SHORT = "e69de29"


def _section_marks() -> dict[str, bool]:
    """A fresh mark set for one ``diff --git`` section."""

    return {
        "preamble": False,  # any `index`/mode/rename line arrived
        "hunk": False,
        "hunk_short": False,  # a hunk's body did not deliver its header's counts
        "unparseable": False,  # a line that is neither a mark nor a body line nor a header
        "binary": False,
        "file_section": False,  # `---` arrived, so `+++` follows
        "old_mode": False,
        "new_mode": False,
        "rename_from": False,
        "rename_to": False,
        "rename_needs_content": False,  # a <100% similarity / dissimilarity implies hunks follow
        "empty_blob": False,
        "content_index": False,  # an index line that promises content must follow
    }


def _fold_index_marks(marks: dict[str, bool], raw: str) -> None:
    """Record what an ``index <old>..<new> [mode]`` line proves about the section."""

    body = raw[len("index ") :].split()
    if not body:
        return
    old, _, new = body[0].partition("..")
    # The zero side is ANY run of zeros: git abbreviates it to 7 characters, this repo's
    # `gh pr diff` output abbreviates to 10 (`index 0000000000..fe91c83f72`), and a full
    # 40-character hash is legal too (gemini-1's round-6 major: `old == "0000000"` made
    # every 10-character empty-file section read as unusable).
    old_is_zero = bool(old) and set(old) == {"0"}
    new_is_zero = bool(new) and set(new) == {"0"}
    marks["preamble"] = True
    marks["empty_blob"] = (old_is_zero and new.startswith(_EMPTY_BLOB_SHORT)) or (
        new_is_zero and old.startswith(_EMPTY_BLOB_SHORT)
    )
    # An `index` that is NOT the empty-file form promises content that must follow: git omits the
    # line entirely for a mode-only change and for a pure rename, and always writes it when it is
    # about to show a hunk. So its presence without a hunk is the same damage as an index-only
    # header — and it is the discriminator that closed the mode+content and rename+content cuts
    # the every-prefix fuzz found after the rename fix.
    marks["content_index"] = not marks["empty_blob"]


def _section_is_complete(marks: dict[str, bool]) -> bool:
    """THE COMPLETENESS TABLE. A section is whole exactly when the marks say so, and the code
    below is a transcription of this table — not of the shapes each review round happened to
    produce. Re-lands from the abandoned #4795, whose three failures were all one class: a
    truncated section reading as clean because a mark that proves *absence of content* was
    allowed to prove *wholeness of content*.

    | marks on the section                                              | whole? |
    |-------------------------------------------------------------------|--------|
    | it declares a hunk, every hunk consumed both counts exactly       | yes    |
    | it declares a hunk, and any hunk is short or overrun              | **no** |
    | no hunk, a binary note                                            | yes    |
    | no hunk, an empty-file index (``…000…`` on one side, empty blob on the other) | yes |
    | no hunk, an ``index`` line that is not the empty-file form        | **no** |
    | no hunk, ``old mode`` **and** ``new mode``, **and no** ``index``  | yes    |
    | no hunk, ``rename from``/``rename to`` with ``similarity index 100%`` | yes |
    | no hunk, a rename with a lower similarity or a ``dissimilarity``  | **no** |
    | no hunk, nothing but preamble (``diff --git``/``---``/``+++``/…)  | **no** |
    | any of the above, plus an **unparseable** line                    | **no** |

    The two rows that say "no hunk" are the fix for codex-1's round-7 critical: a rename or a
    mode pair used to OR its way to "whole" over the top of a short hunk, so a rename-with-
    content or mode-with-content section truncated mid-hunk scanned clean. **A mark that means
    "this section has no content" can only speak for a section that declares no hunk.**

    An unparseable line — anything that is neither a mark nor a body line nor a section header —
    is treated as damage and makes the section not whole (round-7 predicate, clause 1). Measured
    before choosing that strictness: a 72 KB real `gh pr diff` carries **no** blank body lines,
    so real output never has such a line unless it was cut or corrupted.
    """

    if marks["unparseable"]:
        return False
    if marks["hunk"]:
        # Hunk-first: nothing else on the section can outvote a short hunk.
        return not marks["hunk_short"]
    if marks["binary"] or marks["empty_blob"]:
        return True
    if marks["content_index"]:
        # An `index` that is not the empty-file form means git was about to show content; a
        # section that stops here was cut. This is what closes mode+content and rename+content.
        return False
    return bool(
        (marks["old_mode"] and marks["new_mode"])
        or (marks["rename_from"] and marks["rename_to"] and not marks["rename_needs_content"])
    )


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


#: EVERY exemption site in this scanner, declared in one place — including the sites that
#: deliberately do not exist — so a fourth whole-line exemption cannot land unnoticed
#: (rounds 1-3: the same class appeared three times — a proxy substring, a paren window,
#: a protective strip).
#:
#: Rule, from the round-3 review and adopted here as the scanner's contract:
#: **an exemption must be decided per node for Python, and there are NO exemptions for
#: non-Python files.** A line-level match may never suppress a finding produced by a
#: different operation on the same line. The guard test
#: (`tests/scripts/test_check_billing_surface_diff.py::test_no_exemption_is_decided_from_line_content`)
#: asserts this registry's key set exactly and inspects the text path for a smuggled
#: exemption, so adding a site — or re-opening the text path — means editing both.
#:
#: Keys are the sites; values state what each is decided from.
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


def _node_findings_for_region(
    path: str, region: list[tuple[int, str, bool]]
) -> tuple[list[Finding], list[Finding], bool]:
    """Per-node findings for one hunk's post-image region (Python).

    ``region`` is ``(new_line_no, text, is_added)`` in post-image order. Returns
    ``(findings, allowed, parsed)`` — ``allowed`` names every exemption this region
    granted, with its path and line, so the report shows what the gate let through.

    **Every exemption is decided on a NODE, never on a line** (round-3 contract):

    - ``protective_strip`` exempts only the strip's **target** node, so a credential read
      elsewhere on the same line is still counted (the round-3 case,
      ``os.environ.pop("OLD_API_KEY", None); key = os.environ["OPENAI_API_KEY"]``) **and so
      is a read in the strip's own default argument** (the round-4 case,
      ``os.environ.pop("OLD_API_KEY", os.environ["OPENAI_API_KEY"])``);
    - ``proxy`` exempts only a ``Call`` whose own route target is a governed proxy;
    - a node is reported only when an ADDED line falls inside it, so pre-existing code in
      the context lines is not this change's surface.
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
        return [], [], False
    added_lines = {line_no for line_no, _, is_added in region if is_added}
    first_line = region[0][0] if region else 0
    out: list[Finding] = []
    allowed_out: list[Finding] = []

    def node_is_added(node: ast.AST) -> bool:
        # ``ast.walk`` yields nodes with no position (Module, operator singletons, ...).
        # They are not operations and cannot carry a surface.
        if getattr(node, "lineno", None) is None:
            return False
        start = first_line + (node.lineno or 1) - 1
        end = first_line + (getattr(node, "end_lineno", node.lineno) or node.lineno) - 1
        return any(start <= line_no <= end for line_no in added_lines)

    def snippet(node: ast.AST) -> str:
        segment = ast.get_source_segment(source, node) or ""
        return (segment.splitlines() or [""])[0].strip()[:200]

    # ONLY the strip's target node is exempt. Its other children — the default argument
    # above all — are scanned like any other code (codex-1's round-4 critical).
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
                line=first_line + (node.lineno or 1) - 1,
                kind="protective-strip",
                text=snippet(node),
            )
        )

    for node in ast.walk(tree):
        if not node_is_added(node):
            continue
        line_no = first_line + (node.lineno or 1) - 1
        if isinstance(node, ast.Call) and _call_api_key_args(node):
            if _call_is_proxy_bound(node):
                # Exemption site 1, per call — recorded so the report names it.
                allowed_out.append(
                    Finding(
                        path=path,
                        line=line_no,
                        kind="governed-proxy-route",
                        text=snippet(node),
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
    # The two pattern-only classes carry no exemption, so a line rule is safe here.
    for line_no, content, is_added in region:
        if not is_added:
            continue
        for kind in _pattern_only_classes(content):
            out.append(Finding(path=path, line=line_no, kind=kind, text=content.strip()[:200]))
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


def scan_unified_diff(text: str) -> ScanResult:
    findings: list[Finding] = []
    allowed: list[Finding] = []
    scanned: list[str] = []
    path: str | None = None
    skip_file = True
    new_line = 0
    region: list[tuple[int, str, bool]] = []
    saw_hunk = False
    previous_header_path: str | None = None
    marks = _section_marks()
    marked_lines_emitted: set[tuple[str, int]] = set()
    #: Lines a hunk's header still owes on each side, and whether a body is open. A hunk is
    #: whole only when both budgets reach exactly zero (codex-1's round-6 critical).
    hunk_left_old = 0
    hunk_left_new = 0
    in_hunk = False

    def close_hunk() -> None:
        """A hunk that ends short makes the section incomplete (round-6 critical).

        Called at every point a hunk body can end: the next hunk's header, the next file's
        header, and the end of the diff. A body line arriving after both budgets were spent
        is treated the same way — the header lied, so the section is not whole either.
        """

        nonlocal in_hunk
        if in_hunk and (hunk_left_old != 0 or hunk_left_new != 0):
            marks["hunk_short"] = True
        in_hunk = False

    def emit_incomplete(blocking_path: str, where: str) -> None:
        """One finding per section the input never finished delivering.

        The completeness of a section is a property of the INPUT, not of the file's class,
        so this fires for doc files too: a truncated diff is unusable whatever got cut.
        `blocking_path` is the file the section belongs to (or the `diff --git` target when
        no file section arrived), and `where` says which end of the diff cut it.
        """

        if marks["hunk_short"]:
            tail = (
                "a hunk ended short of the line counts its own header declares (or a line "
                "arrived after both counts were spent), so the input was cut inside a hunk"
            )
        else:
            tail = (
                "no hunk, no binary note, and none of the contentless forms git emits whole "
                "(mode-only change, pure rename, empty file)"
            )
        findings.append(
            Finding(
                path=blocking_path or "(unknown path)",
                line=0,
                kind="billing-scan-unusable-input",
                text=(
                    f"the diff ends {where} with an INCOMPLETE section for this file: {tail}. "
                    "An `index`-only header is a truncated content change. Next action: "
                    "regenerate the diff so every section is complete."
                ),
            )
        )

    def emit_line(kinds: tuple[str, ...], line_no: int, content: str) -> None:
        """Record one added line's kinds, applying the marker decision.

        The marker is honoured only on an allowlisted path. Anywhere else it does
        NOT exempt the line (the underlying findings stand) and it is itself a
        finding — never a silent ignore, which would hide the intent.
        """

        if not kinds and ALLOW_MARKER not in content:
            return
        marked = ALLOW_MARKER in content
        marker_ok = marked and _marker_is_allowed_on(path)
        if marked and not marker_ok and (path, line_no) not in marked_lines_emitted:
            marked_lines_emitted.add((path, line_no))
            findings.append(_marker_outside_fixtures_finding(path, line_no, content))
        for kind in kinds:
            finding = Finding(path=path, line=line_no, kind=kind, text=content.strip())
            (allowed if marker_ok else findings).append(finding)

    def flush() -> None:
        """Analyse one hunk's post-image region, then clear it."""

        nonlocal region, saw_hunk
        if not region or path is None:
            region = []
            return
        added = [(line_no, content) for line_no, content, is_added in region if is_added]
        if path.endswith(_PY_SUFFIXES):
            ast_findings, ast_allowed, parsed = _node_findings_for_region(path, region)
        else:
            ast_findings, ast_allowed, parsed = [], [], False
        # Every exemption this region granted is reported, whatever else happens to it.
        allowed.extend(ast_allowed)
        if parsed:
            # Structure decided the api-key class; headers are still line rules.
            for finding in ast_findings:
                line_content = next((c for n, c, _ in region if n == finding.line), finding.text)
                emit_line((finding.kind,), finding.line, line_content)
            for line_no, content in added:
                # Bearer headers are line-level by nature (a header is not a Call) and
                # carry no exemption; the two pattern-only classes likewise.
                line_kinds: tuple[str, ...] = _pattern_only_classes(content)
                if any(p.search(content) for p in _BEARER_RES):
                    line_kinds += ("api-key-route",)
                emit_line(line_kinds, line_no, content)
        else:
            # Unparsed Python, or any non-Python file: line rules, and NO exemption of
            # any kind (round-3 class fix). Neither a proxy argument nor a protective
            # strip exempts here: there is no structure to bind either one to the
            # operation that carries the credential, so nothing on this path may
            # suppress a finding — not per line and not per statement.
            flagged = 0
            for line_no, content in added:
                kinds = _text_classes(content)
                if "api-key-route" in kinds:
                    flagged += 1
                emit_line(kinds, line_no, content)
            if (
                path.endswith(_PY_SUFFIXES)
                and not parsed
                and flagged == 0
                and any(
                    _KEY_BEARING_PROBE.search(content)
                    and not (ALLOW_MARKER in content and _marker_is_allowed_on(path))
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
            close_hunk()
            # The section that just ended must have arrived WHOLE (round 2's no-hunk arm,
            # round 3's no-file-section arm and round 5's index-only-header arm are all the
            # same defect: a section the input never finished delivering reading as clean).
            # The first header opens the diff, so there is no previous section to judge.
            if previous_header_path is not None and not _section_is_complete(marks):
                emit_incomplete(
                    path or previous_header_path or "", where="before the next file header"
                )
            path = None
            skip_file = True
            saw_hunk = False
            previous_header_path = raw[len("diff --git ") :].split(" b/")[-1].strip()
            marks = _section_marks()
            continue
        if raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            marks["binary"] = True  # a section DID arrive; it is simply binary
            continue
        if marks["binary"]:
            # A declared-binary section's payload is opaque; the note is what makes it whole.
            continue
        if raw.startswith("index "):
            _fold_index_marks(marks, raw)
            continue
        if raw.startswith("old mode"):
            marks["old_mode"] = True
            marks["preamble"] = True
            continue
        if raw.startswith("new mode"):
            marks["new_mode"] = True
            marks["preamble"] = True
            continue
        if raw.startswith(("new file mode", "deleted file mode")):
            marks["preamble"] = True
            continue
        if raw.startswith(("rename from", "copy from")):
            marks["rename_from"] = True
            marks["preamble"] = True
            continue
        if raw.startswith(("rename to", "copy to")):
            marks["rename_to"] = True
            marks["preamble"] = True
            continue
        if raw.startswith(("similarity index", "dissimilarity index")):
            marks["preamble"] = True
            # A rename is only whole without hunks when the content is IDENTICAL: git writes
            # `similarity index 100%` for a pure rename and a lower percentage (or a
            # `dissimilarity index`) whenever content changes follow, so a section claiming to
            # be a pure rename on a lower similarity is a section whose hunks were cut.
            similarity = re.match(r"^similarity index (\d+)%$", raw)
            if similarity is None or int(similarity.group(1)) < 100:
                marks["rename_needs_content"] = True
            continue
        # Hunk headers are counted for EVERY section, doc files included: whether the input
        # arrived whole is a property of the diff, not of the file's class (a truncated diff is
        # unusable whatever got cut), so the mark is set before the scan-skip test below. The
        # header check must also precede the body accounting, or a second `@@` would be eaten as
        # a body line.
        header = _HUNK_HEADER_RE.match(raw)
        if header:
            close_hunk()
            flush()
            saw_hunk = True
            marks["hunk"] = True
            hunk_left_old = int(header.group(2) or 1)
            hunk_left_new = int(header.group(4) or 1)
            in_hunk = True
            new_line = int(header.group(3))
            continue
        if raw.startswith("--- ") and not marks["hunk"]:
            marks["file_section"] = True
            marks["preamble"] = True
            continue
        if raw.startswith("+++ ") and not marks["hunk"]:
            flush()
            marks["preamble"] = True
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
        if in_hunk and raw.startswith("\\"):
            # `\ No newline at end of file` is hunk METADATA and is consumed here, never scanned
            # (gemini-1's round-7 major: `pass` fell through to the region, so the marker joined
            # the post-image text and `ast.parse` failed on a diff that was perfectly valid).
            continue
        if in_hunk:
            # The body grammar, strictly: a line is a context line (` `), an added line (`+`) or
            # a removed line (`-`) and nothing else. The old tolerant `else` treated ANY other
            # line as context, which is how damage could pass as content.
            if raw.startswith("+"):
                hunk_left_new -= 1
            elif raw.startswith("-"):
                hunk_left_old -= 1
            elif raw.startswith(" "):
                hunk_left_old -= 1
                hunk_left_new -= 1
            else:
                marks["unparseable"] = True
                continue
            # No separate overshoot guard: a body line after both budgets were spent drives one
            # negative, and `close_hunk`'s single "not zero" test catches it with the short case.
        elif raw.strip():
            # Outside a hunk only the marks and headers handled above are legal.
            marks["unparseable"] = True
            continue
        if skip_file or path is None:
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
    close_hunk()
    # Only a section that was actually OPENED can be incomplete: an empty input has no
    # section to be whole, and `main()` already fails that closed on its own terms.
    if previous_header_path is not None and not _section_is_complete(marks):
        emit_incomplete(path or previous_header_path or "", where="at the end of the diff")
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
        # Every exemption the gate accepted, named by path, line and KIND: a structural
        # one (proxy-bound call, protective strip) is not a marker, and the report must
        # not imply it was.
        print(f"allowed {finding.path}:{finding.line}: {finding.kind}: {finding.text}")
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
        code = 1
    else:
        print(
            "billing-surface-scan: OK: no billing-surface mutation in "
            f"{len(result.scanned_files)} changed file(s)"
        )
        code = 0
    if result.allowed:
        # dev21's point 3: every exemption the gate accepted is named, with its path,
        # so the dossier shows exactly what the scan let through and where.
        print(
            f"billing-surface-scan: exempted {len(result.allowed)} site(s) by structure "
            "or the fixture allowlist ("
            + ", ".join(sorted({f"{f.path}:{f.line}" for f in result.allowed}))
            + ")"
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
