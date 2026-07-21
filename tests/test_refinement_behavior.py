import pytest

from app.models import RoamingPackage, User
from app.services.package_fallback_optimizer import optimize_package_plan
from app.services.roaming_recommendation import build_recommendation
from app.services.user_requirement_parser import parse_user_requirements


BASE_REQUIREMENTS = {
    "data_gb": 1,
    "local_minutes": 20,
    "international_minutes": 5,
    "sms": 5,
}
CURRENT = {
    "selection": {
        "total_data_gb": 20,
        "total_local_minutes": 700,
        "total_international_minutes": 350,
        "total_sms": 150,
        "total_price_aed": 299,
        "total_validity_days": 7,
        "activation_count": 3,
    }
}


def packages():
    return RoamingPackage.query.order_by(RoamingPackage.package_code).all()


@pytest.mark.parametrize(
    ("message", "metric", "minimum"),
    [
        ("I need 10 GB", "total_data_gb", 10),
        ("I need at least 500 international minutes", "total_international_minutes", 500),
        ("I need 100 SMS", "total_sms", 100),
        ("Give me more data", "total_data_gb", 25),
        ("I need more calls", "total_local_minutes", 875),
    ],
)
def test_numeric_and_more_requests_are_hard_constraints(app, message, metric, minimum):
    with app.app_context():
        parsed = parse_user_requirements(message, CURRENT, 7)
        requirements = dict(BASE_REQUIREMENTS)
        requirements.update(parsed["minimums"])
        plan = optimize_package_plan(
            packages(),
            7,
            requirements,
            exact_targets=parsed["exact_targets"],
            preferences=parsed["comparative"],
            current_selection=CURRENT["selection"],
        )
        assert plan["selection"][metric] >= minimum


@pytest.mark.parametrize(
    ("message", "new_field", "old_field"),
    [
        ("Give me less data", "total_data_gb", "total_data_gb"),
        ("I need fewer calls", "combined_calls", "combined_calls"),
        ("Give me a cheaper option", "total_price_aed", "total_price_aed"),
        ("I want fewer activations", "activation_count", "activation_count"),
    ],
)
def test_relative_reductions_are_measured_against_current_plan(
    app, message, new_field, old_field
):
    with app.app_context():
        parsed = parse_user_requirements(message, CURRENT, 7)
        plan = optimize_package_plan(
            packages(),
            7,
            BASE_REQUIREMENTS,
            preferences=parsed["comparative"],
            current_selection=CURRENT["selection"],
        )
        selection = plan["selection"]
        new = (
            selection["total_local_minutes"] + selection["total_international_minutes"]
            if new_field == "combined_calls"
            else selection[new_field]
        )
        old = (
            CURRENT["selection"]["total_local_minutes"]
            + CURRENT["selection"]["total_international_minutes"]
            if old_field == "combined_calls"
            else CURRENT["selection"][old_field]
        )
        assert new < old


def test_longer_validity_and_no_calls_are_reflected_in_validated_requirements(app):
    with app.app_context():
        longer = parse_user_requirements("I need longer validity", CURRENT, 7)
        plan = optimize_package_plan(
            packages(),
            7,
            BASE_REQUIREMENTS,
            preferences=longer["comparative"],
            minimum_validity_days=longer["minimum_validity_days"],
            current_selection=CURRENT["selection"],
        )
        assert plan["selection"]["total_validity_days"] > 7
        assert plan["selection"]["items"][0]["coverage_start_day"] == 1
        assert plan["selection"]["items"][-1]["coverage_end_day"] == 7

        no_calls = parse_user_requirements("I need no calls", CURRENT, 7)
        assert no_calls["minimums"]["local_minutes"] == 0
        assert no_calls["minimums"]["international_minutes"] == 0


def test_longer_validity_preserves_segment_boundaries_and_real_trip_coverage(app):
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        initial = build_recommendation(
            aisha, "France", "2030-08-01", "2030-08-14"
        )
        segmented = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-14",
            latest_message=(
                "For the first week I will have Wi-Fi and need light usage, "
                "and I need heavy data in the second week."
            ),
            current_recommendation=initial,
        )
        longer = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-14",
            latest_message="I need longer validity",
            current_recommendation=segmented,
        )

        assert longer["selection"]["total_validity_days"] > segmented["selection"]["total_validity_days"]
        assert [(row["start_day"], row["end_day"]) for row in longer["segments"]] == [
            (1, 7),
            (8, 14),
        ]
        segment_bounds = {
            row["segment_id"]: (row["start_day"], row["end_day"])
            for row in longer["segments"]
        }
        for item in longer["selection"]["items"]:
            start, end = segment_bounds[item["assigned_segment_id"]]
            assert start <= item["coverage_start_day"] <= item["coverage_end_day"] <= end
        assert longer["tradeoff_summary"] is None


def test_explicit_constraints_persist_until_a_newer_conflict_replaces_them(app):
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        initial = build_recommendation(
            aisha, "France", "2030-08-01", "2030-08-07"
        )
        ten_gb = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-07",
            latest_message="I need 10 GB",
            current_recommendation=initial,
        )
        add_sms = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-07",
            latest_message="I need 100 SMS",
            current_recommendation=ten_gb,
        )
        assert add_sms["_active_requirements"]["minimums"]["data_gb"] == 10
        assert add_sms["_active_requirements"]["minimums"]["sms"] == 100
        assert add_sms["selection"]["total_data_gb"] >= 10
        assert add_sms["selection"]["total_sms"] >= 100

        less_data = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-07",
            latest_message="Give me less data",
            current_recommendation=add_sms,
        )
        assert "data_gb" not in less_data["_active_requirements"]["minimums"]
        assert less_data["_active_requirements"]["minimums"]["sms"] == 100
        assert less_data["selection"]["total_data_gb"] < add_sms["selection"]["total_data_gb"]


def test_restore_original_clears_chat_constraints(app):
    with app.app_context():
        aisha = User.query.filter_by(email="aisha@example.test").one()
        original = build_recommendation(
            aisha, "France", "2030-08-01", "2030-08-07"
        )
        modified = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-07",
            latest_message="I need 10 GB",
            current_recommendation=original,
        )
        restored = build_recommendation(
            aisha,
            "France",
            "2030-08-01",
            "2030-08-07",
            latest_message="Restore my original recommendation",
            current_recommendation=modified,
        )
        assert restored["_active_requirements"]["minimums"] == {}
        assert restored["selection"] == original["selection"]
