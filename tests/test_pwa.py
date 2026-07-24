import json
import struct
from pathlib import Path

from tests.conftest import login_demo


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def png_dimensions(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_manifest_route_is_valid_and_complete(client):
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert response.mimetype == "application/manifest+json"
    manifest = json.loads(response.get_data(as_text=True))

    assert manifest["id"] == "/"
    assert manifest["name"] == "e& Care"
    assert manifest["short_name"] == "e& Care"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert "standalone" in manifest["display_override"]
    assert manifest["orientation"] == "portrait"
    assert manifest["theme_color"] == "#e60000"
    assert manifest["background_color"] == "#f6f7f9"
    assert manifest["description"]
    assert manifest["categories"]


def test_manifest_icons_and_apple_touch_icon_exist_with_required_dimensions(client):
    required = {
        "apple-touch-icon.png": (180, 180),
        "icon-192.png": (192, 192),
        "icon-512.png": (512, 512),
        "icon-maskable-192.png": (192, 192),
        "icon-maskable-512.png": (512, 512),
    }
    for filename, dimensions in required.items():
        path = STATIC / "icons" / filename
        assert path.is_file()
        assert png_dimensions(path) == dimensions
        response = client.get(f"/static/icons/{filename}")
        assert response.status_code == 200
        assert response.mimetype == "image/png"

    manifest = client.get("/manifest.webmanifest").get_json()
    purposes = {(item["sizes"], item["purpose"]) for item in manifest["icons"]}
    assert purposes == {
        ("192x192", "any"),
        ("512x512", "any"),
        ("192x192", "maskable"),
        ("512x512", "maskable"),
    }


def test_service_worker_is_root_scoped_javascript_and_not_browser_cached(client):
    response = client.get("/service-worker.js")
    assert response.status_code == 200
    assert response.mimetype in {"text/javascript", "application/javascript"}
    assert response.headers["Service-Worker-Allowed"] == "/"
    assert "no-store" in response.headers["Cache-Control"]


def test_offline_page_is_public_session_neutral_and_retryable(client):
    response = client.get("/offline")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "Try again" in body
    assert "data-connection-status" in body
    assert "csrf-token" not in body.lower()
    assert "Aisha Noor" not in body
    assert "Set-Cookie" not in response.headers


def test_shared_base_includes_manifest_apple_metadata_and_registration(client):
    response = client.get("/auth/login")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    for expected in (
        'rel="manifest" href="/manifest.webmanifest"',
        'rel="apple-touch-icon" sizes="180x180"',
        'name="theme-color" content="#e60000"',
        'name="mobile-web-app-capable" content="yes"',
        'name="apple-mobile-web-app-capable" content="yes"',
        'name="apple-mobile-web-app-status-bar-style" content="default"',
        'name="apple-mobile-web-app-title" content="e&amp; Care"',
        "maximum-scale=1",
        "user-scalable=no",
        "viewport-fit=cover",
        'src="/static/js/pwa.js"',
    ):
        assert expected in body


def test_start_url_preserves_normal_authentication_flow(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")
    assert client.get("/app").status_code == 302
    login_demo(client)
    assert client.get("/").headers["Location"].endswith("/app")
    assert client.get("/app").status_code == 200


def test_private_html_and_api_responses_are_never_cacheable(client):
    login_demo(client)
    for path in ("/app", "/api/bootstrap", "/api/roaming/saved"):
        response = client.get(path)
        assert response.status_code == 200
        assert "no-store" in response.headers["Cache-Control"]
        assert "private" in response.headers["Cache-Control"]


def test_service_worker_policy_excludes_private_and_mutating_requests():
    source = (STATIC / "service-worker.js").read_text(encoding="utf-8")
    assert 'const CACHE_VERSION = "v10"' in source
    assert 'request.method !== "GET"' in source
    assert 'request.mode === "navigate"' in source
    assert 'fetch(request, { cache: "no-store" })' in source
    assert "ORIGIN_UNAVAILABLE_STATUSES" in source
    for status in (502, 503, 504, 521, 522, 523, 524, 530):
        assert str(status) in source
    assert 'url.pathname.startsWith("/api/")' in source
    assert 'url.pathname.startsWith("/auth/")' in source
    assert 'url.pathname === "/app"' in source
    assert "SAFE_SHELL_PATHS.has(url.pathname)" in source
    assert "response.redirected" in source
    assert "no-store|private" in source
    assert 'redirect: "error"' in source
    assert "cache.put(request, response.clone())" in source
    navigation_block = source.split('if (request.mode === "navigate")', 1)[1].split(
        'if (', 1
    )[0]
    assert "cache.put" not in navigation_block


def test_missing_static_file_is_not_redirected_to_private_html(client):
    login_demo(client)
    response = client.get("/static/definitely-missing.js")
    assert response.status_code == 404
    assert response.mimetype == "text/plain"
    assert "Aisha Noor" not in response.get_data(as_text=True)


def test_update_refresh_is_one_time_and_never_resubmits_a_form():
    source = (STATIC / "js" / "pwa.js").read_text(encoding="utf-8")
    assert "sessionStorage.removeItem(UPDATE_RELOAD_KEY)" in source
    assert "window.location.replace(window.location.href)" in source
    assert "window.location.reload()" not in source


def test_login_next_parameter_cannot_redirect_to_an_external_host(client):
    response = client.post(
        "/auth/login?next=//example.org/escape",
        data={"identity": "aisha@example.test", "password": "Demo123!"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/app")
