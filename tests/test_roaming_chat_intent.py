import pytest

from app.services.roaming_chat_intent import classify_roaming_chat_intent


@pytest.mark.parametrize(
    "message",
    (
        "Hi",
        "Hello!",
        "hey there",
        "Good morning",
        "good afternoon!",
        "Good evening",
        "Greetings",
        "Howdy",
        "Salaam",
        "How are you?",
    ),
)
def test_standalone_greetings_are_handled_without_recommendation_intent(message):
    intent = classify_roaming_chat_intent(message)
    assert intent["kind"] == "greeting"
    assert "roaming plan" in intent["reply"]


def test_greeting_with_a_real_adjustment_is_not_swallowed():
    assert classify_roaming_chat_intent("Hello, I need 5 GB") == {
        "kind": "refinement"
    }


@pytest.mark.parametrize(
    ("message", "kind"),
    (
        ("Can I get the original plan you recommended?", "original"),
        ("Return me to the original package", "original"),
        ("I want to go back to the previous package", "previous"),
        ("Go back one", "previous"),
    ),
)
def test_history_navigation_language(message, kind):
    assert classify_roaming_chat_intent(message)["kind"] == kind
