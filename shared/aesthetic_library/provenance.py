"""Provenance records per asset group.

Each asset group directory (bitchx/, fonts/, enlightenment/themes/<name>/) carries
a `provenance.yaml` capturing source URL, upstream commit, extraction date,
original author, SPDX license, and the canonical attribution line rendered on
credit surfaces.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class Provenance(BaseModel):
    source: str
    source_url: str
    source_commit: str = ""
    extracted_date: str
    original_author: str
    license: str
    license_text_path: str = ""
    attribution_line: str = Field(default="")
    notes: str = ""

    @field_validator("extracted_date", mode="before")
    @classmethod
    def _coerce_date_to_string(cls, v: Any) -> str:
        if isinstance(v, (date, datetime)):
            return v.isoformat()[:10]
        return v

    @classmethod
    def load(cls, path: Path) -> Provenance:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(raw)
