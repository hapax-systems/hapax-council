from pydantic import BaseModel, ConfigDict


class RecentImpingementEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: str
    value: float
    family: str


class RecentImpingements(BaseModel):
    model_config = ConfigDict(frozen=True)
    generated_at: float
    entries: list[RecentImpingementEntry]


class ChatSignalsSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    generated_at: float
    t5_rate_per_min: float = 0.0
    t6_rate_per_min: float = 0.0
    unique_t4_plus_authors_60s: int = 0
    t4_plus_rate_per_min: float = 0.0
    message_count_60s: int = 0
    unique_authors_60s: int = 0
    message_rate_per_min: float = 0.0
    audience_engagement: float = 0.0


class ChatState(BaseModel):
    model_config = ConfigDict(frozen=True)
    generated_at: float
    total_messages: int
    unique_authors: int
