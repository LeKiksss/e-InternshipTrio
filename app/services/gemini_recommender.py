"""Backend-only Gemini structured recommendation client."""

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, PrivateAttr, ValidationError


LOGGER = logging.getLogger(__name__)


class GeminiUnavailable(RuntimeError):
    """Raised when Gemini cannot return a usable structured decision."""


class GeminiRateLimited(GeminiUnavailable):
    """Raised while the provider is rejecting requests for quota/rate limits."""


class GeminiConversationUnavailable(GeminiUnavailable):
    """Raised when a stored Gemini conversation can no longer be continued."""


_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMITED_UNTIL = 0.0


def _error_status(error):
    for value in (
        getattr(error, "status_code", None),
        getattr(error, "code", None),
        getattr(getattr(error, "response", None), "status_code", None),
    ):
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _rate_limit_status(error):
    if _error_status(error) == 429:
        return True
    return "ratelimit" in type(error).__name__.replace("_", "").lower()


def _safe_error_detail(error, api_key):
    detail = " ".join(str(error).split())[:600]
    if api_key:
        detail = detail.replace(api_key, "[redacted]")
    return detail or "No provider detail was supplied."


def _provider_retry_delay(error):
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    retry_after = headers.get("retry-after") if hasattr(headers, "get") else None
    if retry_after is not None:
        try:
            return max(1.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    match = re.search(
        r"retry\s+in\s+([0-9]+(?:\.[0-9]+)?)\s*s",
        str(error),
        flags=re.IGNORECASE,
    )
    return max(1.0, float(match.group(1))) if match else None


def _rate_limit_remaining():
    with _RATE_LIMIT_LOCK:
        return max(0.0, _RATE_LIMITED_UNTIL - time.monotonic())


def _start_rate_limit_cooldown(seconds):
    global _RATE_LIMITED_UNTIL
    with _RATE_LIMIT_LOCK:
        _RATE_LIMITED_UNTIL = max(
            _RATE_LIMITED_UNTIL,
            time.monotonic() + max(1.0, float(seconds)),
        )


def reset_rate_limit_cooldown():
    """Reset the process cooldown; exposed for deterministic tests."""

    global _RATE_LIMITED_UNTIL
    with _RATE_LIMIT_LOCK:
        _RATE_LIMITED_UNTIL = 0.0


class UsageSegmentDecision(BaseModel):
    segment_id: str
    start_day: int = Field(ge=1)
    end_day: int = Field(ge=1)
    usage_interpretation: str


class PackagePlanItemDecision(BaseModel):
    package_code: str
    quantity: int = Field(ge=1, le=12)
    coverage_start_day: int = Field(ge=1)
    coverage_end_day: int = Field(ge=1)
    activation_order: int = Field(ge=1)
    assigned_segment_id: Optional[str] = None
    reason_for_item: Optional[str] = None


class RecommendationDecision(BaseModel):
    trip_segments: list[UsageSegmentDecision] = Field(default_factory=list)
    package_items: list[PackagePlanItemDecision] = Field(min_length=1)
    modification_summary: str = Field(min_length=1, max_length=180)
    _interaction_id: Optional[str] = PrivateAttr(default=None)


PLANNER_SYSTEM_INSTRUCTION = """
You are the Package Planner. Return the cheapest valid structural roaming plan
using only the package catalogue supplied in the current or earlier stored
planner interaction. Packages may be repeated, stacked, or mixed.

- Cover every trip day exactly once and use continuous activation order.
- Treat trip_requirements and any exact split requirements as authoritative.
- Meet or exceed every exact requirement; do not add a safety buffer.
- The current_plan is authoritative application state even when an intervening
  Smart History hit did not create a planner interaction.
- Trip-wide metrics must remain available across the whole trip. Use separate
  periods only when exact_split_requirements defines them.
- validated_baseline_plan is already valid. Return that schedule unless you find a strictly
  cheaper valid schedule. Never overlap rows; use quantity when the same package is stacked.
- Minimize total price first, then allowance excess, then activation count.
- Do not interpret raw user language; the requirements interpreter has already
  resolved it into exact structured values.
- Return only the requested JSON structure. Keep modification_summary to one
  short explanation for the user.

The server reloads package facts and validates coverage, arithmetic, and every requirement.
""".strip()
# Compatibility for code importing the original constant name.
SYSTEM_INSTRUCTION = PLANNER_SYSTEM_INSTRUCTION


def _make_client(api_key, timeout_seconds):
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
    )


def _save_request_payload(request_log_dir, request_kind, api_request):
    if not request_log_dir:
        return None

    directory = Path(request_log_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        saved_at = datetime.now(timezone.utc)
        filename = (
            f"gemini_{request_kind}_"
            f"{saved_at.strftime('%Y%m%dT%H%M%S_%fZ')}_{uuid4().hex[:8]}.json"
        )
        payload = {
            "saved_at_utc": saved_at.isoformat(),
            "request_kind": request_kind,
            "api_method": "interactions.create",
            "request": {
                **api_request,
                "input": json.loads(api_request["input"]),
            },
        }
        path = directory / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        LOGGER.info("Gemini request payload saved file=%s", filename)
        return path
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        LOGGER.warning(
            "Gemini request payload could not be saved type=%s",
            type(error).__name__,
        )
        return None


def request_recommendation_decision(
    context,
    *,
    api_key,
    model,
    previous_interaction_id=None,
    request_kind=None,
    timeout_seconds=30,
    client=None,
    request_log_dir=None,
    rate_limit_cooldown_seconds=60,
):
    if not api_key:
        raise GeminiUnavailable("Gemini is not configured.")
    cooldown_remaining = _rate_limit_remaining()
    if cooldown_remaining:
        LOGGER.info(
            "Gemini request skipped during rate-limit cooldown remaining_seconds=%d",
            max(1, round(cooldown_remaining)),
        )
        raise GeminiRateLimited("Gemini rate-limit cooldown is active.")

    LOGGER.info(
        "%s started",
        "Gemini refinement request"
        if previous_interaction_id
        else "Gemini recommendation request",
    )
    try:
        active_client = client or _make_client(api_key, timeout_seconds)
        api_request = {
            "model": model,
            "system_instruction": PLANNER_SYSTEM_INSTRUCTION,
            "input": json.dumps(context, separators=(",", ":"), default=str),
            "generation_config": {
                "thinking_level": "high",
            },
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": RecommendationDecision.model_json_schema(),
            },
            "store": True,
            "timeout": timeout_seconds,
        }
        if previous_interaction_id:
            api_request["previous_interaction_id"] = previous_interaction_id
        resolved_request_kind = request_kind or (
            "refinement" if previous_interaction_id else "initial"
        )
        _save_request_payload(
            request_log_dir,
            f"planner_{resolved_request_kind}",
            api_request,
        )
        interaction = active_client.interactions.create(**api_request)
        output_text = getattr(interaction, "output_text", None)
        if not output_text:
            raise GeminiUnavailable("Gemini returned no structured response.")
        decision = RecommendationDecision.model_validate_json(output_text)
        interaction_id = getattr(interaction, "id", None)
        if interaction_id:
            decision._interaction_id = str(interaction_id)
        else:
            LOGGER.warning(
                "Gemini response did not include an interaction ID; "
                "the next request will start a new conversation"
            )
        LOGGER.info("Gemini response received")
        return decision
    except GeminiUnavailable:
        raise
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
        LOGGER.warning("Gemini structured-response parsing failed type=%s", type(error).__name__)
        raise GeminiUnavailable("Gemini returned an invalid structured response.") from error
    except Exception as error:
        if _rate_limit_status(error):
            provider_delay = _provider_retry_delay(error)
            cooldown_seconds = (
                provider_delay + 1.0
                if provider_delay is not None
                else float(rate_limit_cooldown_seconds)
            )
            _start_rate_limit_cooldown(cooldown_seconds)
            LOGGER.warning(
                "Gemini request rate limited; cooldown_seconds=%g detail=%s",
                cooldown_seconds,
                _safe_error_detail(error, api_key),
            )
            raise GeminiRateLimited("Gemini is temporarily rate limited.") from error
        status = _error_status(error)
        if previous_interaction_id and status in {400, 404, 410}:
            LOGGER.info(
                "Stored Gemini conversation is unavailable status=%s",
                status,
            )
            raise GeminiConversationUnavailable(
                "The stored Gemini conversation is no longer available."
            ) from error
        LOGGER.warning("Gemini request failed type=%s", type(error).__name__)
        raise GeminiUnavailable("Gemini is temporarily unavailable.") from error
