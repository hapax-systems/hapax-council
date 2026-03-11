"""Pydantic models for the dev-story data layer."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Session(BaseModel):
    id: str
    project_path: str
    project_name: str
    started_at: str
    ended_at: str | None = None
    git_branch: str | None = None
    message_count: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_estimate: float = 0.0
    model_primary: str | None = None


class Message(BaseModel):
    id: str
    session_id: str
    role: str  # user | assistant
    timestamp: str
    content_text: str
    parent_id: str | None = None
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0


class ToolCall(BaseModel):
    message_id: str
    tool_name: str
    sequence_position: int
    arguments_summary: str | None = None
    duration_ms: int | None = None
    success: bool = True


class FileChange(BaseModel):
    message_id: str
    file_path: str
    version: int
    change_type: str  # created | modified | deleted
    timestamp: str


class Commit(BaseModel):
    hash: str
    author_date: str
    message: str
    branch: str | None = None
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0


class CommitFile(BaseModel):
    commit_hash: str
    file_path: str
    operation: str  # A | M | D


class Correlation(BaseModel):
    message_id: str
    commit_hash: str
    confidence: float = Field(ge=0.0, le=1.0)
    method: str  # timestamp_window | file_match | file_and_timestamp | content_match


class SessionMetrics(BaseModel):
    session_id: str
    tool_call_count: int = 0
    tool_diversity: int = 0
    edit_count: int = 0
    bash_count: int = 0
    agent_dispatch_count: int = 0
    avg_response_time_ms: float = 0.0
    user_steering_ratio: float = 0.0
    phase_sequence: str | None = None


class SessionTag(BaseModel):
    session_id: str
    dimension: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class CriticalMoment(BaseModel):
    moment_type: str  # churn | wrong_path | cascade | efficient | unblocking
    severity: float = Field(ge=0.0, le=1.0)
    session_id: str
    description: str
    message_id: str | None = None
    commit_hash: str | None = None
    evidence: str | None = None  # JSON string


class HotspotEntry(BaseModel):
    file_path: str
    change_frequency: int
    session_count: int
    churn_rate: float


class CodeSurvivalEntry(BaseModel):
    file_path: str
    introduced_by_commit: str
    survived_days: float
    introduced_by_session: str | None = None
    replacement_commit: str | None = None
