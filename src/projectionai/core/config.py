"""Application configuration management.

Uses ``pydantic-settings`` to load configuration from:
1. Defaults (hardcoded)
2. ``.env`` file (project root)
3. Environment variables (``PROJECTIONAI_*`` prefix)

Later sources override earlier ones.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Literal, cast

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# AI Provider sub-configs
# ---------------------------------------------------------------------------


class GeminiConfig(BaseSettings):
    """Configuration for the Gemini AI provider."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="gemini_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    model: str = Field(default="gemini-3.5-flash", validation_alias="GEMINI_MODEL")


class OpenAIConfig(BaseSettings):
    """Configuration for the OpenAI AI provider."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="openai_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    model: str = Field(default="gpt-4o", validation_alias="OPENAI_MODEL")
    org_id: str = Field(default="", validation_alias="OPENAI_ORG_ID")


class AnthropicConfig(BaseSettings):
    """Configuration for the Anthropic AI provider."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="anthropic_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    model: str = Field(
        default="claude-3-5-sonnet-20241022", validation_alias="ANTHROPIC_MODEL"
    )


class ReplicateConfig(BaseSettings):
    """Configuration for the Replicate AI provider."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="replicate_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_token: str = Field(default="", validation_alias="REPLICATE_API_TOKEN")
    model: str = Field(
        default="stability-ai/stable-diffusion-3", validation_alias="REPLICATE_MODEL"
    )


# ---------------------------------------------------------------------------
# Application config
# ---------------------------------------------------------------------------

_LOG_LEVELS = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_ENVIRONMENTS = Literal["development", "production", "staging"]
_AI_PROVIDERS = Literal["gemini", "openai", "anthropic", "replicate"]


class AppConfig(BaseSettings):
    """Root application configuration.

    Loaded from environment variables, ``.env``, and optional YAML files.
    """

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="projectionai_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Application --------------------------------------------------------

    env: _ENVIRONMENTS = Field(
        default="development",
        validation_alias="PROJECTIONAI_ENV",
    )
    log_level: _LOG_LEVELS = Field(
        default="DEBUG",
        validation_alias="PROJECTIONAI_LOG_LEVEL",
    )
    data_dir: Path | None = Field(
        default=None,
        validation_alias="PROJECTIONAI_DATA_DIR",
    )

    # -- AI -----------------------------------------------------------------

    ai_provider: _AI_PROVIDERS = Field(
        default="gemini",
        validation_alias="PROJECTIONAI_AI_PROVIDER",
    )

    # -- Sub-configs --------------------------------------------------------

    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    replicate: ReplicateConfig = Field(default_factory=ReplicateConfig)

    # -- Derived helpers ----------------------------------------------------

    @field_validator("data_dir", mode="before")
    @classmethod
    def _resolve_data_dir(cls, v: str | Path | None) -> Path | None:
        if v is None or v == "":
            return None
        return Path(v).resolve()

    @property
    def is_debug(self) -> bool:
        """Shortcut for debug-mode checks."""
        return self.log_level == "DEBUG"

    @property
    def active_ai_provider_config(
        self,
    ) -> GeminiConfig | OpenAIConfig | AnthropicConfig | ReplicateConfig:
        """Return the config dict for the currently selected AI provider."""
        mapping = {
            "gemini": self.gemini,
            "openai": self.openai,
            "anthropic": self.anthropic,
            "replicate": self.replicate,
        }
        return cast(
            "GeminiConfig | OpenAIConfig | AnthropicConfig | ReplicateConfig",
            mapping[self.ai_provider],
        )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_config: AppConfig | None = None


def load_config(path: str | Path | None = None) -> AppConfig:
    """Return the application configuration singleton.

    Args:
        path: Optional path to a YAML/JSON configuration file to load.
              When provided, creates a fresh ``AppConfig`` loaded from
              that file (overriding defaults, ``.env``, and env vars).
    """
    global _config
    if path is not None:
        _config = _build_config(path)
    elif _config is None:
        _config = AppConfig()
    return _config


def _build_config(path: str | Path) -> AppConfig:
    """Load configuration from a YAML/JSON file and return an ``AppConfig``."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Configuration file not found: {p}")

    if p.suffix in (".yaml", ".yml"):
        import yaml

        raw: object = yaml.safe_load(p.read_text("utf-8"))
    elif p.suffix == ".json":
        import json

        raw = json.loads(p.read_text("utf-8"))
    else:
        raise ValueError(
            f"Unsupported config format: {p.suffix} (supported: .json, .yaml, .yml)"
        )

    if not isinstance(raw, dict):
        raise ValueError(
            f"Config file must contain a top-level mapping, got {type(raw).__name__}"
        )

    return AppConfig(**raw)


def reload_config() -> AppConfig:
    """Force-reload the configuration from the environment and files."""
    global _config
    _config = AppConfig()
    return _config
