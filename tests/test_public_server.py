import importlib
import re

import pytest
from flask import request, url_for

FORWARDED_HEADERS = {
    "X-Forwarded-Proto": "https",
    "X-Forwarded-Host": "example.trycloudflare.com",
}
PUBLIC_ORIGIN = "https://example.trycloudflare.com"


def csrf_token(response):
    match = re.search(
        r'<meta name="csrf-token" content="([^"]+)"',
        response.get_data(as_text=True),
    )
    assert match
    return match.group(1)


@pytest.fixture()
def public_server_module():
    return importlib.import_module("serve_public")


@pytest.fixture()
def public_app(public_server_module, monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(public_server_module, "load_dotenv", lambda *_args, **_kwargs: True)
    monkeypatch.setenv("SECRET_KEY", "public-test-secret-key-that-is-long-enough-123")
    monkeypatch.setattr(config.Config, "SECRET_KEY", "stale-import-time-secret")
    monkeypatch.setattr(
        config.Config,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{(tmp_path / 'public.sqlite').as_posix()}",
    )
    monkeypatch.setattr(config.Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config.Config, "GEMINI_REQUEST_LOG_DIR", None)
    application = public_server_module.create_public_app()
    yield application
    with application.app_context():
        from app.extensions import db

        db.session.remove()
        db.drop_all()


def https_get(client, path):
    return client.get(path, base_url=PUBLIC_ORIGIN, headers=FORWARDED_HEADERS)


def https_post(client, path, *, data, follow_redirects=False):
    return client.post(
        path,
        data=data,
        base_url=PUBLIC_ORIGIN,
        headers={**FORWARDED_HEADERS, "Referer": f"{PUBLIC_ORIGIN}{path.split('?')[0]}"},
        follow_redirects=follow_redirects,
    )


def test_public_server_module_import_has_no_startup_side_effect(public_server_module):
    assert callable(public_server_module.create_public_app)
    assert callable(public_server_module.main)


def test_public_server_rejects_missing_or_example_secret(public_server_module, monkeypatch):
    monkeypatch.setattr(public_server_module, "load_dotenv", lambda *_args, **_kwargs: True)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(SystemExit, match="stable SECRET_KEY"):
        public_server_module._load_and_validate_environment()

    monkeypatch.setenv("SECRET_KEY", "replace-with-a-long-random-development-secret")
    with pytest.raises(SystemExit, match="stable SECRET_KEY"):
        public_server_module._load_and_validate_environment()


def test_public_mode_disables_debug_and_enables_secure_cookies(public_app):
    assert public_app.debug is False
    assert public_app.testing is False
    assert public_app.config["PROPAGATE_EXCEPTIONS"] is False
    assert public_app.config["PUBLIC_HTTPS_MODE"] is True
    assert public_app.config["SESSION_COOKIE_SECURE"] is True
    assert public_app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert public_app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert public_app.config["REMEMBER_COOKIE_SECURE"] is True
    assert public_app.config["REMEMBER_COOKIE_HTTPONLY"] is True
    assert public_app.config["SECRET_KEY"] == "public-test-secret-key-that-is-long-enough-123"


def test_proxy_mode_honors_only_forwarded_scheme_and_host(public_app):
    @public_app.get("/_proxy-test")
    def proxy_test():
        return {
            "secure": request.is_secure,
            "host": request.host,
            "remote": request.remote_addr,
            "external": url_for("main.index", _external=True),
        }

    response = public_app.test_client().get(
        "/_proxy-test",
        base_url="http://127.0.0.1:5000",
        headers={
            **FORWARDED_HEADERS,
            "X-Forwarded-For": "203.0.113.50",
            "X-Forwarded-Port": "9443",
            "X-Forwarded-Prefix": "/spoofed",
        },
    )
    assert response.json == {
        "secure": True,
        "host": "example.trycloudflare.com",
        "remote": "127.0.0.1",
        "external": "https://example.trycloudflare.com/",
    }


def test_public_https_registration_login_session_and_logout_keep_csrf(public_app):
    client = public_app.test_client()

    register_page = https_get(client, "/auth/register")
    registration = https_post(
        client,
        "/auth/register",
        data={
            "csrf_token": csrf_token(register_page),
            "full_name": "PWA Customer",
            "email": "pwa.customer@example.com",
            "phone_number": "+971 55 987 6543",
            "password": "Secure123",
            "confirm_password": "Secure123",
            "terms": "y",
        },
    )
    assert registration.status_code == 302
    assert registration.headers["Location"].endswith("/auth/login")

    login_page = https_get(client, "/auth/login")
    login = https_post(
        client,
        "/auth/login",
        data={
            "csrf_token": csrf_token(login_page),
            "identity": "pwa.customer@example.com",
            "password": "Secure123",
            "remember": "y",
        },
    )
    assert login.status_code == 302
    cookies = login.headers.getlist("Set-Cookie")
    assert any("remember_token=" in value and "Secure" in value for value in cookies)
    assert any("session=" in value and "Secure" in value for value in cookies)

    app_page = https_get(client, "/app")
    assert app_page.status_code == 200
    assert b"PWA Customer" in app_page.data
    logout = https_post(
        client,
        "/auth/logout",
        data={"csrf_token": csrf_token(app_page)},
    )
    assert logout.status_code == 302
    assert https_get(client, "/app").status_code == 302


def test_local_http_mode_remains_usable_and_does_not_require_secure_cookie(client):
    response = client.post(
        "/auth/login",
        data={"identity": "aisha@example.test", "password": "Demo123!"},
    )
    assert response.status_code == 302
    session_cookie = next(
        value for value in response.headers.getlist("Set-Cookie") if value.startswith("session=")
    )
    assert "Secure" not in session_cookie
    assert client.get("/app").status_code == 200


def test_public_main_uses_loopback_waitress_and_minimal_proxy_trust(
    public_server_module, monkeypatch
):
    calls = {}
    monkeypatch.setattr(public_server_module, "create_public_app", lambda: object())
    monkeypatch.setattr(public_server_module, "_port", lambda: 5050)

    def fake_serve(application, **kwargs):
        calls["application"] = application
        calls["kwargs"] = kwargs

    monkeypatch.setattr(public_server_module, "serve", fake_serve)
    public_server_module.main()

    assert calls["kwargs"]["host"] == "127.0.0.1"
    assert calls["kwargs"]["port"] == 5050
    assert calls["kwargs"]["expose_tracebacks"] is False
    assert calls["kwargs"]["trusted_proxy"] == "127.0.0.1"
    assert calls["kwargs"]["trusted_proxy_count"] == 1
    assert calls["kwargs"]["trusted_proxy_headers"] == {
        "x-forwarded-host",
        "x-forwarded-proto",
    }
