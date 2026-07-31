from datetime import datetime, timedelta, timezone

import pytest

from app.services.gemini_recommender import RecommendationDecision
from app.services.gemini_requirements_interpreter import (
    RequirementsInterpretation,
)
from app.services.recommendation_values import METRIC_NAMES, canonical_string
from tests.conftest import login_seeded


def trip(days):
    start = datetime.now(timezone.utc).date() + timedelta(days=45)
    return start.isoformat(), (start + timedelta(days=days - 1)).isoformat()


def model_plan(code, days=7):
    return {
        "interpreted_latest_request": None,
        "trip_segments": [],
        "package_items": [
            {
                "package_code": code,
                "quantity": 1,
                "coverage_start_day": 1,
                "coverage_end_day": days,
                "activation_order": 1,
                "assigned_segment_id": None,
                "reason_for_item": "Covers the requested trip.",
            }
        ],
        "reason": "Validated package selection.",
        "why_it_fits": ["All required allowances are covered."],
        "usage_summary": "Calculated usage is covered.",
        "modification_summary": "The latest request was applied.",
        "tradeoff_summary": None,
    }


def test_unauthenticated_recommendation_is_rejected(client):
    start, end = trip(7)
    response = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


@pytest.mark.parametrize(
    "email",
    [
        "aisha@example.test",
        "omar@example.test",
        "layla@example.test",
        "yusuf@example.test",
    ],
)
def test_all_four_seeded_accounts_can_log_in(client, email):
    response = login_seeded(client, email)
    assert response.status_code == 200
    assert b'app-shell' in response.data


def test_route_uses_current_user_and_ignores_browser_user_id(client, app):
    from app.models import User

    login_seeded(client, "aisha@example.test")
    with app.app_context():
        layla_id = User.query.filter_by(email="layla@example.test").one().id
    start, end = trip(7)
    response = client.post(
        "/api/roaming/recommend",
        json={
            "destination": "France",
            "start_date": start,
            "end_date": end,
            "user_id": layla_id,
        },
    )
    assert response.status_code == 200
    assert response.json["usage_analysis"]["pattern"] == "stable"
    assert response.json["usage_analysis"]["monthly_estimate"]["data_gb"] == pytest.approx(
        4.488
    )


def test_route_uses_an_isolated_gemini_conversation_for_each_journey(
    client,
    app,
    monkeypatch,
):
    calls = []
    responses = [
        model_plan("DP-7D"),
        model_plan("DP-7D"),
        model_plan("DP-7D"),
        model_plan("ESS-3D", days=3),
        model_plan("DP-3D", days=3),
        model_plan("DP-7D"),
    ]

    def fake_request(context, **kwargs):
        calls.append(
            {
                "context": context,
                "previous_interaction_id": kwargs.get(
                    "previous_interaction_id"
                ),
            }
        )
        decision = RecommendationDecision.model_validate(responses.pop(0))
        decision._interaction_id = f"interaction-{len(calls)}"
        return decision

    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        fake_request,
    )
    interpreter_calls = []

    def fake_interpreter(context, **_kwargs):
        interpreter_calls.append(context)
        message = context["raw_user_message"]
        target = next(
            (
                value
                for value in (5, 6, 7)
                if str(value) in message
            ),
            5,
        )
        current = dict(context["current_requirements"])
        current["data_gb"] = canonical_string(target, field="data_gb")
        return RequirementsInterpretation.model_validate(
            {
                "fully_understood": True,
                "clarification_required": False,
                "clarification_question": None,
                "unresolved_fragments": [],
                "requirements": current,
                "changed_metrics": ["data_gb"],
                "preserved_metrics": [
                    metric for metric in METRIC_NAMES if metric != "data_gb"
                ],
            }
        )

    monkeypatch.setattr(
        "app.main.routes.request_requirements_interpretation",
        fake_interpreter,
    )
    app.config["GEMINI_API_KEY"] = "configured-for-test"
    login_seeded(client)
    start, end = trip(7)
    initial = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )
    assert initial.status_code == 200
    refined = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial.json["recommendation_id"],
            "message": "I need 5 GB",
        },
    )
    assert refined.status_code == 200
    refined_again = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": refined.json["recommendation_id"],
            "message": "I need 6 GB",
        },
    )
    assert refined_again.status_code == 200
    second_start, second_end = trip(3)
    second_initial = client.post(
        "/api/roaming/recommend",
        json={
            "destination": "Japan",
            "start_date": second_start,
            "end_date": second_end,
        },
    )
    assert second_initial.status_code == 200
    second_refined = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": second_initial.json[
                "recommendation_id"
            ],
            "message": "I need 5 GB",
        },
    )
    assert second_refined.status_code == 200

    assert len(calls) == 5
    assert len(calls[0]["context"]["active_package_catalogue"]) == 42
    assert calls[0]["previous_interaction_id"] is None
    assert "active_package_catalogue" not in calls[1]["context"]
    assert calls[1]["context"]["trip_requirements"]["data_gb"] == "5.000000"
    assert calls[1]["previous_interaction_id"] == "interaction-1"
    assert "active_package_catalogue" not in calls[2]["context"]
    assert calls[2]["context"]["trip_requirements"]["data_gb"] == "6.000000"
    assert calls[2]["previous_interaction_id"] == "interaction-2"
    assert len(calls[3]["context"]["active_package_catalogue"]) == 42
    assert calls[3]["previous_interaction_id"] is None
    assert "active_package_catalogue" not in calls[4]["context"]
    assert calls[4]["previous_interaction_id"] == "interaction-4"
    third_initial = client.post(
        "/api/roaming/recommend",
        json={
            "destination": "France",
            "start_date": start,
            "end_date": end,
        },
    )
    assert third_initial.status_code == 200
    assert third_initial.json["recommendation_source"] == "smart_history"
    assert len(calls) == 5
    with client.session_transaction() as active_session:
        assert "roaming_gemini_interaction_id" not in active_session

    third_refined = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": third_initial.json[
                "recommendation_id"
            ],
            "message": "I need 7 GB",
        },
    )
    assert third_refined.status_code == 200
    assert len(calls) == 6
    assert len(calls[5]["context"]["active_package_catalogue"]) == 42
    assert calls[5]["previous_interaction_id"] is None
    assert len(interpreter_calls) == 4

    for response in (
        initial,
        refined,
        refined_again,
        second_initial,
        second_refined,
        third_initial,
        third_refined,
    ):
        assert "roaming_gemini_interaction_id" not in response.json
        assert "previous_interaction_id" not in response.json
    with client.session_transaction() as active_session:
        assert active_session["roaming_gemini_interaction_id"] == (
            "interaction-6"
        )


def test_seeded_users_receive_usage_appropriate_package_families(client):
    start, end = trip(7)
    families = {}
    for email in (
        "aisha@example.test",
        "omar@example.test",
        "layla@example.test",
        "yusuf@example.test",
    ):
        login_seeded(client, email)
        response = client.post(
            "/api/roaming/recommend",
            json={"destination": "France", "start_date": start, "end_date": end},
        )
        assert response.status_code == 200
        families[email] = {
            item["family"] for item in response.json["selection"]["items"]
        }
        client.post("/auth/logout")

    assert "Roam Essentials" in families["aisha@example.test"]
    assert "Roam Essentials" in families["omar@example.test"]
    assert any(name.startswith("Data") for name in families["layla@example.test"])
    assert any(name.startswith("Voice") for name in families["yusuf@example.test"])


def test_omar_three_day_trip_selects_from_the_exact_requirements(client):
    login_seeded(client, "omar@example.test")
    start, end = trip(3)

    response = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )

    assert response.status_code == 200
    analysis = response.json["usage_analysis"]
    assert analysis["requirements"] == analysis["trip_estimate"]
    assert analysis["requirements"]["data_gb"] == pytest.approx(1.487, abs=0.001)
    assert analysis["requirements"]["data_gb"] < 1.5
    selection = response.json["selection"]
    assert [(item["package_code"], item["quantity"]) for item in selection["items"]] == [
        ("ESS-3D", 1)
    ]
    assert selection["total_price_aed"] == 35
    assert selection["total_validity_days"] == 3


@pytest.mark.parametrize(
    "greeting",
    ("Hello", "Hey there!", "Good morning", "Salaam"),
)
def test_greetings_reply_without_calling_gemini_or_changing_plan(
    client,
    monkeypatch,
    greeting,
):
    login_seeded(client, "omar@example.test")
    start, end = trip(3)
    initial = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    ).json
    calls = []

    def unexpected_request(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("A greeting must not call Gemini.")

    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        unexpected_request,
    )
    response = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial["recommendation_id"],
            "message": greeting,
        },
    )

    assert response.status_code == 200
    assert response.json["response_type"] == "message"
    assert "roaming plan" in response.json["message"]
    assert response.json["recommendation_id"] == initial["recommendation_id"]
    assert calls == []


def test_natural_language_nevermind_budget_request_replaces_old_constraint(client):
    login_seeded(client, "omar@example.test")
    start, end = trip(3)
    initial = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    ).json
    calls_plan = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial["recommendation_id"],
            "message": "200 local minutes",
        },
    ).json
    assert calls_plan["selection"]["items"][0]["package_code"] == "VP-3D"

    cheaper = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": calls_plan["recommendation_id"],
            "message": (
                "nevermind can we go cheap but focus on calls "
                "my budget is like 30dhs"
            ),
        },
    )

    assert cheaper.status_code == 200
    assert cheaper.json["selection"]["items"][0]["package_code"] == "ESS-3D"
    assert cheaper.json["selection"]["total_price_aed"] == 35
    assert "local_minutes" not in cheaper.json["_active_requirements"]["minimums"]
    assert cheaper.json["_active_requirements"]["maximum_price_aed"] == 30
    assert cheaper.json["_active_requirements"]["reset_constraints"] is True
    assert "maximum price" in cheaper.json["chat_message"]


def test_multiple_refinements_restore_previous_and_original_without_gemini(
    client,
    app,
    monkeypatch,
):
    from app.models import RoamingRecommendationHistory

    login_seeded(client, "omar@example.test")
    start, end = trip(3)
    original = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    ).json
    outputs = [original]
    for message in (
        "I need 200 local minutes",
        "I need 100 SMS",
        "I need 5 GB",
    ):
        response = client.post(
            "/api/roaming/refine",
            json={
                "current_recommendation_id": outputs[-1]["recommendation_id"],
                "message": message,
            },
        )
        assert response.status_code == 200
        outputs.append(response.json)

    assert len({item["recommendation_id"] for item in outputs}) == 4
    with app.app_context():
        assert RoamingRecommendationHistory.query.count() == 4

    calls = []

    def unexpected_request(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("History navigation must not call Gemini.")

    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        unexpected_request,
    )
    previous = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": outputs[-1]["recommendation_id"],
            "message": "I want to go back to the previous package",
        },
    )
    assert previous.status_code == 200
    assert previous.json["history_action"] == "previous"
    assert previous.json["recommendation_id"] == outputs[-2]["recommendation_id"]
    assert previous.json["selection"] == outputs[-2]["selection"]

    previous_again = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": previous.json["recommendation_id"],
            "message": "Go back one",
        },
    )
    assert previous_again.status_code == 200
    assert previous_again.json["history_action"] == "previous"
    assert previous_again.json["recommendation_id"] == outputs[-3][
        "recommendation_id"
    ]
    assert previous_again.json["selection"] == outputs[-3]["selection"]

    restored = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": previous_again.json[
                "recommendation_id"
            ],
            "message": "Can I get the original plan you recommended?",
        },
    )
    assert restored.status_code == 200
    assert restored.json["history_action"] == "original"
    assert restored.json["recommendation_id"] == original["recommendation_id"]
    assert restored.json["selection"] == original["selection"]
    assert restored.json["_active_requirements"]["minimums"] == {}
    assert calls == []


def test_saved_multi_package_and_segmented_plans_reopen_with_all_facts(client):
    login_seeded(client)
    start, end = trip(23)
    multi = client.post(
        "/api/roaming/recommend",
        json={"destination": "Canada", "start_date": start, "end_date": end},
    )
    assert multi.status_code == 200
    assert multi.json["selection"]["activation_count"] == 3
    saved_multi = client.post(
        "/api/roaming/saved",
        json={"recommendation_id": multi.json["recommendation_id"]},
    )
    assert saved_multi.status_code == 201
    assert len(saved_multi.json["recommendation"]["selection"]["items"]) == 2

    start, end = trip(14)
    initial = client.post(
        "/api/roaming/recommend",
        json={"destination": "Japan", "start_date": start, "end_date": end},
    )
    segmented = client.post(
        "/api/roaming/refine",
        json={
            "current_recommendation_id": initial.json["recommendation_id"],
            "message": (
                "For the first week I will have Wi-Fi and need light usage, "
                "and I need heavy data in the second week."
            ),
        },
    )
    assert segmented.status_code == 200
    assert len(segmented.json["segments"]) == 2
    saved_segmented = client.post(
        "/api/roaming/saved",
        json={"recommendation_id": segmented.json["recommendation_id"]},
    )
    assert saved_segmented.status_code == 201

    saved = client.get("/api/roaming/saved").json["recommendations"]
    assert len(saved) == 2
    assert any(len(row["segments"]) == 2 for row in saved)
    current = client.get("/api/roaming/current")
    assert current.status_code == 200
    assert current.json["recommendation"]["recommendation_id"] == segmented.json[
        "recommendation_id"
    ]


def test_invalid_dates_and_missing_catalogue_fail_safely(client, app):
    from app.extensions import db
    from app.models import RoamingPackage

    login_seeded(client)
    invalid = client.post(
        "/api/roaming/recommend",
        json={
            "destination": "France",
            "start_date": "2030-08-10",
            "end_date": "2030-08-01",
        },
    )
    assert invalid.status_code == 400
    assert "Return date" in invalid.json["message"]

    with app.app_context():
        RoamingPackage.query.update({RoamingPackage.active: False})
        db.session.commit()
    start, end = trip(7)
    missing = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )
    assert missing.status_code == 400
    assert "catalogue" in missing.json["message"]
