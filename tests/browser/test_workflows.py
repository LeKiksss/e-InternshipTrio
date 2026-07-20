from datetime import date, timedelta

import pytest
from playwright.sync_api import expect

from .conftest import login_demo


pytestmark = pytest.mark.browser


def open_screen(page, name):
    page.locator(f'.bottom-nav [data-nav="{name}"]').click()
    expect(page.locator(f'.screen[data-screen="{name}"]')).to_be_visible()


def complete_network_test(page, location_choice):
    page.locator("#run-speed-test").click()
    expect(page.locator("#location-sheet")).to_be_visible()
    page.locator(f'[data-location-choice="{location_choice}"]').click()
    expect(page.locator("#network-result")).to_be_visible()


def test_demo_identity_and_repeatable_network_and_bill(page, live_app_url):
    login_demo(page, live_app_url)

    open_screen(page, "profile")
    expect(page.locator("#profile-name-display")).to_have_text("Prototype Demo User")
    expect(page.locator("#profile-phone")).to_have_value("+971501234567")

    open_screen(page, "network-bill")
    complete_network_test(page, "allow")
    page.locator("#network-done").click()
    expect(page.locator("#network-latest-result")).to_be_visible()
    complete_network_test(page, "deny")
    expect(page.locator("#diagnostic-history .history-card")).to_have_count(3)
    page.locator("#network-done").click()

    page.locator('[data-segment="bill"]').click()
    page.locator("#analyse-another").click()
    page.locator('[data-bill-mode="upload"]').click()
    page.locator("#bill-file").set_input_files(
        {
            "name": "fictional-demo-bill.pdf",
            "mimeType": "application/pdf",
            "buffer": b"%PDF-1.4 fictional prototype bill",
        }
    )
    expect(page.locator("#bill-filename")).to_have_text("fictional-demo-bill.pdf")
    page.locator("#bill-upload-flow [data-bill-back]").click()
    expect(page.locator("#bill-input-choice")).to_be_visible()
    page.locator('[data-bill-mode="upload"]').click()
    expect(page.locator("#bill-filename")).to_have_text("fictional-demo-bill.pdf")
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

    page.locator("#start-complaint").click()
    page.locator("#consent-form").click()
    page.locator("#complaint-description").fill(
        "Prototype billing amount is incorrect on the fictional July statement."
    )
    page.locator("#complaint-category").select_option(label="Billing")
    page.locator("#complaint-location").fill("Demo location")
    page.locator('#complaint-form button[type="submit"]').click()
    expect(page.locator("#diagnosis-view")).to_be_visible()
    page.locator("#edit-complaint").click()
    expect(page.locator("#complaint-description")).to_have_value(
        "Prototype billing amount is incorrect on the fictional July statement."
    )
    page.locator('#complaint-form button[type="submit"]').click()
    page.locator("#submit-complaint").click()
    expect(page.locator("#complaint-success")).to_be_visible()
    page.locator("#complaint-done").click()
    expect(page.locator("#complaint-latest-dynamic")).to_be_visible()

    page.locator("#start-complaint").click()
    page.locator("#consent-chat").click()
    page.locator("#complaint-input").fill(
        "The fictional mobile data service disconnects in the prototype."
    )
    page.locator("#send-complaint-message").click()
    page.locator("#complaint-chat-back").click()
    expect(page.locator("#complaint-input")).to_have_value(
        "The fictional mobile data service disconnects in the prototype."
    )
    page.locator("#complaint-input").fill(
        "The fictional mobile data service repeatedly disconnects in the prototype."
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
    expect(page.locator("#roaming-title")).to_have_text("Roam Like Home")

    start = date.today() + timedelta(days=2)
    end_nine_days = start + timedelta(days=8)
    end_seven_days = start + timedelta(days=6)

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
    page.locator("#trip-end").fill(end_nine_days.isoformat())
    expect(page.locator("#trip-days")).to_have_text("9")
    page.locator("#dates-next").click()

    expect(page.get_by_role("heading", name="Recommended plan based on your current usage")).to_be_visible()
    expect(page.locator(".recommender-identity strong")).to_have_text("Roam Like Home")
    expect(page.locator("#usage-package-name")).to_have_text("Travel Connect")
    layout = page.evaluate(
        """() => {
          const chips = document.querySelector('.adjustment-chips').getBoundingClientRect();
          const composer = document.querySelector('.roaming-composer').getBoundingClientRect();
          const textarea = document.querySelector('#roaming-adjustment').getBoundingClientRect();
          return { chipsBottom: chips.bottom, composerTop: composer.top, textareaHeight: textarea.height };
        }"""
    )
    assert layout["chipsBottom"] <= layout["composerTop"]
    assert layout["textareaHeight"] >= 90
    page.locator("#usage-more-details").click()
    expect(page.locator("#usage-details-panel")).to_be_visible()
    expect(page.locator("#average-data")).to_have_text("7.2 GB")
    expect(page.locator("#average-local")).to_have_text("144 min")
    expect(page.locator("#average-international")).to_have_text("54 min")
    expect(page.locator("#average-sms")).to_have_text("18")

    page.locator('[data-edit-roaming="2"]').first.click()
    expect(page.locator("#trip-start")).to_have_value(start.isoformat())
    page.locator("#trip-end").fill(end_seven_days.isoformat())
    expect(page.locator("#trip-days")).to_have_text("7")
    page.locator("#dates-next").click()
    expect(page.locator("#average-data")).to_have_text("5.6 GB")

    page.get_by_role("button", name="Cheaper option", exact=True).click()
    expect(page.locator("#usage-package-name")).to_have_text("Travel Data Lite")
    page.get_by_role("button", name="More data", exact=True).click()
    expect(page.locator("#usage-package-name")).to_have_text("Data Max Abroad")
    expect(page.locator('[data-testid="current-usage-recommendation"]')).to_have_count(1)

    page.locator("#continue-roaming-plan").click()
    expect(page.locator('[data-testid="final-roaming-recommendation"]')).to_be_visible()
    expect(page.locator("#package-name")).to_have_text("Data Max Abroad")
    expect(page.locator('[data-testid="carrier-acknowledgement"]')).to_be_visible()
    expect(page.locator("#carrier-note-network")).to_have_text("Preferred Partner 1")
    expect(page.locator("#copy-code")).to_be_disabled()
    expect(page.locator("#open-dialer")).to_be_disabled()
    expect(page.locator("#roaming-done")).to_be_disabled()
    assert page.locator("#activation-code").evaluate(
        "(element) => getComputedStyle(element).filter"
    ) != "none"
    page.locator("#save-recommendation").click()
    expect(page.locator("#save-recommendation")).to_have_text("Saved")
    page.locator("#carrier-acknowledgement").check()
    expect(page.locator("#copy-code")).to_be_enabled()
    expect(page.locator("#open-dialer")).to_be_enabled()
    expect(page.locator("#roaming-done")).to_be_enabled()
    expect(page.locator("#activation-code")).to_have_attribute("aria-hidden", "false")
    expect(page.locator("#copy-code")).to_have_text("Copy code")
    page.locator("#copy-code").click()
    expect(page.locator("#copy-code")).to_have_text("Copied")
    page.locator("#roaming-done").click()
    expect(page.locator("#saved-recommendations-section")).to_be_visible()
    expect(page.locator(".saved-roaming-card")).to_have_count(1)

    page.reload()
    expect(page.locator("#saved-recommendations-section")).to_be_visible()
    expect(page.locator(".saved-roaming-card")).to_have_count(1)
    page.locator("[data-view-saved]").click()
    expect(page.locator("#package-name")).to_have_text("Data Max Abroad")
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
