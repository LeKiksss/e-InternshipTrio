from datetime import date

import pytest

from app.services.mock_roaming import (
    adjusted_package,
    calculate_trip_days,
    current_usage_package,
    parse_adjustment,
    scale_usage,
)


@pytest.mark.parametrize(
    ("days", "data", "local", "international", "sms"),
    [
        (1, 0.8, 16, 6, 2),
        (7, 5.6, 112, 42, 14),
        (9, 7.2, 144, 54, 18),
        (14, 11.2, 224, 84, 28),
        (21, 16.8, 336, 126, 42),
        (30, 24.0, 480, 180, 60),
    ],
)
def test_usage_scales_for_trip_duration(days, data, local, international, sms):
    result = scale_usage(days)
    assert result == {
        "trip_days": days,
        "data_gb": data,
        "local_minutes": local,
        "international_minutes": international,
        "sms": sms,
    }


def test_trip_duration_is_inclusive_and_validated():
    assert calculate_trip_days("2026-08-01", "2026-08-07") == 7
    assert calculate_trip_days("2026-08-01", "2026-08-01") == 1
    with pytest.raises(ValueError):
        calculate_trip_days("2026-08-08", "2026-08-07")
    with pytest.raises(ValueError):
        calculate_trip_days("2026-07-01", "2026-07-02", today=date(2026, 7, 20))


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("That is too expensive", "cheaper"),
        ("I need more data for video", "more_data"),
        ("Mostly messaging and less data", "less_data"),
        ("I need more call minutes", "more_calls"),
        ("I will make no calls", "fewer_calls"),
        ("I need international calls home", "more_international"),
        ("Give me longer validity", "longer"),
        ("Keep this recommendation", "keep"),
    ],
)
def test_comparative_intent_parsing(message, intent):
    assert parse_adjustment(message) == intent


def test_package_variants_change_the_expected_allowance():
    base = current_usage_package("Canada", 9)
    cheaper = adjusted_package("cheaper", "Canada", 9)
    data = adjusted_package("more_data", "Canada", 9)
    voice = adjusted_package("more_calls", "Canada", 9)
    assert base["name"] == "Roam Like Home"
    assert base["validity_days"] >= 9
    assert cheaper["price"] < base["price"]
    assert data["data_gb"] > base["data_gb"]
    assert voice["local_minutes"] > base["local_minutes"]


def test_long_trip_recommendation_covers_the_trip():
    package = current_usage_package("Japan", 21)
    assert package["validity_days"] >= 21
