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
from pydantic import BaseModel, Field, ValidationError


LOGGER = logging.getLogger(__name__)


class GeminiUnavailable(RuntimeError):
    """Raised when Gemini cannot return a usable structured decision."""


class GeminiRateLimited(GeminiUnavailable):
    """Raised while the provider is rejecting requests for quota/rate limits."""


_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMITED_UNTIL = 0.0


def _rate_limit_status(error):
    for value in (
        getattr(error, "status_code", None),
        getattr(error, "code", None),
        getattr(getattr(error, "response", None), "status_code", None),
    ):
        try:
            if int(value) == 429:
                return True
        except (TypeError, ValueError):
            continue
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
    data_requirement_gb: float = Field(ge=0)
    local_minutes_requirement: int = Field(ge=0)
    international_minutes_requirement: int = Field(ge=0)
    sms_requirement: int = Field(ge=0)


class PackagePlanItemDecision(BaseModel):
    package_code: str
    quantity: int = Field(ge=1, le=12)
    coverage_start_day: int = Field(ge=1)
    coverage_end_day: int = Field(ge=1)
    activation_order: int = Field(ge=1)
    assigned_segment_id: Optional[str] = None
    reason_for_item: str


class RecommendationDecision(BaseModel):
    interpreted_latest_request: Optional[str] = None
    trip_segments: list[UsageSegmentDecision] = Field(default_factory=list)
    package_items: list[PackagePlanItemDecision] = Field(min_length=1)
    reason: str
    why_it_fits: list[str] = Field(default_factory=list, max_length=4)
    usage_summary: str
    modification_summary: Optional[str] = None
    tradeoff_summary: Optional[str] = None


SYSTEM_INSTRUCTION = """
Select one complete roaming plan from the supplied catalogue. Listed packages may be repeated,
stacked, or mixed.

Rules:
1. Use only supplied package codes; never alter package facts.
2. Cover all trip days exactly once with continuous activation order.
3. trip_requirements and the latest user instruction are hard constraints. Do not add headroom.
4. Treat each refinement as a change to the current plan, not a fresh plan. Every value in
   active_constraints.preservation_minimums is a hard floor copied from the current plan for a
   service the user did not ask to change. Never reduce those untouched services. If
   active_constraints.reset_constraints is true, abandon the earlier constraints and follow the
   new direction instead.
5. A numeric request applies across the entire trip by default. Every scheduled part of the plan
   must carry its proportional share for each requirement_scope.trip_wide_metrics entry. Higher
   cost is acceptable when necessary to meet the request.
6. Create or preserve different periods only when active_constraints.segments explicitly lists
   them. Otherwise do not confine a requested allowance to one day or part of the trip.
7. Prefer exact duration, then less unused validity, lower cost, less waste, and fewer activations.
8. Return only the structured response with concise explanations.

Python reloads package facts and validates arithmetic, coverage, and requirement scope.
""".strip()


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
    timeout_seconds=45,
    client=None,
    invalid_decision=None,
    validation_errors=None,
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

    request_context = dict(context)
    if invalid_decision is not None:
        request_context["CORRECTION_REQUEST"] = {
            "previous_invalid_plan": invalid_decision,
            "validation_errors": validation_errors or [],
            "instruction": "Correct only the listed failures and return one complete valid plan.",
        }

    LOGGER.info(
        "%s started",
        "Gemini refinement request"
        if context.get("latest_user_instruction")
        else "Gemini recommendation request",
    )
    try:
        active_client = client or _make_client(api_key, timeout_seconds)
        api_request = {
            "model": model,
            "system_instruction": SYSTEM_INSTRUCTION,
            "input": json.dumps(request_context, separators=(",", ":"), default=str),
            "generation_config": {
                "thinking_level": "high",
            },
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": RecommendationDecision.model_json_schema(),
            },
            "store": False,
            "timeout": timeout_seconds,
        }
        request_kind = (
            "correction"
            if invalid_decision is not None
            else "refinement"
            if context.get("latest_user_instruction")
            else "initial"
        )
        _save_request_payload(request_log_dir, request_kind, api_request)
        interaction = active_client.interactions.create(**api_request)
        output_text = getattr(interaction, "output_text", None)
        if not output_text:
            raise GeminiUnavailable("Gemini returned no structured response.")
        decision = RecommendationDecision.model_validate_json(output_text)
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
        LOGGER.warning("Gemini request failed type=%s", type(error).__name__)
        raise GeminiUnavailable("Gemini is temporarily unavailable.") from error
