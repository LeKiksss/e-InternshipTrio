import os
import secrets
import warnings
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _development_secret():
    value = os.getenv("SECRET_KEY")
    if value:
        return value
    warnings.warn(
        "SECRET_KEY is not set; using a temporary local-development secret.",
        RuntimeWarning,
        stacklevel=2,
    )
    return secrets.token_hex(32)


class Config:
    SECRET_KEY = _development_secret()
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{(BASE_DIR / 'instance' / 'prototype.db').as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_TIME_LIMIT = None
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    GEMINI_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30"))
    GEMINI_REQUEST_LOG_DIR = os.getenv(
        "GEMINI_REQUEST_LOG_DIR",
        str(BASE_DIR / "instance" / "api_request_logs"),
    )


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    GEMINI_API_KEY = ""
    GEMINI_REQUEST_LOG_DIR = None
