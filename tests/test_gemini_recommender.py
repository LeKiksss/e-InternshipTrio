import json
from types import SimpleNamespace

import pytest

from app.models import User
from app.services.gemini_recommender import (
    GeminiUnavailable,
    RecommendationDecision,
    request_recommendation_decision,
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
        "modification_summary": None,
        "tradeoff_summary": None,
    }


class FakeInteractions:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(output_text=self.output)


class FakeClient:
    def __init__(self, output=None, error=None):
        self.interactions = FakeInteractions(output, error)


def test_structured_interactions_request_uses_model_schema_and_high_thinking():
    client = FakeClient(json.dumps(valid_decision()))
    result = request_recommendation_decision(
        {"destination": "France", "active_package_catalogue": []},
        api_key="configured-for-test",
        model="gemini-3.5-flash",
        client=client,
    )
    assert isinstance(result, RecommendationDecision)
    call = client.interactions.calls[0]
    assert call["model"] == "gemini-3.5-flash"
    assert call["generation_config"] == {"thinking_level": "high"}
    assert call["response_format"]["mime_type"] == "application/json"
    assert call["response_format"]["schema"] == RecommendationDecision.model_json_schema()
    assert call["store"] is False
    assert "password" not in call["input"].lower()


def test_each_gemini_api_call_saves_its_request_as_json(tmp_path):
    request_log_dir = tmp_path / "api_request_logs"
    client = FakeClient(json.dumps(valid_decision()))
    calls = (
        ({"destination": "France"}, {}, "initial"),
        (
            {"destination": "France", "latest_user_message": "Give me more data"},
            {},
            "refinement",
        ),
        (
            {"destination": "France"},
            {
                "invalid_decision": {"package_items": []},
                "validation_errors": ["Coverage is missing."],
            },
            "correction",
        ),
    )

    for context, extra, _kind in calls:
        request_recommendation_decision(
            context,
            api_key="configured-for-test",
            model="gemini-3.5-flash",
            client=client,
            request_log_dir=request_log_dir,
            **extra,
        )

    files = list(request_log_dir.glob("*.json"))
    assert len(files) == len(client.interactions.calls) == 3
    saved = {
        payload["request_kind"]: payload
        for payload in (
            json.loads(path.read_text(encoding="utf-8")) for path in files
        )
    }
    assert set(saved) == {"initial", "refinement", "correction"}
    assert saved["initial"]["api_method"] == "interactions.create"
    assert saved["initial"]["request"]["input"]["destination"] == "France"
    assert saved["refinement"]["request"]["input"]["latest_user_message"] == (
        "Give me more data"
    )
    assert saved["correction"]["request"]["input"]["CORRECTION_REQUEST"][
        "validation_errors"
    ] == ["Coverage is missing."]
    assert saved["initial"]["request"]["generation_config"] == {
        "thinking_level": "high"
    }
    assert "configured-for-test" not in json.dumps(saved)


def test_correction_request_contains_validation_errors():
    client = FakeClient(json.dumps(valid_decision()))
    request_recommendation_decision(
        {"destination": "France"},
        api_key="configured-for-test",
        model="gemini-3.5-flash",
        client=client,
        invalid_decision={"package_items": []},
        validation_errors=["Coverage is missing."],
    )
    payload = json.loads(client.interactions.calls[0]["input"])
    assert payload["CORRECTION_REQUEST"]["validation_errors"] == [
        "Coverage is missing."
    ]


def test_missing_key_timeout_and_parse_failures_are_safe():
    with pytest.raises(GeminiUnavailable):
        request_recommendation_decision(
            {}, api_key="", model="gemini-3.5-flash", client=FakeClient("{}")
        )
    with pytest.raises(GeminiUnavailable):
        request_recommendation_decision(
            {},
            api_key="configured-for-test",
            model="gemini-3.5-flash",
            client=FakeClient(error=TimeoutError("timed out")),
        )
    with pytest.raises(GeminiUnavailable):
        request_recommendation_decision(
            {},
            api_key="configured-for-test",
            model="gemini-3.5-flash",
            client=FakeClient("not json"),
        )


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
    serialized = json.dumps(context).lower()
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
    assert context["usage_analysis_policy"] == {
        "method": "successive_month_comparison",
        "threshold_percent": 30.0,
        "excluded_values_used_for_profile": False,
    }
    assert len(context["detected_outliers"]) == 4
    assert {
        row["usage_month"] for row in context["detected_outliers"]
    } == {"2026-03-01"}
    assert context["raw_monthly_usage"][2]["data_gb"] == 61.0
    assert context["weighted_monthly_profile"]["data_gb"] == pytest.approx(
        14.867, abs=0.001
    )
    assert context["trip_requirements"]["data_gb"] == pytest.approx(
        3.469, abs=0.001
    )
    assert "buffer" not in json.dumps(context).lower()


def test_invalid_first_plan_gets_one_correction_retry(app, monkeypatch):
    responses = [valid_decision("UNKNOWN"), valid_decision("ESS-7D")]
    calls = []

    def fake_request(_context, **kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        fake_request,
    )
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        result = build_recommendation(
            aisha, "France", "2030-08-01", "2030-08-07"
        )
    assert result["source"] == "gemini"
    assert len(calls) == 2
    assert calls[1]["validation_errors"]
    assert calls[1]["invalid_decision"]["package_items"][0]["package_code"] == "UNKNOWN"


def test_second_invalid_plan_uses_deterministic_fallback(app, monkeypatch):
    calls = []

    def fake_request(_context, **kwargs):
        calls.append(kwargs)
        return valid_decision("UNKNOWN")

    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        fake_request,
    )
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        result = build_recommendation(
            aisha, "France", "2030-08-01", "2030-08-07"
        )
    assert len(calls) == 2
    assert result["source"] == "deterministic_fallback"
    assert result["selection"]["total_validity_days"] == 7


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
    contexts = []
    responses = [valid_decision("ESS-7D"), valid_decision("DP-7D")]

    def fake_request(context, **_kwargs):
        contexts.append(context)
        return responses.pop(0)

    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        fake_request,
    )
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        initial = build_recommendation(
            aisha, "France", "2030-08-01", "2030-08-07"
        )
        refined = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-07",
            latest_message="Give me more data",
            current_recommendation=initial,
            conversation=[],
        )
    assert len(contexts) == 2
    assert contexts[1]["HIGHEST_PRIORITY_LATEST_USER_INSTRUCTION"] == "Give me more data"
    assert contexts[1]["parsed_requirements"]["minimums"]["data_gb"] == 3.75
    assert refined["selection"]["total_data_gb"] >= 3.75


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
            "package_code": "ESS-7D",
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
