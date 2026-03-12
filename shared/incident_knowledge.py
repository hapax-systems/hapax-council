"""Incident knowledge base — structured (failure, fix, outcome) patterns.

Initial storage: YAML file. Migrate to Qdrant if > 500 patterns.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class FailureSignature(BaseModel):
    check: str
    status: str
    message_pattern: str  # regex pattern


class RootCause(BaseModel):
    description: str
    frequency: int = 0


class FixRecord(BaseModel):
    action: str
    params: dict[str, str] = Field(default_factory=dict)
    success_rate: float = 0.0
    last_verified: str = ""
    times_used: int = 0
    times_succeeded: int = 0

    def update_outcome(self, *, success: bool) -> None:
        """Update success rate after a fix attempt."""
        self.times_used += 1
        if success:
            self.times_succeeded += 1
        self.success_rate = self.times_succeeded / max(self.times_used, 1)


class IncidentPattern(BaseModel):
    id: str
    failure_signature: FailureSignature
    root_causes: list[RootCause] = Field(default_factory=list)
    fixes: list[FixRecord] = Field(default_factory=list)
    related_commits: list[str] = Field(default_factory=list)
    last_occurrence: str = ""
    total_occurrences: int = 0

    def best_fix(self) -> FixRecord | None:
        """Return the fix with highest success rate, or None."""
        if not self.fixes:
            return None
        return max(self.fixes, key=lambda f: (f.success_rate, f.times_used))


class IncidentKnowledgeBase(BaseModel):
    version: int = 1
    last_updated: str = ""
    patterns: list[IncidentPattern] = Field(default_factory=list)

    def find_matching(
        self, check: str, status: str, message: str
    ) -> list[IncidentPattern]:
        """Find patterns whose failure_signature matches the given check failure."""
        matches = []
        for pattern in self.patterns:
            sig = pattern.failure_signature
            if sig.check != check or sig.status != status:
                continue
            try:
                if re.search(sig.message_pattern, message):
                    matches.append(pattern)
            except re.error:
                continue
        return matches

    def get_pattern(self, pattern_id: str) -> IncidentPattern | None:
        """Look up a pattern by ID."""
        for p in self.patterns:
            if p.id == pattern_id:
                return p
        return None

    def best_fix_for(self, check: str, status: str, message: str) -> FixRecord | None:
        """Find the best fix for a failure, across all matching patterns."""
        matches = self.find_matching(check, status, message)
        best = None
        best_score = -1.0
        for pattern in matches:
            fix = pattern.best_fix()
            if fix and fix.success_rate > best_score:
                best = fix
                best_score = fix.success_rate
        return best


DEFAULT_KB_PATH = Path.home() / ".cache" / "hapax-council" / "incident-knowledge.yaml"


def load_knowledge_base(path: Path = DEFAULT_KB_PATH) -> IncidentKnowledgeBase:
    """Load the incident knowledge base from YAML."""
    if not path.exists():
        return IncidentKnowledgeBase()
    try:
        data = yaml.safe_load(path.read_text())
        return IncidentKnowledgeBase.model_validate(data)
    except Exception:
        return IncidentKnowledgeBase()


def save_knowledge_base(
    kb: IncidentKnowledgeBase, path: Path = DEFAULT_KB_PATH
) -> None:
    """Save the knowledge base to YAML atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.dump(kb.model_dump(), default_flow_style=False, sort_keys=False))
    tmp.rename(path)
