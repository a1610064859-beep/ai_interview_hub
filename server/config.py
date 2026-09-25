from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = Field("development", validation_alias=AliasChoices("APP_ENV", "app_env"))
    auth_required: bool = Field(True, validation_alias=AliasChoices("AUTH_REQUIRED", "auth_required"))
    auth_session_hours: int = Field(12, ge=1, le=168, validation_alias=AliasChoices("AUTH_SESSION_HOURS", "auth_session_hours"))
    database_url: str = Field("sqlite:///./data/interview.db", validation_alias=AliasChoices("DATABASE_URL", "database_url"))
    resume_upload_dir: str = Field("data/resumes", validation_alias=AliasChoices("RESUME_UPLOAD_DIR", "resume_upload_dir"))
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
    answer_timeout_s: float = Field(300.0, gt=0, validation_alias=AliasChoices("ANSWER_TIMEOUT_S", "answer_timeout_s"))
    lease_renew_interval_seconds: int = Field(10, validation_alias=AliasChoices("LEASE_RENEW_INTERVAL_SECONDS", "lease_renew_interval_seconds"))
    tts_enabled: bool = Field(True, validation_alias=AliasChoices("TTS_ENABLED", "tts_enabled"))
    tts_voice: str = Field("zh-CN-XiaoxiaoNeural", validation_alias=AliasChoices("TTS_VOICE", "tts_voice"))
    tts_output_dir: str = Field("data/audio", validation_alias=AliasChoices("TTS_OUTPUT_DIR", "tts_output_dir"))
    tts_transition_lines: str = Field("嗯，我了解了|请继续|谢谢你的回答", validation_alias=AliasChoices("TTS_TRANSITION_LINES", "tts_transition_lines"))
    tts_timeout_s: float = Field(30.0, validation_alias=AliasChoices("TTS_TIMEOUT_S", "tts_timeout_s"))
    # ASR（T5；键表见 docs/asr-implementation-spec.md §4；模型名/缓存目录/供应商必填，无默认）
    asr_enabled: bool = Field(True, validation_alias=AliasChoices("ASR_ENABLED", "asr_enabled"))
    asr_provider: Literal["funasr"] = Field(..., validation_alias=AliasChoices("ASR_PROVIDER", "asr_provider"))
    asr_model_name: str = Field(..., validation_alias=AliasChoices("ASR_MODEL_NAME", "asr_model_name"))
    asr_device: str = Field("cpu", validation_alias=AliasChoices("ASR_DEVICE", "asr_device"))
    asr_model_cache_dir: str = Field(..., validation_alias=AliasChoices("ASR_MODEL_CACHE_DIR", "asr_model_cache_dir"))
    asr_timeout_s: float = Field(120.0, validation_alias=AliasChoices("ASR_TIMEOUT_S", "asr_timeout_s"))
    asr_preload: bool = Field(True, validation_alias=AliasChoices("ASR_PRELOAD", "asr_preload"))
    audio_process_timeout_s: float = Field(15.0, gt=0, validation_alias=AliasChoices("AUDIO_PROCESS_TIMEOUT_S", "audio_process_timeout_s"))
    asr_max_upload_mb: int = Field(20, validation_alias=AliasChoices("ASR_MAX_UPLOAD_MB", "asr_max_upload_mb"))
    asr_sample_rate: int = Field(16000, validation_alias=AliasChoices("ASR_SAMPLE_RATE", "asr_sample_rate"))
    asr_temp_dir: str | None = Field(None, validation_alias=AliasChoices("ASR_TEMP_DIR", "asr_temp_dir"))
    ffmpeg_path: str = Field("ffmpeg", validation_alias=AliasChoices("FFMPEG_PATH", "ffmpeg_path"))
    ffprobe_path: str = Field("ffprobe", validation_alias=AliasChoices("FFPROBE_PATH", "ffprobe_path"))
    xfyun_app_id: str | None = Field(None, validation_alias=AliasChoices("XFYUN_APP_ID", "xfyun_app_id"))
    xfyun_api_key: str | None = Field(None, validation_alias=AliasChoices("XFYUN_API_KEY", "xfyun_api_key"))
    xfyun_ws_url: str | None = Field(None, validation_alias=AliasChoices("XFYUN_WS_URL", "xfyun_ws_url"))

    @property
    def transition_lines_list(self) -> list[str]:
        if not self.tts_transition_lines:
            return []
        return [line.strip() for line in self.tts_transition_lines.split("|") if line.strip()]

    @property
    def orchestration_timeout_s(self) -> float:
        return self.llm_orchestration_timeout_s

    @property
    def scoring_timeout_s(self) -> float:
        return self.llm_scoring_timeout_s

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

settings = Settings()
