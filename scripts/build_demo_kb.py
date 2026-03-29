"""Build the demo knowledge base from all high-value source material.

Reads ~120K tokens of source files, extracts key claims/citations/insights,
tags by audience relevance, writes a structured YAML file that the demo
pipeline's research gatherer consumes.

Usage: uv run python scripts/build_demo_kb.py
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONSTITUTION_ROOT = PROJECT_ROOT.parent / "hapax-constitution"
OUTPUT_PATH = PROJECT_ROOT / "profiles" / "demo-knowledge-base.yaml"

# ── Source registry ──────────────────────────────────────────────────────

SOURCES: list[dict] = [
    # P0 — Voice & Grounding Research (extract claims via heuristics)
    {
        "path": "agents/hapax_daimonion/proofs/RESEARCH-STATE.md",
        "theme": "voice_grounding",
        "priority": 0,
    },
    {
        "path": "agents/hapax_daimonion/proofs/THEORETICAL-FOUNDATIONS.md",
        "theme": "voice_grounding",
        "priority": 0,
    },
    {
        "path": "agents/hapax_daimonion/proofs/POSITION.md",
        "theme": "voice_grounding",
        "priority": 0,
    },
    {
        "path": "agents/hapax_daimonion/proofs/CYCLE-2-PREREGISTRATION.md",
        "theme": "voice_grounding",
        "priority": 0,
    },
    {
        "path": "agents/hapax_daimonion/proofs/WHY-NO-ONE-IMPLEMENTED-CLARK.md",
        "theme": "voice_grounding",
        "priority": 0,
    },
    {
        "path": "agents/hapax_daimonion/proofs/REFINEMENT-RESEARCH.md",
        "theme": "voice_grounding",
        "priority": 0,
    },
    {
        "path": "agents/hapax_daimonion/proofs/CYCLE-1-PILOT-REPORT.md",
        "theme": "voice_grounding",
        "priority": 0,
    },
    {
        "path": "agents/hapax_daimonion/proofs/BASELINE-ANALYSIS.md",
        "theme": "voice_grounding",
        "priority": 0,
    },
    # P0 — Axiom Governance
    {
        "path": "../hapax-constitution/axioms/registry.yaml",
        "theme": "governance",
        "priority": 0,
        "root": CONSTITUTION_ROOT,
    },
    {
        "path": "../hapax-constitution/axioms/implications/single-user.yaml",
        "theme": "governance",
        "priority": 0,
        "root": CONSTITUTION_ROOT,
    },
    {
        "path": "../hapax-constitution/axioms/implications/executive-function.yaml",
        "theme": "governance",
        "priority": 0,
        "root": CONSTITUTION_ROOT,
    },
    {
        "path": "../hapax-constitution/axioms/implications/management-governance.yaml",
        "theme": "governance",
        "priority": 0,
        "root": CONSTITUTION_ROOT,
    },
    {
        "path": "../hapax-constitution/axioms/implications/corporate-boundary.yaml",
        "theme": "governance",
        "priority": 0,
        "root": CONSTITUTION_ROOT,
    },
    # P0 — Logos UI/UX Reference (extractive, large budget — already narration-quality prose)
    {"path": "docs/logos-ui-reference.md", "theme": "logos_ui", "priority": 1, "max_words": 2000},
    # P0 — Architecture & Stimmung
    {"path": "shared/stimmung.py", "theme": "architecture", "priority": 0},
    {"path": "shared/governance/consent.py", "theme": "governance", "priority": 0},
    {"path": "shared/dimensions.py", "theme": "architecture", "priority": 0},
    {"path": "CLAUDE.md", "theme": "architecture", "priority": 0},
    # P1 — Voice Implementation
    {
        "path": "agents/hapax_daimonion/conversational_policy.py",
        "theme": "voice_implementation",
        "priority": 1,
    },
    {
        "path": "agents/hapax_daimonion/grounding_ledger.py",
        "theme": "voice_implementation",
        "priority": 1,
    },
    {"path": "agents/hapax_daimonion/persona.py", "theme": "voice_implementation", "priority": 1},
    # P1 — Domain Corpus
    {
        "path": "agents/demo_pipeline/domain_corpus/autonomous-agent-architectures.md",
        "theme": "domain",
        "priority": 1,
    },
    {
        "path": "agents/demo_pipeline/domain_corpus/cognitive-load-theory.md",
        "theme": "domain",
        "priority": 1,
    },
    {
        "path": "agents/demo_pipeline/domain_corpus/executive-function-accommodation.md",
        "theme": "domain",
        "priority": 1,
    },
    {
        "path": "agents/demo_pipeline/domain_corpus/llm-interaction-design.md",
        "theme": "domain",
        "priority": 1,
    },
    {
        "path": "agents/demo_pipeline/domain_corpus/neurodivergent-technology-design.md",
        "theme": "domain",
        "priority": 1,
    },
    {
        "path": "agents/demo_pipeline/domain_corpus/personal-knowledge-management.md",
        "theme": "domain",
        "priority": 1,
    },
    # P1 — System & Visual Docs
    {"path": "research/THEORY-MAP.md", "theme": "research", "priority": 1},
    {"path": "research/RESEARCH-INDEX.md", "theme": "research", "priority": 1, "max_words": 1000},
    {"path": "docs/visual-layer-research.md", "theme": "logos_ui", "priority": 1},
    {"path": "docs/multi-camera-operator-sensing-research.md", "theme": "logos_ui", "priority": 1},
    # P2 — Lab Journal
    {"path": "lab-journal/observations.md", "theme": "lab_journal", "priority": 2},
    {"path": "lab-journal/index.md", "theme": "lab_journal", "priority": 2},
]

# ── Audience relevance heuristics ────────────────────────────────────────

KEYWORD_RELEVANCE: dict[str, dict[str, float]] = {
    "consent": {"family": 0.95, "technical-peer": 0.6, "leadership": 0.7, "team-member": 0.5},
    "ethics": {"family": 0.95, "technical-peer": 0.5, "leadership": 0.7, "team-member": 0.4},
    "axiom": {"family": 0.9, "technical-peer": 0.7, "leadership": 0.8, "team-member": 0.5},
    "clark": {"family": 0.8, "technical-peer": 0.9, "leadership": 0.7, "team-member": 0.4},
    "brennan": {"family": 0.8, "technical-peer": 0.9, "leadership": 0.7, "team-member": 0.4},
    "grounding": {"family": 0.8, "technical-peer": 0.95, "leadership": 0.7, "team-member": 0.4},
    "rlhf": {"family": 0.7, "technical-peer": 0.95, "leadership": 0.6, "team-member": 0.3},
    "stimmung": {"family": 0.7, "technical-peer": 0.9, "leadership": 0.6, "team-member": 0.4},
    "perception": {"family": 0.8, "technical-peer": 0.8, "leadership": 0.6, "team-member": 0.5},
    "husserl": {"family": 0.7, "technical-peer": 0.7, "leadership": 0.5, "team-member": 0.3},
    "heidegger": {"family": 0.7, "technical-peer": 0.7, "leadership": 0.5, "team-member": 0.3},
    "executive function": {
        "family": 0.95,
        "technical-peer": 0.6,
        "leadership": 0.7,
        "team-member": 0.6,
    },
    "sced": {"family": 0.5, "technical-peer": 0.9, "leadership": 0.6, "team-member": 0.3},
    "bayesian": {"family": 0.4, "technical-peer": 0.9, "leadership": 0.5, "team-member": 0.2},
    "architecture": {"family": 0.4, "technical-peer": 0.95, "leadership": 0.8, "team-member": 0.5},
    "container": {"family": 0.1, "technical-peer": 0.9, "leadership": 0.7, "team-member": 0.3},
    "agent": {"family": 0.6, "technical-peer": 0.8, "leadership": 0.7, "team-member": 0.7},
    "management": {"family": 0.5, "technical-peer": 0.4, "leadership": 0.8, "team-member": 0.9},
    "accommodation": {"family": 0.8, "technical-peer": 0.5, "leadership": 0.6, "team-member": 0.6},
    "profile": {"family": 0.6, "technical-peer": 0.7, "leadership": 0.5, "team-member": 0.6},
}

THEME_BASE_RELEVANCE: dict[str, dict[str, float]] = {
    "logos_ui": {"family": 0.95, "technical-peer": 0.9, "leadership": 0.8, "team-member": 0.7},
    "voice_grounding": {
        "family": 0.7,
        "technical-peer": 0.9,
        "leadership": 0.6,
        "team-member": 0.4,
    },
    "governance": {"family": 0.9, "technical-peer": 0.7, "leadership": 0.8, "team-member": 0.5},
    "architecture": {"family": 0.4, "technical-peer": 0.9, "leadership": 0.8, "team-member": 0.5},
    "voice_implementation": {
        "family": 0.3,
        "technical-peer": 0.9,
        "leadership": 0.5,
        "team-member": 0.3,
    },
    "domain": {"family": 0.6, "technical-peer": 0.6, "leadership": 0.5, "team-member": 0.5},
    "research": {"family": 0.5, "technical-peer": 0.8, "leadership": 0.5, "team-member": 0.3},
    "lab_journal": {"family": 0.4, "technical-peer": 0.7, "leadership": 0.4, "team-member": 0.3},
}


def _compute_relevance(text: str, theme: str) -> dict[str, float]:
    """Compute audience relevance scores from content keywords + theme baseline."""
    text_lower = text.lower()
    scores = dict(
        THEME_BASE_RELEVANCE.get(
            theme, {"family": 0.5, "technical-peer": 0.5, "leadership": 0.5, "team-member": 0.5}
        )
    )

    for keyword, relevance in KEYWORD_RELEVANCE.items():
        if keyword in text_lower:
            for audience, score in relevance.items():
                scores[audience] = max(scores.get(audience, 0), score)

    # Clamp to [0, 1]
    return {k: min(1.0, round(v, 2)) for k, v in scores.items()}


# ── Extraction functions ────────────────────────────────────────────────


def _extract_p0(text: str, filename: str) -> dict:
    """P0: Extract key claims, citations, and insights from high-value docs."""
    claims: list[str] = []
    citations: list[str] = []

    # Extract bullet points and numbered lists (often contain key claims)
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            claim = stripped.lstrip("-*0123456789. ").strip()
            if 20 < len(claim) < 300 and not claim.startswith("|"):
                claims.append(claim)

    # Extract citations (Author Year, Author et al. Year)
    cite_pattern = re.compile(
        r"(?:[A-Z][a-z]+(?:\s+(?:&|and)\s+[A-Z][a-z]+)?(?:\s+et\s+al\.?)?,?\s*(?:19|20)\d{2}[a-z]?)"
    )
    for match in cite_pattern.finditer(text):
        cite = match.group(0).strip().rstrip(",")
        if cite not in citations and len(cite) > 8:
            citations.append(cite)

    # Extract key insights (lines after ## headers, bold text)
    key_insights: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("**") and stripped.endswith("**") and 20 < len(stripped) < 200:
            key_insights.append(stripped.strip("*").strip())

    # Cap to most important items
    return {
        "source": filename,
        "claims": claims[:15],
        "citations": list(dict.fromkeys(citations))[:10],
        "key_insights": key_insights[:5],
    }


def _extract_p1(text: str, filename: str, max_words: int = 400) -> dict:
    """P1: Extractive summary — first N words + section headers."""
    words = text.split()
    summary = " ".join(words[:max_words])

    # Also grab any section headers for structure
    headers = [
        line.strip().lstrip("#").strip()
        for line in text.split("\n")
        if line.strip().startswith("#") and len(line.strip()) > 3
    ]

    return {
        "source": filename,
        "summary": summary,
        "sections": headers[:10],
    }


def _extract_p2(text: str, filename: str) -> dict:
    """P2: Metadata only — filename + first meaningful line."""
    first_line = ""
    for line in text.split("\n"):
        stripped = line.strip().lstrip("#").strip()
        if stripped and not stripped.startswith("---") and len(stripped) > 10:
            first_line = stripped[:200]
            break

    return {
        "source": filename,
        "description": first_line,
    }


# ── Agent manifest scanner ──────────────────────────────────────────────


def _scan_manifests() -> dict:
    """Extract agent names and purposes from all manifests."""
    manifest_dir = PROJECT_ROOT / "agents" / "manifests"
    agents: list[dict[str, str]] = []

    for path in sorted(manifest_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
            if isinstance(data, dict):
                agents.append(
                    {
                        "name": data.get("name", path.stem),
                        "purpose": (data.get("purpose") or "")[:150],
                        "category": data.get("category", ""),
                    }
                )
        except Exception:
            pass

    return {
        "source": "agents/manifests/*.yaml",
        "agent_count": len(agents),
        "agents": agents,
    }


# ── Main builder ────────────────────────────────────────────────────────


def build() -> None:
    themes: dict[str, dict] = {}
    source_count = 0

    for source_def in SOURCES:
        rel_path = source_def["path"]
        theme = source_def["theme"]
        priority = source_def["priority"]
        root = source_def.get("root", PROJECT_ROOT)

        # Resolve path
        if rel_path.startswith("../"):
            full_path = (PROJECT_ROOT / rel_path).resolve()
        else:
            full_path = root / Path(rel_path)

        if not full_path.exists():
            print(f"  SKIP (missing): {rel_path}")
            continue

        text = full_path.read_text()
        source_count += 1

        # Extract based on priority
        if priority == 0:
            entry = _extract_p0(text, rel_path)
        elif priority == 1:
            max_words = source_def.get("max_words", 400)
            entry = _extract_p1(text, rel_path, max_words=max_words)
        else:
            entry = _extract_p2(text, rel_path)

        # Compute audience relevance
        relevance = _compute_relevance(text, theme)

        # Add to theme
        if theme not in themes:
            themes[theme] = {
                "audience_relevance": relevance,
                "entries": [],
            }
        else:
            # Merge relevance (max per audience)
            for audience, score in relevance.items():
                themes[theme]["audience_relevance"][audience] = max(
                    themes[theme]["audience_relevance"].get(audience, 0), score
                )

        themes[theme]["entries"].append(entry)
        print(f"  {priority} {rel_path} → {theme} ({len(text)} chars)")

    # Add agent manifests as P2
    manifest_data = _scan_manifests()
    themes["agents"] = {
        "audience_relevance": {
            "family": 0.6,
            "technical-peer": 0.8,
            "leadership": 0.7,
            "team-member": 0.7,
        },
        "entries": [manifest_data],
    }
    source_count += 1
    print(f"  2 agents/manifests/*.yaml → agents ({manifest_data['agent_count']} agents)")

    # Build output
    kb = {
        "generated": datetime.now(UTC).isoformat(),
        "source_count": source_count,
        "themes": themes,
    }

    OUTPUT_PATH.write_text(
        yaml.dump(kb, default_flow_style=False, sort_keys=False, width=120, allow_unicode=True)
    )
    print(f"\nKnowledge base written: {OUTPUT_PATH}")
    print(f"  Sources: {source_count}")
    print(f"  Themes: {list(themes.keys())}")

    # Size check
    kb_text = OUTPUT_PATH.read_text()
    tokens = len(kb_text) // 4
    print(f"  Size: {len(kb_text)} chars (~{tokens} tokens)")


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    print("Building demo knowledge base...\n")
    build()
