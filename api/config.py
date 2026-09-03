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

    # --- interview policy ---
    max_questions: int = 12          # 5 probe levels x 3 claims, adaptively stopped
    max_claims: int = 3
    adaptive_probing: bool = True    # false => strict VALIDATION..OUTCOME order
    score_inline: bool = True
    # One TRANSFER probe to a claim that has stalled, instead of abandoning it
    # on the spot. false => the pre-phase interview, question for question.
    transfer_probe: bool = True

    # Voice's share of a claim's score, applied only to voice-answered claims.
    # Set to 0 to remove the text/voice asymmetry entirely.
    voice_weight: float = 0.10

    # --- WhatsApp Business Cloud API (Meta, direct) ---
    whatsapp_phone_number_id: str | None = None
    whatsapp_business_account_id: str | None = None
    whatsapp_access_token: str | None = None
    whatsapp_verify_token: str = "proofscreen-verify"
    whatsapp_app_secret: str | None = None       # for X-Hub-Signature-256
    whatsapp_api_version: str = "v21.0"
    whatsapp_template_name: str | None = None    # to open a conversation
    whatsapp_template_language: str = "en"
    whatsapp_validate_signature: bool = False

    # --- api ---
    cors_origins: str = "*"
    enable_dev_endpoints: bool = True

    # --- resume_score contrast metric ---
    default_job_description: str = (
        "Experienced professional responsible for owning a measurable operational "
        "outcome, running the process day to day, handling escalations, reporting "
        "on metrics to stakeholders, and improving results over time."
    )

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())

    @property
    def llm_mode(self) -> str:
        return "live" if self.llm_enabled else "fixture"

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(self.whatsapp_access_token and self.whatsapp_phone_number_id)

    @property
    def whatsapp_mode(self) -> str:
        return "live" if self.whatsapp_enabled else "dry-run"

    @property
    def graph_api_base(self) -> str:
        return f"https://graph.facebook.com/{self.whatsapp_api_version}"

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
