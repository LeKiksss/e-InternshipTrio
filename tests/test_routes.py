from tests.conftest import login_demo


def test_authenticated_route_protection(client):
    response = client.get("/app")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_authenticated_sections_render(client):
    login_demo(client)
    response = client.get("/app")
    assert response.status_code == 200
    for text in (b"Network &amp; bill", b"Complaint intelligence", b"Roam Like Home", b"Profile"):
        assert text in response.data


def test_diagnostic_result_creation(client, app):
    from app.models import DiagnosticResult
    login_demo(client)
    response = client.post("/api/diagnostics", json={"state": "strong", "location": "Test location"})
    assert response.status_code == 201
    assert response.json["result"]["download_speed"] == 184
    with app.app_context():
        assert DiagnosticResult.query.filter_by(location_label="Test location").count() == 1


def test_complaint_ticket_creation(client, app):
    from app.models import ComplaintTicket
    login_demo(client)
    response = client.post("/api/complaints", json={"summary": "There is no mobile signal in my area today.", "category": "Network", "severity": "High", "location": "Dubai"})
    assert response.status_code == 201
    assert response.json["ticket"]["ticket_number"].startswith("ET-")
    with app.app_context():
        assert ComplaintTicket.query.filter_by(summary="There is no mobile signal in my area today.").count() == 1


def test_roaming_recommendation_returns_one_package(client):
    login_demo(client)
    response = client.post("/api/roaming/recommend", json={"destination": "France", "duration": 7, "requirements": "I need maps, browsing and the lowest price", "rejected_ids": []})
    assert response.status_code == 200
    assert response.json["package"]["name"] == "Travel Data Lite"


def test_workflow_state_initialization_preservation_and_reset(client):
    login_demo(client)
    initial = client.get("/api/workflows/roaming")
    assert initial.json == {"ok": True, "state": {}, "view": "landing"}
    saved = client.put("/api/workflows/roaming", json={"view": "dates", "state": {"destination": "Canada", "step": 2}})
    assert saved.status_code == 200
    restored = client.get("/api/workflows/roaming")
    assert restored.json["view"] == "dates"
    assert restored.json["state"]["destination"] == "Canada"
    assert client.delete("/api/workflows/roaming").status_code == 200
    assert client.get("/api/workflows/roaming").json["state"] == {}


def test_current_usage_and_adjustment_endpoints(client):
    login_demo(client)
    result = client.post("/api/roaming/current-usage", json={
        "destination": "Canada", "start_date": "2030-08-01", "end_date": "2030-08-09",
    })
    assert result.status_code == 200
    assert result.json["trip_days"] == 9
    assert result.json["usage"]["data_gb"] == 7.2
    assert result.json["package"]["recommendation_name"] == "Roam Like Home"
    assert result.json["package"]["name"] == "Travel Connect"
    adjusted = client.post("/api/roaming/adjust", json={"destination": "Canada", "trip_days": 9, "message": "That is too expensive"})
    assert adjusted.status_code == 200
    assert adjusted.json["package"]["price"] < result.json["package"]["price"]
    unknown = client.post("/api/roaming/adjust", json={"destination": "Canada", "trip_days": 9, "message": "surprise me"})
    assert unknown.status_code == 422


def test_session_recommendation_save_duplicate_remove_and_logout_clear(client):
    login_demo(client)
    payload = {
        "package_id": "travel-connect-10", "package_name": "Travel Connect",
        "recommendation_name": "Roam Like Home",
        "destination": "Canada", "start_date": "2030-08-01", "end_date": "2030-08-09",
        "trip_days": 9, "price": 220, "currency": "AED", "validity_days": 10,
        "data_allowance": "10 GB", "local_minutes": 200, "international_minutes": 100,
        "sms_allowance": 50, "preferred_network": "Demo Partner Network",
        "activation_code": "*170*201#", "explanation": "Current usage match.",
    }
    first = client.post("/api/roaming/saved", json=payload)
    assert first.status_code == 201
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


def test_reset_demo_clears_session_workflows_and_saved_roaming(client):
    login_demo(client)
    client.put("/api/workflows/network", json={"view": "result", "state": {"complete": True}})
    with client.session_transaction() as active_session:
        active_session["saved_roaming_recommendations"] = [{"saved_id": "demo"}]
    assert client.post("/api/demo/reset").status_code == 200
    with client.session_transaction() as active_session:
        assert "workflow_drafts" not in active_session
        assert "saved_roaming_recommendations" not in active_session
