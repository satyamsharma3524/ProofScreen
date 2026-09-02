"""
The one and only LLM wrapper. Owned by Dev A, used by both devs.

Contract:
    complete_json(prompt, Schema) -> Schema instance, or LLMContractError.

Rules baked in here so nobody has to remember them at 2am:
  * Every prompt is told to return only JSON. Fences are stripped defensively.
  * On ValidationError -> retry once with the error text appended.
  * On second failure -> LLMContractError, or the caller's fallback if given.
  * Responses are cached by SHA-256 of (model, temperature, prompt, schema).
    Over nine days you will call extract_claims on the same resume 500 times.
  * With no OPENAI_API_KEY the wrapper never touches the network and returns
    the caller's fallback. The whole product runs offline in fixture mode.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from string import Template
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from api.config import settings

log = logging.getLogger("proofscreen.llm")

T = TypeVar("T", bound=BaseModel)

PROMPT_DIR = Path(__file__).parent / "prompts"

_SYSTEM = (
    "You are a precise information-extraction service. "
    "You return only valid JSON matching the requested schema. "
    "No prose, no explanation, no markdown fences."
)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)

# process-local response cache: sha256 -> raw json string
_cache: dict[str, str] = {}
_stats = {"hits": 0, "calls": 0, "fallbacks": 0, "failures": 0}


class LLMContractError(RuntimeError):
    """The model could not produce output matching the schema."""


# ---------------------------------------------------------------------------
# prompt loading
# ---------------------------------------------------------------------------


def load_prompt(name: str, /, **values: object) -> str:
    """Render prompts/<name>.txt.

    Uses string.Template ($var), NOT str.format, because every prompt contains
    a literal JSON schema full of braces.
    """
    raw = (PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8")
    return Template(raw).safe_substitute(
        {k: ("" if v is None else str(v)) for k, v in values.items()}
    )


# ---------------------------------------------------------------------------
# json coercion
# ---------------------------------------------------------------------------


def _strip_fences(text: str) -> str:
    out = _FENCE_RE.sub("", text.strip())
    return out.strip()


def _isolate_json(text: str) -> str:
    """Last-resort: grab the outermost {...} in case the model added prose."""
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _parse(raw: str, schema: type[T]) -> T:
    cleaned = _strip_fences(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = json.loads(_isolate_json(cleaned))
    return schema.model_validate(data)


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI  # imported lazily: no key, no import cost

        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.llm_timeout_seconds,
        )
    return _client


async def _raw_completion(prompt: str, temperature: float) -> str:
    client = _get_client()
    kwargs: dict = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
    }
    try:
        resp = await client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        # Some models reject a non-default temperature or json_object mode.
        # Retry once bare rather than dying on a config mismatch mid-demo.
        if "temperature" in str(exc) or "response_format" in str(exc):
            log.warning("retrying without temperature/response_format: %s", exc)
            kwargs.pop("temperature", None)
            kwargs.pop("response_format", None)
            resp = await client.chat.completions.create(**kwargs)
        else:
            raise
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# public api
# ---------------------------------------------------------------------------


async def complete_json(
    prompt: str,
    schema: type[T],
    *,
    temperature: float | None = None,
    max_retries: int = 2,
    fallback: Callable[[], T] | None = None,
    cache: bool = True,
) -> T:
    """Call the model, parse JSON, validate against `schema`.

    On ValidationError: retry with the error text appended.
    On final failure: return `fallback()` if given, else raise LLMContractError.
    """
    temp = settings.llm_temperature_extract if temperature is None else temperature

    if not settings.llm_enabled:
        if fallback is None:
            raise LLMContractError(
                "OPENAI_API_KEY is not set and this call has no fixture fallback"
            )
        _stats["fallbacks"] += 1
        log.info("fixture mode: %s served from fallback", schema.__name__)
        return fallback()

    key = hashlib.sha256(
        f"{settings.openai_model}|{temp}|{schema.__name__}|{prompt}".encode()
    ).hexdigest()

    if cache and key in _cache:
        _stats["hits"] += 1
        try:
            return _parse(_cache[key], schema)
        except (ValidationError, json.JSONDecodeError):
            _cache.pop(key, None)   # poisoned entry, fall through to a real call

    attempt_prompt = prompt
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            _stats["calls"] += 1
            raw = await _raw_completion(attempt_prompt, temp)
            parsed = _parse(raw, schema)
            if cache:
                _cache[key] = raw
            return parsed
        except (ValidationError, json.JSONDecodeError) as exc:
            last_error = exc
            log.warning(
                "%s attempt %d/%d failed schema validation: %s",
                schema.__name__, attempt, max_retries, exc,
            )
            attempt_prompt = (
                f"{prompt}\n\n"
                f"Your previous reply was rejected with this error:\n{exc}\n"
                f"Return ONLY corrected JSON matching the schema exactly."
            )
        except Exception as exc:  # noqa: BLE001  timeouts, rate limits, 5xx
            last_error = exc
            log.warning(
                "%s attempt %d/%d failed transport: %s",
                schema.__name__, attempt, max_retries, exc,
            )

    _stats["failures"] += 1
    if fallback is not None:
        log.error("%s exhausted retries, using fallback: %s", schema.__name__, last_error)
        return fallback()
    raise LLMContractError(
        f"{schema.__name__} could not be produced after {max_retries} attempts: {last_error}"
    )


def cache_stats() -> dict[str, int]:
    return {**_stats, "cached_entries": len(_cache)}


def clear_cache() -> None:
    _cache.clear()
