from datetime import date, datetime, timedelta, timezone

import pytest

from tests.conftest import login_demo


def future_trip(days=7):
    start = datetime.now(timezone.utc).date() + timedelta(days=30)
    return start.isoformat(), (start + timedelta(days=days - 1)).isoformat()


def test_authenticated_route_protection(client):
    response = client.get("/app")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_authenticated_sections_render(client):
    login_demo(client)
    response = client.get("/app")
    assert response.status_code == 200
    for text in (
        b"Network &amp; bill",
        b"Complaint intelligence",
        b"Roaming Recommender",
        b"Profile",
    ):
        assert text in response.data


@pytest.mark.parametrize(
    ("email", "latest_month", "latest_usage"),
    (
        ("aisha@example.test", b"June 2026", b"4.7 GB"),
        ("omar@example.test", b"June 2026", b"15.6 GB"),
        ("layla@example.test", b"June 2026", b"52.0 GB"),
        ("yusuf@example.test", b"June 2026", b"6.6 GB"),
    ),
)
def test_each_seeded_user_has_six_month_bill_usage_history(
    client, email, latest_month, latest_usage
):
    response = login_demo(client, email=email)

    assert response.status_code == 200
    assert b'id="view-usage-history"' in response.data
    assert b'id="bill-usage-history"' in response.data
    assert response.data.count(b"data-usage-month=") == 6
    assert latest_month in response.data
    assert latest_usage in response.data


def test_bill_usage_history_is_limited_to_the_latest_six_months(client, app):
    from app.extensions import db
    from app.models import User, UserMonthlyUsage

    with app.app_context():
        user = User.query.filter_by(email="aisha@example.test").one()
        db.session.add(
            UserMonthlyUsage(
                user_id=user.id,
                usage_month=date(2025, 12, 1),
                data_gb=3.9,
                local_minutes=100,
                international_minutes=15,
                sms=9,
            )
        )
        db.session.commit()

    response = login_demo(client)

    assert response.data.count(b"data-usage-month=") == 6
    assert b"December 2025" not in response.data


def test_diagnostic_result_creation(client, app):
    from app.models import DiagnosticResult

    login_demo(client)
    response = client.post(
        "/api/diagnostics", json={"state": "strong", "location": "Test location"}
    )
    assert response.status_code == 201
    assert response.json["result"]["download_speed"] == 184
    with app.app_context():
        assert DiagnosticResult.query.filter_by(location_label="Test location").count() == 1


def test_complaint_ticket_creation(client, app):
    from app.models import ComplaintTicket

    login_demo(client)
    response = client.post(
        "/api/complaints",
        json={
            "summary": "There is no mobile signal in my area today.",
            "category": "Network",
            "severity": "High",
            "location": "Dubai",
        },
    )
    assert response.status_code == 201
    assert response.json["ticket"]["ticket_number"].startswith("ET-")
    with app.app_context():
        assert (
            ComplaintTicket.query.filter_by(
                summary="There is no mobile signal in my area today."
            ).count()
            == 1
        )


def test_roaming_recommendation_returns_validated_plan(client):
    login_demo(client)
    start, end = future_trip(7)
    response = client.post(
        "/api/roaming/recommend",
        json={"destination": "France", "start_date": start, "end_date": end},
    )
    assert response.status_code == 200
    assert response.json["destination"] == "France"
    assert response.json["trip"]["trip_days"] == 7
    assert response.json["selection"]["items"]
    assert response.json["selection"]["total_validity_days"] == 7


def test_workflow_state_initialization_preservation_and_reset(client):
    login_demo(client)
    initial = client.get("/api/workflows/roaming")
    assert initial.json == {"ok": True, "state": {}, "view": "landing"}
    saved = client.put(
        "/api/workflows/roaming",
        json={"view": "dates", "state": {"destination": "Canada", "step": 2}},
    )
    assert saved.status_code == 200
    restored = client.get("/api/workflows/roaming")
    assert restored.json["view"] == "dates"
    assert restored.json["state"]["destination"] == "Canada"
    assert client.delete("/api/workflows/roaming").status_code == 200
    assert client.get("/api/workflows/roaming").json["state"] == {}


def test_current_usage_and_adjustment_endpoints(client):
    login_demo(client)
    start, end = future_trip(9)
    result = client.post(
        "/api/roaming/current-usage",
        json={"destination": "Canada", "start_date": start, "end_date": end},
    )
    assert result.status_code == 200
    assert result.json["trip"]["trip_days"] == 9
    assert result.json["usage_analysis"]["trip_estimate"]["data_gb"] > 0
    adjusted = client.post(
        "/api/roaming/adjust",
        json={
            "current_recommendation_id": result.json["recommendation_id"],
            "message": "I need 10 GB",
        },
    )
    assert adjusted.status_code == 200
    assert adjusted.json["selection"]["total_data_gb"] >= 10
    stale = client.post(
        "/api/roaming/adjust",
        json={"current_recommendation_id": "stale", "message": "Give me more data"},
    )
    assert stale.status_code == 409


def test_session_recommendation_save_duplicate_remove_and_logout_clear(client):
    login_demo(client)
    start, end = future_trip(9)
    recommendation = client.post(
        "/api/roaming/recommend",
        json={"destination": "Canada", "start_date": start, "end_date": end},
    ).json
    payload = {"recommendation_id": recommendation["recommendation_id"]}
    first = client.post("/api/roaming/saved", json=payload)
    assert first.status_code == 201
    assert len(first.json["recommendation"]["selection"]["items"]) >= 1
    saved_id = first.json["recommendation"]["saved_id"]
    duplicate = client.post("/api/roaming/saved", json=payload)
    assert duplicate.status_code == 200
    assert duplicate.json["duplicate"] is True
    assert len(client.get("/api/roaming/saved").json["recommendations"]) == 1
    assert client.delete(f"/api/roaming/saved/{saved_id}").status_code == 200
    assert client.get("/api/roaming/saved").json["recommendations"] == []
    client.post("/api/roaming/saved", json=payload)
    client.post("/auth/logout")
    with client.session_transaction() as active_session:
        assert "saved_roaming_recommendations" not in active_session
        assert "workflow_drafts" not in active_session


def test_reset_data_clears_session_workflows_and_saved_roaming(client):
    login_demo(client)
    client.put(
        "/api/workflows/network", json={"view": "result", "state": {"complete": True}}
    )
    with client.session_transaction() as active_session:
        active_session["saved_roaming_recommendations"] = [{"saved_id": "saved"}]
    assert client.post("/api/demo/reset").status_code == 200
    with client.session_transaction() as active_session:
        assert "workflow_drafts" not in active_session
        assert "saved_roaming_recommendations" not in active_session
