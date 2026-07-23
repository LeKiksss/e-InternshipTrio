"""Serve e& Care safely behind a loopback Cloudflare Quick Tunnel."""

import os
from pathlib import Path

from dotenv import load_dotenv
from waitress import serve


BASE_DIR = Path(__file__).resolve().parent
PUBLIC_HOST = "127.0.0.1"


def _port():
    raw_value = os.getenv("APP_PORT", os.getenv("PORT", "5000"))
    try:
        port = int(raw_value)
    except ValueError as error:
        raise SystemExit("APP_PORT or PORT must be a valid integer.") from error
    if not 1 <= port <= 65535:
        raise SystemExit("APP_PORT or PORT must be between 1 and 65535.")
    return port


def _load_and_validate_environment():
    load_dotenv(BASE_DIR / ".env")
    secret = os.getenv("SECRET_KEY", "").strip()
    if (
        len(secret) < 32
        or secret.lower().startswith("replace-with-")
        or secret.lower() in {"changeme", "change-me"}
    ):
        raise SystemExit(
            "A stable SECRET_KEY of at least 32 characters is required for public mode. "
            "Add it to .env without committing that file."
        )
    os.environ["PUBLIC_HTTPS_MODE"] = "true"
    return secret


def create_public_app():
    validated_secret = _load_and_validate_environment()

    from app import create_app
    from config import Config

    class PublicConfig(Config):
        PUBLIC_HTTPS_MODE = True
        SESSION_COOKIE_SECURE = True
        SESSION_COOKIE_HTTPONLY = True
        SESSION_COOKIE_SAMESITE = "Lax"
        REMEMBER_COOKIE_SECURE = True
        REMEMBER_COOKIE_HTTPONLY = True
        REMEMBER_COOKIE_SAMESITE = "Lax"
        PREFERRED_URL_SCHEME = "https"
        DEBUG = False
        TESTING = False
        PROPAGATE_EXCEPTIONS = False

    PublicConfig.SECRET_KEY = validated_secret
    application = create_app(PublicConfig)
    application.debug = False
    return application


def main():
    application = create_public_app()
    port = _port()
    print(f"Serving e& Care securely with Waitress on http://{PUBLIC_HOST}:{port}")
    print("Start cloudflared in a second terminal; press Ctrl+C here to stop the server.")
    serve(
        application,
        host=PUBLIC_HOST,
        port=port,
        threads=8,
        expose_tracebacks=False,
        trusted_proxy=PUBLIC_HOST,
        trusted_proxy_count=1,
        trusted_proxy_headers={"x-forwarded-host", "x-forwarded-proto"},
        clear_untrusted_proxy_headers=True,
    )


if __name__ == "__main__":
    main()
