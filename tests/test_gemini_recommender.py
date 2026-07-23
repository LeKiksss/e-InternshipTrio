import json
from types import SimpleNamespace

import pytest

from app.models import User
from app.services.gemini_recommender import (
    GeminiConversationUnavailable,
    GeminiRateLimited,
    GeminiUnavailable,
    RecommendationDecision,
    _rate_limit_remaining,
    request_recommendation_decision,
    reset_rate_limit_cooldown,
)
from app.services.roaming_recommendation import build_recommendation


def valid_decision(code="ESS-7D"):
    return {
        "interpreted_latest_request": None,
        "trip_segments": [],
        "package_items": [
            {
                "package_code": code,
                "quantity": 1,
                "coverage_start_day": 1,
                "coverage_end_day": 7,
                "activation_order": 1,
                "assigned_segment_id": None,
                "reason_for_item": "Covers this trip.",
            }
        ],
        "reason": "Complete validated coverage.",
        "why_it_fits": ["It covers the full trip."],
        "usage_summary": "Allowances meet the calculated usage.",
        "modification_summary": "Selected the lowest-priced valid plan.",
        "tradeoff_summary": None,
    }


class FakeInteractions:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.calls = []
        self.sequence = 0

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        self.sequence += 1
        return SimpleNamespace(
            id=f"interaction-{self.sequence}",
            output_text=self.output,
        )


class FakeClient:
    def __init__(self, output=None, error=None):
        self.interactions = FakeInteractions(output, error)


class RateLimitError(Exception):
    pass


def test_structured_interactions_request_uses_compact_schema_and_high_thinking():
    client = FakeClient(json.dumps(valid_decision()))
    result = request_recommendation_decision(
        {"destination": "France", "active_package_catalogue": []},
        api_key="configured-for-test",
        model="gemini-3.6-flash",
        client=client,
    )
    assert isinstance(result, RecommendationDecision)
    call = client.interactions.calls[0]
    assert call["model"] == "gemini-3.6-flash"
    assert call["generation_config"] == {"thinking_level": "high"}
    assert call["response_format"]["mime_type"] == "application/json"
    assert call["response_format"]["schema"] == RecommendationDecision.model_json_schema()
    assert call["store"] is True
    assert "previous_interaction_id" not in call
    assert result._interaction_id == "interaction-1"
    assert "password" not in call["input"].lower()
    assert "cheapest valid structural roaming plan" in call["system_instruction"]
    schema_properties = call["response_format"]["schema"]["properties"]
    assert set(schema_properties) == {
        "trip_segments",
        "package_items",
        "modification_summary",
    }


def test_each_gemini_api_call_saves_its_request_as_json(tmp_path):
    request_log_dir = tmp_path / "api_request_logs"
    client = FakeClient(json.dumps(valid_decision()))
    calls = (
        (
            {
                "destination": "France",
                "active_package_catalogue": [{"package_code": "ESS-7D"}],
            },
            {},
            "initial",
        ),
        (
            {"destination": "France", "latest_user_instruction": "Give me more data"},
            {},
            "refinement",
        ),
    )

    previous_interaction_id = None
    for context, extra, _kind in calls:
        result = request_recommendation_decision(
            context,
            api_key="configured-for-test",
            model="gemini-3.6-flash",
            client=client,
            request_log_dir=request_log_dir,
            previous_interaction_id=previous_interaction_id,
            **extra,
        )
        previous_interaction_id = result._interaction_id

    files = list(request_log_dir.glob("*.json"))
    assert len(files) == len(client.interactions.calls) == 2
    saved = {
        payload["request_kind"]: payload
        for payload in (
            json.loads(path.read_text(encoding="utf-8")) for path in files
        )
    }
    assert set(saved) == {"planner_initial", "planner_refinement"}
    initial_log = saved["planner_initial"]
    refinement_log = saved["planner_refinement"]
    assert initial_log["api_method"] == "interactions.create"
    assert initial_log["request"]["input"]["destination"] == "France"
    assert initial_log["request"]["input"]["active_package_catalogue"] == [
        {"package_code": "ESS-7D"}
    ]
    assert refinement_log["request"]["input"]["latest_user_instruction"] == (
        "Give me more data"
    )
    assert (
        "active_package_catalogue"
        not in refinement_log["request"]["input"]
    )
    assert initial_log["request"]["store"] is True
    assert "previous_interaction_id" not in initial_log["request"]
    assert refinement_log["request"]["previous_interaction_id"] == (
        "interaction-1"
    )
    assert initial_log["request"]["generation_config"] == {
        "thinking_level": "high"
    }
    assert "configured-for-test" not in json.dumps(saved)


def test_missing_stored_conversation_is_reported_separately():
    error = RuntimeError("Previous interaction was not found")
    error.status_code = 404

    with pytest.raises(GeminiConversationUnavailable):
        request_recommendation_decision(
            {"latest_user_instruction": "Give me more data"},
            api_key="configured-for-test",
            model="gemini-3.6-flash",
            client=FakeClient(error=error),
            previous_interaction_id="expired-interaction",
        )

def test_missing_key_timeout_and_parse_failures_are_safe():
    with pytest.raises(GeminiUnavailable):
        request_recommendation_decision(
            {}, api_key="", model="gemini-3.6-flash", client=FakeClient("{}")
        )
    with pytest.raises(GeminiUnavailable):
        request_recommendation_decision(
            {},
            api_key="configured-for-test",
            model="gemini-3.6-flash",
            client=FakeClient(error=TimeoutError("timed out")),
        )
    with pytest.raises(GeminiUnavailable):
        request_recommendation_decision(
            {},
            api_key="configured-for-test",
            model="gemini-3.6-flash",
            client=FakeClient("not json"),
        )


def test_rate_limit_starts_cooldown_and_skips_the_next_provider_call():
    reset_rate_limit_cooldown()
    limited = FakeClient(error=RateLimitError("quota exhausted"))
    healthy = FakeClient(json.dumps(valid_decision()))
    try:
        with pytest.raises(GeminiRateLimited):
            request_recommendation_decision(
                {"destination": "France"},
                api_key="configured-for-test",
                model="gemini-3.6-flash",
                client=limited,
                rate_limit_cooldown_seconds=60,
            )
        with pytest.raises(GeminiRateLimited):
            request_recommendation_decision(
                {"destination": "France"},
                api_key="configured-for-test",
                model="gemini-3.6-flash",
                client=healthy,
                rate_limit_cooldown_seconds=60,
            )
        assert len(limited.interactions.calls) == 1
        assert healthy.interactions.calls == []
    finally:
        reset_rate_limit_cooldown()


def test_provider_retry_delay_overrides_the_long_fallback_cooldown():
    reset_rate_limit_cooldown()
    limited = FakeClient(
        error=RateLimitError("Quota exceeded. Please retry in 2.25s.")
    )
    try:
        with pytest.raises(GeminiRateLimited):
            request_recommendation_decision(
                {"destination": "France"},
                api_key="configured-for-test",
                model="gemini-3.6-flash",
                client=limited,
                rate_limit_cooldown_seconds=60,
            )
        assert 2 < _rate_limit_remaining() < 4
    finally:
        reset_rate_limit_cooldown()


def test_back_to_back_requests_keep_working_during_rate_limit_cooldown(app):
    reset_rate_limit_cooldown()
    limited = FakeClient(error=RateLimitError("too many requests"))
    app.config["GEMINI_API_KEY"] = "configured-for-test"
    try:
        with app.app_context():
            omar = User.query.filter_by(email="omar@example.test").one()
            initial = build_recommendation(
                omar,
                "France",
                "2030-08-01",
                "2030-08-03",
                gemini_client=limited,
            )
            calls_plan = build_recommendation(
                omar,
                "France",
                "2030-08-01",
                "2030-08-03",
                latest_message="I need 200 local minutes",
                current_recommendation=initial,
                gemini_client=limited,
            )
            cheaper = build_recommendation(
                omar,
                "France",
                "2030-08-01",
                "2030-08-03",
                latest_message=(
                    "nevermind go cheap and focus on calls, "
                    "my budget is like 30dhs"
                ),
                current_recommendation=calls_plan,
                gemini_client=limited,
            )

        assert len(limited.interactions.calls) == 1
        assert calls_plan["selection"]["total_local_minutes"] >= 200
        assert calls_plan["selection"]["items"][0]["package_code"] == "VP-3D"
        assert calls_plan["gemini_rate_limited"] is True
        assert "Gemini request limit was reached" in calls_plan["chat_message"]
        assert cheaper["selection"]["items"][0]["package_code"] == "ESS-3D"
        assert cheaper["gemini_rate_limited"] is True
        assert "Gemini request limit was reached" in cheaper["chat_message"]
        assert "maximum price" in cheaper["chat_message"]
    finally:
        reset_rate_limit_cooldown()


def test_orchestrator_sends_all_packages_without_personal_contact_details(app, monkeypatch):
    captured = []

    def fake_request(context, **_kwargs):
        captured.append(context)
        return valid_decision()

    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        fake_request,
    )
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        result = build_recommendation(
            aisha, "France", "2030-08-01", "2030-08-07", today=None
        )
    assert result["source"] == "gemini"
    context = captured[0]
    assert len(context["active_package_catalogue"]) == 42
    assert context["validated_baseline_plan"]["package_items"]
    assert context["validated_baseline_plan"]["total_price_aed"] > 0
    serialized = json.dumps(context).lower()
    assert len(json.dumps(context, separators=(",", ":"))) < 7500
    assert "raw_monthly_usage" not in context
    assert "weighted_monthly_profile" not in context
    assert "aisha@example.test" not in serialized
    assert "+971500000101" not in serialized
    assert "password" not in serialized


def test_orchestrator_excludes_omars_march_spike_from_gemini_requirements(
    app, monkeypatch
):
    captured = []

    def fake_request(context, **_kwargs):
        captured.append(context)
        return valid_decision("RLH-7D")

    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        fake_request,
    )
    with app.app_context():
        omar = User.query.filter_by(email="omar@example.test").one()
        result = build_recommendation(
            omar, "France", "2030-08-01", "2030-08-07", today=None
        )

    assert result["source"] == "gemini"
    context = captured[0]
    assert len(result["usage_analysis"]["outliers_detected"]) == 4
    assert {
        row["usage_month"] for row in result["usage_analysis"]["outliers_detected"]
    } == {"2026-03-01"}
    assert float(context["trip_requirements"]["data_gb"]) == pytest.approx(
        3.469, abs=0.001
    )
    assert "selection_requirements" not in context


def test_invalid_plan_uses_fallback_without_a_second_api_call(app, monkeypatch):
    calls = []

    def fake_request(_context, **kwargs):
        calls.append(kwargs)
        decision = RecommendationDecision.model_validate(
            valid_decision("UNKNOWN")
        )
        decision._interaction_id = "invalid-plan-interaction"
        return decision

    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        fake_request,
    )
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        interaction_state = {}
        result = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-07",
            interaction_state=interaction_state,
        )
    assert len(calls) == 1
    assert interaction_state == {}
    assert result["source"] == "deterministic_fallback"
    assert result["selection"]["total_validity_days"] == 7


def test_repeated_trip_wide_violation_uses_valid_full_trip_fallback(app, monkeypatch):
    with app.app_context():
        omar = User.query.filter_by(email="omar@example.test").one()
        initial = build_recommendation(
            omar, "France", "2030-08-01", "2030-08-03"
        )

        invalid = valid_decision()
        invalid["package_items"] = [
            {
                "package_code": code,
                "quantity": 1,
                "coverage_start_day": day,
                "coverage_end_day": day,
                "activation_order": day,
                "assigned_segment_id": None,
                "reason_for_item": "Covers one day.",
            }
            for day, code in enumerate(("ESS-1D", "RLH-1D", "VF-1D"), start=1)
        ]
        calls = []

        def fake_request(_context, **kwargs):
            calls.append(kwargs)
            return invalid

        monkeypatch.setattr(
            "app.services.roaming_recommendation.request_recommendation_decision",
            fake_request,
        )
        result = build_recommendation(
            omar,
            "France",
            "2030-08-01",
            "2030-08-03",
            latest_message="I need 200 local minutes",
            current_recommendation=initial,
        )

    assert len(calls) == 1
    assert result["source"] == "deterministic_fallback"
    assert [
        (item["package_code"], item["coverage_start_day"], item["coverage_end_day"])
        for item in result["selection"]["items"]
    ] == [("VP-3D", 1, 3)]


def test_missing_api_key_fallback_does_not_crash(app):
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        result = build_recommendation(
            aisha, "France", "2030-08-01", "2030-08-07"
        )
    assert result["source"] == "deterministic_fallback"
    assert result["selection"]["items"]


def test_refinement_calls_gemini_again_and_latest_message_is_highest_priority(
    app, monkeypatch
):
    calls = []
    responses = [valid_decision("ESS-7D"), valid_decision("DP-7D")]

    def fake_request(context, **kwargs):
        calls.append((context, kwargs.get("previous_interaction_id")))
        decision = RecommendationDecision.model_validate(responses.pop(0))
        decision._interaction_id = f"interaction-{len(calls)}"
        return decision

    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        fake_request,
    )
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        initial_state = {}
        initial = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-07",
            interaction_state=initial_state,
        )
        refinement_state = {}
        refined = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-07",
            latest_message="Give me more data",
            current_recommendation=initial,
            conversation=[{"role": "user", "content": "private prior chat"}],
            previous_interaction_id=initial_state["interaction_id"],
            interaction_state=refinement_state,
        )
    assert len(calls) == 2
    initial_context, initial_previous = calls[0]
    refinement_context, refinement_previous = calls[1]
    assert len(initial_context["active_package_catalogue"]) == 42
    assert initial_previous is None
    assert refinement_previous == "interaction-1"
    assert "active_package_catalogue" not in refinement_context
    assert refinement_context["latest_user_instruction"] == "Give me more data"
    assert "recent_conversation" not in refinement_context
    assert "private prior chat" not in json.dumps(refinement_context)
    assert refinement_context["active_constraints"]["minimums"]["data_gb"] == 3.001
    assert refinement_context["active_constraints"]["preservation_minimums"] == {
        "local_minutes": initial["selection"]["total_local_minutes"],
        "international_minutes": initial["selection"][
            "total_international_minutes"
        ],
        "sms": initial["selection"]["total_sms"],
    }
    assert refinement_state["interaction_id"] == "interaction-2"
    assert refined["selection"]["total_data_gb"] >= 3.75


def test_refinement_without_a_stored_interaction_bootstraps_with_catalogue(
    app,
    monkeypatch,
):
    captured = []

    def fake_request(context, **kwargs):
        captured.append((context, kwargs.get("previous_interaction_id")))
        decision = RecommendationDecision.model_validate(
            {
                "trip_segments": context["validated_baseline_plan"][
                    "trip_segments"
                ],
                "package_items": context["validated_baseline_plan"][
                    "package_items"
                ],
                "modification_summary": "Kept the closest valid plan.",
            }
        )
        decision._interaction_id = "bootstrapped-interaction"
        return decision

    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        initial = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-07",
        )
        app.config["GEMINI_API_KEY"] = "configured-for-test"
        monkeypatch.setattr(
            "app.services.roaming_recommendation.request_recommendation_decision",
            fake_request,
        )
        interaction_state = {}
        build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-07",
            latest_message="Keep this recommendation",
            current_recommendation=initial,
            previous_interaction_id=None,
            interaction_state=interaction_state,
        )

    context, previous_interaction_id = captured[0]
    assert len(context["active_package_catalogue"]) == 42
    assert previous_interaction_id is None
    assert interaction_state["interaction_id"] == "bootstrapped-interaction"


@pytest.mark.parametrize(
    ("end_date", "package_items", "expected_activations"),
    [
        (
            "2030-08-06",
            [
                {
                    "package_code": "ESS-3D",
                    "quantity": 2,
                    "coverage_start_day": 1,
                    "coverage_end_day": 6,
                    "activation_order": 1,
                    "assigned_segment_id": None,
                    "reason_for_item": "Two ordered activations cover six days.",
                }
            ],
            2,
        ),
        (
            "2030-08-04",
            [
                {
                    "package_code": "ESS-1D",
                    "quantity": 1,
                    "coverage_start_day": 1,
                    "coverage_end_day": 1,
                    "activation_order": 1,
                    "assigned_segment_id": None,
                    "reason_for_item": "Covers the first day.",
                },
                {
                    "package_code": "ESS-3D",
                    "quantity": 1,
                    "coverage_start_day": 2,
                    "coverage_end_day": 4,
                    "activation_order": 2,
                    "assigned_segment_id": None,
                    "reason_for_item": "Covers the remaining days.",
                },
            ],
            2,
        ),
    ],
)
def test_gemini_repeated_and_mixed_plans_flow_through_validation(
    app, monkeypatch, end_date, package_items, expected_activations
):
    payload = valid_decision()
    payload["package_items"] = package_items
    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        lambda _context, **_kwargs: payload,
    )
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        result = build_recommendation(
            aisha, "France", "2030-08-01", end_date
        )
    assert result["source"] == "gemini"
    assert result["selection"]["activation_count"] == expected_activations
    assert result["selection"]["total_validity_days"] == result["trip"]["trip_days"]


def test_gemini_segmented_plan_flows_through_segment_validation(app, monkeypatch):
    segments = [
        {
            "segment_id": "segment-1",
            "start_day": 1,
            "end_day": 7,
            "usage_interpretation": "Wi-Fi available with light data use",
            "data_requirement_gb": 1,
            "local_minutes_requirement": 30,
            "international_minutes_requirement": 6,
            "sms_requirement": 4,
        },
        {
            "segment_id": "segment-2",
            "start_day": 8,
            "end_day": 14,
            "usage_interpretation": "Higher data use during the second week",
            "data_requirement_gb": 9,
            "local_minutes_requirement": 30,
            "international_minutes_requirement": 6,
            "sms_requirement": 4,
        },
    ]
    payload = valid_decision()
    payload["trip_segments"] = segments
    payload["package_items"] = [
        {
                "package_code": "RLH-7D",
            "quantity": 1,
            "coverage_start_day": 1,
            "coverage_end_day": 7,
            "activation_order": 1,
            "assigned_segment_id": "segment-1",
            "reason_for_item": "Light first-week coverage.",
        },
        {
            "package_code": "DP-7D",
            "quantity": 1,
            "coverage_start_day": 8,
            "coverage_end_day": 14,
            "activation_order": 2,
            "assigned_segment_id": "segment-2",
            "reason_for_item": "Higher second-week data coverage.",
        },
    ]
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        current = build_recommendation(
            aisha, "France", "2030-08-01", "2030-08-14"
        )
        monkeypatch.setattr(
            "app.services.roaming_recommendation.request_recommendation_decision",
            lambda _context, **_kwargs: payload,
        )
        result = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-14",
            latest_message=(
                "For the first week I will have Wi-Fi and need light usage, "
                "and I need heavy data in the second week."
            ),
            current_recommendation=current,
        )
    assert result["source"] == "gemini"
    assert len(result["segments"]) == 2
    assert [item["assigned_segment_id"] for item in result["selection"]["items"]] == [
        "segment-1",
        "segment-2",
    ]
