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
    llm_timeout_seconds: float = 25.0

    # --- stt (Groq, OpenAI-compatible /audio/transcriptions route) ---
    # Separate from the openai_* keys above: extraction/question/evidence stay
    # on OpenAI chat completions, only voice transcription moves to Groq.
    groq_api_key: str | None = None
    groq_stt_model: str = "whisper-large-v3-turbo"
    groq_api_base: str = "https://api.groq.com/openai/v1"
    llm_temperature_extract: float = 0.0
    llm_temperature_question: float = 0.4

    # --- interview policy ---
    # WAS 12. Hackathon demo asks for a short, human-feeling interview: 3
    # claims (max_claims below) x 2 questions each (demo_max_questions_per_claim).
    # `MAX_QUESTIONS=12` in the env restores the old budget without a code change.
    max_questions: int = 6
    max_claims: int = 3

    # --- hackathon demo mode -------------------------------------------------
    # One flag for the whole "make the interview feel human, not exhaustive"
    # bundle: caps per claim, one repair per claim instead of one per probe,
    # EXCLUSION/PERTURB moves off, and lightweight answer-threading (see
    # question.detect_thread_entity). All additive to the existing Move
    # planner -- nothing here touches extraction, scoring, the claim graph or
    # the evidence categories. DEMO_MODE=false reverts every one of these at
    # once; PERTURB is disabled via the existing `transfer_probe` flag below,
    # which already exists for exactly this and is separately overridable.
    demo_mode: bool = True
    demo_max_questions_per_claim: int = 2

    # --- claim inventory (recall-first extraction) ------------------------
    # EXTRACTION IS A RECALL STEP, NOT A RANKING STEP. With this on,
    # `extract_claims` returns every verifiable claim it finds: no claim_type
    # dedup, no importance sort, no top-N. Ranking and selection move
    # downstream to the question planner, which is where the interview budget
    # and the role weights already live.
    #
    # DEFAULTS FALSE, AND THE REASON IS A MEASURED SCORING DEFECT, not caution.
    # `graph.build_candidate_graph` appends EVERY claim to `scored_pairs`, and
    # an unprobed claim scores 0 with its full weight. Measured on the traced
    # candidate: the same two probed claims score 69 in an inventory of 2 and
    # **24** in an inventory of 6. Turning this on before `graph.py` stops
    # counting unprobed claims would crater every candidate's competence score
    # for a reason that has nothing to do with their evidence. `graph.py` is
    # Developer B's file -- see docs/CLAIM_INVENTORY.md for the exact change.
    claim_inventory: bool = False

    # Safety ceiling on a runaway reply, NOT a selection budget. It exists so
    # one malformed response cannot write 400 claim rows.
    #
    # WAS 12, MEASURED TO BE AN ACTIVE TRUNCATION POINT, NOT A BACKSTOP.
    # docs/EXTRACTION_ARCHITECTURE_REVIEW.md D1: two real resumes' own claim
    # counts saturated at 17 and 14 once given room -- a ceiling of 12 was
    # silently cutting 5 and 2 genuine claims regardless of whether the number
    # was ever mentioned to the model. 60 is roughly 3.5x measured saturation:
    # far enough above any real resume that it only bites on a malformed or
    # repetitive reply, which is the one thing this constant is for.
    max_inventory_claims: int = 60
    adaptive_probing: bool = True    # false => strict VALIDATION..OUTCOME order
    score_inline: bool = True
    # One TRANSFER probe to a claim that has stalled, instead of abandoning it
    # on the spot. false => the pre-phase interview, question for question.
    # Also how PERTURB is disabled for the hackathon demo (demo_mode above) --
    # the whole PERTURB branch in plan_next_forensic is already gated on this
    # flag, so turning it off needs no new code.
    transfer_probe: bool = False

    # Validate every generated question and regenerate ONCE on failure. false
    # reproduces the Phase 1 question path exactly, question for question.
    question_validation: bool = True
    # Forensic generation: families and moves instead of probe levels. The
    # probe-level generator stays reachable with this off, so a bad question
    # stream is one env var from the previous behaviour rather than a rollback.
    forensic_questions: bool = True

    # v2 — EvidenceCategory planner (api/engine/v2_evidence_planner.py) and
    # api/prompts/v2_forensic_question.txt, in place of the Move ladder above.
    # Exploratory: CROSS_CLAIM_LINK is never offered (no claim_graph.txt call
    # wired yet), and OWNERSHIP/ARTIFACT are permanently under-signalled by
    # today's wired extractor — both degrade gracefully via EXHAUST_AFTER
    # rather than looping. Defaults FALSE; forensic_questions above is what
    # ships without this on.
    evidence_planner_v2: bool = False

    # Route on the candidate's TITLE with one extra model call before claim
    # extraction, falling back to the keyword scorer. Measured on nine real
    # resumes: keyword routing 3/8 correct, title routing 8/8. Defaults FALSE —
    # true is opt-in per deployment, and false reproduces prior routing exactly.
    role_classifier: bool = True

    # A non-answer ("ok", "yes") earns ONE more attempt at the same probe, and
    # that attempt does not consume the interview budget. false => Phase 1.
    repair_turn: bool = True

    # Offline-only, background-task LLM judge that scores every FINALIZED
    # question (clarity/specificity/naturalness/single_focus/answerability/
    # evidence_yield/relevance_to_claim) and logs the result -- never gates,
    # never persisted, never read by anything that scores a candidate. This is
    # a SECOND live model call per turn: real ongoing cost and, being
    # fire-and-forget, the one thing that could still make the interview look
    # slow is a burst of these calls saturating the process, not the turn
    # itself (it is never awaited inline). Defaults FALSE for exactly that
    # reason -- turn on deliberately, not by accident the day of a demo. See
    # docs/QUESTION_EVAL_HARNESS_AND_LEVEL_MODEL.md Part A for the offline
    # (scripts/question_quality_harness.py) version of the same rubric.
    live_question_quality_log: bool = False

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

    # --- D9 tenancy ---
    # false (the default, and what the demo and the test suite run under): a
    # request with no X-API-Key is served as the DEVELOPMENT tenant `t_dev`.
    # true: no key, no service — 401. Turn it on before the URL is public.
    # An unknown key is 401 in BOTH modes.
    require_api_key: bool = False

    # --- D7 provenance ---
    # Which build produced an evaluation. Set at image build time
    # (`--build-arg`/env); `.git` is in .dockerignore, so inside the container
    # this env var is the only source. Empty falls back to reading .git/HEAD,
    # then to the literal "unknown". Never a fabricated SHA.
    build_sha: str | None = None

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
