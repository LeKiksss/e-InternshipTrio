from datetime import date, timedelta

import pytest

from tests.conftest import login_seeded


def trip(days):
    start = date.today() + timedelta(days=45)
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


def test_route_calls_gemini_for_initial_and_every_refinement(client, app, monkeypatch):
    calls = []
    responses = [model_plan("PRE-7D"), model_plan("DP-7D")]

    def fake_request(context, **_kwargs):
        calls.append(context)
        return responses.pop(0)

    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        fake_request,
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
            "message": "Give me more data",
        },
    )
    assert refined.status_code == 200
    assert len(calls) == 2
    assert len(calls[0]["active_package_catalogue"]) == 42
    assert calls[1]["latest_user_message"] == "Give me more data"


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


def test_omar_three_day_trip_uses_roam_essentials_without_a_buffer(client):
    login_seeded(client, "omar@example.test")
    start, end = trip(3)

    response = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )

    assert response.status_code == 200
    analysis = response.json["usage_analysis"]
    assert analysis["requirements"] == analysis["trip_estimate"]
    assert "buffered_requirements" not in analysis
    assert analysis["requirements"]["data_gb"] == pytest.approx(1.487, abs=0.001)
    assert analysis["requirements"]["data_gb"] < 1.5
    assert [
        (item["package_code"], item["quantity"])
        for item in response.json["selection"]["items"]
    ] == [("ESS-3D", 1)]
    assert response.json["selection"]["total_price_aed"] == 35


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
