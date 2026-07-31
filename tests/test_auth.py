import pytest

from app.models import User
from tests.conftest import login_demo


def registration_payload(**overrides):
    data = {
        "full_name": "Test Customer",
        "email": "customer@example.com",
        "phone_number": "+971 55 123 4567",
        "password": "Secure123",
        "confirm_password": "Secure123",
        "terms": "y",
    }
    data.update(overrides)
    return data


def test_user_registration(client, app):
    response = client.post("/auth/register", data=registration_payload(), follow_redirects=True)
    assert response.status_code == 200
    assert b"Account created securely" in response.data
    with app.app_context():
        assert User.query.filter_by(email="customer@example.com").first() is not None


def test_duplicate_email_rejected(client):
    first = registration_payload()
    client.post("/auth/register", data=first)
    response = client.post("/auth/register", data=registration_payload(phone_number="+971 56 765 4321"))
    assert response.status_code == 200
    assert b"already exists with this email" in response.data


def test_password_is_argon2_hash(client, app):
    client.post("/auth/register", data=registration_payload())
    with app.app_context():
        user = User.query.filter_by(email="customer@example.com").first()
        assert user.password_hash != "Secure123"
        assert user.password_hash.startswith("$argon2")
        assert user.check_password("Secure123")


def test_valid_login(client):
    response = login_demo(client)
    assert response.status_code == 200
    assert b"What can we help with?" in response.data


def test_invalid_login(client):
    response = client.post(
        "/auth/login",
        data={"identity": "aisha@example.test", "password": "wrong"},
    )
    assert response.status_code == 200
    assert b"incorrect" in response.data


@pytest.mark.parametrize(
    "unsafe_target",
    ["//example.com", "https://example.com", "/\\example.com"],
)
def test_login_rejects_external_or_ambiguous_redirect_targets(client, unsafe_target):
    response = client.post(
        "/auth/login",
        query_string={"next": unsafe_target},
        data={"identity": "aisha@example.test", "password": "Demo123!"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/app")


def test_login_accepts_an_internal_redirect_target(client):
    response = client.post(
        "/auth/login",
        query_string={"next": "/app#roaming"},
        data={"identity": "aisha@example.test", "password": "Demo123!"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/app#roaming")


def test_logout(client):
    login_demo(client)
    response = client.post("/auth/logout", follow_redirects=True)
    assert response.status_code == 200
    assert b"Welcome back" in response.data
    assert b"signed out securely" in response.data
