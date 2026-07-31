import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.models import (
    SmartRecommendationHistory,
    User,
    UserMonthlyUsage,
)
from app.services.gemini_recommender import (
    GeminiRateLimited,
    GeminiUnavailable,
    RecommendationDecision,
    request_recommendation_decision,
)
from app.services.gemini_requirements_interpreter import (
    RequirementsInterpretation,
    request_requirements_interpretation,
    validate_interpreted_requirements,
)
from app.services.recommendation_values import METRIC_NAMES, canonical_string
from tests.conftest import login_seeded


def trip(days):
    start = datetime.now(timezone.utc).date() + timedelta(days=60)
    return start.isoformat(), (start + timedelta(days=days - 1)).isoformat()


def complete_interpretation(context, updates=None, *, split_details=None):
    current = dict(context["current_requirements"])
    updates = updates or {}
    for metric, value in updates.items():
        current[metric] = canonical_string(value, field=metric)
    if split_details is not None:
        current["split"] = True
        current["split_details"] = split_details
        for metric in METRIC_NAMES:
            current[metric] = canonical_string(
                sum(Decimal(segment[metric]) for segment in split_details),
                field=metric,
            )
    changed = list(updates)
    if split_details is not None:
        changed = list(METRIC_NAMES)
    return RequirementsInterpretation.model_validate(
        {
            "fully_understood": True,
            "clarification_required": False,
            "clarification_question": None,
            "unresolved_fragments": [],
            "requirements": current,
            "changed_metrics": changed,
            "preserved_metrics": [
                metric for metric in METRIC_NAMES if metric not in changed
            ],
        }
    )


def clarification(context, question="Do you mean local or international minutes?"):
    return RequirementsInterpretation.model_validate(
        {
            "fully_understood": False,
            "clarification_required": True,
            "clarification_question": question,
            "unresolved_fragments": ["unqualified minutes"],
            "requirements": context["current_requirements"],
            "changed_metrics": [],
            "preserved_metrics": list(METRIC_NAMES),
        }
    )


class PlannerStub:
    def __init__(self):
        self.calls = []
        self.invalid_on = set()

    def __call__(self, context, **kwargs):
        self.calls.append((context, kwargs))
        call_number = len(self.calls)
        if call_number in self.invalid_on:
            payload = {
                "trip_segments": [],
                "package_items": [
                    {
                        "package_code": "UNKNOWN",
                        "quantity": 1,
                        "coverage_start_day": 1,
                        "coverage_end_day": context["trip_days"],
                        "activation_order": 1,
                        "assigned_segment_id": None,
                    }
                ],
                "modification_summary": "Invalid test plan.",
            }
        else:
            baseline = context["validated_baseline_plan"]
            payload = {
                "trip_segments": baseline["trip_segments"],
                "package_items": baseline["package_items"],
                "modification_summary": "Selected the lowest-priced valid plan.",
            }
        decision = RecommendationDecision.model_validate(payload)
        decision._interaction_id = f"planner-interaction-{call_number}"
        return decision


class InterpreterStub:
    def __init__(self, factory):
        self.factory = factory
        self.calls = []

    def __call__(self, context, **kwargs):
        self.calls.append((context, kwargs))
        return self.factory(context, len(self.calls))


def configure_two_model_stubs(app, monkeypatch, interpreter):
    planner = PlannerStub()
    app.config.update(
        GEMINI_API_KEY="one-shared-test-key",
        GEMINI_INTERPRETER_MODEL="gemini-3.5-flash-lite",
        GEMINI_PLANNER_MODEL="gemini-3.6-flash",
    )
    monkeypatch.setattr(
        "app.main.routes.request_requirements_interpretation",
        interpreter,
    )
    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        planner,
    )
    return planner


def test_interpreter_request_is_high_thinking_stateless_and_never_gets_packages():
    current = {
        "data_gb": "3.000000",
        "local_minutes": "100.000000",
        "international_minutes": "35.000000",
        "sms": "30.000000",
        "period_days": 7,
        "split": False,
        "split_details": None,
    }
    output = complete_interpretation(
        {"current_requirements": current},
        {"data_gb": 5},
    )

    class FakeInteractions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(output_text=output.model_dump_json())

    client = SimpleNamespace(interactions=FakeInteractions())
    decision = request_requirements_interpretation(
        {
            "raw_user_message": "I need 5 GB",
            "current_requirements": current,
            "trip_context": {"trip_days": 7},
        },
        api_key="shared-key",
        model="gemini-3.5-flash-lite",
        client=client,
    )

    call = client.interactions.calls[0]
    assert decision.fully_understood is True
    assert call["model"] == "gemini-3.5-flash-lite"
    assert call["generation_config"] == {"thinking_level": "high"}
    assert call["store"] is False
    assert "previous_interaction_id" not in call
    assert "active_package_catalogue" not in call["input"]
    assert "package_items" not in call["response_format"]["schema"]["properties"]


def test_unqualified_minutes_is_forced_to_clarification_even_if_model_guesses():
    current = {
        "data_gb": "3.000000",
        "local_minutes": "100.000000",
        "international_minutes": "35.000000",
        "sms": "30.000000",
        "period_days": 7,
        "split": False,
        "split_details": None,
    }
    guessed = complete_interpretation(
        {"current_requirements": current},
        {"local_minutes": 200},
    )
    client = SimpleNamespace(
        interactions=SimpleNamespace(
            create=lambda **_kwargs: SimpleNamespace(
                output_text=guessed.model_dump_json()
            )
        )
    )

    decision = request_requirements_interpretation(
        {
            "raw_user_message": "I need 200 minutes",
            "current_requirements": current,
            "trip_context": {"trip_days": 7},
        },
        api_key="shared-key",
        model="gemini-3.5-flash-lite",
        client=client,
    )

    assert decision.clarification_required is True
    assert "local" in decision.clarification_question.lower()
    assert decision.requirements == RequirementsInterpretation.model_validate(
        {
            "fully_understood": False,
            "clarification_required": True,
            "clarification_question": "Question",
            "unresolved_fragments": ["minutes"],
            "requirements": current,
            "changed_metrics": [],
            "preserved_metrics": list(METRIC_NAMES),
        }
    ).requirements


def test_more_minutes_then_local_resolves_to_next_package_allowance():
    current = {
        "data_gb": "3.000000",
        "local_minutes": "40.000000",
        "international_minutes": "15.000000",
        "sms": "10.000000",
        "period_days": 7,
        "split": False,
        "split_details": None,
    }
    offered = {
        "data_gb": "5.000000",
        "local_minutes": "100.000000",
        "international_minutes": "35.000000",
        "sms": "30.000000",
    }
    guessed = complete_interpretation(
        {"current_requirements": current},
        {"local_minutes": 200},
    )
    first_client = SimpleNamespace(
        interactions=SimpleNamespace(
            create=lambda **_kwargs: SimpleNamespace(
                output_text=guessed.model_dump_json()
            )
        )
    )
    first = request_requirements_interpretation(
        {
            "raw_user_message": "I need more minutes",
            "current_requirements": current,
            "current_plan_allowances": offered,
            "trip_context": {"trip_days": 7},
        },
        api_key="shared-key",
        model="gemini-3.5-flash-lite",
        client=first_client,
    )
    assert first.clarification_required is True
    assert "local" in first.clarification_question.lower()
    assert "international" in first.clarification_question.lower()
    assert "how many" not in first.clarification_question.lower()

    second_context = {
        "raw_user_message": "Local minutes",
        "current_requirements": current,
        "current_plan_allowances": offered,
        "trip_context": {"trip_days": 7},
        "pending_clarification": {
            "original_request": "I need more minutes",
            "prior_answers": [],
        },
    }
    model_asks_for_amount = clarification(
        second_context,
        question="How many local minutes would you like?",
    )
    second_client = SimpleNamespace(
        interactions=SimpleNamespace(
            create=lambda **_kwargs: SimpleNamespace(
                output_text=model_asks_for_amount.model_dump_json()
            )
        )
    )
    resolved = request_requirements_interpretation(
        second_context,
        api_key="shared-key",
        model="gemini-3.5-flash-lite",
        client=second_client,
    )

    assert resolved.fully_understood is True
    assert resolved.clarification_required is False
    assert resolved.changed_metrics == ["local_minutes"]
    assert resolved.requirements.local_minutes == "101.000000"
    assert resolved.requirements.data_gb == current["data_gb"]
    assert resolved.requirements.international_minutes == current[
        "international_minutes"
    ]
    assert resolved.requirements.sms == current["sms"]


def test_unresolved_fewer_calls_fragment_is_not_silently_ignored():
    current = {
        "data_gb": "3.000000",
        "local_minutes": "100.000000",
        "international_minutes": "35.000000",
        "sms": "30.000000",
        "period_days": 7,
        "split": False,
        "split_details": None,
    }
    partial_guess = complete_interpretation(
        {"current_requirements": current},
        {"local_minutes": 200},
    )
    client = SimpleNamespace(
        interactions=SimpleNamespace(
            create=lambda **_kwargs: SimpleNamespace(
                output_text=partial_guess.model_dump_json()
            )
        )
    )

    decision = request_requirements_interpretation(
        {
            "raw_user_message": "I need 200 local minutes and fewer calls",
            "current_requirements": current,
            "trip_context": {"trip_days": 7},
        },
        api_key="shared-key",
        model="gemini-3.5-flash-lite",
        client=client,
    )

    assert decision.clarification_required is True
    assert decision.unresolved_fragments == ["fewer calls"]
    assert "local-minute" in decision.clarification_question.lower()
    assert "international-minute" in decision.clarification_question.lower()


def test_python_rejects_a_changed_value_labeled_as_preserved():
    current = {
        "data_gb": "3.000000",
        "local_minutes": "100.000000",
        "international_minutes": "35.000000",
        "sms": "30.000000",
        "period_days": 7,
        "split": False,
        "split_details": None,
    }
    dishonest = RequirementsInterpretation.model_validate(
        {
            "fully_understood": True,
            "clarification_required": False,
            "clarification_question": None,
            "unresolved_fragments": [],
            "requirements": {**current, "sms": "31.000000"},
            "changed_metrics": ["data_gb"],
            "preserved_metrics": [
                "local_minutes",
                "international_minutes",
                "sms",
            ],
        }
    )

    with pytest.raises(ValueError, match="preserved sms"):
        validate_interpreted_requirements(
            dishonest,
            7,
            current_requirements=current,
        )
    with pytest.raises(ValueError, match="split_details"):
        RequirementsInterpretation.model_validate(
            {
                "fully_understood": True,
                "clarification_required": False,
                "clarification_question": None,
                "unresolved_fragments": [],
                "requirements": {
                    **current,
                    "split_details": [],
                },
                "changed_metrics": [],
                "preserved_metrics": list(METRIC_NAMES),
            }
        )


def test_initial_repeat_skips_both_models_for_same_and_equivalent_other_user(
    app,
    client,
    monkeypatch,
):
    interpreter = InterpreterStub(
        lambda _context, _count: pytest.fail(
            "Initial recommendations must not call the interpreter."
        )
    )
    planner = configure_two_model_stubs(app, monkeypatch, interpreter)
    login_seeded(client, "aisha@example.test")
    start, end = trip(7)
    payload = {
        "destination": "France",
        "start_date": start,
        "end_date": end,
    }

    first = client.post("/api/roaming/recommend", json=payload)
    with client.session_transaction() as active_session:
        assert active_session["roaming_planner_initialized"] is True
        assert active_session["roaming_gemini_interaction_id"] == (
            "planner-interaction-1"
        )
    second = client.post("/api/roaming/recommend", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json["recommendation_source"] == "gemini"
    assert second.json["recommendation_source"] == "smart_history"
    assert len(interpreter.calls) == 0
    assert len(planner.calls) == 1
    first_context, first_kwargs = planner.calls[0]
    assert len(first_context["active_package_catalogue"]) == 42
    assert first_kwargs["model"] == "gemini-3.6-flash"
    assert first_kwargs["api_key"] == "one-shared-test-key"
    assert first_kwargs["previous_interaction_id"] is None
    with client.session_transaction() as active_session:
        assert active_session["roaming_planner_initialized"] is False
        assert "roaming_gemini_interaction_id" not in active_session

    client.post("/auth/logout")
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        omar = User.query.filter_by(email="omar@example.test").one()
        source_rows = UserMonthlyUsage.query.filter_by(
            user_id=aisha.id
        ).order_by(UserMonthlyUsage.usage_month).all()
        target_rows = UserMonthlyUsage.query.filter_by(
            user_id=omar.id
        ).order_by(UserMonthlyUsage.usage_month).all()
        for source, target in zip(source_rows, target_rows, strict=True):
            target.data_gb = source.data_gb
            target.local_minutes = source.local_minutes
            target.international_minutes = source.international_minutes
            target.sms = source.sms
        db.session.commit()
    login_seeded(client, "omar@example.test")
    other_user = client.post("/api/roaming/recommend", json=payload)

    assert other_user.status_code == 200
    assert other_user.json["recommendation_source"] == "smart_history"
    assert len(interpreter.calls) == 0
    assert len(planner.calls) == 1
    with app.app_context():
        row = SmartRecommendationHistory.query.one()
        assert row.hit_count == 2


def test_chat_after_planner_initial_uses_interpreter_then_continues_without_packages(
    app,
    client,
    monkeypatch,
):
    interpreter = InterpreterStub(
        lambda context, _count: complete_interpretation(
            context,
            {"data_gb": 5},
        )
    )
    planner = configure_two_model_stubs(app, monkeypatch, interpreter)
    login_seeded(client)
    start, end = trip(7)
    initial = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )
    refined = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial.json["recommendation_id"],
            "message": "I need 5 GB",
        },
    )

    assert refined.status_code == 200
    assert len(interpreter.calls) == 1
    interpreter_context, interpreter_kwargs = interpreter.calls[0]
    assert interpreter_context["raw_user_message"] == "I need 5 GB"
    assert "active_package_catalogue" not in interpreter_context
    assert interpreter_kwargs["model"] == "gemini-3.5-flash-lite"
    assert interpreter_kwargs["api_key"] == "one-shared-test-key"
    assert len(planner.calls) == 2
    planner_context, planner_kwargs = planner.calls[1]
    assert "active_package_catalogue" not in planner_context
    assert "latest_user_instruction" not in planner_context
    assert planner_context["trip_requirements"]["data_gb"] == "5.000000"
    assert planner_context["current_plan"]["items"]
    assert planner_kwargs["previous_interaction_id"] == (
        "planner-interaction-1"
    )
    assert planner_kwargs["model"] == "gemini-3.6-flash"
    with client.session_transaction() as active_session:
        assert active_session["roaming_planner_initialized"] is True
        assert active_session["roaming_gemini_interaction_id"] == (
            "planner-interaction-2"
        )


def test_smart_initial_bootstraps_planner_then_uses_latest_interaction(
    app,
    client,
    monkeypatch,
):
    values = iter((5, 6))
    interpreter = InterpreterStub(
        lambda context, _count: complete_interpretation(
            context,
            {"data_gb": next(values)},
        )
    )
    planner = configure_two_model_stubs(app, monkeypatch, interpreter)
    login_seeded(client)
    start, end = trip(7)
    payload = {
        "destination": "France",
        "start_date": start,
        "end_date": end,
    }
    client.post("/api/roaming/recommend", json=payload)
    smart_initial = client.post("/api/roaming/recommend", json=payload)
    assert smart_initial.json["smart_history_hit"] is True
    assert len(planner.calls) == 1

    first_chat = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": smart_initial.json[
                "recommendation_id"
            ],
            "message": "I need 5 GB",
        },
    )
    second_chat = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": first_chat.json["recommendation_id"],
            "message": "I need 6 GB",
        },
    )

    assert first_chat.status_code == second_chat.status_code == 200
    bootstrap_context, bootstrap_kwargs = planner.calls[1]
    assert len(bootstrap_context["active_package_catalogue"]) == 42
    assert bootstrap_context["trip_requirements"]["data_gb"] == "5.000000"
    assert bootstrap_context["current_plan"]["items"]
    assert bootstrap_kwargs["previous_interaction_id"] is None
    later_context, later_kwargs = planner.calls[2]
    assert "active_package_catalogue" not in later_context
    assert later_kwargs["previous_interaction_id"] == (
        "planner-interaction-2"
    )
    assert len(interpreter.calls) == 2


def test_history_hit_between_planner_turns_preserves_chain_and_current_state(
    app,
    client,
    monkeypatch,
):
    initial_requirements = {}

    def interpret(context, count):
        if count == 1:
            initial_requirements.update(context["current_requirements"])
            return complete_interpretation(context, {"data_gb": 5})
        if count == 2:
            return RequirementsInterpretation.model_validate(
                {
                    "fully_understood": True,
                    "clarification_required": False,
                    "clarification_question": None,
                        "unresolved_fragments": [],
                        "requirements": initial_requirements,
                        "changed_metrics": list(METRIC_NAMES),
                        "preserved_metrics": [],
                    }
                )
        return complete_interpretation(context, {"data_gb": 6})

    interpreter = InterpreterStub(interpret)
    planner = configure_two_model_stubs(app, monkeypatch, interpreter)
    login_seeded(client)
    start, end = trip(7)
    initial = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )
    five = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial.json["recommendation_id"],
            "message": "I need 5 GB",
        },
    )
    history_hit = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": five.json["recommendation_id"],
            "message": "Use the earlier exact allowance levels",
        },
    )
    assert history_hit.json["smart_history_hit"] is True
    assert history_hit.json["_requirements_state"] == initial.json[
        "_requirements_state"
    ]
    structural_fields = (
        "package_code",
        "quantity",
        "coverage_start_day",
        "coverage_end_day",
        "activation_order",
        "assigned_segment_id",
    )
    assert [
        {field: item.get(field) for field in structural_fields}
        for item in history_hit.json["selection"]["items"]
    ] == [
        {field: item.get(field) for field in structural_fields}
        for item in initial.json["selection"]["items"]
    ]
    assert len(planner.calls) == 2
    with client.session_transaction() as active_session:
        assert active_session["roaming_gemini_interaction_id"] == (
            "planner-interaction-2"
        )

    six = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": history_hit.json[
                "recommendation_id"
            ],
            "message": "I need 6 GB",
        },
    )

    assert six.status_code == 200
    context, kwargs = planner.calls[2]
    assert kwargs["previous_interaction_id"] == "planner-interaction-2"
    assert "active_package_catalogue" not in context
    assert context["trip_requirements"]["data_gb"] == "6.000000"
    assert context["current_plan"]["items"] == [
        {
            "package_code": item["package_code"],
            "quantity": item["quantity"],
            "coverage_start_day": item["coverage_start_day"],
            "coverage_end_day": item["coverage_end_day"],
            "activation_order": item["activation_order"],
            "assigned_segment_id": item.get("assigned_segment_id"),
        }
        for item in history_hit.json["selection"]["items"]
    ]


def test_clarification_skips_history_and_planner_and_returns_pending_context(
    app,
    client,
    monkeypatch,
):
    def interpret(context, count):
        if count == 1:
            return clarification(context)
        assert context["pending_clarification"]["original_request"] == (
            "I need 200 minutes"
        )
        assert context["raw_user_message"] == "Local minutes"
        return complete_interpretation(
            context,
            {"local_minutes": 200},
        )

    interpreter = InterpreterStub(interpret)
    planner = configure_two_model_stubs(app, monkeypatch, interpreter)
    history_calls = []
    original_lookup = __import__(
        "app.services.roaming_recommendation",
        fromlist=["find_valid_history_plan"],
    ).find_valid_history_plan

    def tracked_lookup(*args, **kwargs):
        history_calls.append(True)
        return original_lookup(*args, **kwargs)

    monkeypatch.setattr(
        "app.services.roaming_recommendation.find_valid_history_plan",
        tracked_lookup,
    )
    login_seeded(client)
    start, end = trip(7)
    initial = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )
    history_calls.clear()
    ambiguous = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial.json["recommendation_id"],
            "message": "I need 200 minutes",
        },
    )

    assert ambiguous.status_code == 200
    assert ambiguous.json["clarification_required"] is True
    assert ambiguous.json["recommendation_id"] == initial.json[
        "recommendation_id"
    ]
    assert history_calls == []
    assert len(planner.calls) == 1

    resolved = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial.json["recommendation_id"],
            "message": "Local minutes",
        },
    )
    assert resolved.status_code == 200
    assert len(interpreter.calls) == 2
    assert history_calls


def test_more_minutes_clarification_uses_only_interpreter_until_local_is_known(
    app,
    client,
    monkeypatch,
):
    class ProviderBackedInterpreter:
        def __init__(self):
            self.calls = []

        def __call__(self, context, **kwargs):
            self.calls.append((context, kwargs))
            if len(self.calls) == 1:
                model_output = complete_interpretation(
                    context,
                    {"local_minutes": 200},
                )
            else:
                model_output = clarification(
                    context,
                    question="How many local minutes would you like?",
                )
            provider = SimpleNamespace(
                interactions=SimpleNamespace(
                    create=lambda **_request: SimpleNamespace(
                        output_text=model_output.model_dump_json()
                    )
                )
            )
            return request_requirements_interpretation(
                context,
                api_key=kwargs["api_key"],
                model=kwargs["model"],
                client=provider,
            )

    interpreter = ProviderBackedInterpreter()
    planner = configure_two_model_stubs(
        app,
        monkeypatch,
        interpreter,
    )
    login_seeded(client)
    start, end = trip(7)
    initial = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )
    current_local = initial.json["selection"]["total_local_minutes"]

    ambiguous = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial.json["recommendation_id"],
            "message": "I need more minutes",
        },
    )
    assert ambiguous.status_code == 200
    assert ambiguous.json["clarification_required"] is True
    assert "local" in ambiguous.json["message"].lower()
    assert "international" in ambiguous.json["message"].lower()
    assert "how many" not in ambiguous.json["message"].lower()
    assert len(interpreter.calls) == 1
    assert len(planner.calls) == 1

    resolved = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial.json["recommendation_id"],
            "message": "Local minutes",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json["response_type"] == "recommendation"
    assert len(interpreter.calls) == 2
    assert len(planner.calls) == 2
    planner_context, planner_kwargs = planner.calls[1]
    assert planner_context["trip_requirements"]["local_minutes"] == (
        canonical_string(current_local + 1, field="local_minutes")
    )
    assert planner_context["trip_requirements"]["data_gb"] == (
        canonical_string(
            initial.json["selection"]["total_data_gb"],
            field="data_gb",
        )
    )
    assert planner_context["trip_requirements"][
        "international_minutes"
    ] == canonical_string(
        initial.json["selection"]["total_international_minutes"],
        field="international_minutes",
    )
    assert planner_context["trip_requirements"]["sms"] == canonical_string(
        initial.json["selection"]["total_sms"],
        field="sms",
    )
    assert planner_kwargs["previous_interaction_id"] == (
        "planner-interaction-1"
    )


@pytest.mark.parametrize(
    ("error_type", "expected_limit"),
    [
        (GeminiRateLimited, True),
        (GeminiUnavailable, False),
    ],
)
def test_interpreter_failure_uses_python_adjustment_instead_of_giving_up(
    app,
    client,
    monkeypatch,
    error_type,
    expected_limit,
):
    def unavailable_interpreter(_context, **_kwargs):
        raise error_type("provider unavailable for test")

    planner = configure_two_model_stubs(
        app,
        monkeypatch,
        unavailable_interpreter,
    )
    login_seeded(client)
    start, end = trip(7)
    initial = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )
    current = initial.json["selection"]

    refined = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial.json["recommendation_id"],
            "message": "I need more local minutes",
        },
    )

    assert refined.status_code == 200
    assert refined.json["response_type"] == "recommendation"
    assert refined.json["recommendation_source"] == "fallback"
    assert refined.json["gemini_rate_limited"] is expected_limit
    assert refined.json["selection"]["total_local_minutes"] > (
        current["total_local_minutes"]
    )
    assert refined.json["selection"]["total_data_gb"] >= (
        current["total_data_gb"]
    )
    assert refined.json["selection"]["total_international_minutes"] >= (
        current["total_international_minutes"]
    )
    assert refined.json["selection"]["total_sms"] >= current["total_sms"]
    assert len(planner.calls) == 1
    assert "could not safely interpret" not in refined.json[
        "chat_message"
    ].lower()
    if expected_limit:
        assert "Gemini limit:" in refined.json[
            "chat_message"
        ]
    with client.session_transaction() as active_session:
        assert active_session["roaming_gemini_interaction_id"] == (
            "planner-interaction-1"
        )


def test_split_interpretation_is_summed_by_python_and_uses_exact_split_key(
    app,
    client,
    monkeypatch,
):
    split_details = [
        {
            "start_day": 1,
            "end_day": 1,
            "data_gb": "1.000000",
            "local_minutes": "10.000000",
            "international_minutes": "5.000000",
            "sms": "2.000000",
        },
        {
            "start_day": 2,
            "end_day": 3,
            "data_gb": "0.500000",
            "local_minutes": "20.000000",
            "international_minutes": "5.000000",
            "sms": "2.000000",
        },
    ]
    interpreter = InterpreterStub(
        lambda context, _count: complete_interpretation(
            context,
            split_details=split_details,
        )
    )
    planner = configure_two_model_stubs(app, monkeypatch, interpreter)
    login_seeded(client, "omar@example.test")
    start, end = trip(3)
    initial = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )
    split = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial.json["recommendation_id"],
            "message": "Split the trip into these exact periods",
        },
    )

    assert split.status_code == 200
    context, _kwargs = planner.calls[1]
    assert context["trip_requirements"] == {
        "data_gb": "1.500000",
        "local_minutes": "30.000000",
        "international_minutes": "10.000000",
        "sms": "4.000000",
    }
    assert context["exact_split_requirements"] == split_details
    with app.app_context():
        row = SmartRecommendationHistory.query.filter_by(split=True).one()
        assert row.data_gb == Decimal("1.500000")
        assert row.local_minutes == Decimal("30.000000")
        assert row.international_minutes == Decimal("10.000000")
        assert row.sms == Decimal("4.000000")
        assert row.split_signature != "UNSPLIT"

    repeated = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": split.json["recommendation_id"],
            "message": "Keep these exact split periods",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json["smart_history_hit"] is True
    assert repeated.json["_requirements_state"] == split.json[
        "_requirements_state"
    ]
    assert len(planner.calls) == 2

    bad = complete_interpretation(
        {
            "current_requirements": {
                **split.json["_requirements_state"],
                "split": False,
                "split_details": None,
            }
        },
        split_details=split_details,
    )
    bad.requirements.data_gb = "2.000000"
    with pytest.raises(ValueError, match="do not equal"):
        validate_interpreted_requirements(bad, 3)


def test_invalid_planner_output_does_not_advance_interaction_id(
    app,
    client,
    monkeypatch,
):
    interpreter = InterpreterStub(
        lambda context, _count: complete_interpretation(
            context,
            {"data_gb": 5},
        )
    )
    planner = configure_two_model_stubs(app, monkeypatch, interpreter)
    planner.invalid_on.add(2)
    login_seeded(client)
    start, end = trip(7)
    initial = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )
    refined = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial.json["recommendation_id"],
            "message": "I need 5 GB",
        },
    )

    assert refined.status_code == 200
    assert refined.json["recommendation_source"] == "fallback"
    with client.session_transaction() as active_session:
        assert active_session["roaming_gemini_interaction_id"] == (
            "planner-interaction-1"
        )


def test_planner_request_is_stored_high_thinking_and_uses_configured_model():
    output = {
        "trip_segments": [],
        "package_items": [
            {
                "package_code": "ESS-7D",
                "quantity": 1,
                "coverage_start_day": 1,
                "coverage_end_day": 7,
                "activation_order": 1,
                "assigned_segment_id": None,
            }
        ],
        "modification_summary": "Selected one valid plan.",
    }

    class FakeInteractions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                id="planner-id",
                output_text=json.dumps(output),
            )

    client = SimpleNamespace(interactions=FakeInteractions())
    request_recommendation_decision(
        {
            "trip_requirements": dict.fromkeys(METRIC_NAMES, "1.000000"),
            "active_package_catalogue": [],
        },
        api_key="shared-key",
        model="gemini-3.6-flash",
        client=client,
    )
    call = client.interactions.calls[0]
    assert call["model"] == "gemini-3.6-flash"
    assert call["generation_config"] == {"thinking_level": "high"}
    assert call["store"] is True
    with pytest.raises(ValueError):
        RecommendationDecision.model_validate(
            {**output, "modification_summary": ""}
        )
