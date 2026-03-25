"""Typed configuration for hapax-council.

All 30+ council env vars validated at import time via pydantic-settings.
Feature-gated: set HAPAX_USE_SETTINGS=1 to activate in config.py.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LiteLLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LITELLM_")

    base_url: str = Field(
        default="http://localhost:4000",
        validation_alias=AliasChoices("LITELLM_API_BASE", "LITELLM_BASE_URL"),
    )
    api_key: SecretStr = SecretStr("")


class QdrantSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QDRANT_")

    url: str = "http://localhost:6333"


class OllamaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OLLAMA_")

    host: str = "http://localhost:11434"


class LangfuseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LANGFUSE_")

    host: str = "http://localhost:3000"
    public_key: SecretStr = SecretStr("")
    secret_key: SecretStr = SecretStr("")


class NtfySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NTFY_")

    base_url: str = "http://localhost:8090"
    topic: str = "cockpit"
    dedup_cooldown_s: int = Field(default=3600, ge=0)


class EngineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENGINE_")

    debounce_ms: int = Field(default=1500, ge=50, le=10000)
    gpu_concurrency: int = Field(default=1, ge=1, le=8)
    cloud_concurrency: int = Field(default=2, ge=1, le=16)
    action_timeout_s: float = Field(default=120.0, ge=1.0)
    quiet_window_s: float = Field(default=180.0, ge=0.0)
    cooldown_s: float = Field(default=600.0, ge=0.0)


class PathSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HAPAX_")

    home: str = ""
    work_vault_path: str = "~/Documents/Work"
    personal_vault_path: str = "~/Documents/Personal"


class LogSettings(BaseSettings):
    model_config = SettingsConfigDict()

    log_level: str = Field(
        default="INFO",
        validation_alias="LOG_LEVEL",
    )
    hapax_log_human: bool = Field(
        default=False,
        validation_alias="HAPAX_LOG_HUMAN",
    )
    hapax_service: str = Field(
        default="hapax-council",
        validation_alias="HAPAX_SERVICE",
    )


class GovernanceSettings(BaseSettings):
    model_config = SettingsConfigDict()

    enforce_block: bool = Field(
        default=False,
        validation_alias="AXIOM_ENFORCE_BLOCK",
    )


class CouncilSettings(BaseSettings):
    """Top-level council configuration. Validated at import time."""

    litellm: LiteLLMSettings = Field(default_factory=LiteLLMSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    ntfy: NtfySettings = Field(default_factory=NtfySettings)
    engine: EngineSettings = Field(default_factory=EngineSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    logging: LogSettings = Field(default_factory=LogSettings)
    governance: GovernanceSettings = Field(default_factory=GovernanceSettings)
