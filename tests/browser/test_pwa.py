import json

import pytest
from playwright.sync_api import expect

from .conftest import login_demo


pytestmark = pytest.mark.browser

IPHONE_SAFARI_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
    "Mobile/15E148 Safari/604.1"
)


def iphone_context(browser, *, standalone=False, viewport=None):
    selected_viewport = viewport or {"width": 390, "height": 844}
    context = browser.new_context(
        viewport=selected_viewport,
        user_agent=IPHONE_SAFARI_USER_AGENT,
        is_mobile=selected_viewport["width"] <= 760,
        has_touch=True,
    )
    context.add_init_script(
        f"""
        Object.defineProperty(navigator, "vendor", {{ get: () => "Apple Computer, Inc." }});
        Object.defineProperty(navigator, "standalone", {{ get: () => {str(standalone).lower()} }});
        """
    )
    return context


def transition_details(locator):
    return locator.evaluate(
        """(element) => {
          const animation = element.getAnimations().find(
            (item) => item.animationName?.startsWith("viewEnter")
          );
          const firstTransform = animation?.effect.getKeyframes()?.[0]?.transform || "none";
          const startX = firstTransform === "none" ? 0 : new DOMMatrix(firstTransform).m41;
          const style = getComputedStyle(element);
          return {
            animationName: style.animationName,
            direction: element.dataset.transitionDirection,
            durationMs: parseFloat(style.animationDuration) * 1000,
            easing: style.animationTimingFunction,
            startX,
          };
        }"""
    )


def assert_transition(locator, direction):
    details = transition_details(locator)
    assert details["animationName"] == (
        "viewEnterBack" if direction == "back" else "viewEnterForward"
    )
    assert details["direction"] == direction
    assert 340 <= details["durationMs"] <= 400
    assert details["easing"] == "cubic-bezier(0.22, 1, 0.36, 1)"
    if direction == "forward":
        assert details["startX"] < -20, details
    else:
        assert details["startX"] > 20, details


def test_iphone_safari_install_help_layout_and_dismissal(browser, live_app_url):
    context = iphone_context(browser)
    page = context.new_page()
    page.goto(f"{live_app_url}/auth/login")

    expect(page.locator("[data-ios-install-prompt]")).to_be_visible()
    expect(page.locator(".preview-tools")).to_be_hidden()
    expect(page.locator(".phone-notch")).to_be_hidden()
    expect(page.locator(".home-indicator")).to_be_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    assert int(page.locator("#identity").evaluate("el => parseFloat(getComputedStyle(el).fontSize)")) >= 16

    page.locator("[data-ios-install-open]").click()
    sheet = page.locator("#ios-install-sheet")
    expect(sheet).to_be_visible()
    expect(sheet.locator("li")).to_have_count(4)
    expect(sheet).to_contain_text("Tap the Share button in Safari")
    expect(sheet).to_contain_text("Open as Web App")
    sheet.locator("[data-ios-install-dismiss]").click()
    expect(page.locator("[data-ios-install-prompt]")).to_be_hidden()
    page.reload()
    expect(page.locator("[data-ios-install-prompt]")).to_be_hidden()
    context.close()


def test_standalone_mode_removes_frame_and_keeps_safe_navigation(browser, live_app_url):
    context = browser.new_context(
        viewport={"width": 820, "height": 900},
        has_touch=True,
    )
    context.add_init_script(
        'Object.defineProperty(navigator, "standalone", { get: () => true });'
    )
    page = context.new_page()
    login_demo(page, live_app_url)
    page.wait_for_function("document.documentElement.classList.contains('is-standalone')")
    page.evaluate(
        """document.documentElement.style.setProperty('--safe-top', '47px');
        document.documentElement.style.setProperty('--safe-bottom', '34px');"""
    )
    page.wait_for_timeout(400)

    expect(page.locator("[data-ios-install-prompt]")).to_be_hidden()
    expect(page.locator(".preview-tools")).to_be_hidden()
    frame = page.locator(".phone-device").evaluate(
        """el => ({
          width: el.getBoundingClientRect().width,
          border: getComputedStyle(el).borderTopWidth,
          parentWidth: el.parentElement.getBoundingClientRect().width,
          htmlWidth: document.documentElement.getBoundingClientRect().width,
          innerWidth: window.innerWidth,
          viewportWidth: window.visualViewport?.width,
          declaredWidth: getComputedStyle(el).width,
        })"""
    )
    assert frame["width"] == frame["htmlWidth"], frame
    assert frame["border"] == "0px"

    nav = page.locator(".bottom-nav").bounding_box()
    assert nav is not None
    assert nav["y"] + nav["height"] <= 901
    for button in page.locator(".bottom-nav button").all():
        box = button.bounding_box()
        assert box is not None and box["width"] > 0 and box["height"] >= 44
    context.close()


def test_service_worker_caches_only_shell_and_offline_never_private_content(
    browser, live_app_url
):
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    login_demo(page, live_app_url)
    page.evaluate("navigator.serviceWorker.ready")
    page.reload()
    page.wait_for_function("Boolean(navigator.serviceWorker.controller)")

    expect(page.locator("[data-ios-install-prompt]")).to_be_hidden()
    expect(page.locator(".bottom-nav")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    nav = page.locator(".bottom-nav").bounding_box()
    assert nav is not None and nav["y"] + nav["height"] <= 845
    for button in page.locator(".bottom-nav button").all():
        box = button.bounding_box()
        assert box is not None and box["height"] >= 44

    manifest_result = context.new_cdp_session(page).send("Page.getAppManifest")
    assert manifest_result["errors"] == []
    browser_manifest = json.loads(manifest_result["data"])
    assert browser_manifest["start_url"] == "/"
    assert browser_manifest["scope"] == "/"
    assert browser_manifest["display"] == "standalone"

    missing_asset = page.evaluate(
        """async () => {
          const response = await fetch('/static/definitely-missing.js');
          return {
            status: response.status,
            contentType: response.headers.get('Content-Type'),
            body: await response.text(),
          };
        }"""
    )
    assert missing_asset["status"] == 404
    assert missing_asset["contentType"].startswith("text/plain")
    assert "Aisha Noor" not in missing_asset["body"]

    cached_urls = page.evaluate(
        """async () => {
          const names = await caches.keys();
          const entries = [];
          for (const name of names) {
            const requests = await (await caches.open(name)).keys();
            entries.push(...requests.map((request) => new URL(request.url).pathname));
          }
          return entries;
        }"""
    )
    assert "/offline" in cached_urls
    assert "/app" not in cached_urls
    assert "/static/definitely-missing.js" not in cached_urls
    assert not any(path.startswith("/api/") or path.startswith("/auth/") for path in cached_urls)

    page.goto(f"{live_app_url}/_test/origin-unavailable")
    expect(page.locator("#offline-title")).to_be_visible()
    expect(page.locator("[data-connection-status]")).to_contain_text("Connection restored")
    page.locator("[data-offline-retry]").click()
    expect(page.locator(".app-shell")).to_be_visible()

    context.set_offline(True)
    page.goto(f"{live_app_url}/app")
    expect(page.locator("#offline-title")).to_be_visible()
    body = page.locator("body").inner_text()
    assert "Aisha Noor" not in body
    assert "What can we help with?" not in body
    context.set_offline(False)
    page.locator("[data-offline-retry]").click()
    expect(page.locator(".app-shell")).to_be_visible()
    page.wait_for_function("typeof window.App?.navigate === 'function'")

    page.evaluate("window.App.navigate('profile')")
    page.locator("#logout-button").click()
    page.locator("#confirm-action").click()
    expect(page.locator("#identity")).to_be_visible()

    context.set_offline(True)
    page.goto(f"{live_app_url}/app")
    expect(page.locator("#offline-title")).to_be_visible()
    assert "Aisha Noor" not in page.locator("body").inner_text()
    context.set_offline(False)
    page.locator("[data-offline-retry]").click()
    expect(page.locator("#identity")).to_be_visible()
    context.close()


def test_iphone_keyboard_keeps_shell_stable_and_positions_roaming_chat(
    browser, live_app_url
):
    context = iphone_context(browser)
    page = context.new_page()
    login_demo(page, live_app_url)
    page.evaluate(
        """() => {
          window.App.navigate('roaming');
          window.WorkflowState.get('roaming').go('step3', {
            push: false,
            save: false,
            replace: true,
          });
          document.querySelector('#app-scroll').scrollTop = 0;
        }"""
    )
    textarea = page.locator("#roaming-adjustment")
    expect(textarea).to_be_visible()

    before = page.evaluate(
        """() => {
          const viewport = window.visualViewport;
          window.__testVisualViewportHeight = viewport.height;
          Object.defineProperty(viewport, 'height', {
            configurable: true,
            get: () => window.__testVisualViewportHeight,
          });
          const nav = document.querySelector('.bottom-nav').getBoundingClientRect();
          const phone = document.querySelector('.phone-device').getBoundingClientRect();
          return {
            appHeight: parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--app-viewport-height')),
            visualHeight: viewport.height,
            phoneHeight: phone.height,
            navTop: nav.top,
            viewportScale: viewport.scale,
            viewportMeta: document.querySelector('meta[name="viewport"]').content,
          };
        }"""
    )
    assert before["viewportScale"] == 1
    assert "maximum-scale=1" in before["viewportMeta"]
    assert "user-scalable=no" in before["viewportMeta"]

    textarea.focus()
    page.evaluate(
        """() => {
          window.__testVisualViewportHeight = Math.max(320, window.__testVisualViewportHeight - 360);
          window.visualViewport.dispatchEvent(new Event('resize'));
        }"""
    )
    page.wait_for_timeout(500)

    after = page.evaluate(
        """() => {
          const nav = document.querySelector('.bottom-nav');
          const navBox = nav.getBoundingClientRect();
          const phone = document.querySelector('.phone-device').getBoundingClientRect();
          const chat = document.querySelector('.adjustment-chat').getBoundingClientRect();
          const scroll = document.querySelector('#app-scroll');
          const scrollBox = scroll.getBoundingClientRect();
          return {
            appHeight: parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--app-viewport-height')),
            phoneHeight: phone.height,
            navTop: navBox.top,
            navVisibility: getComputedStyle(nav).visibility,
            keyboardOpen: document.documentElement.classList.contains('keyboard-open'),
            chatTop: chat.top,
            scrollTopEdge: scrollBox.top,
            scrollTop: scroll.scrollTop,
            textareaFontSize: parseFloat(getComputedStyle(document.querySelector('#roaming-adjustment')).fontSize),
            noOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
          };
        }"""
    )
    assert after["keyboardOpen"] is True
    assert after["navVisibility"] == "hidden"
    assert abs(after["appHeight"] - before["appHeight"]) <= 1
    assert abs(after["phoneHeight"] - before["phoneHeight"]) <= 1
    assert abs(after["navTop"] - before["navTop"]) <= 1
    assert after["scrollTop"] > 0
    assert abs(after["chatTop"] - after["scrollTopEdge"]) <= 12
    assert after["textareaFontSize"] >= 16
    assert after["noOverflow"] is True

    textarea.blur()
    page.evaluate(
        """() => {
          window.__testVisualViewportHeight = window.innerHeight;
          window.visualViewport.dispatchEvent(new Event('resize'));
        }"""
    )
    page.wait_for_timeout(300)
    assert page.evaluate("!document.documentElement.classList.contains('keyboard-open')")
    expect(page.locator(".bottom-nav")).to_have_css("visibility", "visible")
    context.close()


def test_all_screens_and_workflows_use_fluid_directional_transitions(
    browser, live_app_url
):
    context = iphone_context(browser)
    page = context.new_page()
    login_demo(page, live_app_url)
    page.evaluate(
        """async () => {
          await Promise.all(
            ["network", "bill", "complaints", "roaming"].map(
              (name) => window.WorkflowState.get(name).reset()
            )
          );
        }"""
    )

    page.evaluate("window.App.navigate('roaming')")
    assert_transition(page.locator('.screen[data-screen="roaming"]'), "forward")
    horizontal_stability = page.locator("#app-scroll").evaluate(
        """(element) => {
          element.scrollLeft = 100;
          return {
            overflowX: getComputedStyle(element).overflowX,
            scrollLeft: element.scrollLeft,
          };
        }"""
    )
    assert horizontal_stability["overflowX"] in {"clip", "hidden"}
    assert horizontal_stability["scrollLeft"] == 0
    page.wait_for_timeout(420)
    page.evaluate("window.App.navigate('home')")
    assert_transition(page.locator('.screen[data-screen="home"]'), "back")

    page.wait_for_timeout(420)
    page.evaluate("window.App.navigate('network-bill')")
    assert_transition(page.locator('.screen[data-screen="network-bill"]'), "forward")

    page.locator('[data-segment="bill"]').click()
    assert_transition(page.locator('[data-panel="bill"]'), "forward")
    page.locator('[data-segment="network"]').click()
    assert_transition(page.locator('[data-panel="network"]'), "back")

    page.evaluate(
        "window.WorkflowState.get('network').go('testing', {save: false})"
    )
    assert_transition(page.locator("#speed-test-card"), "forward")
    page.evaluate(
        "window.WorkflowState.get('network').go('landing', {save: false})"
    )
    assert_transition(page.locator('[data-panel="network"]'), "back")

    page.locator('[data-segment="bill"]').click()
    page.evaluate("window.WorkflowState.get('bill').go('fields', {save: false})")
    assert_transition(page.locator("#bill-fields"), "forward")
    page.evaluate("window.WorkflowState.get('bill').go('landing', {save: false})")
    assert_transition(page.locator("#bill-input-choice"), "back")

    page.evaluate("window.App.navigate('complaints')")
    page.evaluate(
        "window.WorkflowState.get('complaints').go('form', {save: false})"
    )
    assert_transition(page.locator("#complaint-form-section"), "forward")
    page.evaluate(
        "window.WorkflowState.get('complaints').go('landing', {save: false})"
    )
    assert_transition(page.locator("#complaint-landing"), "back")

    page.evaluate("window.App.navigate('roaming')")
    page.locator("#start-roaming").click()
    step_one = page.locator('[data-roaming-step="1"]')
    assert_transition(step_one, "forward")
    page.locator('[data-country="United Kingdom"]').click()
    page.locator("#destination-next").click()
    step_two = page.locator('[data-roaming-step="2"]')
    assert_transition(step_two, "forward")
    step_two.locator('[data-edit-roaming="1"]').first.click()
    assert_transition(step_one, "back")
    context.close()


def test_reduced_motion_skips_page_transitions(browser, live_app_url):
    context = iphone_context(browser)
    page = context.new_page()
    page.emulate_media(reduced_motion="reduce")
    login_demo(page, live_app_url)

    page.evaluate("window.App.navigate('roaming')")
    roaming = page.locator('.screen[data-screen="roaming"]')
    assert roaming.evaluate(
        """(element) => !element.classList.contains("view-enter-forward")
          && !element.classList.contains("view-enter-back")
          && element.getAnimations().length === 0"""
    )
    context.close()
