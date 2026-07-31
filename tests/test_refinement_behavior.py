import pytest

from app.models import RoamingPackage, User
from app.services.package_fallback_optimizer import optimize_package_plan
from app.services.roaming_recommendation import (
    _refinement_preservation_minimums,
    build_recommendation,
)
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
ALLOWANCE_TOTAL_FIELDS = {
    "data_gb": "total_data_gb",
    "local_minutes": "total_local_minutes",
    "international_minutes": "total_international_minutes",
    "sms": "total_sms",
}


def packages():
    return RoamingPackage.query.order_by(RoamingPackage.package_code).all()


@pytest.mark.parametrize(
    ("message", "metric", "minimum"),
    [
        ("I need 10 GB", "total_data_gb", 10),
        ("I need at least 500 international minutes", "total_international_minutes", 500),
        ("I need 100 SMS", "total_sms", 100),
        ("Give me more data", "total_data_gb", 20.001),
        ("I need more calls", "total_local_minutes", 701),
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
            trip_wide_minimums={
                field: requirements[field]
                for field in parsed["trip_wide_metrics"]
            },
        )
        assert plan["selection"][metric] >= minimum


@pytest.mark.parametrize(
    ("message", "changed_metrics"),
    [
        ("I need 10 GB", {"data_gb"}),
        ("I need 200 local minutes", {"local_minutes"}),
        ("I need 100 international minutes", {"international_minutes"}),
        ("I need 75 SMS", {"sms"}),
        ("I need 300 call minutes", {"local_minutes", "international_minutes"}),
    ],
)
def test_refinement_preserves_every_untouched_current_allowance(
    message,
    changed_metrics,
):
    parsed = parse_user_requirements(message, CURRENT, 7)
    minimums = _refinement_preservation_minimums(CURRENT, parsed)

    assert set(minimums) == set(ALLOWANCE_TOTAL_FIELDS) - changed_metrics
    for metric, value in minimums.items():
        assert value == CURRENT["selection"][ALLOWANCE_TOTAL_FIELDS[metric]]


def test_sequential_refinements_preserve_the_immediately_previous_plan(app):
    steps = (
        ("I need 200 local minutes", "local_minutes", 200),
        ("I need 70 SMS", "sms", 70),
        ("I need 5 GB", "data_gb", 5),
        ("I need 300 international minutes", "international_minutes", 300),
    )

    with app.app_context():
        omar = User.query.filter_by(email="omar@example.test").one()
        current = build_recommendation(
            omar, "France", "2030-08-01", "2030-08-03"
        )

        for message, changed_metric, requested_value in steps:
            previous = current
            current = build_recommendation(
                omar,
                "France",
                "2030-08-01",
                "2030-08-03",
                latest_message=message,
                current_recommendation=previous,
            )

            assert (
                current["selection"][ALLOWANCE_TOTAL_FIELDS[changed_metric]]
                >= requested_value
            )
            expected_preservation = {}
            for metric, total_field in ALLOWANCE_TOTAL_FIELDS.items():
                if metric == changed_metric:
                    continue
                previous_total = previous["selection"][total_field]
                expected_preservation[metric] = previous_total
                assert current["selection"][total_field] >= previous_total
            assert current["_active_requirements"]["preservation_minimums"] == (
                expected_preservation
            )


def test_unchanged_plan_is_reported_truthfully_instead_of_claiming_recalculation(app):
    with app.app_context():
        omar = User.query.filter_by(email="omar@example.test").one()
        initial = build_recommendation(
            omar, "France", "2030-08-01", "2030-08-03"
        )
        reviewed = build_recommendation(
            omar,
            "France",
            "2030-08-01",
            "2030-08-03",
            latest_message="Please review the package again",
            current_recommendation=initial,
        )

    assert reviewed["selection"] == initial["selection"]
    assert "kept it unchanged" in reviewed["chat_message"]
    assert "recalculated" not in reviewed["chat_message"].lower()


def test_omar_local_minutes_apply_across_all_three_days_and_survive_correction(app):
    with app.app_context():
        omar = User.query.filter_by(email="omar@example.test").one()
        initial = build_recommendation(
            omar, "France", "2030-08-01", "2030-08-03"
        )
        requested = build_recommendation(
            omar,
            "France",
            "2030-08-01",
            "2030-08-03",
            latest_message="I need 200 local minutes",
            current_recommendation=initial,
        )

        assert requested["_active_requirements"]["minimums"]["local_minutes"] == 200
        assert requested["_active_requirements"]["trip_wide_metrics"] == [
            "local_minutes"
        ]
        assert requested["segments"] == []
        assert [
            (item["package_code"], item["coverage_start_day"], item["coverage_end_day"])
            for item in requested["selection"]["items"]
        ] == [("VP-3D", 1, 3)]

        corrected = build_recommendation(
            omar,
            "France",
            "2030-08-01",
            "2030-08-03",
            latest_message="No, 200 across the 3 days",
            current_recommendation=requested,
        )

        assert corrected["selection"] == requested["selection"]
        assert corrected["_active_requirements"]["minimums"]["local_minutes"] == 200
        assert corrected["_active_requirements"]["trip_wide_metrics"] == [
            "local_minutes"
        ]
        assert corrected["_active_requirements"]["segments"] == []


def test_day_specific_local_fallback_preserves_the_complete_split_request(app):
    with app.app_context():
        omar = User.query.filter_by(email="omar@example.test").one()
        initial = build_recommendation(
            omar, "France", "2030-08-01", "2030-08-03"
        )
        split = build_recommendation(
            omar,
            "France",
            "2030-08-01",
            "2030-08-03",
            latest_message=(
                "I need 10 GB on Day 1 and 2 GB combined across Days 2 and 3. "
                "Keep everything else the same."
            ),
            current_recommendation=initial,
            force_python_fallback=True,
        )

    assert [
        (segment["start_day"], segment["end_day"])
        for segment in split["segments"]
    ] == [(1, 1), (2, 3)]
    assert [
        segment["requirements"]["data_gb"] for segment in split["segments"]
    ] == pytest.approx([10, 2])
    assert split["selection"]["total_data_gb"] >= 12
    assert {
        item["assigned_segment_id"] for item in split["selection"]["items"]
    } == {"segment-1", "segment-2"}


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
