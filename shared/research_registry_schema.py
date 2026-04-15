"""Pydantic schema for LRR Phase 1 research registry condition files.

Type-safe validation layer on top of the existing
``scripts/research-registry.py`` CLI. The CLI owns the write path + file
lifecycle; this module owns structural validation + load-time type
checking so downstream consumers (daimonion, compositor, audit drops)
can import ``ResearchCondition`` and trust the fields without
dict-based `.get()` sprawl.

The schema mirrors the on-disk YAML structure at
``~/hapax-state/research-registry/<condition_id>/condition.yaml`` as
written by the CLI's ``cmd_init``/``cmd_open`` + the PR #792 bundle 2
§4 schema additions (parent/sibling/collection timestamps).

Part of LRR Phase 1 item 1 per
``docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md``
§3.1. Delta's pre-staging spec (commit ``8a2c42bcf``) asked for a
separate importable pydantic module; PRs #791/#792/#804 built the CLI
side but inlined the schema as dict-based YAML parsing. This module
fills the library-split gap so callers can ``from
shared.research_registry_schema import ResearchCondition`` and pattern-
match against the validated model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Matches the CLI's ``cond-<slug>-<NNN>`` generator where slug is
# lowercase kebab-case and NNN is zero-padded to 3 digits.
CONDITION_ID_PATTERN = r"^cond-[a-z0-9][a-z0-9-]*-\d{3}$"


class SubstrateInfo(BaseModel):
    """LLM substrate that produced reactions under this condition.

    Immutable after condition open — a substrate change opens a new
    condition (per LRR epic axiom I-1: append-only research conditions).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(..., min_length=1)
    backend: str = Field(..., min_length=1)
    route: str = Field(..., min_length=1)


class DirectiveEntry(BaseModel):
    """One frozen directives-manifest entry.

    The CLI records the `sha256` of each listed file at condition open
    time so readers can detect tampering with the directive bodies.
    Empty list is allowed — the initial condition ships with an empty
    manifest per the `grounding_directives.py` gap noted in the live
    condition.yaml's inline comment.
    """

    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1)
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class PreRegistrationInfo(BaseModel):
    """OSF pre-registration metadata.

    `filed: false` is the open state. Once filed, `url` and `filed_at`
    must be set; the CLI's ``cmd_open`` refuses to set `filed: true`
    without both.
    """

    model_config = ConfigDict(extra="forbid")

    filed: bool = False
    url: str | None = None
    filed_at: datetime | None = None


class ResearchCondition(BaseModel):
    """One research registry condition.

    Matches the on-disk YAML structure at
    ``~/hapax-state/research-registry/<condition_id>/condition.yaml``.

    Append-only semantics (enforced at write-time by the CLI, not this
    schema): `opened_at`, `substrate`, `frozen_files`, `claim_id`,
    `directives_manifest`, `parent_condition_id` are write-once at
    condition open. `closed_at`, `osf_project_id`, `pre_registration`,
    `notes`, `sibling_condition_ids`, `collection_started_at`,
    `collection_halt_at` are mutable via the CLI's ``cmd_close`` +
    sibling/registry-mutation subcommands. This pydantic schema
    validates structure and types on load; it does NOT enforce the
    append-only mutations (that's the CLI's job via flock + atomic
    writes).
    """

    model_config = ConfigDict(extra="forbid")

    condition_id: str = Field(..., pattern=CONDITION_ID_PATTERN)
    claim_id: str = Field(..., min_length=1)
    opened_at: datetime
    closed_at: datetime | None = None
    substrate: SubstrateInfo
    frozen_files: list[str] = Field(default_factory=list)
    directives_manifest: list[DirectiveEntry] = Field(default_factory=list)

    # PR #792 bundle 2 §4 schema additions
    parent_condition_id: str | None = None
    sibling_condition_ids: list[str] = Field(default_factory=list)
    collection_started_at: datetime | None = None
    collection_halt_at: datetime | None = None

    osf_project_id: str | None = None
    pre_registration: PreRegistrationInfo = Field(default_factory=PreRegistrationInfo)
    notes: str = ""

    @field_validator("parent_condition_id")
    @classmethod
    def _parent_id_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        import re

        if not re.match(CONDITION_ID_PATTERN, v):
            raise ValueError(
                f"parent_condition_id {v!r} does not match required pattern {CONDITION_ID_PATTERN}"
            )
        return v

    @field_validator("sibling_condition_ids")
    @classmethod
    def _sibling_ids_format(cls, v: list[str]) -> list[str]:
        import re

        for sibling in v:
            if not re.match(CONDITION_ID_PATTERN, sibling):
                raise ValueError(
                    f"sibling_condition_id {sibling!r} does not match required "
                    f"pattern {CONDITION_ID_PATTERN}"
                )
        return v

    @classmethod
    def from_yaml(cls, yaml_text: str) -> ResearchCondition:
        """Parse a YAML string into a validated ResearchCondition.

        Raises :class:`pydantic.ValidationError` on structural drift,
        malformed datetimes, missing required fields, or unknown keys
        (``extra="forbid"`` is enforced on every nested model).
        """
        import yaml

        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            raise ValueError(f"condition YAML root must be a mapping, got {type(data).__name__}")
        return cls.model_validate(data)

    def to_yaml(self) -> str:
        """Serialize to YAML using ``yaml.safe_dump``.

        Datetimes are serialized as ISO 8601 strings; ``None`` values
        are preserved; nested models are flattened to plain dicts via
        ``model_dump()``. The output is parseable by
        :meth:`from_yaml` round-trip.
        """
        import yaml

        data: dict[str, Any] = self.model_dump(mode="json")
        return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
