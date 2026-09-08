"""
Unit tests for conversational fallback behavior on candidate skip / memory exhaustion.
"""

import pytest
from api.engine import evidence as evidence_engine
from api.engine import question as question_engine


def test_is_memory_exhausted_or_skip_triggers():
    """Verify all prompt-specified skip & memory exhaustion phrases are detected."""
    phrases = [
        "I don't know",
        "Not sure",
        "I can't remember",
        "I forgot",
        "No idea",
        "I don't recall",
        "Hard to remember",
        "Nothing else comes to mind",
        "That's all I remember",
        "Skip",
        "Let's skip this",
        "Can't think of anything",
        "I am not sure about the exact numbers",
        "idk",
        "pass",
        "difficult to recall",
    ]
    for p in phrases:
        assert evidence_engine.is_memory_exhausted_or_skip(p) is True, f"Failed for phrase: {p}"
        assert evidence_engine.is_non_answer(p) is True, f"Failed is_non_answer for phrase: {p}"


def test_conversational_transition_formatting():
    """Verify warm conversational acknowledgements are prepended and robotic phrases removed."""
    q_raw = 'On "Payment Gateway Integration" — What part of that work did you spend the most time on?'
    
    # Transition to different claim
    formatted = question_engine.format_conversational_transition(
        q_raw, turn_index=0, is_different_claim=True, claim_text="Payment Gateway Integration"
    )
    assert any(formatted.startswith(ack) for ack in question_engine.CONVERSATIONAL_ACKS)

    # Transition to same claim / different move
    formatted_same = question_engine.format_conversational_transition(
        "What was your role there?", turn_index=1, is_different_claim=False
    )
    assert formatted_same.startswith("Makes sense.")
    assert "What was your role there?" in formatted_same

    # Robotic phrase removal
    robotic = "Let's move to another experience. How did the team decide on that approach?"
    formatted_robotic = question_engine.format_conversational_transition(
        robotic, turn_index=2
    )
    assert "Let's move to another experience" not in formatted_robotic
    assert formatted_robotic.startswith("Got it.")
