#!/usr/bin/env python3
"""unguarded-cd analyzer — a failed `cd` must never let later commands run in
the wrong directory.

Class history (2026-06-11, twice in one session): a failed `cd` inside a
compound command ran `git add -A && git commit` in the booby-trapped primary
tree, then ran greps in the wrong tree an hour later despite a prose rule in
memory. Prose is not a mechanism; this is.

v2 (review-team fix round, PR #4091): replaced the verified-fail-open regex
with a tokenizer. v3 (adversarial-panel round, 25 execution-verified bypasses
+ 6 false positives): quote-aware heredoc stripping and substitution
extraction, shell-keyword handling (if/then/do/case bodies), condition-
position cds, prefix unwrapping (\\cd, command, builtin, time), eval
recursion, process substitution, command-position-only brace groups,
failure-propagating group analysis, statement-local pipeline detection, and
strict errexit accounting (conditional `set -e` gets no credit; `set +o
errexit` revokes it).

THE CONTRACT (deliberately strict — wrong-directory READS were part of the
incident class, so "harmless" trailing statements still count):

  A `cd`/`pushd` with a target is SAFE only if, were it to fail, no later
  statement in the same shell scope could run. Concretely:
    - errexit (`set -e`, unconditional) is active at that point, or
    - every later statement in scope is reached only through `&&`, or
    - its `||` branch terminates the scope (exit / return / continue /
      break), or
    - it sits in condition position (`if cd X; then ...` — flow-controlled),
    - or nothing in scope runs after it. Subshell/substitution interiors are
      their own scope; a cd inside one cannot poison the parent (but interior
      hazards still block — wrong-directory reads counted in the incident).
  `cd X && a; b` is BLOCKED on purpose: a failed cd skips `a` but still runs
  `b` in the wrong directory. `cd X || true; b` is the incident mechanism
  itself and is BLOCKED.

Payload-shape failures fail OPEN with a stderr note: bricking every Bash call
on a harness format change is a worse failure mode than one missed guard —
pinned by a test. Parser exceptions on alien grammar likewise fail open,
loudly. Killswitch: HAPAX_UNGUARDED_CD_GUARD_OFF=1.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

CD_WORDS = ("cd", "pushd")
TERMINATORS = ("exit", "return", "continue", "break")
#: words stripped from statement heads; bash reserved words that wrap a body
#: statement without isolating it from the parent shell scope
_BODY_KEYWORDS = ("then", "do", "else", "fi", "done", "esac", "coproc", "!")
#: words that make the FOLLOWING command a flow condition (its failure is
#: handled by the construct, not fallen through)
_COND_KEYWORDS = ("if", "elif", "while", "until")
#: prefix words unwrapped before cd detection (still run cd in this shell)
_PREFIX_WORDS = ("builtin", "command", "time")
_CASE_HEAD_RE = re.compile(r"^case\b.*?\bin\b\s*", re.S)
_CASE_PATTERN_RE = re.compile(r"""^[\w*?@.$"'\[\]{}/|-]+\)\s*""")
_HEREDOC_DELIM_RE = re.compile(r"""^-?\s*(?:'([\w.-]+)'|"([\w.-]+)"|([\w.-]+))""")
_WORD_RE = re.compile(r"\S+")


@dataclass
class Finding:
    offending: str

    def message(self) -> str:
        return (
            "BLOCKED: unguarded `cd` — if this cd fails, later commands run in "
            "the WRONG directory (2026-06-11 primary-tree incident class).\n"
            f"  offending: {self.offending[:120]}\n"
            "  guarded forms: unconditional `set -e` before the cd; chain "
            "EVERYTHING after the cd with `&&`; `cd X || exit 1`; "
            "`if cd X; then ...` ; or avoid cd (`git -C`, `make -C`). Note "
            "`cd X && a; b` still blocks: `b` runs even when the cd fails."
        )


def _strip_heredocs(text: str) -> str:
    """Drop heredoc bodies, quote-aware (a `<<EOF` inside quotes is text, not
    a heredoc — and a quoted/hyphenated delimiter like <<'EOF-SCRIPT' is
    real). `<<<` here-strings are not heredocs."""
    out: list[str] = []
    pending: list[str] = []
    quote: str | None = None
    arith = 0  # paren balance inside $(( )) — `1<<2` there is a shift, not a heredoc
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                out.append(text[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
            out.append(ch)
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(text[i : i + 2])
            i += 2
            continue
        if text.startswith("$((", i):
            arith += 2
            out.append("$((")
            i += 3
            continue
        if arith:
            if ch == "(":
                arith += 1
            elif ch == ")":
                arith -= 1
            out.append(ch)
            i += 1
            continue
        if ch == "\n" and pending:
            out.append(ch)
            i += 1
            # swallow full lines until every pending delimiter is consumed
            while pending and i < n:
                eol = text.find("\n", i)
                line = text[i:] if eol == -1 else text[i:eol]
                i = n if eol == -1 else eol + 1
                if line.strip() == pending[0]:
                    pending.pop(0)
            continue
        if text.startswith("<<", i) and not text.startswith("<<<", i):
            m = _HEREDOC_DELIM_RE.match(text[i + 2 :])
            if m:
                pending.append(m.group(1) or m.group(2) or m.group(3))
                i += 2 + m.end()
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_comments(text: str) -> str:
    """Drop `#`-to-EOL outside quotes (a `#` mid-word, e.g. ${x#y}, stays)."""
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < len(text):
                out.append(text[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
            out.append(ch)
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch == "#" and (i == 0 or text[i - 1] in " \t;\n&|("):
            j = text.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_top(text: str, seps: tuple[str, ...]) -> list[tuple[str, str]]:
    """Split at top-level separators (outside quotes, (), command-position
    {} groups, backticks). Returns [(separator_before_piece, piece)] with ""
    for the first piece."""
    pieces: list[tuple[str, str]] = []
    quote: str | None = None
    depth = 0
    brace = 0
    backtick = False
    at_cmd_pos = True
    cur: list[str] = []
    last_sep = ""
    i = 0
    n = len(text)
    ordered = sorted(seps, key=len, reverse=True)
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                cur.append(text[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
            cur.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            cur.append(text[i : i + 2])
            at_cmd_pos = False
            i += 2
            continue
        if ch in ("'", '"'):
            quote = ch
            cur.append(ch)
            at_cmd_pos = False
            i += 1
            continue
        if ch == "`":
            backtick = not backtick
            cur.append(ch)
            i += 1
            continue
        if not backtick:
            if ch == "(":
                depth += 1
                at_cmd_pos = True
            elif ch == ")":
                depth = max(0, depth - 1)
            elif ch == "{":
                # a group opener only in command position followed by space;
                # `echo {a` and `${var}` are plain text (panel finding)
                prev = text[i - 1] if i else ""
                nxt = text[i + 1] if i + 1 < n else " "
                if at_cmd_pos and prev != "$" and nxt in " \t\n":
                    brace += 1
                    at_cmd_pos = True
                else:
                    at_cmd_pos = False
            elif ch == "}":
                if brace > 0 and at_cmd_pos:
                    brace = max(0, brace - 1)
                else:
                    at_cmd_pos = False
        if depth == 0 and brace == 0 and not backtick:
            consumed_whole = None
            for op in ("&&", "||"):
                if text.startswith(op, i) and op not in seps:
                    consumed_whole = op
                    break
            if consumed_whole:
                cur.append(consumed_whole)
                at_cmd_pos = True
                i += 2
                continue
            matched = None
            for sep in ordered:
                if text.startswith(sep, i):
                    if sep == "&" and cur and cur[-1] in "<>":
                        continue
                    matched = sep
                    break
            if matched:
                pieces.append((last_sep, "".join(cur)))
                cur = []
                last_sep = matched
                at_cmd_pos = True
                i += len(matched)
                continue
        if ch in (";", "\n", "&", "|"):
            at_cmd_pos = True
        elif ch == ")" and i > 0 and text[i - 1] == "(":
            # `name()` of a function definition: the following `{` opens the
            # body group (round-2 review finding: function bodies were glued
            # into opaque text and their interior cds never analyzed)
            at_cmd_pos = True
        elif ch not in (" ", "\t"):
            at_cmd_pos = False
        cur.append(ch)
        i += 1
    pieces.append((last_sep, "".join(cur)))
    return pieces


def _prep_statement(stmt: str) -> tuple[str, bool, int, int]:
    """Strip shell keywords / case patterns from a statement head. Returns
    (cleaned, condition_position, loops_opened, loops_closed):
    condition_position means the command's failure is consumed by the
    construct (if/elif/while/until); loops_opened counts `do` strips (a loop
    body begins) and loops_closed counts `done` strips — the caller tracks
    loop depth so `continue`/`break` only terminate inside real loop bodies."""
    s = stmt.strip()
    condition = False
    loops_opened = 0
    loops_closed = 0
    changed = True
    while changed:
        changed = False
        m = _CASE_HEAD_RE.match(s)
        if m:
            s = s[m.end() :].lstrip()
            changed = True
            continue
        m = _CASE_PATTERN_RE.match(s)
        # only a case-arm pattern if the `)` is not a subshell closer
        if m and "(" not in m.group(0):
            s = s[m.end() :].lstrip()
            changed = True
            continue
        w = _WORD_RE.match(s)
        word = w.group(0) if w else ""
        if word in _BODY_KEYWORDS:
            s = s[len(word) :].lstrip()
            condition = False
            if word == "do":
                loops_opened += 1
            elif word == "done":
                loops_closed += 1
            changed = True
            continue
        if word in _COND_KEYWORDS or word == "for":
            s = s[len(word) :].lstrip()
            condition = word in _COND_KEYWORDS
            changed = True
            continue
    return s, condition, loops_opened, loops_closed


def _first_word(stmt: str) -> str:
    s = stmt.strip()
    while True:
        m = re.match(r"[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S)*\s+", s)
        if not m:
            break
        s = s[m.end() :]
    m = _WORD_RE.match(s)
    return m.group(0) if m else ""


def _stmt_after_first_word(stmt: str) -> str:
    s = stmt.strip()
    w = _first_word(stmt)
    idx = s.find(w)
    return s[idx + len(w) :].strip() if w else ""


def _unwrap_prefixes(stmt: str) -> str:
    """Peel `\\`, `command`, `builtin`, `time` (+ their flags) off a command
    head — they all still run the cd in THIS shell (panel findings)."""
    s = stmt.strip()
    while True:
        w = _first_word(s)
        if w.startswith("\\") and len(w) > 1:
            s = s.replace("\\", "", 1).strip()
            continue
        if w in _PREFIX_WORDS:
            s = _stmt_after_first_word(s)
            while True:
                nxt = _first_word(s)
                if nxt.startswith("-") and nxt not in ("-",):
                    s = _stmt_after_first_word(s)
                    continue
                break
            continue
        return s


def _is_cd(stmt: str) -> bool:
    s = _unwrap_prefixes(stmt)
    if s.startswith("(") or s.startswith("{"):
        return False
    w = _first_word(s)
    if w in CD_WORDS:
        target = _stmt_after_first_word(s)
        target = re.sub(r"(^|\s)-[A-Za-z]+(?=\s|$)", " ", target).strip()
        return bool(target)
    return False


def _is_terminating(stmt: str, loop_depth: int = 0, in_function: bool = False) -> bool:
    """Does this ||-branch stop the scope? FIRST-WORD check only — terminator
    words as data (`echo "exit"`) must not count (round-2 review finding).
    Context matters (round-2 review finding): `exit` always terminates;
    `continue`/`break` only inside a loop body; `return` only inside a
    function body — at top level bash prints an error and KEEPS GOING, so
    `cd /x || return; git add` still runs git add in the wrong directory."""
    s = stmt.strip()
    if s.startswith("{"):
        inner = s[1 : s.rfind("}")] if "}" in s else s[1:]
        words = [
            _first_word(_unwrap_prefixes(piece))
            for _sep, piece in _split_top(inner, (";", "\n"))
            if piece.strip()
        ]
    else:
        words = [_first_word(_unwrap_prefixes(s))]
    for w in words:
        if w == "exit":
            return True
        if w in ("continue", "break") and loop_depth > 0:
            return True
        if w == "return" and in_function:
            return True
    return False


def _set_e_effect(stmt: str) -> bool | None:
    """True: enables errexit. False: disables. None: not a set statement.
    Handles flag clusters (-e, -euo), `-o errexit`, `+e`, `+o errexit`."""
    s = stmt.strip()
    if _first_word(s) != "set":
        return None
    tokens = _stmt_after_first_word(s).split()
    effect: bool | None = None
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok in ("-o", "+o") and idx + 1 < len(tokens):
            if tokens[idx + 1] == "errexit":
                effect = tok == "-o"
            idx += 2
            continue
        if tok.startswith("-") and "e" in tok[1:] and tok[1:].isalpha():
            effect = True
        elif tok.startswith("+") and "e" in tok[1:] and tok[1:].isalpha():
            effect = False
        idx += 1
    return effect


def _inner_scopes(stmt: str) -> list[str]:
    """Extract $(...), `...`, <(...) and >(...) bodies for recursion —
    quote-aware: single quotes suppress substitution, double quotes don't
    (panel false-positive findings)."""
    bodies: list[str] = []
    quote: str | None = None
    i = 0
    n = len(stmt)
    while i < n:
        ch = stmt[i]
        if quote == "'":
            if ch == "'":
                quote = None
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "'" and quote is None:
            quote = "'"
            i += 1
            continue
        if ch == '"':
            quote = None if quote == '"' else '"'
            i += 1
            continue
        opener = None
        if (
            stmt.startswith("$(", i)
            and not stmt.startswith("$((", i)
            or quote is None
            and (stmt.startswith("<(", i) or stmt.startswith(">(", i))
        ):
            opener = i + 2
        if opener is not None:
            depth = 1
            j = opener
            while j < n and depth:
                if stmt[j] == "(":
                    depth += 1
                elif stmt[j] == ")":
                    depth -= 1
                j += 1
            bodies.append(stmt[opener : j - 1])
            i = j
            continue
        if ch == "`":
            j = stmt.find("`", i + 1)
            if j == -1:
                break
            bodies.append(stmt[i + 1 : j])
            i = j + 1
            continue
        i += 1
    return bodies


def _strip_outer_quotes(text: str) -> str:
    s = text.strip()
    if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
        return s[1:-1]
    return s


def _runs_after_failure(
    stmts: list[tuple[str, str]],
    si: int,
    later_lists: bool,
    has_following: bool,
    loop_depth: int = 0,
    in_function: bool = False,
) -> bool:
    """If stmts[si] FAILS, does any later same-scope statement still run?
    Walk its and-or list (left-associative): `&&` successors are skipped
    while failed; a non-terminating `||` successor recovers status (then
    everything after runs); a terminating `||` successor stops the scope."""
    failed = True
    for nop, nstmt in stmts[si + 1 :]:
        if failed and nop == "&&":
            continue
        if failed and nop == "||":
            if _is_terminating(nstmt, loop_depth, in_function):
                return False
            failed = False
            continue
        if not failed:
            return True
    return later_lists or has_following


_FUNCDEF_RE = re.compile(
    r"^(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{|^function\s+([A-Za-z_][\w-]*)\s*\{"
)


def _analyze_scope(
    text: str, errexit: bool, has_following: bool, in_function: bool = False
) -> tuple[Finding | None, bool]:
    """Analyze one shell scope. Returns (finding, errexit_state_after)."""
    lists = [(sep, piece) for sep, piece in _split_top(text, (";", "\n", "&")) if piece.strip()]
    loop_depth = 0
    for li, (_sep, list_text) in enumerate(lists):
        backgrounded = li + 1 < len(lists) and lists[li + 1][0] == "&"
        later_lists = any(p.strip() for _s, p in lists[li + 1 :])
        stmts = [(op, s) for op, s in _split_top(list_text, ("&&", "||", "|")) if s.strip()]

        for si, (_op, raw_stmt) in enumerate(stmts):
            s, condition_pos, loops_opened, loops_closed = _prep_statement(raw_stmt)
            loop_depth += loops_opened
            if not s:
                loop_depth = max(0, loop_depth - loops_closed)
                continue

            # pipeline membership is LOCAL to the statement: a `|` elsewhere
            # in the list must not exempt this cd (panel finding #1)
            in_pipeline = stmts[si][0] == "|" or (si + 1 < len(stmts) and stmts[si + 1][0] == "|")

            eff = _set_e_effect(s)
            if eff is not None and not backgrounded and not in_pipeline:
                # conditional `set -e` (an &&/|| successor) gets NO credit:
                # it may never run (panel finding). Disabling always counts.
                if eff is False or stmts[si][0] == "":
                    errexit = eff
                loop_depth = max(0, loop_depth - loops_closed)
                continue

            # function definition: the body runs IN THIS SHELL when called.
            # Analyzed (with `return` valid) iff the payload also INVOKES the
            # function — a bare definition runs nothing, and shell state does
            # not persist across tool calls (round-2 review finding).
            fm = _FUNCDEF_RE.match(s)
            if fm:
                name = fm.group(1) or fm.group(2)
                body = s[s.find("{") + 1 : s.rfind("}")] if "}" in s else s[s.find("{") + 1 :]
                invoked = False
                for _nop, nstmt in stmts[si + 1 :]:
                    ns, _c, _lo, _lc = _prep_statement(nstmt)
                    if _first_word(_unwrap_prefixes(ns)) == name:
                        invoked = True
                        break
                if not invoked:
                    for _ls, later_piece in lists[li + 1 :]:
                        for _nop, nstmt in _split_top(later_piece, ("&&", "||", "|")):
                            ns, _c, _lo, _lc = _prep_statement(nstmt)
                            if _first_word(_unwrap_prefixes(ns)) == name:
                                invoked = True
                                break
                        if invoked:
                            break
                if invoked:
                    # has_following=False is a documented approximation: a
                    # body whose LAST statement is the cd, plus an unguarded
                    # call site with followers, slips through; interior
                    # post-cd statements (the incident shape) are caught.
                    finding, errexit = _analyze_scope(
                        body, errexit, has_following=False, in_function=True
                    )
                    if finding:
                        return finding, errexit
                loop_depth = max(0, loop_depth - loops_closed)
                continue

            # subshell: its own scope; cannot poison the parent
            if s.startswith("("):
                inner = s[1 : s.rfind(")")] if ")" in s else s[1:]
                finding, _ = _analyze_scope(inner, errexit, False, in_function)
                if finding:
                    return finding, errexit
                loop_depth = max(0, loop_depth - loops_closed)
                continue

            # brace group: SAME shell. Interior cds poison whatever would run
            # were the group to fail — its `&&` successors are protected by
            # the group's own exit status (panel false-positive #30)
            if s.startswith("{"):
                inner = s[1 : s.rfind("}")] if "}" in s else s[1:]
                group_following = _runs_after_failure(
                    stmts, si, later_lists, has_following, loop_depth, in_function
                )
                finding, errexit = _analyze_scope(inner, errexit, group_following, in_function)
                if finding:
                    return finding, errexit
                loop_depth = max(0, loop_depth - loops_closed)
                continue

            # eval runs its argument in THIS shell (panel finding)
            if _first_word(s) == "eval":
                inner = _strip_outer_quotes(_stmt_after_first_word(s))
                eval_following = _runs_after_failure(
                    stmts, si, later_lists, has_following, loop_depth, in_function
                )
                finding, errexit = _analyze_scope(inner, errexit, eval_following, in_function)
                if finding:
                    return finding, errexit
                loop_depth = max(0, loop_depth - loops_closed)
                continue

            # command/process substitutions: own scopes, interior-only hazard
            for body in _inner_scopes(s):
                finding, _ = _analyze_scope(body, errexit, False, in_function)
                if finding:
                    return finding, errexit

            if _is_cd(s) and not (errexit or backgrounded or in_pipeline or condition_pos):
                if _runs_after_failure(
                    stmts, si, later_lists, has_following, loop_depth, in_function
                ):
                    return Finding(offending=s), errexit
            loop_depth = max(0, loop_depth - loops_closed)
    return None, errexit


def analyze(command: str) -> Finding | None:
    text = _strip_comments(_strip_heredocs(command.replace("\\\n", " ")))
    # normalize the ksh-style `function name {` definition to `name() {` so
    # the tokenizer's function-paren rule sees one shape (occurrences inside
    # quotes are data and never analyzed as code, so the rewrite is inert)
    text = re.sub(r"\bfunction\s+([A-Za-z_][\w-]*)\s*(\(\)\s*)?\{", r"\1() {", text)
    finding, _ = _analyze_scope(text, errexit=False, has_following=False)
    return finding


def main() -> int:
    import json
    import os

    raw = sys.stdin.read()
    try:
        command = json.loads(raw).get("tool_input", {}).get("command", "")
    except Exception:
        # Documented fail-open: a malformed harness payload must not brick
        # every Bash call; the guard's scope is cd semantics, not payloads.
        print(
            "unguarded-cd-guard: unparsable payload — allowing. next: check the "
            "PreToolUse payload shape (JSON with tool_input.command); to silence "
            "intentionally set HAPAX_UNGUARDED_CD_GUARD_OFF=1",
            file=sys.stderr,
        )
        return 0
    if not command or os.environ.get("HAPAX_UNGUARDED_CD_GUARD_OFF") == "1":
        return 0
    try:
        finding = analyze(command)
    except Exception as exc:  # alien grammar: fail open, loudly
        print(
            f"unguarded-cd-guard: analyzer error ({exc}) — allowing. next: pin the "
            "offending command as a test in tests/test_unguarded_cd_guard.py and fix "
            "the parser; to bypass intentionally set HAPAX_UNGUARDED_CD_GUARD_OFF=1",
            file=sys.stderr,
        )
        return 0
    if finding:
        print(finding.message(), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
