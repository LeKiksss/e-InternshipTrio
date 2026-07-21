import logging
from pathlib import Path

from app.models import User
from app.services.roaming_recommendation import build_recommendation
from app.services.usage_analysis import analyse_usage


def test_operational_events_are_logged_without_contact_details(app, caplog):
    with app.app_context(), caplog.at_level(logging.INFO):
        omar = User.query.filter_by(email="omar@example.test").one()
        analyse_usage(omar.monthly_usage)
        aisha = User.query.filter_by(email="aisha@example.test").one()
        build_recommendation(aisha, "France", "2030-08-01", "2030-08-07")

    log_text = caplog.text
    assert "Usage analysis started" in log_text
    assert "Isolated outlier identified" in log_text
    assert "Pattern classification calculated" in log_text
    assert "Deterministic fallback used" in log_text
    assert "aisha@example.test" not in log_text
    assert "omar@example.test" not in log_text
    assert "+971" not in log_text
    assert "Demo123!" not in log_text


def test_api_key_name_and_value_are_absent_from_frontend_sources():
    root = Path(__file__).resolve().parents[1]
    frontend_files = [
        *root.joinpath("app", "static", "js").glob("*.js"),
        *root.joinpath("app", "templates").rglob("*.html"),
    ]
    for path in frontend_files:
        text = path.read_text(encoding="utf-8")
        assert "GEMINI_API_KEY" not in text
        assert "your_gemini_api_key_here" not in text


def test_automated_test_configuration_cannot_use_a_local_gemini_key(app):
    assert app.config["GEMINI_API_KEY"] == ""
