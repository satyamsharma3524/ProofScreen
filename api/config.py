"""Env-driven settings. One object, imported everywhere."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- database ---
    database_url: str = (
        "postgresql+asyncpg://proofscreen:proofscreen@localhost:5432/proofscreen"
    )

    # --- llm ---
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    openai_stt_model: str = "whisper-1"
    llm_timeout_seconds: float = 25.0
    llm_temperature_extract: float = 0.0
    llm_temperature_question: float = 0.4

    # --- conversation policy ---
    max_questions: int = 5
    max_claims: int = 3
    adaptive_followups: bool = True
    score_inline: bool = True

    # --- twilio ---
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_from: str = "whatsapp:+14155238886"
    twilio_validate_signature: bool = False
    public_base_url: str | None = None

    # --- api ---
    cors_origins: str = "*"
    enable_dev_endpoints: bool = True

    # --- resume_score contrast metric ---
    default_job_description: str = (
        "Support operations lead responsible for a large customer support team, "
        "CSAT improvement, escalation workflow design, SLA management, queue and "
        "staffing planning, stakeholder reporting, and process automation."
    )

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())

    @property
    def llm_mode(self) -> str:
        return "live" if self.llm_enabled else "fixture"

    @property
    def twilio_enabled(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token)

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if raw in ("", "*"):
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
