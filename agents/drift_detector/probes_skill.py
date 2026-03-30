"""Skill health sufficiency probes."""

from __future__ import annotations

import ast
import re

from .config import CLAUDE_CONFIG_DIR
from .sufficiency_probes import SufficiencyProbe

_KNOWN_SYNC_METHODS = {"get_pending_review", "promote", "reject", "search"}


def _check_skill_syntax() -> tuple[bool, str]:
    """Check that Claude Code skill definitions are syntactically valid."""
    skills_dir = CLAUDE_CONFIG_DIR / "skills"
    if not skills_dir.exists():
        return False, "skills directory not found"

    checked = 0
    problems: list[str] = []

    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md" if skill_dir.is_dir() else None
        if skill_file is None or not skill_file.exists():
            continue

        checked += 1
        content = skill_file.read_text()

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                import yaml

                try:
                    fm = yaml.safe_load(parts[1])
                    if not fm or not fm.get("name") or not fm.get("description"):
                        problems.append(
                            f"{skill_dir.name}: missing name or description in frontmatter"
                        )
                        continue
                except yaml.YAMLError as e:
                    problems.append(f"{skill_dir.name}: invalid YAML frontmatter: {e}")
                    continue
            else:
                problems.append(f"{skill_dir.name}: malformed frontmatter")
                continue

        for m in re.finditer(r'python -c\s+"((?:[^"\\]|\\.)*)"', content):
            snippet = m.group(1).replace('\\"', '"')
            try:
                tree = ast.parse(snippet)
            except SyntaxError as e:
                problems.append(f"{skill_dir.name}: Python syntax error: {e}")
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
                    func = node.value.func
                    if isinstance(func, ast.Attribute) and func.attr in _KNOWN_SYNC_METHODS:
                        problems.append(f"{skill_dir.name}: await on sync method .{func.attr}()")

    if checked == 0:
        return False, "no skill definitions found"

    if not problems:
        return True, f"all {checked} skill definitions are syntactically valid"
    return False, f"{len(problems)} issue(s): {'; '.join(problems[:3])}"


SKILL_PROBES: list[SufficiencyProbe] = [
    SufficiencyProbe(
        id="probe-skill-health-001",
        axiom_id="executive_function",
        implication_id="ex-skill-health-001",
        level="subsystem",
        question="Are all Claude Code skill definitions syntactically valid?",
        check=_check_skill_syntax,
    ),
]
