"""The existing immutable reference primitive, independent of admission machinery."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContentAddress(BaseModel):
    """An exact external object reference and its content hash."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    ref: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("wire strings must be nonblank without edge whitespace")
        value.encode("utf-8", errors="strict")
        return value
