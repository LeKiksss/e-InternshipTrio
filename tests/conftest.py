import pytest

from app import create_app
from app.extensions import db
from config import TestConfig


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()


def login_demo(client):
    return client.post(
        "/auth/login",
        data={"identity": "demo@prototype.local", "password": "Demo123!", "remember": "y"},
        follow_redirects=True,
    )

