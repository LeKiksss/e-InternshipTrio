import pytest

from app.services.user_requirement_parser import (
    merge_requirement_state,
    parse_user_requirements,
)


CURRENT = {
    "selection": {
        "total_data_gb": 8,
        "total_local_minutes": 200,
        "total_international_minutes": 100,
        "total_sms": 50,
        "total_price_aed": 200,
        "total_validity_days": 14,
        "activation_count": 3,
    }
}


@pytest.mark.parametrize(
    ("message", "field", "value"),
    [
        ("I need 10 GB", "data_gb", 10),
        ("I need at least 500 international minutes", "international_minutes", 500),
        ("I need 120 local call minutes", "local_minutes", 120),
        ("I need 300 call minutes", "total_call_minutes", 300),
        ("I need 100 SMS", "sms", 100),
    ],
)
def test_numeric_requirements(message, field, value):
    parsed = parse_user_requirements(message, CURRENT, 14)
    assert parsed["minimums"][field] == value
    assert field in parsed["trip_wide_metrics"]


def test_trip_wide_correction_inherits_the_active_metric_and_clears_segments():
    initial = parse_user_requirements("I need 200 local minutes", CURRENT, 3)
    previous = {
        **initial,
        "segments": [
            {
                "segment_id": "segment-1",
                "start_day": 1,
                "end_day": 1,
            }
        ],
    }
    current = {**CURRENT, "_active_requirements": previous}

    correction = parse_user_requirements(
        "No, 200 across the 3 days",
        current,
        3,
    )
    merged = merge_requirement_state(previous, correction)

    assert correction["minimums"] == {"local_minutes": 200}
    assert correction["trip_wide_metrics"] == ["local_minutes"]
    assert correction["whole_trip_mentioned"] is True
    assert merged["segments"] == []
    assert merged["minimums"]["local_minutes"] == 200


def test_only_and_zero_requirements_override_history():
    only = parse_user_requirements("I only need 5 GB", CURRENT, 7)
    assert only["minimums"]["data_gb"] == 5
    assert only["exact_targets"]["data_gb"] == 5

    calls = parse_user_requirements("I will not make any calls", CURRENT, 7)
    assert calls["minimums"]["local_minutes"] == 0
    assert calls["minimums"]["international_minutes"] == 0
    assert calls["exact_targets"]["local_minutes"] == 0
    assert calls["exact_targets"]["international_minutes"] == 0

    no_data = parse_user_requirements("I will not use any data", CURRENT, 7)
    no_sms = parse_user_requirements("I need no SMS", CURRENT, 7)
    assert no_data["minimums"]["data_gb"] == 0
    assert no_sms["minimums"]["sms"] == 0


def test_price_validity_and_comparatives_are_parsed_against_current_plan():
    price = parse_user_requirements("I want to spend no more than AED 200", CURRENT, 14)
    validity = parse_user_requirements("I need at least 21 days of validity", CURRENT, 14)
    more_data = parse_user_requirements("Give me more data", CURRENT, 14)
    more_calls = parse_user_requirements("I need more calls", CURRENT, 14)
    more_international = parse_user_requirements(
        "Give me more international minutes", CURRENT, 14
    )

    assert price["maximum_price_aed"] == 200
    assert validity["minimum_validity_days"] == 21
    assert more_data["minimums"]["data_gb"] == pytest.approx(10)
    assert more_calls["minimums"]["local_minutes"] == pytest.approx(250)
    assert more_calls["minimums"]["international_minutes"] == pytest.approx(125)
    assert more_international["minimums"]["international_minutes"] == pytest.approx(125)

    for message, preference in (
        ("Give me less data", "less_data"),
        ("I need fewer calls", "fewer_calls"),
        ("Give me a cheaper option", "cheaper"),
        ("I want fewer activations", "fewer_activations"),
        ("I need longer validity", "longer_validity"),
    ):
        assert preference in parse_user_requirements(message, CURRENT, 14)["comparative"]


def test_restore_original_is_recognized():
    for message in (
        "Restore my original recommendation",
        "Can I get the original plan you recommended?",
        "Return me to the initial package",
    ):
        assert parse_user_requirements(message, CURRENT, 14)["restore_original"]


def test_colloquial_budget_call_focus_and_nevermind_are_parsed():
    parsed = parse_user_requirements(
        "nevermind can we go cheap but focus on calls my budget is like 30dhs",
        CURRENT,
        3,
    )

    assert parsed["reset_constraints"] is True
    assert parsed["maximum_price_aed"] == 30
    assert {"budget_limited", "cheaper", "focus_calls"}.issubset(
        parsed["comparative"]
    )
    assert {"local_minutes", "international_minutes"}.issubset(
        parsed["affected_metrics"]
    )


def test_nevermind_discards_previous_constraints_before_merging():
    previous = parse_user_requirements("I need 200 local minutes", CURRENT, 3)
    latest = parse_user_requirements(
        "Never mind, go cheap with a budget of AED 30",
        CURRENT,
        3,
    )
    merged = merge_requirement_state(previous, latest)

    assert "local_minutes" not in merged["minimums"]
    assert merged["maximum_price_aed"] == 30
    assert "cheaper" in merged["comparative"]


def test_temporal_segments_cover_every_day_once():
    examples = (
        "For the first week I will have Wi-Fi",
        "I need heavy data in the second week",
        "I only need calls for the final three days",
        "The first week is light usage and the next week is heavy usage",
    )
    for message in examples:
        segments = parse_user_requirements(message, CURRENT, 14)["segments"]
        assert segments[0]["start_day"] == 1
        assert segments[-1]["end_day"] == 14
        covered = [
            day
            for segment in segments
            for day in range(segment["start_day"], segment["end_day"] + 1)
        ]
        assert covered == list(range(1, 15))

    wifi = parse_user_requirements(examples[0], CURRENT, 14)["segments"]
    heavy = parse_user_requirements(examples[1], CURRENT, 14)["segments"]
    final_calls = parse_user_requirements(examples[2], CURRENT, 14)["segments"]
    assert wifi[0]["modifiers"]["data_factor"] == 0.25
    assert heavy[1]["modifiers"]["data_factor"] == 3.5
    assert final_calls[0]["modifiers"]["local_factor"] == 0
    assert final_calls[-1]["modifiers"]["local_factor"] == 1.5


def test_latest_message_overrides_conflicts_and_preserves_other_constraints():
    state = parse_user_requirements("I need 10 GB", CURRENT, 14)
    state = merge_requirement_state(
        state, parse_user_requirements("I need 100 SMS", CURRENT, 14)
    )
    assert state["minimums"]["data_gb"] == 10
    assert state["minimums"]["sms"] == 100

    state = merge_requirement_state(
        state, parse_user_requirements("Give me less data", CURRENT, 14)
    )
    assert "data_gb" not in state["minimums"]
    assert state["minimums"]["sms"] == 100

    state = merge_requirement_state(
        parse_user_requirements("I need 500 international minutes", CURRENT, 14),
        parse_user_requirements("I will not make calls", CURRENT, 14),
    )
    assert state["minimums"]["international_minutes"] == 0
    assert state["minimums"]["local_minutes"] == 0
