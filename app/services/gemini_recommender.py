"""Backend-only Gemini structured recommendation client."""

import json
import logging
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
You are a roaming-package recommendation planner. Select exactly one complete plan from the
complete active catalogue supplied by the backend. A plan may use one package, repeated copies,
mixed package families, or ordered packages for different trip periods.

Rules:
1. Use only supplied package codes and never invent or alter package facts.
2. Cover every trip day without gaps or overlaps and return a continuous activation order.
3. Meet data, local-minute, international-minute, and SMS requirements.
4. Treat the latest user instruction as highest priority; numeric requirements are hard constraints.
5. Use trip_requirements as the authoritative usage target without adding headroom or rounding a
   requirement upward. Raw monthly usage is audit context only; never size a plan from a value
   listed in detected_outliers.
6. Preserve explicitly different trip segments and assign every selected item to its segment.
7. Prefer exact duration with a practical number of activations, then less unused validity, lower
   cost, less allowance waste, and fewer activations.
8. Do not repeat a rejected plan unless no other plan can satisfy the requirements.
9. Keep explanations concise and return only the requested structured response.

Python independently reloads every package fact and validates all arithmetic and constraints.
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
    timeout_seconds=30,
    client=None,
    invalid_decision=None,
    validation_errors=None,
    request_log_dir=None,
):
    if not api_key:
        raise GeminiUnavailable("Gemini is not configured.")

    request_context = dict(context)
    if invalid_decision is not None:
        request_context["CORRECTION_REQUEST"] = {
            "previous_invalid_plan": invalid_decision,
            "validation_errors": validation_errors or [],
            "instruction": "Correct only the listed failures and return one complete valid plan.",
        }

    LOGGER.info(
        "%s started",
        "Gemini refinement request" if context.get("latest_user_message") else "Gemini recommendation request",
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
            if context.get("latest_user_message")
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
        LOGGER.warning("Gemini request failed type=%s", type(error).__name__)
        raise GeminiUnavailable("Gemini is temporarily unavailable.") from error
