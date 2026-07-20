import threading

import pytest
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from app import create_app
from app.extensions import db
from config import TestConfig


@pytest.fixture(scope="session")
def live_app_url(tmp_path_factory):
    database = tmp_path_factory.mktemp("browser-db") / "prototype.sqlite"

    class BrowserConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database.as_posix()}"

    application = create_app(BrowserConfig)
    server = make_server("127.0.0.1", 0, application, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture()
def page(browser):
    context = browser.new_context(
        viewport={"width": 430, "height": 900},
        permissions=["clipboard-read", "clipboard-write"],
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(f"page error: {getattr(error, 'stack', error)}"))
    page.on(
        "console",
        lambda message: errors.append(f"console error: {message.text}")
        if message.type == "error"
        else None,
    )
    page.on(
        "response",
        lambda response: errors.append(f"HTTP {response.status}: {response.url}")
        if response.status >= 500
        else None,
    )
    yield page
    context.close()
    assert not errors, "\n".join(errors)


def login_demo(page, live_app_url):
    page.goto(live_app_url)
    visible_copy = page.locator("body").inner_text().lower()
    for label in ("demo", "prototype", "fictional", "proof of concept"):
        assert label not in visible_copy
    page.locator("#identity").fill("demo@prototype.local")
    page.locator("#password").fill("Demo123!")
    page.locator('input[type="submit"]').click()
    page.locator(".app-shell").wait_for(state="visible")
