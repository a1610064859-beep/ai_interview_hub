from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./data/interview.db"
    llm_orchestration_timeout_s: float = 6
    local_base_url: str | None = None
    local_api_key: str | None = None
    local_model: str | None = None
    flash_base_url: str | None = None
    flash_api_key: str | None = None
    flash_model: str | None = None
    flagship_base_url: str | None = None
    flagship_api_key: str | None = None
    flagship_model: str | None = None

    @property
    def orchestration_timeout_s(self):
        return self.llm_orchestration_timeout_s

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
