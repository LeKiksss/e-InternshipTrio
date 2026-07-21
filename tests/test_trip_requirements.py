from datetime import date, timedelta

import pytest

from app.services.usage_analysis import (
    calculate_trip_days,
    scale_usage_to_trip,
)


@pytest.mark.parametrize("trip_days", [1, 3, 7, 9, 14, 21, 23, 30])
def test_inclusive_trip_durations(trip_days):
    start = date(2030, 8, 1)
    end = start + timedelta(days=trip_days - 1)
    assert calculate_trip_days(start.isoformat(), end.isoformat()) == trip_days


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (None, "2030-08-01"),
        ("invalid", "2030-08-01"),
        ("2030-08-02", "2030-08-01"),
    ],
)
def test_invalid_trip_dates_are_rejected(start, end):
    with pytest.raises(ValueError):
        calculate_trip_days(start, end)


def test_past_trip_is_rejected_when_ui_policy_is_applied():
    with pytest.raises(ValueError, match="future"):
        calculate_trip_days("2026-01-01", "2026-01-07", today=date(2026, 7, 21))


def test_trip_scaling_uses_thirty_day_month_without_rounding():
    monthly = {
        "data_gb": 30,
        "local_minutes": 300,
        "international_minutes": 150,
        "sms": 60,
    }
    result = scale_usage_to_trip(monthly, 7)
    assert result == pytest.approx(
        {
            "data_gb": 7,
            "local_minutes": 70,
            "international_minutes": 35,
            "sms": 14,
        }
    )
