from dataclasses import dataclass
from datetime import date

import pytest

from app.models import User
from app.services.usage_analysis import (
    OUTLIER_CHANGE_THRESHOLD,
    RECENCY_WEIGHTS,
    analyse_usage,
)


@dataclass
class UsageRow:
    usage_month: date
    data_gb: float
    local_minutes: int
    international_minutes: int
    sms: int
    user_id: int = 99

    def to_dict(self):
        return {
            "usage_month": self.usage_month.isoformat(),
            "data_gb": self.data_gb,
            "local_minutes": self.local_minutes,
            "international_minutes": self.international_minutes,
            "sms": self.sms,
        }


def reference_weighted(values, excluded=()):
    included = [
        (value, weight)
        for index, (value, weight) in enumerate(
            zip(values, RECENCY_WEIGHTS, strict=True)
        )
        if index not in excluded
    ]
    total = sum(weight for _value, weight in included)
    return sum(value * weight / total for value, weight in included)


def rows_for(values, *, local=None, international=None, sms=None):
    local = local or [10] * 6
    international = international or [5] * 6
    sms = sms or [2] * 6
    return [
        UsageRow(date(2026, index + 1, 1), values[index], local[index], international[index], sms[index])
        for index in range(6)
    ]


@pytest.mark.parametrize(
    ("email", "classification"),
    [
        ("aisha@example.test", "stable"),
        ("omar@example.test", "isolated_outlier"),
        ("layla@example.test", "upward_trend"),
        ("yusuf@example.test", "downward_trend"),
    ],
)
def test_seeded_usage_patterns(app, email, classification):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        result = analyse_usage(user.monthly_usage)
        assert result["pattern_classification"] == classification


def test_aisha_uses_exact_recency_weights_without_exclusions(app):
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        result = analyse_usage(aisha.monthly_usage)
        for metric, metric_result in result["metric_results"].items():
            values = [float(getattr(row, metric)) for row in aisha.monthly_usage]
            assert metric_result["excluded_months"] == []
            assert metric_result["effective_weights"] == pytest.approx(RECENCY_WEIGHTS)
            assert metric_result["weighted_estimate"] == pytest.approx(
                reference_weighted(values)
            )


def test_omar_excludes_only_march_per_metric_and_renormalizes(app):
    with app.app_context():
        omar = User.query.filter_by(email="omar@example.test").one()
        result = analyse_usage(omar.monthly_usage)
        assert len(result["excluded_outliers"]) == 4
        for metric, metric_result in result["metric_results"].items():
            values = [float(getattr(row, metric)) for row in omar.monthly_usage]
            assert metric_result["excluded_months"] == ["2026-03-01"]
            assert metric_result["effective_weights"][2] == 0
            assert sum(metric_result["effective_weights"]) == pytest.approx(1)
            assert metric_result["weighted_estimate"] == pytest.approx(
                reference_weighted(values, excluded={2})
            )
            changes = metric_result["successive_month_changes"]
            assert changes[1]["from_month"] == "2026-02-01"
            assert changes[1]["to_month"] == "2026-03-01"
            assert changes[1]["exceeds_outlier_threshold"] is True
            assert changes[2]["from_month"] == "2026-03-01"
            assert changes[2]["to_month"] == "2026-04-01"
            assert changes[2]["exceeds_outlier_threshold"] is True

        assert result["outlier_policy"] == {
            "method": "successive_month_comparison",
            "threshold_percent": 30.0,
            "excluded_values_used_for_profile": False,
        }


@pytest.mark.parametrize(
    ("email", "direction"),
    [
        ("layla@example.test", "upward_trend"),
        ("yusuf@example.test", "downward_trend"),
    ],
)
def test_trends_keep_all_observations_and_do_not_extrapolate(app, email, direction):
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        result = analyse_usage(user.monthly_usage)
        for metric, metric_result in result["metric_results"].items():
            values = [float(getattr(row, metric)) for row in user.monthly_usage]
            assert metric_result["detected_pattern"] == direction
            assert metric_result["excluded_months"] == []
            assert metric_result["effective_weights"] == pytest.approx(RECENCY_WEIGHTS)
            assert metric_result["weighted_estimate"] == pytest.approx(
                reference_weighted(values)
            )
            assert min(values) <= metric_result["weighted_estimate"] <= max(values)


def test_identical_values_are_stable():
    result = analyse_usage(rows_for([5, 5, 5, 5, 5, 5]))
    assert result["pattern_classification"] == "stable"
    assert result["excluded_outliers"] == []


def test_extreme_final_month_is_isolated():
    isolated = analyse_usage(rows_for([5, 5, 5, 5, 5, 100]))
    assert isolated["metric_results"]["data_gb"]["excluded_months"] == ["2026-06-01"]


def test_gradual_change_over_six_months_is_not_an_outlier():
    upward = analyse_usage(rows_for([10, 11.6, 13.4, 15.5, 18, 21]))
    downward = analyse_usage(rows_for([21, 18, 15.5, 13.4, 11.6, 10]))

    assert upward["metric_results"]["data_gb"]["detected_pattern"] == "upward_trend"
    assert downward["metric_results"]["data_gb"]["detected_pattern"] == "downward_trend"
    assert upward["metric_results"]["data_gb"]["excluded_months"] == []
    assert downward["metric_results"]["data_gb"]["excluded_months"] == []
    assert upward["metric_results"]["data_gb"]["raw_values"][-1] > (
        upward["metric_results"]["data_gb"]["raw_values"][0] * 2
    )
    assert all(
        abs(change["change_percent"]) <= OUTLIER_CHANGE_THRESHOLD * 100
        for change in upward["metric_results"]["data_gb"]["successive_month_changes"]
    )


def test_outlier_threshold_is_strictly_greater_than_thirty_percent():
    exactly_thirty = analyse_usage(rows_for([10, 13, 10, 10, 10, 10]))
    above_thirty = analyse_usage(rows_for([10, 13.1, 10, 10, 10, 10]))

    assert exactly_thirty["metric_results"]["data_gb"]["excluded_months"] == []
    assert above_thirty["metric_results"]["data_gb"]["excluded_months"] == [
        "2026-02-01"
    ]


def test_outlier_handling_is_independent_per_metric():
    result = analyse_usage(
        rows_for(
            [4, 4, 80, 4, 4, 4],
            local=[10, 11, 12, 13, 14, 15],
            international=[5, 5, 5, 5, 5, 5],
            sms=[1, 1, 1, 1, 1, 1],
        )
    )
    assert result["metric_results"]["data_gb"]["excluded_months"] == ["2026-03-01"]
    assert result["metric_results"]["local_minutes"]["excluded_months"] == []
    assert result["metric_results"]["international_minutes"]["excluded_months"] == []
    assert result["metric_results"]["sms"]["excluded_months"] == []
