from datetime import date, timedelta

import pytest
from playwright.sync_api import expect

from .conftest import login_demo


pytestmark = pytest.mark.browser


def open_screen(page, name):
    page.locator(f'.bottom-nav [data-nav="{name}"]').click()
    expect(page.locator(f'.screen[data-screen="{name}"]')).to_be_visible()


def assert_clean_visible_copy(page):
    visible_copy = page.locator("body").inner_text().lower()
    for label in (
        "demo",
        "prototype",
        "fictional",
        "fake",
        "mock",
        "placeholder",
        "simulated",
        "proof of concept",
    ):
        assert label not in visible_copy


def assert_no_horizontal_overflow(page):
    page.wait_for_timeout(320)
    audit = page.locator("#app-scroll").evaluate(
        """(element) => {
          const root = element.getBoundingClientRect();
          const offenders = [...element.querySelectorAll('*')].flatMap((node) => {
            const rect = node.getBoundingClientRect();
            if (!rect.width || getComputedStyle(node).display === 'none') return [];
            if (rect.left < root.left - 1 || rect.right > root.right + 1) {
              return [{ tag: node.tagName, id: node.id, className: String(node.className), left: rect.left, right: rect.right, width: rect.width }];
            }
            return [];
          }).slice(0, 12);
          return { clientWidth: element.clientWidth, scrollWidth: element.scrollWidth, rootLeft: root.left, rootRight: root.right, offenders };
        }"""
    )
    assert audit["scrollWidth"] <= audit["clientWidth"] + 1, audit


def complete_network_test(page, location_choice):
    page.locator("#run-speed-test").click()
    expect(page.locator("#location-sheet")).to_be_visible()
    page.locator(f'[data-location-choice="{location_choice}"]').click()
    expect(page.locator("#network-result")).to_be_visible()


def test_expanded_preview_keeps_phone_toggle_reachable(browser, live_app_url):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    login_demo(page, live_app_url)
    expanded = page.locator('.preview-mode[data-mode="expanded"]')
    phone = page.locator('.preview-mode[data-mode="phone"]')
    expanded.click()
    expect(page.locator(".desktop-stage")).to_have_attribute("data-preview", "expanded")
    expect(phone).to_be_visible()
    box = phone.bounding_box()
    assert box is not None
    assert 0 <= box["x"] < 1440
    assert 0 <= box["y"] < 1000
    assert box["x"] + box["width"] <= 1440
    assert box["y"] + box["height"] <= 1000
    phone.click()
    expect(page.locator(".desktop-stage")).to_have_attribute("data-preview", "phone")
    context.close()


def test_seeded_identity_and_repeatable_network_and_bill(page, live_app_url):
    login_demo(page, live_app_url)
    assert_clean_visible_copy(page)

    open_screen(page, "profile")
    expect(page.locator("#profile-name-display")).to_have_text("Aisha Noor")
    expect(page.locator("#profile-email")).to_have_value("aisha@example.test")
    expect(page.locator("#profile-phone")).to_have_value("+971500000101")
    assert_clean_visible_copy(page)
    assert_no_horizontal_overflow(page)
    page.locator('[data-open-sheet="help-sheet"]:visible').first.click()
    expect(page.locator("#help-sheet")).to_be_visible()
    assert_clean_visible_copy(page)
    page.locator("#help-sheet [data-close-sheet]").click()

    open_screen(page, "network-bill")
    assert_clean_visible_copy(page)
    assert_no_horizontal_overflow(page)
    complete_network_test(page, "allow")
    page.locator("#network-done").click()
    expect(page.locator("#network-latest-result")).to_be_visible()
    complete_network_test(page, "deny")
    expect(page.locator("#diagnostic-history .history-card")).to_have_count(3)
    page.locator("#network-done").click()

    page.locator('[data-segment="bill"]').click()
    page.locator("#view-usage-history").click()
    expect(page.locator("#bill-usage-history")).to_be_visible()
    expect(page.locator("#bill-usage-history .usage-history-card")).to_have_count(6)
    latest_usage = page.locator('[data-usage-month="2026-06-01"]')
    expect(latest_usage).to_contain_text("June 2026")
    expect(latest_usage).to_contain_text("4.7 GB")
    expect(latest_usage).to_contain_text("119 min")
    page.locator("#usage-history-back").click()
    expect(page.locator("#bill-input-choice")).to_be_visible()
    assert_no_horizontal_overflow(page)

    page.locator("#analyse-another").click()
    page.locator('[data-bill-mode="upload"]').click()
    page.locator("#bill-file").set_input_files(
        {
            "name": "july-bill.pdf",
            "mimeType": "application/pdf",
            "buffer": b"%PDF-1.4 customer bill",
        }
    )
    expect(page.locator("#bill-filename")).to_have_text("july-bill.pdf")
    page.locator("#bill-upload-flow [data-bill-back]").click()
    expect(page.locator("#bill-input-choice")).to_be_visible()
    page.locator('[data-bill-mode="upload"]').click()
    expect(page.locator("#bill-filename")).to_have_text("july-bill.pdf")
    page.locator("#parse-bill").click()
    expect(page.locator("#bill-fields")).to_be_visible()

    page.locator("#bill-total").fill("500")
    page.locator("#bill-data").fill("250")
    page.locator("#bill-calls").fill("80")
    page.locator("#bill-roaming").fill("100")
    page.locator("#bill-addons").fill("70")
    page.locator("#bill-fields [data-bill-back]").click()
    page.locator("#parse-bill").click()
    expect(page.locator("#bill-total")).to_have_value("500")
    page.locator('#bill-form button[type="submit"]').click()
    expect(page.locator("#bill-analysis")).to_be_visible()
    page.locator("#bill-result-back").click()
    expect(page.locator("#bill-total")).to_have_value("500")
    page.locator('#bill-form button[type="submit"]').click()
    page.locator("#bill-done").click()
    expect(page.locator("#bill-landing-total")).to_have_text("AED 500")

    page.locator("#analyse-another").click()
    page.locator('[data-bill-mode="manual"]').click()
    page.locator("#bill-total").fill("200")
    page.locator("#bill-data").fill("100")
    page.locator("#bill-calls").fill("50")
    page.locator("#bill-roaming").fill("25")
    page.locator("#bill-addons").fill("25")
    page.locator('#bill-form button[type="submit"]').click()
    expect(page.locator("#bill-analysis")).to_be_visible()
    page.locator("#bill-done").click()
    expect(page.locator("#bill-landing-total")).to_have_text("AED 200")


def test_complaint_back_state_and_second_request(page, live_app_url):
    login_demo(page, live_app_url)
    open_screen(page, "complaints")
    assert_clean_visible_copy(page)
    assert_no_horizontal_overflow(page)

    page.locator("#start-complaint").click()
    page.locator("#consent-form").click()
    page.locator("#complaint-description").fill(
        "The billing amount is incorrect on the July statement."
    )
    page.locator("#complaint-category").select_option(label="Billing")
    page.locator("#complaint-location").fill("Dubai")
    page.locator('#complaint-form button[type="submit"]').click()
    expect(page.locator("#diagnosis-view")).to_be_visible()
    page.locator("#edit-complaint").click()
    expect(page.locator("#complaint-description")).to_have_value(
        "The billing amount is incorrect on the July statement."
    )
    page.locator('#complaint-form button[type="submit"]').click()
    page.locator("#submit-complaint").click()
    expect(page.locator("#complaint-success")).to_be_visible()
    page.locator("#complaint-done").click()
    expect(page.locator("#complaint-latest-dynamic")).to_be_visible()

    page.locator("#start-complaint").click()
    page.locator("#consent-chat").click()
    page.locator("#complaint-input").fill(
        "The mobile data service disconnects several times each day."
    )
    page.locator("#send-complaint-message").click()
    page.locator("#complaint-chat-back").click()
    expect(page.locator("#complaint-input")).to_have_value(
        "The mobile data service disconnects several times each day."
    )
    page.locator("#complaint-input").fill(
        "The mobile data service repeatedly disconnects throughout the day."
    )
    page.locator("#send-complaint-message").click()
    for reply in ("Network", "Today", "Dubai", "Still happening", "Unable to use service"):
        page.get_by_role("button", name=reply, exact=True).click()
    expect(page.locator("#diagnosis-view")).to_be_visible()
    page.locator("#submit-complaint").click()
    expect(page.locator("#complaint-success")).to_be_visible()
    page.locator("#complaint-done").click()
    expect(page.locator("#ticket-list .ticket-row")).to_have_count(3)


def test_roaming_recalculates_adjusts_saves_and_clears_on_logout(page, live_app_url):
    login_demo(page, live_app_url)
    open_screen(page, "roaming")
    expect(page.locator("#roaming-title")).to_have_text("Roaming Recommender")
    assert_clean_visible_copy(page)
    assert_no_horizontal_overflow(page)

    start = date.today() + timedelta(days=2)
    end_seven_days = start + timedelta(days=6)
    end_nine_days = start + timedelta(days=8)
    end_fourteen_days = start + timedelta(days=13)

    page.locator("#start-roaming").click()
    country_snapshot = page.locator("#country-list").evaluate(
        """(list) => ({
          letters: [...list.querySelectorAll('.country-letter')].map((item) => item.textContent.trim()),
          countries: [...list.querySelectorAll('button[data-country]')].map((item) => item.dataset.country),
          letterTags: [...list.querySelectorAll('.country-letter')].map((item) => item.tagName),
        })"""
    )
    assert len(country_snapshot["countries"]) == 32
    assert country_snapshot["countries"] == sorted(country_snapshot["countries"])
    assert country_snapshot["letters"] == sorted(country_snapshot["letters"])
    assert all(tag != "BUTTON" for tag in country_snapshot["letterTags"])
    expect(page.locator("#country-count")).to_have_text("32 countries")
    page.locator("#country-search").fill("b")
    visible_countries = page.locator("#country-list button[data-country]:visible")
    expect(visible_countries).to_have_count(3)
    assert visible_countries.evaluate_all(
        "(buttons) => buttons.every((button) => button.dataset.country.toLowerCase().startsWith('b'))"
    )
    expect(page.locator('[data-country="Saudi Arabia"]')).to_be_hidden()
    expect(page.locator("[data-country-group]:visible .country-letter")).to_have_text("B")
    expect(page.locator("#country-count")).to_have_text("3 countries")
    page.locator("#country-search").fill("zz")
    expect(page.locator("#country-list button[data-country]:visible")).to_have_count(0)
    expect(page.locator("#country-count")).to_have_text("0 countries")
    expect(page.locator("#country-empty")).to_be_visible()
    page.locator("#country-search").fill("")
    expect(page.locator("#country-count")).to_have_text("32 countries")
    expect(page.locator("#country-empty")).to_be_hidden()
    page.locator('[data-country="United Kingdom"]').click()
    page.locator("#destination-next").click()
    page.locator("#trip-start").fill(start.isoformat())
    page.locator("#trip-end").fill(end_seven_days.isoformat())
    expect(page.locator("#trip-days")).to_have_text("7")
    page.locator("#dates-next").click()

    expect(page.locator('[data-testid="current-usage-recommendation"]')).to_be_visible()
    expect(page.locator(".recommender-identity strong")).to_have_text("Roam Like Home")
    assert_clean_visible_copy(page)
    assert_no_horizontal_overflow(page)
    expect(page.locator("#usage-plan-items .plan-item")).to_have_count(1)
    expect(page.locator('#usage-plan-items [data-package-code="ESS-7D"]')).to_be_visible()

    page.locator('[data-edit-roaming="2"]').first.click()
    expect(page.locator("#trip-start")).to_have_value(start.isoformat())
    page.locator("#trip-end").fill(end_nine_days.isoformat())
    expect(page.locator("#trip-days")).to_have_text("9")
    page.locator("#dates-next").click()
    expect(page.locator("#usage-plan-items .plan-item")).to_have_count(2)
    expect(page.locator("#usage-activation-count")).to_have_text("3")

    layout = page.evaluate(
        """() => {
          const chat = document.querySelector('.adjustment-chat').getBoundingClientRect();
          const composer = document.querySelector('.roaming-composer').getBoundingClientRect();
          const textarea = document.querySelector('#roaming-adjustment').getBoundingClientRect();
          return {
            suggestionCount: document.querySelectorAll('.adjustment-chips').length,
            chatWidth: chat.width,
            composerWidth: composer.width,
            textareaHeight: textarea.height,
          };
        }"""
    )
    assert layout["suggestionCount"] == 0
    assert layout["composerWidth"] >= layout["chatWidth"] - 40
    assert layout["textareaHeight"] >= 125
    page.locator("#usage-more-details").click()
    expect(page.locator("#usage-details-panel")).to_be_visible()
    expect(page.locator("#average-data")).to_have_text("1.3 GB")
    expect(page.locator("#average-local")).to_have_text("34 min")
    expect(page.locator("#average-international")).to_have_text("6 min")
    expect(page.locator("#average-sms")).to_have_text("4")

    page.locator('[data-edit-roaming="2"]').first.click()
    expect(page.locator("#trip-start")).to_have_value(start.isoformat())
    page.locator("#trip-end").fill(end_fourteen_days.isoformat())
    expect(page.locator("#trip-days")).to_have_text("14")
    page.locator("#dates-next").click()
    expect(page.locator("#average-data")).to_have_text("2.1 GB")

    page.locator("#roaming-adjustment").fill(
        "For the first week I will have Wi-Fi and need light usage, and I need heavy data in the second week."
    )
    page.locator("#send-roaming-adjustment").click()
    expect(page.locator("#usage-segment-timeline")).to_be_visible()
    expect(page.locator("#roaming-chat-messages .chat-message")).to_have_count(2)
    expect(page.locator("#usage-segment-timeline .segment-card")).to_have_count(2)
    expect(page.locator("#usage-plan-items .plan-item")).not_to_have_count(0)
    expect(page.locator('[data-testid="current-usage-recommendation"]')).to_have_count(1)

    page.locator("#continue-roaming-plan").click()
    expect(page.locator('[data-testid="final-roaming-recommendation"]')).to_be_visible()
    assert_clean_visible_copy(page)
    assert_no_horizontal_overflow(page)
    expect(page.locator("#final-plan-items .plan-item")).not_to_have_count(0)
    expect(page.locator("#final-segment-timeline .segment-card")).to_have_count(2)
    expect(page.locator('[data-testid="final-roaming-recommendation"] .fit-explanation')).to_have_count(0)
    expect(page.locator("#package-why")).to_have_count(0)
    expect(page.locator('[data-testid="carrier-acknowledgement"]')).to_be_visible()
    expect(page.locator("#carrier-note-network")).to_have_text("Automatic partner selection")
    expect(page.locator("#copy-code")).to_be_disabled()
    expect(page.locator("#open-dialer")).to_be_disabled()
    expect(page.locator("#roaming-done")).to_be_disabled()
    expect(page.locator("#activation-sequence .activation-step")).not_to_have_count(0)
    assert "*170*" not in page.locator("#activation-sequence").inner_text()
    page.locator("#save-recommendation").click()
    expect(page.locator("#save-recommendation")).to_have_text("Saved")
    page.locator("#carrier-acknowledgement").check()
    expect(page.locator("#copy-code")).to_be_enabled()
    expect(page.locator("#open-dialer")).to_be_enabled()
    expect(page.locator("#roaming-done")).to_be_enabled()
    expect(page.locator("#activation-code")).to_have_attribute("aria-hidden", "false")
    assert "*170*" in page.locator("#activation-sequence").inner_text()
    expect(page.locator("#copy-code")).to_have_text("Copy activation codes")
    page.locator("#copy-code").click()
    expect(page.locator("#copy-code")).to_have_text("Copied")
    page.locator("#roaming-done").click()
    expect(page.locator("#saved-recommendations-section")).to_be_visible()
    expect(page.locator(".saved-roaming-card")).to_have_count(1)

    page.reload()
    expect(page.locator("#saved-recommendations-section")).to_be_visible()
    expect(page.locator(".saved-roaming-card")).to_have_count(1)
    page.locator("[data-view-saved]").click()
    expect(page.locator("#final-plan-items .plan-item")).not_to_have_count(0)
    expect(page.locator("#final-segment-timeline .segment-card")).to_have_count(2)
    expect(page.locator("#copy-code")).to_be_disabled()
    page.locator("#roaming-result-back").click()
    page.locator("[data-remove-saved]").click()
    page.locator("#confirm-action").click()
    expect(page.locator(".saved-roaming-card")).to_have_count(0)

    open_screen(page, "profile")
    page.locator("#logout-button").click()
    page.locator("#confirm-action").click()
    expect(page.locator("#identity")).to_be_visible()
    login_demo(page, live_app_url)
    open_screen(page, "roaming")
    expect(page.locator(".saved-roaming-card")).to_have_count(0)
