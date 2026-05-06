"""HARDM anti-anthropomorphization lint for layout configs.

Per `project_hardm_anti_anthropomorphization`: HARDM refuses face-iconography.
No eyes/mouths/expressions/avatars. Raw signal-density on a grid.

This test extends the anti-personification linter's scope from GEAL-only
(``test_geal_anti_personification.py``) to the compositor layout configs
(``config/compositor-layouts/*.json``). Layout surface names, descriptions,
and metadata must not reference face-iconography or anthropomorphic elements
as visual-surface content (consent-gate detection context is excluded).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAYOUTS_DIR = REPO_ROOT / "config" / "compositor-layouts"

FACE_ICONOGRAPHY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("avatar", re.compile(r"\bavatar(s)?\b", re.IGNORECASE)),
    ("emoji", re.compile(r"\bemoji(s)?\b", re.IGNORECASE)),
    ("selfie", re.compile(r"\bselfie(s)?\b", re.IGNORECASE)),
    ("portrait-mode", re.compile(r"\bportrait[\s_-]?mode\b", re.IGNORECASE)),
    ("face-cam", re.compile(r"\bface[\s_-]?cam\b", re.IGNORECASE)),
    ("webcam-selfie", re.compile(r"\bwebcam[\s_-]?selfie\b", re.IGNORECASE)),
    ("profile-pic", re.compile(r"\bprofile[\s_-]?pic(ture)?\b", re.IGNORECASE)),
)

# Strings allowed in detection/consent context (not iconography).
CONSENT_CONTEXT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "face was detected",
        "face_detected",
        "face detection",
        "face-obscure",
        "face_obscure",
        "InsightFace",
        "SCRFD",
    }
)


def _is_consent_context(line: str) -> bool:
    return any(ctx in line for ctx in CONSENT_CONTEXT_ALLOWLIST)


class TestLayoutHardmLint:
    def test_no_face_iconography_in_layout_configs(self) -> None:
        violations: list[tuple[str, str, str]] = []
        for path in sorted(LAYOUTS_DIR.glob("*.json")):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if _is_consent_context(line):
                    continue
                for label, pat in FACE_ICONOGRAPHY_PATTERNS:
                    if pat.search(line):
                        violations.append((path.name, f"line {lineno}", label))
        if violations:
            lines = ["HARDM face-iconography violations in layout configs:"]
            for name, loc, label in violations:
                lines.append(f"  {name}:{loc} pattern={label}")
            lines.append("")
            lines.append(
                "Per project_hardm_anti_anthropomorphization: layout surfaces "
                "must not reference face-iconography or anthropomorphic visual "
                "content. Use structural/geometric/signal-density names instead."
            )
            import pytest

            pytest.fail("\n".join(lines))

    def test_layout_configs_exist(self) -> None:
        layouts = list(LAYOUTS_DIR.glob("*.json"))
        assert len(layouts) > 0, "No layout configs found — test scope is empty"
