"""Stateless Gemini interpretation of roaming-chat requirements."""

import json
import logging
import re
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from .gemini_recommender import (
    GeminiRateLimited,
    GeminiUnavailable,
    _make_client,
    _provider_retry_delay,
    _rate_limit_remaining,
    _rate_limit_status,
    _safe_error_detail,
    _save_request_payload,
    _start_rate_limit_cooldown,
)
from .recommendation_values import (
    METRIC_NAMES,
    canonical_decimal,
    canonical_string,
)
from .user_requirement_parser import parse_user_requirements


LOGGER = logging.getLogger(__name__)
MetricName = Literal[
    "data_gb",
    "local_minutes",
    "international_minutes",
    "sms",
]
MetricString = Annotated[
    str,
    StringConstraints(pattern=r"^(?:0|[1-9]\d*)\.\d{6}$"),
]


class InterpretedSplitSegment(BaseModel):
    start_day: int = Field(ge=1)
    end_day: int = Field(ge=1)
    data_gb: MetricString
    local_minutes: MetricString
    international_minutes: MetricString
    sms: MetricString


class CompleteRequirements(BaseModel):
    data_gb: MetricString
    local_minutes: MetricString
    international_minutes: MetricString
    sms: MetricString
    period_days: int = Field(ge=1)
    split: bool
    split_details: Optional[list[InterpretedSplitSegment]] = None

    @model_validator(mode="after")
    def validate_split_shape(self):
        if self.split and not self.split_details:
            raise ValueError(
                "Split requirements must include at least one exact segment."
            )
        if not self.split and self.split_details is not None:
            raise ValueError(
                "Unsplit requirements must set split_details to null."
            )
        return self


class RequirementsInterpretation(BaseModel):
    fully_understood: bool
    clarification_required: bool
    clarification_question: Optional[str] = Field(default=None, max_length=240)
    unresolved_fragments: list[str] = Field(default_factory=list, max_length=8)
    requirements: CompleteRequirements
    changed_metrics: list[MetricName] = Field(default_factory=list)
    preserved_metrics: list[MetricName] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_interpretation_state(self):
        if self.fully_understood == self.clarification_required:
            raise ValueError(
                "Exactly one of fully_understood and clarification_required must be true."
            )
        changed = list(dict.fromkeys(self.changed_metrics))
        preserved = list(dict.fromkeys(self.preserved_metrics))
        if self.clarification_required:
            if not str(self.clarification_question or "").strip():
                raise ValueError(
                    "A clarification question is required when meaning is unresolved."
                )
            if changed or set(preserved) != set(METRIC_NAMES):
                raise ValueError(
                    "Clarification must leave every requirement metric unchanged."
                )
        elif self.clarification_question is not None or self.unresolved_fragments:
            raise ValueError(
                "A fully understood request cannot contain unresolved fragments."
            )

        if (
            len(changed) != len(self.changed_metrics)
            or len(preserved) != len(self.preserved_metrics)
            or set(changed) & set(preserved)
            or set(changed) | set(preserved) != set(METRIC_NAMES)
        ):
            raise ValueError(
                "Changed and preserved metrics must form one complete, disjoint set."
            )
        return self


INTERPRETER_SYSTEM_INSTRUCTION = """
You are the Requirements Interpreter for a roaming package service.
Interpret the user's message; do not select, rank, name, or discuss packages.

Return the complete updated requirements, never only a delta:
- data_gb, local_minutes, international_minutes, and sms as non-negative strings
  with exactly six decimal places;
- period_days exactly as supplied by the server;
- split=false with split_details=null for trip-wide requirements;
- split=true only with exact, non-overlapping segments that cover Day 1 through
  the final day once. Every segment must contain all four metrics, and each
  overall metric must equal the exact sum of its segment values.

Preserve every current metric the user did not explicitly change. Never add a
safety buffer or infer package facts. The server supplies
current_plan_allowances separately from current requirements. A request for
"more", "extra", "higher", "increase", or "boost" in a named service is
fully resolvable without asking for an amount: set that service to the supplied
current package allowance plus the smallest server-defined service increment,
and preserve every other metric. This represents the strict next allowance
tier; it is not a usage buffer.

An unqualified request such as "I need 200 minutes" or "I need more minutes"
is ambiguous: ask only whether the minutes are local or international. Do not
ask how many minutes. Once the user answers local or international, resolve the
original comparative request using current_plan_allowances and continue. A
request containing both an exact amount and an unresolved comparative phrase
must not ignore the phrase; either resolve every affected metric or ask one
specific clarification question.

If any other material fragment cannot be resolved safely, set
clarification_required=true, leave the complete requirements unchanged, list
the unresolved fragment, and ask one short specific question. Never ask for an
exact amount merely because the user expressed a relative increase.

When pending_clarification is present, interpret the original request and the
new clarification answer together against the unchanged current requirements.
Return only the requested JSON structure.
""".strip()


def _current_requirements_payload(context):
    current = context.get("current_requirements")
    if not isinstance(current, dict):
        raise GeminiUnavailable("The current requirements are unavailable.")
    return CompleteRequirements.model_validate(current)


def _clarification_from_current(context, question, unresolved):
    current = _current_requirements_payload(context)
    return RequirementsInterpretation(
        fully_understood=False,
        clarification_required=True,
        clarification_question=question,
        unresolved_fragments=unresolved,
        requirements=current,
        changed_metrics=[],
        preserved_metrics=list(METRIC_NAMES),
    )


_INCREASE_WORDS = re.compile(
    r"\b(?:more|extra|additional|higher|increase|increased|boost|upgrade)\b",
    re.IGNORECASE,
)
_SERVICE_INCREMENTS = {
    "data_gb": Decimal("0.001000"),
    "local_minutes": Decimal("1.000000"),
    "international_minutes": Decimal("1.000000"),
    "sms": Decimal("1.000000"),
}


def _pending_original(context):
    pending = context.get("pending_clarification")
    return (
        str(pending.get("original_request") or "")
        if isinstance(pending, dict)
        else ""
    )


def _combined_request(context):
    original = _pending_original(context)
    message = str(context.get("raw_user_message") or "")
    return f"{original} {message}".strip()


def _current_plan_allowances(context):
    supplied = context.get("current_plan_allowances")
    return supplied if isinstance(supplied, dict) else {}


def _pending_qualified_metric(context):
    original = _pending_original(context)
    answer = str(context.get("raw_user_message") or "")
    if not original or not _INCREASE_WORDS.search(original):
        return None
    if not re.search(r"\b(?:minutes?|calls?|voice)\b", original, re.IGNORECASE):
        return None
    if re.search(r"\binternational\b", answer, re.IGNORECASE):
        return "international_minutes"
    if re.search(r"\blocal\b", answer, re.IGNORECASE):
        return "local_minutes"
    return None


def _comparative_metrics(context):
    combined = _combined_request(context)
    if not _INCREASE_WORDS.search(combined):
        return [], False
    if re.search(
        r"\b\d+(?:\.\d+)?\s*(?:gb|local(?:\s+call)?\s+minutes?|"
        r"international(?:\s+call)?\s+minutes?|sms|texts?)\b",
        combined,
        re.IGNORECASE,
    ):
        return [], False

    metrics = []
    pending_metric = _pending_qualified_metric(context)
    if pending_metric:
        metrics.append(pending_metric)
    if re.search(
        r"\b(?:more|extra|additional|higher|increase(?:d)?|boost|upgrade)"
        r"[^.?!]{0,24}\bdata\b"
        r"|\bdata\b[^.?!]{0,18}\b(?:increase|boost|upgrade)\b",
        combined,
        re.IGNORECASE,
    ):
        metrics.append("data_gb")
    if re.search(
        r"\b(?:more|extra|additional|higher|increase(?:d)?|boost|upgrade)"
        r"[^.?!]{0,28}\blocal(?:\s+(?:calls?|minutes?))?\b"
        r"|\blocal(?:\s+(?:calls?|minutes?))?\b[^.?!]{0,18}"
        r"\b(?:increase|boost|upgrade)\b",
        combined,
        re.IGNORECASE,
    ):
        metrics.append("local_minutes")
    if re.search(
        r"\b(?:more|extra|additional|higher|increase(?:d)?|boost|upgrade)"
        r"[^.?!]{0,34}\binternational(?:\s+(?:calls?|minutes?))?\b"
        r"|\binternational(?:\s+(?:calls?|minutes?))?\b[^.?!]{0,18}"
        r"\b(?:increase|boost|upgrade)\b",
        combined,
        re.IGNORECASE,
    ):
        metrics.append("international_minutes")
    if re.search(
        r"\b(?:more|extra|additional|higher|increase(?:d)?|boost|upgrade)"
        r"[^.?!]{0,24}\b(?:sms|texts?)\b"
        r"|\b(?:sms|texts?)\b[^.?!]{0,18}\b(?:increase|boost|upgrade)\b",
        combined,
        re.IGNORECASE,
    ):
        metrics.append("sms")

    metrics = list(dict.fromkeys(metrics))
    mentions_minutes = bool(
        re.search(r"\b(?:minutes?|calls?|voice)\b", combined, re.IGNORECASE)
    )
    ambiguous_minutes = mentions_minutes and not any(
        metric in metrics
        for metric in ("local_minutes", "international_minutes")
    )
    return metrics, ambiguous_minutes


def resolve_comparative_interpretation(context):
    """Resolve relative increases from the package currently being offered."""

    metrics, ambiguous_minutes = _comparative_metrics(context)
    if ambiguous_minutes:
        return _clarification_from_current(
            context,
            "Would you like more local minutes or more international minutes?",
            ["unqualified minutes"],
        )
    if not metrics:
        return None

    current = _current_requirements_payload(context)
    if current.split:
        labels = ", ".join(metric.replace("_", " ") for metric in metrics)
        return _clarification_from_current(
            context,
            (
                f"Should the additional {labels} apply to every trip period "
                "or to one specific period?"
            ),
            ["split allocation"],
        )

    requirements = current.model_dump()
    offered = _current_plan_allowances(context)
    for metric in metrics:
        baseline = canonical_decimal(
            offered.get(metric, requirements[metric]),
            field=metric,
        )
        requirements[metric] = canonical_string(
            baseline + _SERVICE_INCREMENTS[metric],
            field=metric,
        )
    return RequirementsInterpretation(
        fully_understood=True,
        clarification_required=False,
        clarification_question=None,
        unresolved_fragments=[],
        requirements=CompleteRequirements.model_validate(requirements),
        changed_metrics=metrics,
        preserved_metrics=[
            metric for metric in METRIC_NAMES if metric not in metrics
        ],
    )


def _pending_numeric_interpretation(context):
    original = _pending_original(context)
    answer = str(context.get("raw_user_message") or "")
    amount = re.search(
        r"\b(\d+(?:\.\d+)?)\s+(?:(?:call|voice)\s+)?minutes?\b",
        original,
        re.IGNORECASE,
    )
    if not amount:
        return None
    if re.search(r"\binternational\b", answer, re.IGNORECASE):
        metric = "international_minutes"
    elif re.search(r"\blocal\b", answer, re.IGNORECASE):
        metric = "local_minutes"
    else:
        return None
    current = _current_requirements_payload(context)
    if current.split:
        return _clarification_from_current(
            context,
            (
                "Should those minutes apply to every trip period or to one "
                "specific period?"
            ),
            ["split allocation"],
        )
    requirements = current.model_dump()
    requirements[metric] = canonical_string(amount.group(1), field=metric)
    return RequirementsInterpretation(
        fully_understood=True,
        clarification_required=False,
        clarification_question=None,
        unresolved_fragments=[],
        requirements=CompleteRequirements.model_validate(requirements),
        changed_metrics=[metric],
        preserved_metrics=[
            item for item in METRIC_NAMES if item != metric
        ],
    )


def interpret_requirements_locally(context):
    """Best-effort exact interpreter used when the provider is unavailable."""

    comparative = resolve_comparative_interpretation(context)
    if comparative is not None:
        return comparative
    pending_numeric = _pending_numeric_interpretation(context)
    if pending_numeric is not None:
        return pending_numeric

    current = _current_requirements_payload(context)
    combined = _combined_request(context)
    selection = {
        {
            "data_gb": "total_data_gb",
            "local_minutes": "total_local_minutes",
            "international_minutes": "total_international_minutes",
            "sms": "total_sms",
        }[metric]: float(
            canonical_decimal(value, field=metric)
        )
        for metric, value in _current_plan_allowances(context).items()
        if metric in METRIC_NAMES
    }
    parsed = parse_user_requirements(
        combined,
        current_recommendation={"selection": selection},
        trip_days=current.period_days,
    )
    if "total_call_minutes" in parsed.get("minimums", {}):
        return _clarification_from_current(
            context,
            "Do you mean local minutes or international minutes?",
            ["unqualified minutes"],
        )
    changed = [
        metric
        for metric in METRIC_NAMES
        if metric in parsed.get("minimums", {})
    ]
    if not changed or parsed.get("segments"):
        return None
    if current.split:
        return _clarification_from_current(
            context,
            (
                "Should that change apply to every trip period or to one "
                "specific period?"
            ),
            ["split allocation"],
        )
    requirements = current.model_dump()
    for metric in changed:
        requirements[metric] = canonical_string(
            parsed["minimums"][metric],
            field=metric,
        )
    return RequirementsInterpretation(
        fully_understood=True,
        clarification_required=False,
        clarification_question=None,
        unresolved_fragments=[],
        requirements=CompleteRequirements.model_validate(requirements),
        changed_metrics=changed,
        preserved_metrics=[
            metric for metric in METRIC_NAMES if metric not in changed
        ],
    )


def _apply_safety_guards(decision, context):
    """Enforce the explicit ambiguity rules even if a model over-interprets."""

    comparative = resolve_comparative_interpretation(context)
    if comparative is not None:
        return comparative
    pending_numeric = _pending_numeric_interpretation(context)
    if pending_numeric is not None:
        return pending_numeric
    if decision.clarification_required:
        return decision

    message = str(context.get("raw_user_message") or "")
    pending = context.get("pending_clarification")
    original = (
        str(pending.get("original_request") or "")
        if isinstance(pending, dict)
        else ""
    )
    combined = f"{original} {message}".strip()
    answer_resolves_unit = bool(
        original
        and re.search(r"\b(?:local|international)\b", message, re.IGNORECASE)
    )
    unqualified_minutes = bool(
        re.search(
            r"\b\d+(?:\.\d+)?\s+(?:(?:call|voice)\s+)?minutes?\b",
            combined,
            re.IGNORECASE,
        )
        and not re.search(
            r"\b\d+(?:\.\d+)?\s+(?:local|international)"
            r"(?:\s+call)?\s+minutes?\b",
            combined,
            re.IGNORECASE,
        )
        and not answer_resolves_unit
    )
    if unqualified_minutes:
        return _clarification_from_current(
            context,
            "Do you mean local minutes or international minutes?",
            ["unqualified minutes"],
        )

    unresolved_fewer_calls = bool(
        re.search(
            r"\b(?:fewer|less|lower|reduce)\s+(?:calls?|call minutes?|voice)\b",
            combined,
            re.IGNORECASE,
        )
        and not {
            "local_minutes",
            "international_minutes",
        }.issubset(set(decision.changed_metrics))
    )
    if unresolved_fewer_calls:
        return _clarification_from_current(
            context,
            (
                "What exact local-minute and international-minute amounts "
                "would you like?"
            ),
            ["fewer calls"],
        )
    return decision


def request_requirements_interpretation(
    context,
    *,
    api_key,
    model,
    timeout_seconds=30,
    client=None,
    request_log_dir=None,
    rate_limit_cooldown_seconds=60,
):
    """Call the stateless interpreter and return its strict structured result."""

    if not api_key:
        raise GeminiUnavailable("Gemini is not configured.")
    cooldown_remaining = _rate_limit_remaining()
    if cooldown_remaining:
        raise GeminiRateLimited("Gemini rate-limit cooldown is active.")

    try:
        active_client = client or _make_client(api_key, timeout_seconds)
        api_request = {
            "model": model,
            "system_instruction": INTERPRETER_SYSTEM_INSTRUCTION,
            "input": json.dumps(context, separators=(",", ":"), default=str),
            "generation_config": {"thinking_level": "high"},
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": RequirementsInterpretation.model_json_schema(),
            },
            "store": False,
            "timeout": timeout_seconds,
        }
        _save_request_payload(request_log_dir, "interpreter", api_request)
        interaction = active_client.interactions.create(**api_request)
        output_text = getattr(interaction, "output_text", None)
        if not output_text:
            raise GeminiUnavailable(
                "Gemini did not return interpreted requirements."
            )
        decision = RequirementsInterpretation.model_validate_json(output_text)
        return _apply_safety_guards(decision, context)
    except GeminiUnavailable:
        raise
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
        LOGGER.warning(
            "Gemini requirements parsing failed type=%s",
            type(error).__name__,
        )
        raise GeminiUnavailable(
            "Gemini returned invalid interpreted requirements."
        ) from error
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
                "Gemini interpreter rate limited; cooldown_seconds=%g detail=%s",
                cooldown_seconds,
                _safe_error_detail(error, api_key),
            )
            raise GeminiRateLimited(
                "Gemini is temporarily rate limited."
            ) from error
        LOGGER.warning(
            "Gemini interpreter failed type=%s",
            type(error).__name__,
        )
        raise GeminiUnavailable(
            "Gemini requirements interpretation is temporarily unavailable."
        ) from error


def validate_interpreted_requirements(
    decision,
    expected_period_days,
    current_requirements=None,
):
    """Validate exact totals and independently rebuild numeric split segments."""

    if not isinstance(decision, RequirementsInterpretation):
        decision = RequirementsInterpretation.model_validate(decision)
    requirements = decision.requirements
    if requirements.period_days != int(expected_period_days):
        raise ValueError(
            "Interpreted period_days must match the active trip period."
        )

    totals = {
        metric: canonical_decimal(getattr(requirements, metric), field=metric)
        for metric in METRIC_NAMES
    }
    if current_requirements is not None:
        for metric in decision.preserved_metrics:
            current_value = canonical_decimal(
                current_requirements.get(metric),
                field=metric,
            )
            if totals[metric] != current_value:
                raise ValueError(
                    f"The interpreter changed preserved {metric.replace('_', ' ')}."
                )
    canonical_segments = []
    planner_segments = []
    split_details = requirements.split_details or []
    if requirements.split:
        if not split_details:
            raise ValueError("A split request must include exact split details.")
        expected_day = 1
        segment_totals = {metric: Decimal("0") for metric in METRIC_NAMES}
        for index, raw in enumerate(
            sorted(split_details, key=lambda item: (item.start_day, item.end_day)),
            start=1,
        ):
            if raw.start_day != expected_day or raw.end_day < raw.start_day:
                raise ValueError(
                    "Split details must cover every trip day once without gaps."
                )
            expected_day = raw.end_day + 1
            values = {
                metric: canonical_decimal(getattr(raw, metric), field=metric)
                for metric in METRIC_NAMES
            }
            for metric, value in values.items():
                segment_totals[metric] += value
            canonical_segment = {
                "start_day": raw.start_day,
                "end_day": raw.end_day,
                **{
                    metric: canonical_string(value, field=metric)
                    for metric, value in values.items()
                },
            }
            canonical_segments.append(canonical_segment)
            planner_segments.append(
                {
                    "segment_id": f"segment-{index}",
                    "start_day": raw.start_day,
                    "end_day": raw.end_day,
                    "usage_interpretation": (
                        f"Exact interpreted requirements for Days "
                        f"{raw.start_day}-{raw.end_day}."
                    ),
                    "requirements": {
                        metric: float(value)
                        for metric, value in values.items()
                    },
                    "exact_targets": {},
                }
            )
        if expected_day != requirements.period_days + 1:
            raise ValueError(
                "Split details must end on the final active trip day."
            )
        for metric in METRIC_NAMES:
            if segment_totals[metric] != totals[metric]:
                raise ValueError(
                    f"Split {metric.replace('_', ' ')} values do not equal "
                    "the complete requirement."
                )
    elif split_details:
        raise ValueError("Unsplit requirements cannot include split details.")

    return {
        "requirements": {
            metric: float(value) for metric, value in totals.items()
        },
        "requirement_strings": {
            metric: canonical_string(value, field=metric)
            for metric, value in totals.items()
        },
        "period_days": requirements.period_days,
        "split": requirements.split,
        "split_details": canonical_segments if requirements.split else None,
        "segments": planner_segments,
        "changed_metrics": list(decision.changed_metrics),
        "preserved_metrics": list(decision.preserved_metrics),
    }
