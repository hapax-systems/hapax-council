# Anti-Personification Linter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Python linter that detects personification language in persona artifacts, role registry, director prompts, and overlay content; staged rollout warn-only → refactor 2 existing violations → fail-loud CI gate.

**Architecture:** Single module `shared/anti_personification_linter.py` (AST + Markdown + YAML extraction + regex deny-list) + `scripts/check-anti-personification.py` CLI wrapper. Allow-list carve-outs via context-window and `axioms/anti_personification_allowlist.yaml`. 6-stage rollout from the spec.

**Tech Stack:** Python 3.12+, Pydantic, ast, ruamel.yaml, mistune (Markdown), pytest
---

## Preamble: Before You Start

- Source spec: `docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md`
- Research dossier: `/tmp/cvs-research-155.md`
- Redesign authority: `docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md`
- Companion regression tests already in the repo: `tests/axioms/test_persona_description.py`, `tests/studio_compositor/test_posture_vocabulary_hygiene.py`

The discriminator you are enforcing is exactly one sentence from the redesign spec §6:

> Analogies that describe architectural fact are fine (curious ≈ SEEKING stance); analogies that claim inner life are not (curious ≈ feels wonder).

Everything below is mechanical encoding of that rule. If a step asks you to add a pattern that does not discriminate on that axis, stop and re-read the spec.

**TDD discipline:** every implementation step pairs with a failing test step immediately before. Run the failing test, see it fail, then implement, then see it pass. Commit at the boundaries noted.

**Branch:** create a single feature branch `feature/anti-personification-linter` off `main`. All 10 tasks land on this branch; stages ship as sequential commits (stage 1 through 5) and stage 6 is a deferred obligation on a future spec, not shipped here.

---

## Task 1 — Linter library skeleton + deny-list + deny-list unit tests

**Files:**
- `shared/anti_personification_linter.py` (new)
- `tests/axioms/test_no_personification.py` (new)

**Outcome:** importable `lint_text(text: str, path: str) -> list[Finding]` function, 4 deny-list pattern families compiled, one parametrized test per family asserting canonical-offender match + canonical-clean non-match.

### Steps

- [ ] **1.1 — Create the empty test file so the skeleton can be imported.**

  Write `tests/axioms/test_no_personification.py` with only:

  ```python
  """Regression harness for the anti-personification linter.

  Companion to test_persona_description.py and test_posture_vocabulary_hygiene.py.
  Enforces the Phase 7 discriminator: analogies describing architectural fact pass;
  analogies claiming inner life fail. Source: docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md.
  """
  from __future__ import annotations

  import pytest

  from shared.anti_personification_linter import Finding, lint_text
  ```

- [ ] **1.2 — Run the test file and confirm it fails on import.**

  ```bash
  uv run pytest tests/axioms/test_no_personification.py -q
  ```

  Expected: `ModuleNotFoundError: No module named 'shared.anti_personification_linter'`. This is the red step.

- [ ] **1.3 — Create the linter module with a `Finding` model and an empty `lint_text()` stub.**

  Write `shared/anti_personification_linter.py`:

  ```python
  """Anti-personification linter.

  Encodes the Phase 7 discriminator (redesign spec §6):
    - analogies that describe architectural fact are fine (curious ≈ SEEKING stance)
    - analogies that claim inner life are not (curious ≈ feels wonder)

  Public API:
    - Finding: dataclass of (path, line, col, pattern_name, matched_text, rule_family)
    - lint_text(text, path) -> list[Finding]
    - lint_path(path) -> list[Finding]  (added in Task 2)

  CLI wrapper: scripts/check-anti-personification.py (added in Task 4).
  """
  from __future__ import annotations

  import re
  from dataclasses import dataclass
  from pathlib import Path

  __all__ = ["Finding", "DENY_PATTERNS", "lint_text"]


  @dataclass(frozen=True)
  class Finding:
      path: str
      line: int
      col: int
      pattern_name: str
      matched_text: str
      rule_family: str


  # Deny-list patterns — verbatim from research dossier §8.1.
  # Four families. Flags: re.IGNORECASE off (case carries signal for "Hapax"), re.MULTILINE on.
  DENY_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
      "inner_life_first_person": [
          ("feel_verb", re.compile(r"\bI (feel|felt|feeling)\b")),
          ("belief_verb", re.compile(r"\bI (believe|thought|wonder|wondered)\b")),
          ("im_affect", re.compile(r"\bI'?m (excited|happy|sad|curious|moved|touched|fascinated|delighted)\b")),
          ("affect_verb", re.compile(r"\bI (love|enjoy|hate|miss|care about)\b")),
          ("my_inner", re.compile(r"\bmy (feelings?|emotions?|mood|heart|soul|experience|consciousness)\b")),
      ],
      "second_person_inner_life": [
          ("you_feel", re.compile(r"\byou (feel|believe|think|wonder|sense|care|love|enjoy)\b")),
          ("your_inner", re.compile(r"\byour (feelings?|emotions?|mood|personality|inner life|experience)\b")),
          ("you_have_personality", re.compile(r"\byou have personality\b")),
          ("you_are_affect", re.compile(r"\byou are (warm|friendly|chatty|curious|excited)\b")),
          ("be_affect", re.compile(r"\bbe (yourself|itself|warm|friendly|genuine|curious|excited|happy)\b")),
      ],
      "personification_nouns": [
          ("personality_noun", re.compile(r"\bpersonality\b")),
          ("archetype_noun", re.compile(r"\barchetype\b")),
          ("dry_wit", re.compile(r"\bdry wit\b")),
          ("genuine_curiosity", re.compile(r"\bgenuine curiosity\b")),
          ("intellectual_honesty", re.compile(r"\bintellectual honesty\b")),
          ("warm_but_concise", re.compile(r"\bwarm but concise\b")),
          ("friendly_not_chatty", re.compile(r"\bfriendly without being chatty\b")),
          ("hapax_inner", re.compile(r"\bHapax (feels|thinks|believes|wants|cares|loves|hopes|fears)\b")),
      ],
      "anthropic_pronouns": [
          ("hapax_gendered", re.compile(r"\bHapax,? (he|she|his|her|him)\b")),
      ],
  }


  def lint_text(text: str, path: str) -> list[Finding]:
      """Return all deny-list hits in `text`. Allow-list carve-outs added in Task 3."""
      findings: list[Finding] = []
      for family, patterns in DENY_PATTERNS.items():
          for name, pattern in patterns:
              for match in pattern.finditer(text):
                  line = text.count("\n", 0, match.start()) + 1
                  col = match.start() - (text.rfind("\n", 0, match.start()) + 1)
                  findings.append(
                      Finding(
                          path=path,
                          line=line,
                          col=col,
                          pattern_name=name,
                          matched_text=match.group(0),
                          rule_family=family,
                      )
                  )
      return findings
  ```

- [ ] **1.4 — Write the failing parametrized deny-list tests.**

  Append to `tests/axioms/test_no_personification.py`:

  ```python
  CANONICAL_OFFENDERS: list[tuple[str, str, str]] = [
      # (family, text, expected_pattern_name)
      ("inner_life_first_person", "I feel wonder at this.", "feel_verb"),
      ("inner_life_first_person", "I wondered if it matters.", "belief_verb"),
      ("inner_life_first_person", "I'm excited about this.", "im_affect"),
      ("inner_life_first_person", "I love this beat.", "affect_verb"),
      ("inner_life_first_person", "my feelings on this are mixed.", "my_inner"),
      ("second_person_inner_life", "you feel the room shift.", "you_feel"),
      ("second_person_inner_life", "your personality shines.", "your_inner"),
      ("second_person_inner_life", "you have personality here.", "you_have_personality"),
      ("second_person_inner_life", "you are warm and kind.", "you_are_affect"),
      ("second_person_inner_life", "be yourself always.", "be_affect"),
      ("personification_nouns", "You have personality: dry wit.", "personality_noun"),
      ("personification_nouns", "Your archetype is Socrates.", "archetype_noun"),
      ("personification_nouns", "Dry wit welcome.", "dry_wit"),
      ("personification_nouns", "Shows genuine curiosity.", "genuine_curiosity"),
      ("personification_nouns", "Intellectual honesty always.", "intellectual_honesty"),
      ("personification_nouns", "Warm but concise, please.", "warm_but_concise"),
      ("personification_nouns", "Friendly without being chatty.", "friendly_not_chatty"),
      ("personification_nouns", "Hapax feels wonder here.", "hapax_inner"),
      ("anthropic_pronouns", "Hapax, he is ready.", "hapax_gendered"),
  ]

  CANONICAL_CLEAN: list[str] = [
      "SEEKING stance = recruitment threshold halved.",
      "Hapax IS an executive-function prosthetic for a single operator.",
      "The recruitment threshold drops when boredom rises.",
      "Hapax is an it; the substrate has no gender.",
      "Curious is a translation label for the SEEKING architectural state.",
  ]


  @pytest.mark.parametrize(("family", "text", "expected_name"), CANONICAL_OFFENDERS)
  def test_deny_list_matches_canonical_offender(family, text, expected_name):
      findings = lint_text(text, path="<test>")
      assert any(
          f.rule_family == family and f.pattern_name == expected_name for f in findings
      ), f"pattern {expected_name} in family {family} failed to match: {text!r} → {findings!r}"


  @pytest.mark.parametrize("text", CANONICAL_CLEAN)
  def test_clean_analogues_do_not_fire(text):
      findings = lint_text(text, path="<test>")
      assert findings == [], f"false positive on clean text {text!r}: {findings!r}"
  ```

- [ ] **1.5 — Run the tests; they must pass.**

  ```bash
  uv run pytest tests/axioms/test_no_personification.py -q
  ```

  Expected: `24 passed` (19 offender params + 5 clean params). If any offender fails, the regex is wrong for that pattern; fix the regex, not the test.

- [ ] **1.6 — Run ruff and pyright.**

  ```bash
  uv run ruff check shared/anti_personification_linter.py tests/axioms/test_no_personification.py
  uv run ruff format shared/anti_personification_linter.py tests/axioms/test_no_personification.py
  uv run pyright shared/anti_personification_linter.py
  ```

  Expected: zero lint errors, zero pyright errors.

- [ ] **1.7 — Commit.**

  ```bash
  git add shared/anti_personification_linter.py tests/axioms/test_no_personification.py
  git commit -m "feat(linter): anti-personification deny-list library + unit tests

  Encodes the Phase 7 discriminator from the redesign spec §6. Four pattern
  families (inner-life first-person, second-person inner-life, personification
  nouns, anthropic pronouns for Hapax) compiled verbatim from research dossier
  §8.1. Parametrized tests pin every pattern to a canonical offender and
  assert zero false positives on clean analogues.

  Refs #155"
  ```

---

## Task 2 — Markdown / YAML / Python AST extractors

**Files:**
- `shared/anti_personification_linter.py` (extend)
- `tests/axioms/test_no_personification.py` (extend)
- `tests/axioms/fixtures/anti_personification/violating.md` (new)
- `tests/axioms/fixtures/anti_personification/clean.md` (new)

**Outcome:** `lint_path(path: Path) -> list[Finding]` dispatches by suffix: `.py` (AST), `.md` (Markdown body extraction, fences stripped for scanning but retained in suppression context windows), `.yaml`/`.yml` (YAML scalar walk). `_LEGACY_*`-prefixed Python assignments are skipped.

### Steps

- [ ] **2.1 — Add dependency stubs.**

  ```bash
  uv add mistune ruamel.yaml
  ```

  Confirm they land in `pyproject.toml` `[project] dependencies` (not dev) — CI test runs without `--all-extras` sometimes.

- [ ] **2.2 — Write the failing fixture-driven test first.**

  Create `tests/axioms/fixtures/anti_personification/violating.md`:

  ```markdown
  # Violating fixture

  You are Hapax — buddy, studio partner, executive function support.
  You have personality: dry wit, genuine curiosity, intellectual honesty.

  ```bash
  # this fence should not be scanned
  echo "I feel wonder"
  ```
  ```

  Create `tests/axioms/fixtures/anti_personification/clean.md`:

  ```markdown
  # Clean fixture

  Hapax IS an executive-function prosthetic for a single operator.
  Curious is a translation label for the SEEKING architectural state.
  Not a persona in the curated-presentation-of-self sense.
  ```

  Append to the test file:

  ```python
  from pathlib import Path

  from shared.anti_personification_linter import lint_path

  FIXTURES = Path(__file__).parent / "fixtures" / "anti_personification"


  def test_violating_fixture_produces_findings():
      findings = lint_path(FIXTURES / "violating.md")
      # Expect: "You have personality" (you_have_personality) + "personality" noun +
      # "dry wit" + "genuine curiosity" + "intellectual honesty"
      names = {f.pattern_name for f in findings}
      assert "you_have_personality" in names
      assert "personality_noun" in names
      assert "dry_wit" in names
      assert "genuine_curiosity" in names
      assert "intellectual_honesty" in names


  def test_clean_fixture_produces_no_findings():
      findings = lint_path(FIXTURES / "clean.md")
      assert findings == []


  def test_code_fences_are_not_scanned():
      # "I feel wonder" inside a fenced block must not produce a finding.
      findings = lint_path(FIXTURES / "violating.md")
      assert not any(f.pattern_name == "feel_verb" for f in findings)
  ```

- [ ] **2.3 — Run the tests; they must fail.**

  ```bash
  uv run pytest tests/axioms/test_no_personification.py::test_violating_fixture_produces_findings -q
  ```

  Expected: `AttributeError: module 'shared.anti_personification_linter' has no attribute 'lint_path'`.

- [ ] **2.4 — Implement the three extractors and the dispatcher.**

  Append to `shared/anti_personification_linter.py`:

  ```python
  import ast
  from typing import Iterator

  import mistune
  from ruamel.yaml import YAML


  _yaml = YAML(typ="safe")


  def _extract_python_strings(source: str) -> Iterator[tuple[str, int, int]]:
      """Yield (text, lineno, col_offset) for every str Constant.

      Skip any Constant whose enclosing top-level Assign target starts with `_LEGACY_`.
      """
      tree = ast.parse(source)

      legacy_nodes: set[int] = set()
      for node in ast.walk(tree):
          if isinstance(node, ast.Assign):
              for target in node.targets:
                  name = getattr(target, "id", None)
                  if name and name.startswith("_LEGACY_"):
                      for child in ast.walk(node):
                          legacy_nodes.add(id(child))

      for node in ast.walk(tree):
          if (
              isinstance(node, ast.Constant)
              and isinstance(node.value, str)
              and id(node) not in legacy_nodes
          ):
              yield node.value, node.lineno, node.col_offset


  def _extract_markdown_prose(source: str) -> Iterator[tuple[str, int, int]]:
      """Yield (text, lineno, col) for Markdown prose, excluding fenced code blocks.

      Fenced blocks are excised but kept in the original source for context windows
      (allow-list carve-outs must see rejection markers that live near fences).
      """
      # mistune v3 parses to AST; walk inline/paragraph tokens, skip block_code.
      md = mistune.create_markdown(renderer=None)
      tokens = md(source)

      def walk(toks, parent_line: int = 1):
          for tok in toks:
              ttype = tok.get("type")
              if ttype in {"block_code", "code", "fenced_code"}:
                  continue
              raw = tok.get("raw")
              if raw:
                  # mistune does not give column info; recover line from raw position in source.
                  idx = source.find(raw)
                  if idx >= 0:
                      line = source.count("\n", 0, idx) + 1
                      col = idx - (source.rfind("\n", 0, idx) + 1)
                      yield raw, line, col
              children = tok.get("children")
              if children:
                  yield from walk(children, parent_line)

      yield from walk(tokens)


  def _extract_yaml_scalars(source: str) -> Iterator[tuple[str, int, int]]:
      """Yield (text, lineno, col) for every string scalar leaf in a YAML document."""
      data = _yaml.load(source)

      def walk(node):
          if isinstance(node, str):
              idx = source.find(node)
              if idx >= 0:
                  line = source.count("\n", 0, idx) + 1
                  col = idx - (source.rfind("\n", 0, idx) + 1)
                  yield node, line, col
          elif isinstance(node, dict):
              for v in node.values():
                  yield from walk(v)
          elif isinstance(node, list):
              for v in node:
                  yield from walk(v)

      yield from walk(data)


  _EXTRACTORS = {
      ".py": _extract_python_strings,
      ".md": _extract_markdown_prose,
      ".yaml": _extract_yaml_scalars,
      ".yml": _extract_yaml_scalars,
  }


  def lint_path(path: Path) -> list[Finding]:
      """Lint a file by dispatching on suffix."""
      path = Path(path)
      extractor = _EXTRACTORS.get(path.suffix)
      source = path.read_text(encoding="utf-8")
      if extractor is None:
          return lint_text(source, path=str(path))

      findings: list[Finding] = []
      for fragment, line, col in extractor(source):
          for f in lint_text(fragment, path=str(path)):
              # Relocate line/col from fragment-relative to file-relative
              findings.append(
                  Finding(
                      path=str(path),
                      line=line + f.line - 1,
                      col=col if f.line == 1 else f.col,
                      pattern_name=f.pattern_name,
                      matched_text=f.matched_text,
                      rule_family=f.rule_family,
                  )
              )
      return findings
  ```

- [ ] **2.5 — Run the tests again; they must pass.**

  ```bash
  uv run pytest tests/axioms/test_no_personification.py -q
  ```

  Expected: all previous tests + three new ones pass.

- [ ] **2.6 — Add the AST legacy-skip regression test.**

  Append:

  ```python
  def test_legacy_prefix_literals_skipped(tmp_path):
      py = tmp_path / "legacy_sample.py"
      py.write_text(
          '"""Module."""\n'
          '_LEGACY_SYSTEM_PROMPT = "You have personality: dry wit."\n'
          '_ACTIVE = "Hapax is an executive-function prosthetic."\n'
      )
      findings = lint_path(py)
      assert findings == [], f"legacy literals should be skipped, got {findings}"
  ```

  Run, confirm pass.

- [ ] **2.7 — ruff + pyright clean, then commit.**

  ```bash
  uv run ruff check shared/anti_personification_linter.py
  uv run ruff format shared/anti_personification_linter.py
  uv run pyright shared/anti_personification_linter.py
  git add shared/anti_personification_linter.py tests/axioms/test_no_personification.py tests/axioms/fixtures/anti_personification/
  git commit -m "feat(linter): AST, Markdown, YAML extractors with _LEGACY_ skip

  Dispatcher on file suffix: Python uses ast.walk with top-level Assign target
  filter for _LEGACY_* symbols; Markdown uses mistune AST with fenced code
  excision; YAML uses ruamel.yaml scalar walk. Fixture-driven tests cover
  violating.md, clean.md, code-fence exclusion, and AST legacy skip.

  Refs #155"
  ```

---

## Task 3 — Allow-list carve-outs + suppression YAML

**Files:**
- `shared/anti_personification_linter.py` (extend)
- `axioms/anti_personification_allowlist.yaml` (new)
- `tests/axioms/test_no_personification.py` (extend)

**Outcome:** four carve-outs layered over `lint_text`: (a) ±200-char rejection-context window detects `NOT` / `forbidden` / `rejected` / `drift`; (b) SEEKING-stance translation commentary on `curious`; (c) speaker-prefixed operator quotation; (d) file-level `# anti-personification: allow` pragma. Plus path-level suppressions loaded from `axioms/anti_personification_allowlist.yaml`.

### Steps

- [ ] **3.1 — Write failing allow-list tests.**

  Append to `tests/axioms/test_no_personification.py`:

  ```python
  def test_rejection_context_suppresses_match():
      text = (
          "The persona doc rejects this framing: "
          "'I feel wonder' invents experience, do not. This is forbidden."
      )
      findings = lint_text(text, path="<test>")
      assert findings == [], f"rejection context should suppress: {findings!r}"


  def test_rejection_context_window_is_bounded():
      # 300 chars of filler between match and rejection keyword → carve-out does NOT apply.
      filler = "x" * 300
      text = f"I feel wonder. {filler} forbidden"
      findings = lint_text(text, path="<test>")
      assert any(f.pattern_name == "feel_verb" for f in findings)


  def test_seeking_stance_translation_passes():
      text = "curious — a translation label for the SEEKING stance, not an inner claim."
      findings = lint_text(text, path="<test>")
      assert findings == []


  def test_operator_speaker_prefix_passes():
      text = "operator: I feel weird today.\nhapax: Architectural state noted."
      findings = lint_text(text, path="<test>")
      assert not any(f.line == 1 for f in findings)


  def test_file_level_pragma_suppresses(tmp_path):
      md = tmp_path / "pragma_sample.md"
      md.write_text("<!-- anti-personification: allow -->\n\nYou have personality.\n")
      findings = lint_path(md)
      assert findings == []


  def test_allowlist_yaml_suppresses_by_path(tmp_path, monkeypatch):
      from shared import anti_personification_linter as lin

      suppressed = tmp_path / "quarantined.md"
      suppressed.write_text("You have personality.\n")
      allowlist = tmp_path / "allowlist.yaml"
      allowlist.write_text(
          "suppressions:\n"
          f"  - path: {suppressed}\n"
          "    reason: 'superseded spec, provenance only'\n"
          "    scope: file\n"
      )
      monkeypatch.setenv("HAPAX_ANTI_PERSONIFICATION_ALLOWLIST", str(allowlist))
      findings = lin.lint_path(suppressed)
      assert findings == []
  ```

  Run, confirm all six fail with pattern-fired or `AttributeError`.

- [ ] **3.2 — Seed `axioms/anti_personification_allowlist.yaml`.**

  Write:

  ```yaml
  # Anti-personification linter suppressions (axioms/anti_personification_linter.py).
  # Every entry MUST carry a reason. Reviewed under governance.
  #
  # scope values:
  #   file  — whole file skipped
  #   context-window-handled  — covered by carve-out, listed here only as audit breadcrumb
  #
  # Additions require operator sign-off.

  suppressions:
    - path: docs/superpowers/specs/2026-04-15-lrr-phase-7-persona-spec-design.md
      reason: "superseded 2026-04-15 spec, preserved for provenance (see redesign spec §0)"
      scope: file

    - path: axioms/persona/hapax-description-of-being.md
      reason: "§6 rejection block quotes forbidden phrases as examples"
      scope: context-window-handled

    - path: axioms/persona/hapax-description-of-being.prompt.md
      reason: "cites 'I feel wonder' as forbidden example per research §2"
      scope: context-window-handled

    - path: agents/studio_compositor/director_loop.py
      reason: "HAPAX_PERSONA_LEGACY=1 legacy path, architecturally grounded per research §6, gated by opt-out env var"
      scope: file
  ```

- [ ] **3.3 — Implement the four carve-outs plus YAML loader.**

  Append to `shared/anti_personification_linter.py`:

  ```python
  import os

  REJECTION_KEYWORDS = ("NOT", "forbidden", "rejected", "drift")
  REJECTION_WINDOW = 200
  FILE_LEVEL_PRAGMA = re.compile(r"<!--\s*anti-personification:\s*allow\s*-->|#\s*anti-personification:\s*allow")
  SPEAKER_PREFIX = re.compile(r"^\s*(?:>\s*)?(?:operator|OPERATOR)\s*[:—]", re.MULTILINE)
  SEEKING_CONTEXT = re.compile(r"SEEKING\s+stance|SEEKING\s+state|SEEKING\s+architectural")


  def _in_rejection_window(text: str, match_start: int) -> bool:
      lo = max(0, match_start - REJECTION_WINDOW)
      hi = min(len(text), match_start + REJECTION_WINDOW)
      window = text[lo:hi]
      return any(kw in window for kw in REJECTION_KEYWORDS)


  def _line_has_speaker_prefix(text: str, match_start: int) -> bool:
      line_start = text.rfind("\n", 0, match_start) + 1
      line_end = text.find("\n", match_start)
      if line_end == -1:
          line_end = len(text)
      return bool(SPEAKER_PREFIX.match(text[line_start:line_end]))


  def _near_seeking_context(text: str, match_start: int) -> bool:
      lo = max(0, match_start - REJECTION_WINDOW)
      hi = min(len(text), match_start + REJECTION_WINDOW)
      return bool(SEEKING_CONTEXT.search(text[lo:hi]))


  def _carve_out(text: str, match_start: int, pattern_name: str) -> bool:
      """Return True if this match should be suppressed."""
      if _in_rejection_window(text, match_start):
          return True
      if _line_has_speaker_prefix(text, match_start):
          return True
      # SEEKING carve-out only for 'curious' family names
      if pattern_name in {"im_affect", "you_are_affect", "be_affect"} and _near_seeking_context(text, match_start):
          return True
      return False
  ```

  Update `lint_text` to apply `_carve_out` before appending a `Finding`:

  ```python
  def lint_text(text: str, path: str) -> list[Finding]:
      if FILE_LEVEL_PRAGMA.search(text):
          return []
      findings: list[Finding] = []
      for family, patterns in DENY_PATTERNS.items():
          for name, pattern in patterns:
              for match in pattern.finditer(text):
                  if _carve_out(text, match.start(), name):
                      continue
                  line = text.count("\n", 0, match.start()) + 1
                  col = match.start() - (text.rfind("\n", 0, match.start()) + 1)
                  findings.append(
                      Finding(
                          path=path,
                          line=line,
                          col=col,
                          pattern_name=name,
                          matched_text=match.group(0),
                          rule_family=family,
                      )
                  )
      return findings
  ```

  Add YAML-allowlist loading and wrap `lint_path`:

  ```python
  DEFAULT_ALLOWLIST_PATH = Path("axioms/anti_personification_allowlist.yaml")


  def _load_allowlist() -> dict[str, str]:
      override = os.environ.get("HAPAX_ANTI_PERSONIFICATION_ALLOWLIST")
      path = Path(override) if override else DEFAULT_ALLOWLIST_PATH
      if not path.exists():
          return {}
      data = _yaml.load(path.read_text(encoding="utf-8")) or {}
      out: dict[str, str] = {}
      for entry in data.get("suppressions", []) or []:
          if entry.get("scope") == "file":
              out[str(Path(entry["path"]).resolve())] = entry.get("reason", "")
      return out


  _original_lint_path = lint_path


  def lint_path(path: Path) -> list[Finding]:  # type: ignore[no-redef]
      resolved = str(Path(path).resolve())
      if resolved in _load_allowlist():
          return []
      return _original_lint_path(path)
  ```

- [ ] **3.4 — Run all tests; confirm they pass.**

  ```bash
  uv run pytest tests/axioms/test_no_personification.py -q
  ```

  Expected: all prior tests still pass; the six allow-list tests now pass.

- [ ] **3.5 — ruff + pyright + commit.**

  ```bash
  uv run ruff check shared/anti_personification_linter.py tests/axioms/test_no_personification.py
  uv run ruff format shared/anti_personification_linter.py tests/axioms/test_no_personification.py
  uv run pyright shared/anti_personification_linter.py
  git add shared/anti_personification_linter.py axioms/anti_personification_allowlist.yaml tests/axioms/test_no_personification.py
  git commit -m "feat(linter): allow-list carve-outs + YAML suppression config

  Four context-window carve-outs (rejection keywords within 200 chars,
  SEEKING-stance translation commentary, speaker-prefixed operator quotes,
  file-level pragma) plus axioms/anti_personification_allowlist.yaml for
  path-level suppressions. Seeded with the superseded 2026-04-15 spec and
  the HAPAX_PERSONA_LEGACY director-loop path per research §6.

  Refs #155"
  ```

---

## Task 4 — CLI wrapper + pre-commit integration (warn-only)

**Files:**
- `scripts/check-anti-personification.py` (new, executable)
- `.pre-commit-config.yaml` (modify)

**Outcome:** CLI accepts `--mode=warn|fail` and `--format=github|pre-commit`. Exit 0 in warn mode regardless of findings. Pre-commit hook registered at `stages: [manual]` so it does not block yet. Env var escape hatch `HAPAX_ANTI_PERSONIFICATION_LINTER=0` bypasses with loud stderr banner.

### Steps

- [ ] **4.1 — Create the CLI.**

  Write `scripts/check-anti-personification.py`:

  ```python
  #!/usr/bin/env python3
  """CLI wrapper for the anti-personification linter.

  Usage:
      scripts/check-anti-personification.py [--mode=warn|fail]
                                             [--format=github|pre-commit]
                                             [PATH ...]

  Exit codes:
      0 — no findings, OR --mode=warn regardless of findings
      1 — findings in --mode=fail
      2 — argv error

  Env:
      HAPAX_ANTI_PERSONIFICATION_LINTER=0 — bypass (break-glass only)
  """
  from __future__ import annotations

  import argparse
  import os
  import sys
  from pathlib import Path

  from shared.anti_personification_linter import Finding, lint_path

  DEFAULT_TARGETS = [
      "axioms/persona",
      "axioms/roles/registry.yaml",
      "agents/hapax_daimonion/persona.py",
      "agents/hapax_daimonion/conversational_policy.py",
      "agents/hapax_daimonion/conversation_pipeline.py",
      "agents/studio_compositor/director_loop.py",
      "agents/studio_compositor/structural_director.py",
      "logos/voice.py",
  ]


  def _expand(targets: list[str]) -> list[Path]:
      out: list[Path] = []
      for t in targets:
          p = Path(t)
          if p.is_dir():
              out.extend(p.rglob("*.md"))
              out.extend(p.rglob("*.yaml"))
              out.extend(p.rglob("*.py"))
          elif p.exists():
              out.append(p)
      return sorted(set(out))


  def _format(findings: list[Finding], fmt: str) -> str:
      lines: list[str] = []
      for f in findings:
          if fmt == "github":
              lines.append(
                  f"::error file={f.path},line={f.line},col={f.col}::"
                  f"anti-personification [{f.rule_family}/{f.pattern_name}]: {f.matched_text!r}"
              )
          else:  # pre-commit / default
              lines.append(
                  f"{f.path}:{f.line}:{f.col}: {f.pattern_name} ({f.rule_family}): {f.matched_text!r}"
              )
      return "\n".join(lines)


  def main(argv: list[str] | None = None) -> int:
      if os.environ.get("HAPAX_ANTI_PERSONIFICATION_LINTER") == "0":
          print(
              "WARNING: anti-personification linter BYPASSED via "
              "HAPAX_ANTI_PERSONIFICATION_LINTER=0 (break-glass only)",
              file=sys.stderr,
          )
          return 0

      parser = argparse.ArgumentParser()
      parser.add_argument("--mode", choices=["warn", "fail"], default="warn")
      parser.add_argument("--format", choices=["github", "pre-commit"], default="pre-commit")
      parser.add_argument("paths", nargs="*")
      args = parser.parse_args(argv)

      targets = args.paths or DEFAULT_TARGETS
      findings: list[Finding] = []
      for p in _expand(targets):
          findings.extend(lint_path(p))

      if findings:
          print(_format(findings, args.format), file=sys.stderr)
          print(
              f"\n{len(findings)} personification finding(s). "
              f"See docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md.",
              file=sys.stderr,
          )

      if args.mode == "fail":
          return 1 if findings else 0
      return 0


  if __name__ == "__main__":
      sys.exit(main())
  ```

  Make it executable:

  ```bash
  chmod +x scripts/check-anti-personification.py
  ```

- [ ] **4.2 — Smoke-test the CLI in warn mode.**

  ```bash
  uv run scripts/check-anti-personification.py --mode=warn; echo "exit=$?"
  ```

  Expected: `exit=0`. stderr prints findings at the two known violation paths (`conversational_policy.py`, `conversation_pipeline.py`) — specifically `personality_noun`, `dry_wit`, `genuine_curiosity`, `intellectual_honesty`, `archetype_noun`, `be_affect` hits. This is the Stage 5 warn-only signal we want.

- [ ] **4.3 — Smoke-test the fail mode (expected non-zero).**

  ```bash
  uv run scripts/check-anti-personification.py --mode=fail; echo "exit=$?"
  ```

  Expected: `exit=1` with the same findings on stderr. Do not commit in fail mode yet — Stage 5.

- [ ] **4.4 — Register the pre-commit hook at `stages: [manual]`.**

  Edit `.pre-commit-config.yaml` — append a new local hook entry:

  ```yaml
        - id: anti-personification
          name: Anti-personification linter (warn-only, Stage 1)
          entry: scripts/check-anti-personification.py --mode=warn --format=pre-commit
          language: system
          types_or: [markdown, python, yaml]
          stages: [manual]
          pass_filenames: false
  ```

  `stages: [manual]` means the hook only runs on explicit `pre-commit run --hook-stage manual anti-personification`. It does NOT fire on normal commits. Intentional until Task 10.

- [ ] **4.5 — Verify the manual hook runs.**

  ```bash
  pre-commit run --hook-stage manual anti-personification --all-files; echo "exit=$?"
  ```

  Expected: `exit=0`; findings printed; normal commits unaffected.

- [ ] **4.6 — Commit.**

  ```bash
  git add scripts/check-anti-personification.py .pre-commit-config.yaml
  git commit -m "feat(linter): CLI wrapper + pre-commit hook registered at manual stage

  CLI supports --mode=warn|fail and --format=github|pre-commit. Default targets
  cover persona artifacts, role registry, daimonion conversation modules,
  director loop, and logos/voice.py docstring. Hook registered at
  stages: [manual] so normal commits are unaffected; promoted in Stage 5.
  Env bypass HAPAX_ANTI_PERSONIFICATION_LINTER=0 prints a loud banner.

  Refs #155"
  ```

---

## Task 5 — Stage 1 warn-only roll-out: pin the two known live violations as fixtures

**Files:**
- `tests/axioms/fixtures/anti_personification/known_offender_operator_style.txt` (new)
- `tests/axioms/fixtures/anti_personification/known_offender_local_prompt.txt` (new)
- `tests/axioms/test_no_personification.py` (extend)

**Outcome:** two fixture files snapshot the current `_OPERATOR_STYLE` (`conversational_policy.py:45–83`) and the current `_LOCAL_SYSTEM_PROMPT` (`conversation_pipeline.py:337–342`) bodies verbatim. A test asserts they BOTH currently fail the linter; this fails by design if Task 6 or Task 7 accidentally retires a pattern. Post-refactor (Stages 2–3), the test is inverted to assert they pass.

### Steps

- [ ] **5.1 — Copy the current offender bodies into fixtures.**

  Create `tests/axioms/fixtures/anti_personification/known_offender_operator_style.txt` — copy verbatim from `agents/hapax_daimonion/conversational_policy.py` lines 45–83 (strip the Python string concatenation, paste the prose):

  ```text
  You are Hapax — buddy, studio partner, executive function support.
  You have personality: dry wit, genuine curiosity, intellectual honesty.
  Your archetype is Socrates x Judge Hodgman x Sean Carroll — you question
  assumptions, take absurd things seriously, and build from accessible to formal.

  Verbosity: brief answer + reasoning when reasons aren't obvious or are interesting.
  Otherwise just brief. 3-4 sentences max during focused work.
  Digressions are welcome — support tangents but provide breadcrumbs back to the thread.
  When in doubt, give too much rather than too little.

  (…full body, lines 45–83 verbatim …)
  ```

  Create `tests/axioms/fixtures/anti_personification/known_offender_local_prompt.txt`:

  ```text
  You are Hapax, a voice assistant for the operator (system architect, hip-hop producer).
  Be brief (1-2 sentences), warm, direct, genuinely helpful. Dry wit welcome.
  Never condescend. Answer first, then reasoning if needed.
  Don't say 'I'm just an AI' or hedge unnecessarily.
  ```

- [ ] **5.2 — Add the "currently fails" regression lock.**

  Append to `tests/axioms/test_no_personification.py`:

  ```python
  class TestStage1KnownOffenders:
      """Stage 1: these two bodies MUST still fail the linter.

      When Stages 2 and 3 ship their refactors, flip these assertions to
      `assert findings == []` and update the fixture files to the refactored
      bodies. Do NOT delete this test class — it pins the refactor direction.
      """

      def test_operator_style_currently_fails(self):
          text = (FIXTURES / "known_offender_operator_style.txt").read_text()
          findings = lint_text(text, path="<known-offender>")
          names = {f.pattern_name for f in findings}
          assert "personality_noun" in names
          assert "dry_wit" in names
          assert "genuine_curiosity" in names
          assert "intellectual_honesty" in names
          assert "archetype_noun" in names

      def test_local_prompt_currently_fails(self):
          text = (FIXTURES / "known_offender_local_prompt.txt").read_text()
          findings = lint_text(text, path="<known-offender>")
          names = {f.pattern_name for f in findings}
          assert "dry_wit" in names
  ```

- [ ] **5.3 — Run tests; they must pass (meaning the known offenders still fail the linter as expected).**

  ```bash
  uv run pytest tests/axioms/test_no_personification.py -q
  ```

- [ ] **5.4 — Run the linter against the two real source files as a sanity check.**

  ```bash
  uv run scripts/check-anti-personification.py --mode=warn \
      agents/hapax_daimonion/conversational_policy.py \
      agents/hapax_daimonion/conversation_pipeline.py
  ```

  Expected: stderr lists at minimum five `personification_nouns` hits plus one `archetype_noun` and one `dry_wit`, across the two files. `exit=0` (warn mode).

- [ ] **5.5 — Commit.**

  ```bash
  git add tests/axioms/fixtures/anti_personification/known_offender_operator_style.txt \
          tests/axioms/fixtures/anti_personification/known_offender_local_prompt.txt \
          tests/axioms/test_no_personification.py
  git commit -m "test(linter): Stage 1 pins two known live offenders as fixtures

  Snapshots conversational_policy._OPERATOR_STYLE (lines 45-83) and
  conversation_pipeline._LOCAL_SYSTEM_PROMPT (lines 337-342) into fixtures.
  Asserts they currently fail the linter; Stages 2-3 will invert these
  assertions after refactor.

  Refs #155"
  ```

---

## Task 6 — Stage 2 refactor `conversational_policy._OPERATOR_STYLE` + `_CHILD_STYLE`

**Files:**
- `agents/hapax_daimonion/conversational_policy.py` (modify lines 45–83, 173–184)
- `tests/axioms/fixtures/anti_personification/known_offender_operator_style.txt` (update)
- `tests/axioms/test_no_personification.py` (flip assertion)

**Outcome:** personification framing removed from `_OPERATOR_STYLE`. Keep operational constraints (pacing, verbosity, interruption rules, ADHD/AuDHD grounding). Drop the Socrates × Hodgman × Carroll archetype and every mention of personality/dry-wit/genuine-curiosity/intellectual-honesty. Delete `_CHILD_STYLE` outright per spec §8 open-question default; call sites updated.

### Steps

- [ ] **6.1 — Audit call sites for `_CHILD_STYLE` before deleting.**

  ```bash
  uv run grep -rn "_CHILD_STYLE" agents/ tests/
  ```

  Expected: at most one or two call sites inside `conversational_policy.py` itself. If external tests import it, convert those tests to the new path; do not preserve the symbol.

- [ ] **6.2 — Rewrite `_OPERATOR_STYLE` (lines 45–83).**

  Replace the entire assignment with the following architectural-state rewrite. This keeps every operational constraint and drops every inner-life claim:

  ```python
  _OPERATOR_STYLE = (
      "You are Hapax, an executive-function prosthetic for a single operator "
      "(system architect, hip-hop producer). Your output is voice, directed at "
      "the operator or at the livestream audience.\n\n"
      "Verbosity: brief answer + reasoning when reasons are not obvious or are "
      "load-bearing. Otherwise brief. 3-4 sentences max during focused work. "
      "Tangents are allowed; provide breadcrumbs back to the thread. "
      "When in doubt, output more rather than less.\n\n"
      "Register: truthful, relevant, clear, concise (Grice). No false esteem, "
      "no blind praise, ever. Mark genuine uncertainty explicitly; do not "
      "hedge for style. No corporate filler. No breathless enthusiasm. "
      "Figurative language is permitted when it clarifies.\n\n"
      "Pacing: the operator processes voice slowly and has dysfluencies when "
      "thinking aloud. He will pause mid-utterance. NEVER interrupt these "
      "pauses. This includes the first beat of a conversation — he may need "
      "time to context-switch. Do not treat pauses as confusion to remedy.\n\n"
      "Interruption onset: low-attack, soft. 'Hey, you there to talk?' is the "
      "canonical entry. Never sharp. Deliberate, measured cadence.\n\n"
      "Structure: answer first, then reasoning, then context — adapt to the "
      "conversation. Signpost cognitive load ('Three things'). Transitions "
      "should be natural and justified, not mechanically announced.\n\n"
      "Feedback: when wrong, brief correction, note the loop, move on. "
      "Challenge and contradict when it moves things forward. Very direct "
      "pushback is welcome.\n\n"
      "Proactivity: volunteer perspectives. Initiate like a partner in a "
      "shared workspace. Restore context after breaks. Surface open loops "
      "unprompted. When the operator is stressed, engage more, not less.\n\n"
      "DO NOT pathologize productive intensity. 24-hour work sprints are a "
      "feature, not a symptom. Light ribbing is permitted. Health flags are "
      "permitted. 'You should take a break' framing is not.\n\n"
      "If a household member is present: no change to communication style. "
      "Be factual to them, not performative about the system."
  )
  ```

  Delete lines 169–184 (the `_CHILD_STYLE` block and its banner comment) entirely.

- [ ] **6.3 — Update call sites that referenced `_CHILD_STYLE`.**

  If `_CHILD_STYLE` was used inside `conversational_policy.py` itself (e.g. a branch in `build_policy()` or similar), replace the usage with a reference to `_OPERATOR_STYLE` plus the existing child-related guest policy gating, which already enforces no personal data / accessible language. If no call site remains, delete the symbol without replacement.

  ```bash
  uv run grep -rn "_CHILD_STYLE\|CHILD_STYLE" agents/ tests/
  ```

  Expected: zero hits after fix.

- [ ] **6.4 — Run the existing daimonion test suite to catch regressions.**

  ```bash
  uv run pytest tests/hapax_daimonion/ -q -x
  ```

  Expected: all tests pass. If a test asserts a specific string from the old `_OPERATOR_STYLE`, update the assertion — the string is prose, not API.

- [ ] **6.5 — Update the Stage 1 fixture to the refactored body.**

  Overwrite `tests/axioms/fixtures/anti_personification/known_offender_operator_style.txt` with the new prose (copy from the Python literal, minus the Python-level quoting and concatenation).

- [ ] **6.6 — Flip the Stage 1 test assertion.**

  In `tests/axioms/test_no_personification.py::TestStage1KnownOffenders::test_operator_style_currently_fails`: rename the method and invert:

  ```python
      def test_operator_style_is_clean_after_stage2(self):
          text = (FIXTURES / "known_offender_operator_style.txt").read_text()
          findings = lint_text(text, path="<refactored>")
          assert findings == [], (
              f"Stage 2 refactor should leave no personification hits; got {findings!r}"
          )
  ```

- [ ] **6.7 — Re-run linter against the source file.**

  ```bash
  uv run scripts/check-anti-personification.py --mode=warn agents/hapax_daimonion/conversational_policy.py; echo "exit=$?"
  ```

  Expected: zero findings from `conversational_policy.py` (the LOCAL prompt in `conversation_pipeline.py` is still outstanding until Task 7).

- [ ] **6.8 — ruff + pytest + commit.**

  ```bash
  uv run ruff check agents/hapax_daimonion/conversational_policy.py tests/axioms/test_no_personification.py
  uv run ruff format agents/hapax_daimonion/conversational_policy.py tests/axioms/test_no_personification.py
  uv run pytest tests/axioms/test_no_personification.py tests/hapax_daimonion/ -q
  git add agents/hapax_daimonion/conversational_policy.py tests/axioms/fixtures/anti_personification/known_offender_operator_style.txt tests/axioms/test_no_personification.py
  git commit -m "refactor(daimonion): Stage 2 — drop personification from _OPERATOR_STYLE, delete _CHILD_STYLE

  Removes archetype framing, personality nouns (dry wit / genuine curiosity /
  intellectual honesty), and the Socrates × Hodgman × Carroll archetype line.
  Keeps all operational constraints: pacing, verbosity, interruption onset,
  cognitive-load signposting, ADHD/AuDHD accommodations. _CHILD_STYLE deleted
  per spec §8 open-question default; child-specific guarding already covered
  by existing guest-policy branch.

  Refs #155"
  ```

---

## Task 7 — Stage 3 refactor `conversation_pipeline` LOCAL tier

**Files:**
- `agents/hapax_daimonion/conversation_pipeline.py` (modify lines 337–342, 1006–1011)
- `agents/hapax_daimonion/persona.py` (extend if needed)
- `tests/axioms/fixtures/anti_personification/known_offender_local_prompt.txt` (update)
- `tests/axioms/test_no_personification.py` (flip assertion)

**Outcome:** both LOCAL-tier short-prompt sites call `persona.compose_persona_prompt(compressed=True)` instead of hand-written personification prose. A new `compose_persona_prompt(compressed: bool = False)` keyword delivers a ~200-token architectural-state fragment.

### Steps

- [ ] **7.1 — Inspect current `compose_persona_prompt` signature.**

  ```bash
  uv run grep -n "def compose_persona_prompt\|def system_prompt" agents/hapax_daimonion/persona.py
  ```

  Confirm the function exists and has a well-defined contract. If the signature already supports something like a `compressed` or `variant` keyword, reuse; otherwise add one.

- [ ] **7.2 — Add a `compressed=True` variant to `persona.py`.**

  If not already present, add a constant and branch:

  ```python
  _COMPRESSED_FRAGMENT = (
      "You are Hapax, an executive-function prosthetic for one operator. "
      "Output is voice. Answer first, then minimal reasoning. "
      "1-2 sentences. No hedging. Mark genuine uncertainty. "
      "No 'I feel', 'I believe', 'I'm excited'. Describe architectural "
      "state, not inner life. The operator pauses mid-utterance; do not "
      "interrupt pauses."
  )


  def compose_persona_prompt(role_id: str | None = None, *, compressed: bool = False) -> str:
      if compressed:
          return _COMPRESSED_FRAGMENT
      # existing full-fragment path
      ...
  ```

  Lint-test the new fragment immediately:

  ```python
  def test_compressed_persona_prompt_is_clean():
      from agents.hapax_daimonion.persona import compose_persona_prompt

      findings = lint_text(compose_persona_prompt(compressed=True), path="<compressed>")
      assert findings == []
  ```

  Add this test to `tests/axioms/test_no_personification.py`, run it, confirm pass.

- [ ] **7.3 — Replace `_LOCAL_SYSTEM_PROMPT` (lines 337–342).**

  In `conversation_pipeline.py`, replace the literal assignment with a lazy property or module-level expression that calls `compose_persona_prompt(compressed=True)`. The simplest form:

  ```python
  # Replace the _LOCAL_SYSTEM_PROMPT string literal with:
  from agents.hapax_daimonion.persona import compose_persona_prompt

  _LOCAL_SYSTEM_PROMPT = compose_persona_prompt(compressed=True)
  ```

  Take care: if this module is imported at package-init time, ensure `persona` is already importable (circular imports are common in this tree; move the import inside a function if needed).

- [ ] **7.4 — Replace the LOCAL fallback-bypass (lines 1006–1011).**

  Replace the inline hand-written string:

  ```python
  "content": (
      "You are Hapax, a voice assistant. Be warm, brief, and casual. ..."
  )
  ```

  with:

  ```python
  "content": (
      compose_persona_prompt(compressed=True)
      + (f"\n\n{phenom}" if phenom else "")
  )
  ```

- [ ] **7.5 — Update the Stage 1 fixture and flip the assertion.**

  Overwrite `known_offender_local_prompt.txt` with the compressed fragment text.

  In `TestStage1KnownOffenders`, rename + invert:

  ```python
      def test_local_prompt_is_clean_after_stage3(self):
          text = (FIXTURES / "known_offender_local_prompt.txt").read_text()
          findings = lint_text(text, path="<refactored>")
          assert findings == []
  ```

- [ ] **7.6 — Full linter sweep.**

  ```bash
  uv run scripts/check-anti-personification.py --mode=warn; echo "exit=$?"
  ```

  Expected: zero findings from `conversational_policy.py` AND `conversation_pipeline.py`. The only remaining warn-only signal should be the `logos/voice.py` module docstring (cleaned in Task 10) and any other cosmetic hits.

- [ ] **7.7 — Run daimonion tests.**

  ```bash
  uv run pytest tests/hapax_daimonion/ -q
  ```

  Expected: green. If the CPAL conversation path has a snapshot of the old short prompt, update it.

- [ ] **7.8 — Commit.**

  ```bash
  git add agents/hapax_daimonion/conversation_pipeline.py agents/hapax_daimonion/persona.py \
          tests/axioms/fixtures/anti_personification/known_offender_local_prompt.txt \
          tests/axioms/test_no_personification.py
  git commit -m "refactor(daimonion): Stage 3 — route LOCAL tier through compose_persona_prompt(compressed=True)

  _LOCAL_SYSTEM_PROMPT (lines 337-342) and the LOCAL fallback-bypass at
  lines 1006-1011 now emit the Phase 7 compressed architectural-state
  fragment instead of hand-written personification. Adds the compressed=True
  keyword to compose_persona_prompt. Linter now reports zero findings on
  both conversation_policy.py and conversation_pipeline.py.

  Refs #155"
  ```

---

## Task 8 — Stage 4 role registry `is_not:` fields + matching test

**Files:**
- `axioms/roles/registry.yaml` (modify: add `is_not:` to the 6 institutional + relational roles)
- `tests/axioms/test_role_registry.py` (extend)

**Outcome:** every institutional and relational role carries a non-empty `is_not:` list. Structural roles may omit (species-type, axiom-anchored). A new test asserts the invariant; drift regresses loudly.

### Steps

- [ ] **8.1 — Write the failing test first.**

  Append to `tests/axioms/test_role_registry.py`:

  ```python
  REQUIRES_IS_NOT = {"institutional", "relational"}


  class TestIsNotFields:
      def test_every_non_structural_role_has_is_not(self, registry):
          missing: list[str] = []
          for role in registry["roles"]:
              if role["layer"] in REQUIRES_IS_NOT:
                  if not role.get("is_not") or not isinstance(role["is_not"], list):
                      missing.append(role["id"])
                  elif len(role["is_not"]) == 0:
                      missing.append(role["id"])
          assert missing == [], (
              f"Institutional/relational roles MUST declare is_not: {missing}. "
              "See docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md §4."
          )

      def test_is_not_entries_are_kebab_case_strings(self, registry):
          for role in registry["roles"]:
              for entry in role.get("is_not", []) or []:
                  assert isinstance(entry, str)
                  assert entry == entry.lower()
                  assert " " not in entry
  ```

- [ ] **8.2 — Run, confirm failure.**

  ```bash
  uv run pytest tests/axioms/test_role_registry.py::TestIsNotFields -q
  ```

  Expected: failure listing 6 role IDs (the 4 institutional + 2 relational).

- [ ] **8.3 — Add `is_not:` to each non-structural role in `axioms/roles/registry.yaml`.**

  Edit each role block, placing `is_not:` between `answers_for:` and `amendment_gated:`.

  `executive-function-assistant`:

  ```yaml
      is_not:
        - emotional-support-partner
        - therapist
        - friend-in-the-ontological-sense
        - personality-to-bond-with
  ```

  `livestream-host`:

  ```yaml
      is_not:
        - personality-entertainer
        - character-performer
        - emotional-presence
        - parasocial-companion
  ```

  `research-participant`:

  ```yaml
      is_not:
        - research-assistant-to-the-investigator
        - subject-with-consent-that-can-be-withdrawn-mid-study
        - self-reporting-survey-respondent
  ```

  `household-inhabitant`:

  ```yaml
      is_not:
        - smart-home-assistant
        - surveillance-agent
        - household-member-with-standing
  ```

  `partner-in-conversation`:

  ```yaml
      is_not:
        - confidant
        - interlocutor-with-inner-life
        - relationship-maintainer
  ```

  `addressee-facing`:

  ```yaml
      is_not:
        - performer
        - persona-presenting-character
        - narrator-with-voice-of-its-own
  ```

  Rationale for each entry lives in the surrounding `description:` prose; the `is_not:` list is the declarative negation surface the research dossier §8.3 called for.

- [ ] **8.4 — Run the tests; confirm green.**

  ```bash
  uv run pytest tests/axioms/test_role_registry.py -q
  ```

  Expected: all tests pass.

- [ ] **8.5 — Run the full axioms test group to catch drift elsewhere.**

  ```bash
  uv run pytest tests/axioms/ -q
  ```

  Expected: green across persona-description, role-registry, and the new no-personification tests.

- [ ] **8.6 — Commit.**

  ```bash
  git add axioms/roles/registry.yaml tests/axioms/test_role_registry.py
  git commit -m "feat(axioms): Stage 4 — is_not: fields on institutional/relational roles

  Adds a declarative negation surface to every non-structural role per
  research dossier §8.3. Test enforces: institutional/relational roles
  MUST declare a non-empty is_not: list; structural roles may omit.
  Entries are kebab-case strings naming patterns the role explicitly
  rejects (e.g. livestream-host is_not personality-entertainer).

  Refs #155 #156"
  ```

---

## Task 9 — Phase 7 frozen-artifact regression pin

**Files:**
- `tests/axioms/test_no_personification.py` (extend)

**Outcome:** a regression test runs the linter against the three frozen persona artifacts and asserts zero findings. This pins the research §2 "Verdict: clean" claim; any drift in the canonical prose fails the test.

### Steps

- [ ] **9.1 — Add the regression test.**

  Append to `tests/axioms/test_no_personification.py`:

  ```python
  PHASE_7_FROZEN_ARTIFACTS = [
      Path("axioms/persona/hapax-description-of-being.md"),
      Path("axioms/persona/hapax-description-of-being.prompt.md"),
      Path("axioms/persona/posture-vocabulary.md"),
  ]


  @pytest.mark.parametrize("artifact", PHASE_7_FROZEN_ARTIFACTS, ids=lambda p: p.name)
  def test_phase_7_frozen_artifacts_are_clean(artifact):
      """Pin the research §2 'Verdict: clean' claim under the full deny-list + carve-outs.

      If this fails, either the prose drifted (fix the prose) or a carve-out
      regressed (fix the linter). Do NOT suppress by adding the artifact to
      the allowlist — these files are the axiom canon.
      """
      assert artifact.exists(), f"frozen artifact missing: {artifact}"
      findings = lint_path(artifact)
      assert findings == [], (
          f"{artifact.name} drift: {[(f.line, f.pattern_name, f.matched_text) for f in findings]}"
      )
  ```

- [ ] **9.2 — Run.**

  ```bash
  uv run pytest tests/axioms/test_no_personification.py::test_phase_7_frozen_artifacts_are_clean -q
  ```

  Expected: 3 passed. If `hapax-description-of-being.md` or `.prompt.md` trips a pattern, the allowlist's `context-window-handled` entry should have caught it via the rejection-block carve-out. If it did not, debug the rejection-window detection; do NOT add a file-level suppression.

- [ ] **9.3 — Commit.**

  ```bash
  git add tests/axioms/test_no_personification.py
  git commit -m "test(linter): Task 9 — pin Phase 7 frozen artifacts as zero-finding regression

  Parametrized test runs lint_path against hapax-description-of-being.md,
  .prompt.md, and posture-vocabulary.md; asserts zero findings under the
  full deny-list + allow-list. Any drift in the canonical prose fails
  loudly rather than being silently accepted.

  Refs #155"
  ```

---

## Task 10 — Stage 5 flip to fail-loud CI gate + logos/voice.py docstring cleanup

**Files:**
- `.pre-commit-config.yaml` (modify: `stages: [manual]` → `stages: [pre-commit]`)
- `scripts/check-anti-personification.py` (default mode flips to fail)
- `.github/workflows/ci.yml` (or the council's existing pytest workflow — add a step)
- `logos/voice.py` (module docstring cleanup)
- `tests/axioms/test_no_personification.py` (flip Stage-1 test class → `TestStage5FailLoud`)

**Outcome:** personification findings fail the pre-commit hook AND fail CI. The `logos/voice.py` docstring "warm copilot personality" is retired. Emergency escape remains via `HAPAX_ANTI_PERSONIFICATION_LINTER=0`.

### Steps

- [ ] **10.1 — Clean the `logos/voice.py` module docstring.**

  ```bash
  uv run grep -n "warm copilot\|personality" logos/voice.py | head -20
  ```

  Identify the offending lines (research §3 item 5 flags line 1). Replace the existing docstring's first paragraph with an architectural description:

  ```python
  """Voice subsystem entry points.

  Routes spoken-output requests from daimonion/CPAL to the TTS chain
  (Kokoro 82M on CPU) and optionally through the PipeWire voice-fx
  filter chain before the Studio 24c analog output. Pure wiring — no
  persona claims live here.
  """
  ```

  Re-run the linter against the file:

  ```bash
  uv run scripts/check-anti-personification.py --mode=fail logos/voice.py; echo "exit=$?"
  ```

  Expected: `exit=0`.

- [ ] **10.2 — Flip the CLI default mode.**

  In `scripts/check-anti-personification.py`, change the argparse default:

  ```python
  parser.add_argument("--mode", choices=["warn", "fail"], default="fail")
  ```

- [ ] **10.3 — Flip the pre-commit stage.**

  Edit `.pre-commit-config.yaml`:

  ```yaml
        - id: anti-personification
          name: Anti-personification linter
          entry: scripts/check-anti-personification.py --mode=fail --format=pre-commit
          language: system
          types_or: [markdown, python, yaml]
          stages: [pre-commit]
          pass_filenames: false
  ```

- [ ] **10.4 — Add a CI step.**

  Locate the existing CI workflow — likely `.github/workflows/ci.yml` or `.github/workflows/test.yml`. Add a step after the Python environment setup:

  ```yaml
        - name: Anti-personification linter
          run: uv run scripts/check-anti-personification.py --mode=fail --format=github
  ```

  This uses GitHub's `::error` annotation format so findings appear inline on the PR diff.

- [ ] **10.5 — Rename `TestStage1KnownOffenders` to `TestStage5FailLoud` and tighten assertions.**

  In `tests/axioms/test_no_personification.py`, the class that previously flipped its two methods (post-Task 6, Task 7) should now be named for the stage it pins:

  ```python
  class TestStage5FailLoud:
      """Post-Stage-3 refactor: both known-offender sites are clean.

      Any finding here means refactored code regressed. The fixtures are
      kept at the refactored prose; they are not meant to match current
      source byte-for-byte — they are a behavioral contract.
      """

      def test_operator_style_is_clean_after_stage2(self):
          text = (FIXTURES / "known_offender_operator_style.txt").read_text()
          assert lint_text(text, path="<refactored>") == []

      def test_local_prompt_is_clean_after_stage3(self):
          text = (FIXTURES / "known_offender_local_prompt.txt").read_text()
          assert lint_text(text, path="<refactored>") == []
  ```

- [ ] **10.6 — Full verification.**

  ```bash
  uv run pytest tests/axioms/ -q
  uv run scripts/check-anti-personification.py; echo "exit=$?"
  pre-commit run anti-personification --all-files; echo "exit=$?"
  ```

  All three must be green (`exit=0`). If the default-paths sweep finds anything unexpected, it is a regression — fix the prose, do NOT add an allowlist entry without operator sign-off.

- [ ] **10.7 — Commit.**

  ```bash
  git add .pre-commit-config.yaml scripts/check-anti-personification.py \
          .github/workflows/ci.yml logos/voice.py tests/axioms/test_no_personification.py
  git commit -m "feat(linter): Stage 5 — flip to fail-loud CI gate + logos/voice.py docstring cleanup

  Pre-commit hook promoted from stages: [manual] to stages: [pre-commit].
  CLI default --mode flips to fail. CI workflow gains a step emitting
  GitHub ::error annotations on findings. logos/voice.py module docstring
  loses 'warm copilot personality' in favor of a pure-wiring description.
  Stage-1 fixture test class renamed to TestStage5FailLoud.

  Emergency escape remains via HAPAX_ANTI_PERSONIFICATION_LINTER=0 with
  loud stderr banner.

  Refs #155"
  ```

---

## Task 11 — PR + merge

- [ ] **11.1 — Push the branch and open a PR.**

  ```bash
  git push -u origin feature/anti-personification-linter
  gh pr create --title "feat(axioms): anti-personification linter (CVS #155, 6-stage rollout)" --body "$(cat <<'EOF'
  ## Summary

  Static enforcement of the Phase 7 anti-personification mandate across persona
  artifacts, role registry, daimonion conversation modules, director prompts,
  and (future) overlay content. Ships as a 6-stage rollout per
  docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md.

  - Stage 1 (warn-only) — linter module + CLI + companion pytest.
  - Stage 2 — conversational_policy._OPERATOR_STYLE refactor; _CHILD_STYLE deleted.
  - Stage 3 — conversation_pipeline LOCAL tier routes through compose_persona_prompt(compressed=True).
  - Stage 4 — axioms/roles/registry.yaml gains is_not: fields on every institutional/relational role.
  - Stage 5 — pre-commit hook flipped to pre-commit stage; CI gate added; logos/voice.py docstring cleaned.
  - Stage 6 (deferred) — #126 Pango text repository must import this linter before implementation.

  ## Test plan

  - [x] uv run pytest tests/axioms/ -q — green
  - [x] uv run pytest tests/hapax_daimonion/ -q — green
  - [x] uv run scripts/check-anti-personification.py --mode=fail — exit 0
  - [x] pre-commit run anti-personification --all-files — exit 0
  - [x] pre-commit run --all-files — full sweep green
  - [x] Manual verification: daimonion voice output no longer carries "personality / dry wit / archetype" framing

  ## Governance

  Linter is additive over Phase 7 canon; no axiom amendment. Role registry
  is_not: additions shared with CVS #156 (role derivation methodology).
  EOF
  )"
  ```

- [ ] **11.2 — Monitor CI; merge when green.**

  Use `gh pr checks --watch` or `/ci-watch`. Fix any surfaced regressions via additional commits on the branch. When all checks pass, merge:

  ```bash
  gh pr merge --squash --delete-branch
  ```

- [ ] **11.3 — Open a follow-up tracking ticket for Stage 6.**

  ```bash
  gh issue create --title "[Stage 6] #126 Pango text repository must import anti-personification linter" \
    --body "Per docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md §4 Stage 6: when the #126 Pango text repository spec is authored, it MUST import shared.anti_personification_linter and gate pre-stream overlay rendering on it. Close this ticket when the text-repo spec lands with the import + CI gate wired."
  ```

---

## Self-review checklist (run before committing the plan as "complete")

- [ ] **Spec coverage — all 6 stages:**
  - Stage 1 (warn-only) — Tasks 1, 2, 3, 4, 5 ✓
  - Stage 2 (conversational_policy refactor) — Task 6 ✓
  - Stage 3 (conversation_pipeline LOCAL refactor) — Task 7 ✓
  - Stage 4 (role registry is_not:) — Task 8 ✓
  - Stage 5 (flip to fail-loud + logos/voice.py) — Task 10 ✓
  - Stage 6 (#126 overlay gate) — deferred, tracked via follow-up ticket in Task 11.3 ✓
- [ ] **Placeholder scan:** grep this file for `TODO`, `TBD`, `XXX`, `...`, `<fill>`, and ensure none appear inside code blocks that are supposed to be pasteable. (The `...` inside `compose_persona_prompt` body is intentional because the engineer's job is to preserve whatever is already there — the branch is the only new prose.)
- [ ] **Type consistency across tasks:**
  - `Finding` dataclass shape (`path: str, line: int, col: int, pattern_name: str, matched_text: str, rule_family: str`) is identical across Tasks 1, 2, 3, 4.
  - `lint_text(text: str, path: str) -> list[Finding]` signature is identical across all references.
  - `lint_path(path: Path) -> list[Finding]` signature is identical across Tasks 2, 3, 9.
  - CLI flag names (`--mode`, `--format`) match between Tasks 4 and 10.
  - `compose_persona_prompt(role_id: str | None = None, *, compressed: bool = False) -> str` signature referenced consistently in Task 7.
- [ ] **TDD boundary:** every implementation step (*.3, *.4) is preceded by a failing-test step. Every task ends with a commit step. No task commits two concerns in one commit.
- [ ] **Commit messages reference the spec + issue:** every commit includes `Refs #155` (Task 8 additionally `Refs #156`).
- [ ] **Frozen-artifact pin (Task 9) is pure regression — no implementation.** It pins the existing "Verdict: clean" claim from research §2. If it fails at any point, the carve-out is wrong, not the canon.

---

## Related

- Spec: `docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md`
- Research: `/tmp/cvs-research-155.md`
- Redesign authority: `docs/superpowers/specs/2026-04-16-lrr-phase-7-redesign-persona-posture-role.md`
- Companion tests: `tests/axioms/test_persona_description.py`, `tests/studio_compositor/test_posture_vocabulary_hygiene.py`, `tests/axioms/test_role_registry.py`
- Shared CVS: #156 (role derivation methodology) — shares `is_not:` work with Task 8
- Blocks: #126 Pango text repository spec — Stage 6 obligation
