from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = Field("development", validation_alias=AliasChoices("APP_ENV", "app_env"))
    database_url: str = Field("sqlite:///./data/interview.db", validation_alias=AliasChoices("DATABASE_URL", "database_url"))
    llm_orchestration_timeout_s: float = Field(6.0, validation_alias=AliasChoices("LLM_ORCHESTRATION_TIMEOUT_S", "llm_orchestration_timeout_s"))
    llm_scoring_timeout_s: float = Field(60.0, validation_alias=AliasChoices("LLM_SCORING_TIMEOUT_S", "llm_scoring_timeout_s"))
    llm_usage_log_path: str = Field("logs/llm_usage.jsonl", validation_alias=AliasChoices("LLM_USAGE_LOG_PATH", "llm_usage_log_path"))
    local_base_url: str | None = Field(None, validation_alias=AliasChoices("LLM_LOCAL_BASE_URL", "LOCAL_BASE_URL", "local_base_url"))
    local_api_key: str | None = Field(None, validation_alias=AliasChoices("LLM_LOCAL_API_KEY", "LOCAL_API_KEY", "local_api_key"))
    local_model: str | None = Field(None, validation_alias=AliasChoices("LLM_LOCAL_MODEL", "LOCAL_MODEL", "local_model"))
    flash_base_url: str | None = Field(None, validation_alias=AliasChoices("LLM_FLASH_BASE_URL", "FLASH_BASE_URL", "flash_base_url"))
    flash_api_key: str | None = Field(None, validation_alias=AliasChoices("LLM_FLASH_API_KEY", "FLASH_API_KEY", "flash_api_key"))
    flash_model: str | None = Field(None, validation_alias=AliasChoices("LLM_FLASH_MODEL", "FLASH_MODEL", "flash_model"))
    flagship_base_url: str | None = Field(None, validation_alias=AliasChoices("LLM_FLAGSHIP_BASE_URL", "FLAGSHIP_BASE_URL", "flagship_base_url"))
    flagship_api_key: str | None = Field(None, validation_alias=AliasChoices("LLM_FLAGSHIP_API_KEY", "FLAGSHIP_API_KEY", "flagship_api_key"))
    flagship_model: str | None = Field(None, validation_alias=AliasChoices("LLM_FLAGSHIP_MODEL", "FLAGSHIP_MODEL", "flagship_model"))
    lease_duration_seconds: int = Field(30, validation_alias=AliasChoices("LEASE_DURATION_SECONDS", "lease_duration_seconds"))
    lease_renew_interval_seconds: int = Field(10, validation_alias=AliasChoices("LEASE_RENEW_INTERVAL_SECONDS", "lease_renew_interval_seconds"))

    @property
    def orchestration_timeout_s(self) -> float:
        return self.llm_orchestration_timeout_s

    @property
    def scoring_timeout_s(self) -> float:
        return self.llm_scoring_timeout_s

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

settings = Settings()
