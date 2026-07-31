import re
from pathlib import Path

import pytest

import config

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".txt",
    ".toml",
    ".webmanifest",
    ".yaml",
    ".yml",
}
ROOT_TEXT_FILES = {
    ".codespellrc",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "requirements.txt",
}


def repository_text_files():
    """Yield distributable text files without opening local secrets or runtime data."""

    excluded_directories = {".git", ".venv", "instance", "__pycache__", ".pytest_cache"}
    this_file = Path(__file__).resolve()
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in excluded_directories for part in path.parts):
            continue
        if path.resolve() == this_file:
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in ROOT_TEXT_FILES:
            yield path


def parse_environment_template():
    values = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        values[name] = value
    return values


def test_environment_template_contains_no_secret_or_fake_api_key():
    values = parse_environment_template()
    assert values["SECRET_KEY"] == ""
    assert values["GEMINI_API_KEY"] == ""
    assert values["APP_HOST"] == "127.0.0.1"
    assert values["APP_PORT"] == "5000"


def test_local_secrets_databases_and_runtime_logs_are_ignored():
    ignore_rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignore_rules
    assert ".env.*" in ignore_rules
    assert "!.env.example" in ignore_rules
    assert "instance/" in ignore_rules
    assert "*.db" in ignore_rules
    assert ".venv/" in ignore_rules


def test_distributable_text_has_no_key_shapes_or_user_specific_paths():
    key_patterns = {
        "Google API key": re.compile(r"AI" r"za[0-9A-Za-z_-]{20,}"),
        "GitHub token": re.compile(
            r"(?:gh" r"[pousr]_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,})"
        ),
        "AWS access key": re.compile(r"AK" r"IA[0-9A-Z]{16}"),
        "private key": re.compile(r"-----BEGIN " r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    }
    path_patterns = {
        "Windows user path": re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\"),
        "Windows user path with slashes": re.compile(r"[A-Za-z]:/Users/[^/\s]+/"),
        "macOS user path": re.compile(r"/Users/[^/\s]+/"),
        "Linux user path": re.compile(r"/home/[^/\s]+/"),
    }
    findings = []
    for path in repository_text_files():
        text = path.read_text(encoding="utf-8")
        for label, pattern in {**key_patterns, **path_patterns}.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}: {label}")
    assert findings == []


def test_copied_placeholders_never_enable_gemini_or_a_known_session_secret(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "your_gemini_api_key_here")
    assert config._optional_api_key() == ""

    monkeypatch.setenv("SECRET_KEY", "replace-with-a-long-random-development-secret")
    with pytest.warns(RuntimeWarning, match="temporary local-development secret"):
        generated = config._development_secret()
    assert generated != "replace-with-a-long-random-development-secret"
    assert len(generated) == 64


def test_relative_request_log_folder_is_rooted_in_the_repository(monkeypatch):
    monkeypatch.setenv("GEMINI_REQUEST_LOG_DIR", "instance/team-request-logs")
    expected = (ROOT / "instance" / "team-request-logs").resolve()
    assert Path(config._project_path("GEMINI_REQUEST_LOG_DIR", "unused")) == expected
