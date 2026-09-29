# File-Version: 1.0.0
"""
Tests for the market classifier.
"""

from src.intelligence.classification import EventType, Topic
from src.intelligence.market_classifier import MarketClassifier
from src.intelligence.outcomes import Outcome


def classify(question: str):
    market = {
        "question": question,
    }

    return MarketClassifier().classify(market)


def test_detects_leadership_market():

    market = classify(
        "Will Xi Jinping be removed before 2027?"
    )

    assert market.event_type == EventType.LEADERSHIP
    assert market.supported_proposition


def test_detects_country():

    market = classify(
        "Will China invade Taiwan?"
    )

    assert "China" in market.countries


def test_detects_actor():

    market = classify(
        "Will Xi Jinping be removed before 2027?"
    )

    assert "Xi Jinping" in market.actors


def test_detects_politics_topic():

    market = classify(
        "Will Xi Jinping be removed before 2027?"
    )

    assert Topic.POLITICS in market.topics


def test_detects_expected_outcome():

    market = classify(
        "Will Xi Jinping be removed before 2027?"
    )

    assert market.expected_outcome == Outcome.LEADER_REMOVED


def test_rejects_explicitly_negated_invasion_proposition():
    market = classify("Will China not invade Taiwan?")

    assert not market.supported_proposition
    assert "explicit negation" in market.unsupported_reason


def test_actor_only_question_is_not_inferred_as_leadership_removal():
    market = classify("Will Xi Jinping publish a memoir before 2027?")

    assert "Xi Jinping" in market.actors
    assert market.event_type == EventType.OTHER
    assert market.expected_outcome == Outcome.OTHER
    assert not market.supported_proposition
    assert "no recognized" in market.unsupported_reason


def test_valid_invasion_proposition_remains_supported():
    market = classify("Will China invade Taiwan before 2027?")

    assert market.event_type == EventType.INVASION
    assert market.supported_proposition


def test_aliases_do_not_match_inside_unrelated_larger_words():
    market = classify("Will Russia invade Ukraine during a crisis?")

    assert "Russia" in market.countries
    assert "Ukraine" in market.countries
    assert "United States" not in market.countries
    assert "ISIS" not in market.actors


def test_legitimate_multi_word_alias_still_matches():
    market = classify("Will the People's Liberation Army invade Taiwan?")

    assert "PLA" in market.actors
    assert market.supported_proposition


def test_event_keyword_does_not_match_inside_larger_word():
    market = classify("Will a football striker visit Russia?")

    assert market.event_type == EventType.DIPLOMATIC
    assert market.supported_proposition


def test_no_confidence_phrase_is_not_mistaken_for_proposition_negation():
    market = classify("Will Xi Jinping lose a vote of no confidence?")

    assert market.event_type == EventType.LEADERSHIP
    assert market.supported_proposition


def test_subordinate_if_not_clause_does_not_negate_affirmative_intent():
    market = classify("Will China invade Taiwan if not deterred?")

    assert market.event_type == EventType.INVASION
    assert market.supported_proposition
