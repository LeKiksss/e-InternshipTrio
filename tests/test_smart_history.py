import json
from decimal import Decimal

import pytest
from sqlalchemy import Numeric, inspect

from app.extensions import db
from app import seed_database
from app.models import (
    BillRecord,
    RoamingPackage,
    SmartRecommendationHistory,
    User,
)
from app.services.recommendation_values import (
    canonical_decimal,
    canonical_string,
)
from app.services.package_fallback_optimizer import optimize_package_plan
from app.services.roaming_recommendation import build_recommendation
from app.services.smart_history import (
    UNSPLIT_SIGNATURE,
    build_history_key,
    is_history_eligible,
    normalize_split_details,
    split_signature,
    structural_plan_json,
    upsert_validated_gemini_plan,
)
from app.services.usage_analysis import build_trip_usage_analysis
from tests.conftest import login_seeded


METRICS = {
    "data_gb": 5,
    "local_minutes": 100,
    "international_minutes": 35,
    "sms": 30,
}


def package_decision(code, days, *, items=None, segments=None, reason="Private wording"):
    return {
        "interpreted_latest_request": "Private interpretation",
        "trip_segments": segments or [],
        "package_items": items
        or [
            {
                "package_code": code,
                "quantity": 1,
                "coverage_start_day": 1,
                "coverage_end_day": days,
                "activation_order": 1,
                "assigned_segment_id": None,
                "reason_for_item": "Private item wording",
            }
        ],
        "reason": reason,
        "why_it_fits": ["Private fit wording"],
        "usage_summary": "Private usage wording",
        "modification_summary": "Private modification wording",
        "tradeoff_summary": None,
    }


def split_decision(first_end=7, period_days=10):
    second_start = first_end + 1
    if (first_end, period_days) == (7, 10):
        items = [
            {
                "package_code": "PRE-7D",
                "quantity": 1,
                "coverage_start_day": 1,
                "coverage_end_day": 7,
                "activation_order": 1,
                "assigned_segment_id": "segment-1",
                "reason_for_item": "First segment.",
            },
            {
                "package_code": "PRE-3D",
                "quantity": 1,
                "coverage_start_day": 8,
                "coverage_end_day": 10,
                "activation_order": 2,
                "assigned_segment_id": "segment-2",
                "reason_for_item": "Second segment.",
            },
        ]
    else:
        items = [
            {
                "package_code": "PRE-3D",
                "quantity": 2,
                "coverage_start_day": 1,
                "coverage_end_day": first_end,
                "activation_order": 1,
                "assigned_segment_id": "segment-1",
                "reason_for_item": "First segment.",
            },
            {
                "package_code": "PRE-1D",
                "quantity": 1,
                "coverage_start_day": second_start,
                "coverage_end_day": second_start,
                "activation_order": 3,
                "assigned_segment_id": "segment-2",
                "reason_for_item": "Second segment start.",
            },
            {
                "package_code": "PRE-3D",
                "quantity": 1,
                "coverage_start_day": second_start + 1,
                "coverage_end_day": period_days,
                "activation_order": 4,
                "assigned_segment_id": "segment-2",
                "reason_for_item": "Second segment remainder.",
            },
        ]
    return package_decision(
        "PRE-7D",
        period_days,
        items=items,
        segments=[
            {
                "segment_id": "segment-1",
                "start_day": 1,
                "end_day": first_end,
                "usage_interpretation": "First numeric period.",
                "data_requirement_gb": 10,
                "local_minutes_requirement": 1,
                "international_minutes_requirement": 1,
                "sms_requirement": 1,
            },
            {
                "segment_id": "segment-2",
                "start_day": second_start,
                "end_day": period_days,
                "usage_interpretation": "Second numeric period.",
                "data_requirement_gb": 2,
                "local_minutes_requirement": 1,
                "international_minutes_requirement": 1,
                "sms_requirement": 1,
            },
        ],
    )


def current_plan(package):
    return {
        "selection": {
            "items": [
                {
                    "package_code": package.package_code,
                    "quantity": 1,
                    "coverage_start_day": 1,
                    "coverage_end_day": package.validity_days,
                    "activation_order": 1,
                    "assigned_segment_id": None,
                }
            ],
            "total_price_aed": float(package.price_aed),
            "total_validity_days": package.validity_days,
            "total_data_gb": float(package.data_gb),
            "total_local_minutes": package.local_minutes,
            "total_international_minutes": package.international_minutes,
            "total_sms": package.sms,
            "activation_count": 1,
        },
        "_active_requirements": {},
    }


def call_refinement(user, current, message, *, days=7):
    return build_recommendation(
        user,
        "France",
        "2030-08-01",
        f"2030-08-{days:02d}",
        latest_message=message,
        current_recommendation=current,
    )


def install_fake(monkeypatch, factory):
    calls = []

    def fake(context, **kwargs):
        calls.append((context, kwargs))
        return factory(context, len(calls))

    monkeypatch.setattr(
        "app.services.roaming_recommendation.request_recommendation_decision",
        fake,
    )
    return calls


def test_model_uses_exact_decimal_columns_and_has_no_user_key(app):
    with app.app_context():
        table_names = inspect(db.engine).get_table_names()
        assert "smart_recommendation_history" in table_names
        columns = SmartRecommendationHistory.__table__.columns
        assert "user_id" not in columns
        for name in METRICS:
            assert isinstance(columns[name].type, Numeric)
            assert columns[name].type.precision == 18
            assert columns[name].type.scale == 6
        unique = next(
            constraint
            for constraint in SmartRecommendationHistory.__table__.constraints
            if constraint.name == "uq_smart_history_exact_requirement"
        )
        assert {column.name for column in unique.columns} == {
            *METRICS,
            "period_days",
            "split",
            "split_signature",
        }


def test_decimal_canonicalization_is_stable_and_one_percent_stays_distinct():
    assert canonical_decimal(10) == Decimal("10.000000")
    assert canonical_decimal("10.000000") == Decimal("10.000000")
    assert canonical_string(10) == "10.000000"
    assert canonical_decimal("10.1") != canonical_decimal("10")


def test_split_json_is_canonical_complete_and_contains_only_numeric_meaning():
    first = [
        {
            "start_day": 8,
            "end_day": 10,
            "requirements": {**METRICS, "data_gb": 2},
            "usage_interpretation": "I am staying with my aunt.",
        },
        {
            "start_day": 1,
            "end_day": 7,
            "requirements": {**METRICS, "data_gb": 10},
            "usage_interpretation": "I have business meetings.",
        },
    ]
    totals = {
        metric: sum(segment["requirements"][metric] for segment in first)
        for metric in METRICS
    }
    normalized = normalize_split_details(first, 10, totals)
    payload = json.loads(normalized)
    assert [item["start_day"] for item in payload] == [1, 8]
    assert payload[0]["data_gb"] == "10.000000"
    assert payload[1]["data_gb"] == "2.000000"
    assert "aunt" not in normalized
    assert "meeting" not in normalized
    assert normalize_split_details(list(reversed(first)), 10, totals) == normalized
    assert split_signature(normalized) == split_signature(
        normalize_split_details(first, 10, totals)
    )


@pytest.mark.parametrize(
    "segments",
    [
        [{"start_day": 2, "end_day": 10, **METRICS}],
        [
            {"start_day": 1, "end_day": 4, **METRICS},
            {"start_day": 6, "end_day": 10, **METRICS},
        ],
        [
            {"start_day": 1, "end_day": 7, **METRICS},
            {"start_day": 7, "end_day": 10, **METRICS},
        ],
    ],
)
def test_split_segments_must_cover_each_day_once(segments):
    with pytest.raises(ValueError, match="every trip day"):
        normalize_split_details(segments, 10)


def test_split_signature_changes_for_boundaries_ordered_meaning_and_each_metric():
    base = [
        {"start_day": 1, "end_day": 7, **METRICS, "data_gb": 10},
        {"start_day": 8, "end_day": 10, **METRICS, "data_gb": 2},
    ]
    variants = [
        [
            {"start_day": 1, "end_day": 3, **METRICS, "data_gb": 2},
            {"start_day": 4, "end_day": 10, **METRICS, "data_gb": 10},
        ],
        [
            {"start_day": 1, "end_day": 7, **METRICS, "data_gb": 2},
            {"start_day": 8, "end_day": 10, **METRICS, "data_gb": 10},
        ],
        [
            {"start_day": 1, "end_day": 7, **METRICS, "data_gb": 10.1},
            {"start_day": 8, "end_day": 10, **METRICS, "data_gb": 1.9},
        ],
        [
            {"start_day": 1, "end_day": 7, **METRICS, "local_minutes": 101},
            {"start_day": 8, "end_day": 10, **METRICS, "local_minutes": 99},
        ],
        [
            {
                "start_day": 1,
                "end_day": 7,
                **METRICS,
                "international_minutes": 36,
            },
            {
                "start_day": 8,
                "end_day": 10,
                **METRICS,
                "international_minutes": 34,
            },
        ],
        [
            {"start_day": 1, "end_day": 7, **METRICS, "sms": 31},
            {"start_day": 8, "end_day": 10, **METRICS, "sms": 29},
        ],
    ]
    base_details = normalize_split_details(base, 10)
    signatures = {
        split_signature(normalize_split_details(variant, 10))
        for variant in variants
    }
    assert split_signature(base_details) not in signatures
    assert len(signatures) == len(variants)


def test_unsplit_and_split_keys_never_match():
    unsplit = build_history_key(METRICS, 10)
    split = build_history_key(
        METRICS,
        10,
        [
            {
                "start_day": 1,
                "end_day": 5,
                "data_gb": 2.5,
                "local_minutes": 50,
                "international_minutes": 17.5,
                "sms": 15,
            },
            {
                "start_day": 6,
                "end_day": 10,
                "data_gb": 2.5,
                "local_minutes": 50,
                "international_minutes": 17.5,
                "sms": 15,
            },
        ],
    )
    assert unsplit.metrics == split.metrics
    assert unsplit.period_days == split.period_days
    assert unsplit.split is False
    assert unsplit.split_signature == UNSPLIT_SIGNATURE
    assert split.split is True
    assert split.split_signature != UNSPLIT_SIGNATURE


def test_exact_repeat_skips_gemini_and_is_shared_between_users(app, monkeypatch):
    calls = install_fake(
        monkeypatch,
        lambda _context, _count: package_decision("RLH-7D", 7),
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="ESS-7D").one())
        aisha = User.query.filter_by(email="aisha@example.test").one()
        omar = User.query.filter_by(email="omar@example.test").one()
        first = call_refinement(aisha, current, "I need 5 GB")
        second = call_refinement(omar, current, "I need 5.000000 GB")
        row = SmartRecommendationHistory.query.one()

    assert len(calls) == 1
    assert first["recommendation_source"] == "gemini"
    assert first["smart_history_hit"] is False
    assert second["recommendation_source"] == "smart_history"
    assert second["smart_history_hit"] is True
    assert row.hit_count == 1
    assert row.last_used_at is not None


def test_ten_gb_matches_ten_but_not_ten_point_one_and_may_select_twelve_gb(
    app, monkeypatch
):
    calls = install_fake(
        monkeypatch,
        lambda _context, _count: package_decision("RLH-10D", 10),
    )
    with app.app_context():
        packages = RoamingPackage.query.filter_by(active=True).all()
        current = current_plan(RoamingPackage.query.filter_by(package_code="RLH-10D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        first = call_refinement(user, current, "I need 10 GB", days=10)
        repeated = call_refinement(user, current, "I need 10.000000 GB", days=10)
        changed = call_refinement(user, current, "I need 10.1 GB", days=10)
        cheapest = optimize_package_plan(
            packages,
            10,
            {
                "data_gb": 10,
                "local_minutes": 450,
                "international_minutes": 225,
                "sms": 100,
            },
            exact_only=True,
        )
        rows = SmartRecommendationHistory.query.order_by(
            SmartRecommendationHistory.data_gb
        ).all()

    assert first["selection"]["total_data_gb"] == 12
    assert first["selection"]["total_price_aed"] == 199
    assert cheapest["selection"]["total_price_aed"] == 199
    assert [
        item["package_code"] for item in cheapest["selection"]["items"]
    ] == ["RLH-10D"]
    assert repeated["smart_history_hit"] is True
    assert changed["smart_history_hit"] is False
    assert len(calls) == 2
    assert [row.data_gb for row in rows] == [
        Decimal("10.000000"),
        Decimal("10.100000"),
    ]


def test_ten_gb_does_not_reuse_a_twelve_gb_requirement_history_row(
    app, monkeypatch
):
    calls = install_fake(
        monkeypatch,
        lambda _context, _count: package_decision("RLH-10D", 10),
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="RLH-10D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        twelve = call_refinement(user, current, "I need 12 GB", days=10)
        ten = call_refinement(user, current, "I need 10 GB", days=10)
        keys = {
            row.data_gb for row in SmartRecommendationHistory.query.order_by(
                SmartRecommendationHistory.data_gb
            ).all()
        }

    assert twelve["smart_history_hit"] is False
    assert ten["smart_history_hit"] is False
    assert len(calls) == 2
    assert keys == {Decimal("10.000000"), Decimal("12.000000")}


def test_api_returns_source_metadata_without_internal_history_fields(
    app, client, monkeypatch
):
    calls = install_fake(
        monkeypatch,
        lambda _context, _count: package_decision("RLH-7D", 7),
    )
    login_seeded(client)
    payload = {
        "destination": "France",
        "start_date": "2030-08-01",
        "end_date": "2030-08-07",
    }
    first = client.post("/api/roaming/recommend", json=payload)
    second = client.post("/api/roaming/recommend", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json["recommendation_source"] == "gemini"
    assert first.json["smart_history_hit"] is False
    assert second.json["recommendation_source"] == "smart_history"
    assert second.json["smart_history_hit"] is True
    assert "history_id" not in second.json
    assert "split_signature" not in second.json
    assert len(calls) == 1


def test_initial_key_gemini_validation_and_history_use_the_same_exact_requirements(
    app, monkeypatch
):
    calls = install_fake(
        monkeypatch,
        lambda _context, _count: package_decision("ESS-3D", 3),
    )
    with app.app_context():
        user = User.query.filter_by(email="omar@example.test").one()
        exact_trip = build_trip_usage_analysis(user.monthly_usage, 3)["trip_estimate"]
        first = build_recommendation(
            user,
            "France",
            "2030-08-01",
            "2030-08-03",
        )
        second = build_recommendation(
            user,
            "France",
            "2030-08-01",
            "2030-08-03",
        )
        row = SmartRecommendationHistory.query.one()

    context = calls[0][0]
    for metric in METRICS:
        assert getattr(row, metric) == canonical_decimal(
            exact_trip[metric],
            field=metric,
        )
        assert context["trip_requirements"][metric] == canonical_string(
            exact_trip[metric],
            field=metric,
        )
        assert first["_requirements_state"][metric] == canonical_string(
            exact_trip[metric],
            field=metric,
        )
    assert "selection_requirements" not in context
    assert len(calls) == 1
    assert second["smart_history_hit"] is True
    assert first["selection"]["items"][0]["package_code"] == "ESS-3D"
    assert first["selection"]["total_data_gb"] == 1.5


@pytest.mark.parametrize(
    "changed_message",
    [
        "I need 5.05 GB, 100 local minutes, 35 international minutes, and 30 SMS",
        "I need 5 GB, 101 local minutes, 35 international minutes, and 30 SMS",
        "I need 5 GB, 100 local minutes, 36 international minutes, and 30 SMS",
        "I need 5 GB, 100 local minutes, 35 international minutes, and 31 SMS",
    ],
)
def test_any_metric_difference_calls_gemini(app, monkeypatch, changed_message):
    calls = install_fake(
        monkeypatch,
        lambda _context, _count: package_decision("RLH-7D", 7),
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="ESS-7D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        call_refinement(
            user,
            current,
            "I need 5 GB, 100 local minutes, 35 international minutes, and 30 SMS",
        )
        changed = call_refinement(user, current, changed_message)
    assert len(calls) == 2
    assert changed["recommendation_source"] == "gemini"


def test_period_difference_calls_gemini(app, monkeypatch):
    eight_day_items = [
        {
            "package_code": "RLH-7D",
            "quantity": 1,
            "coverage_start_day": 1,
            "coverage_end_day": 7,
            "activation_order": 1,
            "assigned_segment_id": None,
            "reason_for_item": "First seven days.",
        },
        {
            "package_code": "RLH-1D",
            "quantity": 1,
            "coverage_start_day": 8,
            "coverage_end_day": 8,
            "activation_order": 2,
            "assigned_segment_id": None,
            "reason_for_item": "Final day.",
        },
    ]
    calls = install_fake(
        monkeypatch,
        lambda context, _count: (
            package_decision("RLH-7D", 7)
            if context["trip_days"] == 7
            else package_decision("RLH-7D", 8, items=eight_day_items)
        ),
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="ESS-7D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        call_refinement(user, current, "I need 5 GB", days=7)
        changed = call_refinement(user, current, "I need 5 GB", days=8)
    assert len(calls) == 2
    assert changed["smart_history_hit"] is False


def test_exact_split_repeat_skips_gemini_for_another_user(app, monkeypatch):
    calls = install_fake(monkeypatch, lambda _context, _count: split_decision())
    message = (
        "For the first seven days I need 10 GB, and for the final three days "
        "I need 2 GB."
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="RLH-10D").one())
        aisha = User.query.filter_by(email="aisha@example.test").one()
        omar = User.query.filter_by(email="omar@example.test").one()
        first = call_refinement(aisha, current, message, days=10)
        second = call_refinement(omar, current, message, days=10)
        row = SmartRecommendationHistory.query.one()

    assert len(calls) == 1
    assert first["smart_history_hit"] is False
    assert second["smart_history_hit"] is True
    assert second["segments"]
    assert row.split is True
    assert "first seven" not in row.split_details.lower()
    assert json.loads(row.split_details)[0]["data_gb"] == "10.000000"


def test_same_totals_changing_only_split_flag_calls_gemini(app, monkeypatch):
    calls = install_fake(
        monkeypatch,
        lambda context, _count: (
            split_decision()
            if context["active_constraints"]["segments"]
            else package_decision("RLH-10D", 10)
        ),
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="RLH-10D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        unsplit = call_refinement(user, current, "I need 12 GB", days=10)
        split = call_refinement(
            user,
            current,
            "For the first 7 days I need 10 GB and for the final 3 days I need 2 GB",
            days=10,
        )
    assert unsplit["usage_analysis"]["requirements"] == split["usage_analysis"][
        "requirements"
    ]
    assert unsplit["smart_history_hit"] is False
    assert split["smart_history_hit"] is False
    assert len(calls) == 2


def test_same_split_totals_with_different_boundaries_call_gemini(app, monkeypatch):
    calls = install_fake(
        monkeypatch,
        lambda context, _count: split_decision(
            first_end=context["active_constraints"]["segments"][0]["end_day"]
        ),
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="RLH-10D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        call_refinement(
            user,
            current,
            "For the first 7 days I need 10 GB and for the final 3 days I need 2 GB",
            days=10,
        )
        changed = call_refinement(
            user,
            current,
            "For the first 6 days I need 10 GB and for the final 4 days I need 2 GB",
            days=10,
        )
    assert len(calls) == 2
    assert changed["smart_history_hit"] is False


@pytest.mark.parametrize(
    "changed_message",
    [
        (
            "For the first 7 days I need 10.1 GB, 300 local minutes, 150 "
            "international minutes and 70 SMS; for the final 3 days I need "
            "1.9 GB, 150 local minutes, 75 international minutes and 30 SMS"
        ),
        (
            "For the first 7 days I need 10 GB, 301 local minutes, 150 "
            "international minutes and 70 SMS; for the final 3 days I need "
            "2 GB, 149 local minutes, 75 international minutes and 30 SMS"
        ),
        (
            "For the first 7 days I need 10 GB, 300 local minutes, 151 "
            "international minutes and 70 SMS; for the final 3 days I need "
            "2 GB, 150 local minutes, 74 international minutes and 30 SMS"
        ),
        (
            "For the first 7 days I need 10 GB, 300 local minutes, 150 "
            "international minutes and 71 SMS; for the final 3 days I need "
            "2 GB, 150 local minutes, 75 international minutes and 29 SMS"
        ),
    ],
)
def test_same_split_totals_with_a_changed_segment_metric_call_gemini(
    app, monkeypatch, changed_message
):
    calls = install_fake(monkeypatch, lambda _context, _count: split_decision())
    base_message = (
        "For the first 7 days I need 10 GB, 300 local minutes, 150 "
        "international minutes and 70 SMS; for the final 3 days I need "
        "2 GB, 150 local minutes, 75 international minutes and 30 SMS"
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="RLH-10D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        call_refinement(user, current, base_message, days=10)
        changed = call_refinement(user, current, changed_message, days=10)
    assert len(calls) == 2
    assert changed["smart_history_hit"] is False


def test_non_numeric_preferences_are_never_history_eligible():
    base = {
        "affected_metrics": ["data_gb"],
        "segments": [],
        "comparative": [],
        "maximum_price_aed": None,
        "minimum_validity_days": None,
    }
    assert is_history_eligible(base) is True
    assert is_history_eligible({**base, "comparative": ["cheaper"]}) is False
    assert is_history_eligible({**base, "maximum_price_aed": 200}) is False
    assert is_history_eligible({**base, "minimum_validity_days": 14}) is False
    assert is_history_eligible({**base, "affected_metrics": []}) is False
    for message in (
        "I need 5 GB but do not use Roam Like Home",
        "I need 5 GB and prefer one package",
        "I need 5 GB on a premium plan",
    ):
        assert is_history_eligible({**base, "latest_message": message}) is False


@pytest.mark.parametrize(
    "message",
    (
        "I need 5 GB but do not use Roam Like Home",
        "I need 5 GB and prefer one package",
        "I need 5 GB on a premium plan",
    ),
)
def test_unrepresented_preference_calls_gemini_even_when_numeric_key_exists(
    app, monkeypatch, message
):
    calls = install_fake(
        monkeypatch,
        lambda _context, _count: package_decision("RLH-7D", 7),
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="ESS-7D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        call_refinement(user, current, "I need 5 GB")
        preferred = call_refinement(user, current, message)
    assert len(calls) == 2
    assert preferred["smart_history_hit"] is False
    assert preferred["recommendation_source"] == "gemini"


def test_duplicate_key_upserts_one_row(app):
    plan = {
        "selection": {
            "items": [
                {
                    "package_code": "RLH-7D",
                    "quantity": 1,
                    "coverage_start_day": 1,
                    "coverage_end_day": 7,
                    "activation_order": 1,
                    "assigned_segment_id": None,
                }
            ]
        }
    }
    with app.app_context():
        key = build_history_key(METRICS, 7)
        first = upsert_validated_gemini_plan(key, plan)
        first_id = first.id
        upsert_validated_gemini_plan(key, plan)
        assert SmartRecommendationHistory.query.count() == 1
        assert SmartRecommendationHistory.query.one().id == first_id


def test_stored_plan_contains_structure_not_package_facts_or_explanations(app):
    plan = {
        "selection": {
            "items": [
                {
                    "package_code": "RLH-7D",
                    "package_name": "Must not persist",
                    "price_per_package_aed": 999,
                    "data_gb_per_package": 999,
                    "quantity": 1,
                    "coverage_start_day": 1,
                    "coverage_end_day": 7,
                    "activation_order": 1,
                    "assigned_segment_id": None,
                    "reason_for_item": "Mariam asked for this",
                }
            ]
        },
        "reason": "aisha@example.test +971500000101",
    }
    stored = structural_plan_json(plan)
    assert set(json.loads(stored)["items"][0]) == {
        "package_code",
        "quantity",
        "coverage_start_day",
        "coverage_end_day",
        "activation_order",
        "assigned_segment_id",
    }
    assert "999" not in stored
    assert "Mariam" not in stored
    assert "aisha" not in stored


@pytest.mark.parametrize("failure", ["missing", "inactive", "insufficient"])
def test_stale_package_plan_causes_history_miss(app, monkeypatch, failure):
    calls = install_fake(
        monkeypatch,
        lambda _context, count: package_decision(
            "RLH-7D" if count == 1 else "PRE-7D",
            7,
        ),
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="ESS-7D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        call_refinement(user, current, "I need 5 GB")
        selected = RoamingPackage.query.filter_by(package_code="RLH-7D").one()
        if failure == "missing":
            db.session.delete(selected)
        elif failure == "inactive":
            selected.active = False
        else:
            selected.data_gb = 0
            selected.local_minutes = 0
            selected.international_minutes = 0
            selected.sms = 0
        db.session.commit()
        refreshed = call_refinement(user, current, "I need 5 GB")
    assert len(calls) == 2
    assert refreshed["recommendation_source"] == "gemini"
    assert refreshed["selection"]["items"][0]["package_code"] == "PRE-7D"


def test_history_hit_reloads_current_package_price(app, monkeypatch):
    calls = install_fake(
        monkeypatch,
        lambda _context, _count: package_decision("RLH-7D", 7),
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="ESS-7D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        call_refinement(user, current, "I need 5 GB")
        package = RoamingPackage.query.filter_by(package_code="RLH-7D").one()
        package.price_aed = Decimal("177.00")
        db.session.commit()
        reused = call_refinement(user, current, "I need 5 GB")
    assert len(calls) == 1
    assert reused["selection"]["total_price_aed"] == 177.0


def test_invalid_stored_coverage_causes_gemini_call(app, monkeypatch):
    calls = install_fake(
        monkeypatch,
        lambda _context, count: package_decision(
            "RLH-7D" if count == 1 else "PRE-7D",
            7,
        ),
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="ESS-7D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        call_refinement(user, current, "I need 5 GB")
        row = SmartRecommendationHistory.query.one()
        payload = json.loads(row.plan_json)
        payload["items"][0]["coverage_end_day"] = 6
        row.plan_json = json.dumps(payload)
        db.session.commit()
        refreshed = call_refinement(user, current, "I need 5 GB")
    assert len(calls) == 2
    assert refreshed["selection"]["items"][0]["package_code"] == "PRE-7D"


def test_stored_multi_package_plan_is_reused(app, monkeypatch):
    items = [
        {
            "package_code": "ESS-3D",
            "quantity": 2,
            "coverage_start_day": 1,
            "coverage_end_day": 6,
            "activation_order": 1,
            "assigned_segment_id": None,
            "reason_for_item": "Two copies.",
        }
    ]
    calls = install_fake(
        monkeypatch,
        lambda _context, _count: package_decision("ESS-3D", 6, items=items),
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="ESS-3D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        first = call_refinement(user, current, "I need 2 GB", days=6)
        second = call_refinement(user, current, "I need 2 GB", days=6)
    assert len(calls) == 1
    assert first["selection"]["activation_count"] == 2
    assert second["smart_history_hit"] is True


def test_fallback_is_not_saved_and_metadata_is_explicit(app):
    with app.app_context():
        user = User.query.filter_by(email="aisha@example.test").one()
        result = build_recommendation(
            user,
            "France",
            "2030-08-01",
            "2030-08-07",
        )
        assert SmartRecommendationHistory.query.count() == 0
    assert result["recommendation_source"] == "fallback"
    assert result["smart_history_hit"] is False


def test_history_hit_uses_generic_explanation_and_exposes_no_row_id(app, monkeypatch):
    calls = install_fake(
        monkeypatch,
        lambda _context, _count: package_decision(
            "RLH-7D",
            7,
            reason="Aisha is staying with her aunt at +971500000101.",
        ),
    )
    with app.app_context():
        current = current_plan(RoamingPackage.query.filter_by(package_code="ESS-7D").one())
        user = User.query.filter_by(email="aisha@example.test").one()
        first = call_refinement(user, current, "I need 5 GB")
        second = call_refinement(user, current, "I need 5 GB")
        row = SmartRecommendationHistory.query.one()
        stored = row.plan_json + (row.split_details or "")
    assert first["reason"] != second["reason"]
    assert "aunt" not in second["reason"].lower()
    assert "history_id" not in second
    assert "history_id" not in stored
    assert "aisha" not in stored.lower()
    assert len(calls) == 1


def test_cli_stats_and_confirmed_clear_only_smart_history(app, runner):
    with app.app_context():
        bill_count = BillRecord.query.count()
        plan = {
            "selection": {
                "items": [
                    {
                        "package_code": "RLH-7D",
                        "quantity": 1,
                        "coverage_start_day": 1,
                        "coverage_end_day": 7,
                        "activation_order": 1,
                        "assigned_segment_id": None,
                    }
                ]
            }
        }
        upsert_validated_gemini_plan(build_history_key(METRICS, 7), plan)

    stats = runner.invoke(args=["smart-history-stats"])
    refused = runner.invoke(args=["clear-smart-history"])
    cleared = runner.invoke(args=["clear-smart-history", "--confirm"])
    assert stats.exit_code == 0
    assert "Total Smart History entries: 1" in stats.output
    assert "Non-split entries: 1" in stats.output
    assert refused.exit_code != 0
    assert "without --confirm" in refused.output
    assert cleared.exit_code == 0
    with app.app_context():
        assert SmartRecommendationHistory.query.count() == 0
        assert BillRecord.query.count() == bill_count


def test_seed_logout_and_account_reset_do_not_clear_smart_history(app, client):
    plan = {
        "selection": {
            "items": [
                {
                    "package_code": "RLH-7D",
                    "quantity": 1,
                    "coverage_start_day": 1,
                    "coverage_end_day": 7,
                    "activation_order": 1,
                    "assigned_segment_id": None,
                }
            ]
        }
    }
    with app.app_context():
        upsert_validated_gemini_plan(build_history_key(METRICS, 7), plan)
        seed_database()
        assert SmartRecommendationHistory.query.count() == 1

    login_seeded(client)
    client.post("/auth/logout")
    with app.app_context():
        assert SmartRecommendationHistory.query.count() == 1

    login_seeded(client)
    response = client.post("/api/demo/reset")
    assert response.status_code == 200
    with app.app_context():
        assert SmartRecommendationHistory.query.count() == 1
