import pytest

from app.models import RoamingPackage
from app.services.package_fallback_optimizer import optimize_package_plan
from app.services.recommendation_validator import validate_recommendation_decision


LOW = {"data_gb": 0.1, "local_minutes": 1, "international_minutes": 1, "sms": 1}


def item(code, quantity, start, end, order, segment=None, **extra):
    return {
        "package_code": code,
        "quantity": quantity,
        "coverage_start_day": start,
        "coverage_end_day": end,
        "activation_order": order,
        "assigned_segment_id": segment,
        "reason_for_item": "Matches this travel period.",
        **extra,
    }


def decision(items, segments=None):
    return {
        "interpreted_latest_request": None,
        "trip_segments": segments or [],
        "package_items": items,
        "reason": "Selected from the active catalogue.",
        "why_it_fits": ["Coverage and allowances are sufficient."],
        "usage_summary": "Validated usage coverage.",
        "modification_summary": None,
        "tradeoff_summary": None,
    }


def active_packages():
    return RoamingPackage.query.order_by(RoamingPackage.package_code).all()


@pytest.mark.parametrize(
    ("trip_days", "items", "activation_count"),
    [
        (7, [item("ESS-7D", 1, 1, 7, 1)], 1),
        (6, [item("ESS-3D", 2, 1, 6, 1)], 2),
        (
            4,
            [item("ESS-1D", 1, 1, 1, 1), item("ESS-3D", 1, 2, 4, 2)],
            2,
        ),
    ],
)
def test_valid_single_repeated_and_mixed_plans(app, trip_days, items, activation_count):
    with app.app_context():
        plan, errors = validate_recommendation_decision(
            decision(items), active_packages(), trip_days, LOW
        )
        assert errors == []
        assert plan["selection"]["activation_count"] == activation_count
        assert plan["selection"]["total_validity_days"] == trip_days


def test_valid_segmented_plan_checks_each_period(app):
    with app.app_context():
        segments = [
            {
                "segment_id": "segment-1",
                "start_day": 1,
                "end_day": 7,
                "usage_interpretation": "Wi-Fi available",
            },
            {
                "segment_id": "segment-2",
                "start_day": 8,
                "end_day": 14,
                "usage_interpretation": "Higher data use",
            },
        ]
        parsed = {
            "segments": [
                {**segments[0], "requirements": LOW},
                {
                    **segments[1],
                    "requirements": {**LOW, "data_gb": 20},
                },
            ]
        }
        plan, errors = validate_recommendation_decision(
            decision(
                [
                    item("ESS-7D", 1, 1, 7, 1, "segment-1"),
                    item("DP-7D", 1, 8, 14, 2, "segment-2"),
                ],
                segments,
            ),
            active_packages(),
            14,
            {**LOW, "data_gb": 20},
            parsed_requirements=parsed,
        )
        assert errors == []
        assert len(plan["segments"]) == 2
        assert {row["assigned_segment_id"] for row in plan["selection"]["items"]} == {
            "segment-1",
            "segment-2",
        }


@pytest.mark.parametrize(
    ("items", "error_fragment"),
    [
        ([item("UNKNOWN", 1, 1, 7, 1)], "Unknown package"),
        ([item("ESS-7D", 0, 1, 7, 1)], "quantity"),
        ([item("ESS-7D", 1.5, 1, 7, 1)], "whole number"),
        (
            [item("ESS-3D", 1, 1, 3, 1), item("ESS-3D", 1, 5, 7, 2)],
            "uncovered",
        ),
        (
            [item("ESS-3D", 1, 1, 3, 1), item("ESS-3D", 1, 3, 5, 2)],
            "overlaps",
        ),
    ],
)
def test_invalid_codes_quantities_and_coverage_are_rejected(app, items, error_fragment):
    with app.app_context():
        plan, errors = validate_recommendation_decision(
            decision(items), active_packages(), 7, LOW
        )
        assert plan is None
        assert any(error_fragment.lower() in error.lower() for error in errors)


def test_inactive_package_is_rejected(app):
    with app.app_context():
        package = RoamingPackage.query.filter_by(package_code="ESS-7D").one()
        package.active = False
        plan, errors = validate_recommendation_decision(
            decision([item("ESS-7D", 1, 1, 7, 1)]), active_packages(), 7, LOW
        )
        assert plan is None
        assert any("inactive" in error for error in errors)


@pytest.mark.parametrize(
    ("requirements", "fragment"),
    [
        ({**LOW, "data_gb": 4}, "data"),
        ({**LOW, "local_minutes": 101}, "local"),
        ({**LOW, "international_minutes": 36}, "international"),
        ({**LOW, "sms": 31}, "sms"),
        ({**LOW, "total_call_minutes": 136}, "total call"),
    ],
)
def test_insufficient_allowances_are_rejected(app, requirements, fragment):
    with app.app_context():
        plan, errors = validate_recommendation_decision(
            decision([item("ESS-7D", 1, 1, 7, 1)]),
            active_packages(),
            7,
            requirements,
        )
        assert plan is None
        assert any(fragment in error for error in errors)


def test_excessive_duration_is_rejected_when_exact_fit_exists(app):
    with app.app_context():
        plan, errors = validate_recommendation_decision(
            decision([item("ESS-30D", 1, 1, 23, 1)]),
            active_packages(),
            23,
            LOW,
        )
        assert plan is None
        assert any("exact-duration" in error for error in errors)


@pytest.mark.parametrize(
    "segments",
    [
        [
            {"segment_id": "a", "start_day": 1, "end_day": 8},
            {"segment_id": "b", "start_day": 8, "end_day": 14},
        ],
        [
            {"segment_id": "a", "start_day": 1, "end_day": 6},
            {"segment_id": "b", "start_day": 8, "end_day": 14},
        ],
    ],
)
def test_invalid_segment_boundaries_are_rejected(app, segments):
    with app.app_context():
        for segment in segments:
            segment["usage_interpretation"] = "Period"
        plan, errors = validate_recommendation_decision(
            decision(
                [
                    item("ESS-7D", 1, 1, 7, 1, "a"),
                    item("ESS-7D", 1, 8, 14, 2, "b"),
                ],
                segments,
            ),
            active_packages(),
            14,
            LOW,
        )
        assert plan is None
        assert any("segments" in error.lower() for error in errors)


def test_model_cannot_shift_user_requested_segment_boundaries(app):
    requested = [
        {
            "segment_id": "segment-1",
            "start_day": 1,
            "end_day": 7,
            "requirements": LOW,
        },
        {
            "segment_id": "segment-2",
            "start_day": 8,
            "end_day": 14,
            "requirements": {**LOW, "data_gb": 20},
        },
    ]
    shifted = [
        {
            "segment_id": "segment-1",
            "start_day": 1,
            "end_day": 6,
            "usage_interpretation": "Wi-Fi available",
        },
        {
            "segment_id": "segment-2",
            "start_day": 7,
            "end_day": 14,
            "usage_interpretation": "Higher data use",
        },
    ]
    with app.app_context():
        plan, errors = validate_recommendation_decision(
            decision(
                [
                    item("ESS-3D", 2, 1, 6, 1, "segment-1"),
                    item("ESS-1D", 1, 7, 7, 3, "segment-2"),
                    item("DP-7D", 1, 8, 14, 4, "segment-2"),
                ],
                shifted,
            ),
            active_packages(),
            14,
            {**LOW, "data_gb": 20},
            parsed_requirements={"segments": requested},
        )
        assert plan is None
        assert any("latest user instruction" in error for error in errors)


def test_database_facts_replace_untrusted_model_values(app):
    with app.app_context():
        model_item = item(
            "ESS-7D",
            1,
            1,
            7,
            1,
            price_per_package_aed=1,
            activation_code="invented",
            data_gb_per_package=999,
        )
        plan, errors = validate_recommendation_decision(
            decision([model_item]), active_packages(), 7, LOW
        )
        assert errors == []
        factual = plan["selection"]["items"][0]
        assert factual["price_per_package_aed"] == 69
        assert factual["activation_code"] == "*170*11*07#"
        assert factual["data_gb_per_package"] == 3


def test_optimizer_builds_exact_23_day_sequence_and_combined_totals(app):
    with app.app_context():
        plan = optimize_package_plan(active_packages(), 23, LOW)
        selection = plan["selection"]
        assert selection["total_validity_days"] == 23
        assert selection["unused_validity_days"] == 0
        assert selection["activation_count"] == 3
        assert [
            (row["package_code"], row["quantity"])
            for row in selection["items"]
        ] == [("ESS-10D", 2), ("ESS-3D", 1)]
        assert selection["total_price_aed"] == 225
        assert selection["total_data_gb"] == 11.5
        assert selection["total_local_minutes"] == 345
        assert selection["total_international_minutes"] == 115
        assert selection["total_sms"] == 105


def test_optimizer_supports_segment_families_and_relative_refinements(app):
    with app.app_context():
        segments = [
            {
                "segment_id": "segment-1",
                "start_day": 1,
                "end_day": 7,
                "usage_interpretation": "Light first week",
                "requirements": LOW,
                "exact_targets": {},
            },
            {
                "segment_id": "segment-2",
                "start_day": 8,
                "end_day": 14,
                "usage_interpretation": "Heavy second week",
                "requirements": {**LOW, "data_gb": 25},
                "exact_targets": {},
            },
        ]
        segmented = optimize_package_plan(active_packages(), 14, LOW, segments=segments)
        assert len(segmented["segments"]) == 2
        assert segmented["selection"]["total_validity_days"] == 14
        assert any(item["family"].startswith("Data") for item in segmented["selection"]["items"])

        expensive = {
            "total_price_aed": 299,
            "total_data_gb": 20,
            "total_local_minutes": 700,
            "total_international_minutes": 350,
            "total_validity_days": 7,
            "activation_count": 3,
        }
        cheaper = optimize_package_plan(
            active_packages(), 7, LOW, preferences=["cheaper"], current_selection=expensive
        )
        fewer = optimize_package_plan(
            active_packages(),
            7,
            LOW,
            preferences=["fewer_activations"],
            current_selection=expensive,
        )
        assert cheaper["selection"]["total_price_aed"] < 299
        assert fewer["selection"]["activation_count"] < 3


def test_optimizer_returns_closest_plan_when_price_limit_is_impossible(app):
    with app.app_context():
        plan = optimize_package_plan(
            active_packages(), 7, LOW, maximum_price_aed=1
        )
        assert plan["selection"]["total_price_aed"] > 1
        assert "maximum price" in plan["tradeoff_summary"]


def test_optimizer_explains_impossible_minimum_validity_without_extending_coverage(app):
    with app.app_context():
        plan = optimize_package_plan(
            active_packages(),
            1,
            LOW,
            minimum_validity_days=1000,
        )
        assert plan["selection"]["items"][0]["coverage_start_day"] == 1
        assert plan["selection"]["items"][-1]["coverage_end_day"] == 1
        assert "minimum validity" in plan["tradeoff_summary"]
