from tests.conftest import login_demo


def test_authenticated_route_protection(client):
    response = client.get("/app")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_authenticated_sections_render(client):
    login_demo(client)
    response = client.get("/app")
    assert response.status_code == 200
    for text in (b"Network &amp; bill", b"Complaint intelligence", b"Roaming advisor", b"Profile"):
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

