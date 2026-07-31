"""
Unit tests for the market filtering utilities.
"""

from src.filters import (
    filter_geopolitical_markets,
    is_geopolitical_market,
)


def test_is_geopolitical_market_returns_true_for_iran_market():
    """
    Markets mentioning Iran should be identified as geopolitical.
    """

    market = {
        "question": "Will Israel attack Iran?",
        "events": [],
    }

    assert is_geopolitical_market(market)


def test_is_geopolitical_market_returns_true_for_china_market():
    """
    Markets mentioning China or Taiwan should be identified.
    """

    market = {
        "question": "Will China invade Taiwan in 2027?",
        "events": [],
    }

    assert is_geopolitical_market(market)


def test_is_geopolitical_market_returns_true_for_event_title():
    """
    Keywords should also be detected inside event titles.
    """

    market = {
        "question": "Who will win?",
        "events": [
            {
                "title": "China and Taiwan Relations",
            }
        ],
    }

    assert is_geopolitical_market(market)


def test_is_geopolitical_market_returns_false_for_non_geopolitical_market():
    """
    Unrelated markets should not match.
    """

    market = {
        "question": "Will Manchester United win the Premier League?",
        "events": [],
    }

    assert not is_geopolitical_market(market)


def test_is_geopolitical_market_returns_false_for_empty_market():
    """
    Empty markets should not match.
    """

    market = {}

    assert not is_geopolitical_market(market)


def test_filter_geopolitical_markets_only_returns_matching_markets():
    """
    Only geopolitical markets should remain after filtering.
    """

    markets = [
        {
            "question": "Will Israel attack Iran?",
            "events": [],
        },
        {
            "question": "Will Manchester United win?",
            "events": [],
        },
        {
            "question": "Will China invade Taiwan?",
            "events": [],
        },
    ]

    filtered = filter_geopolitical_markets(markets)

    assert len(filtered) == 2

    assert filtered[0]["question"] == "Will Israel attack Iran?"
    assert filtered[1]["question"] == "Will China invade Taiwan?"


def test_is_geopolitical_market_does_not_match_partial_words():
    """
    Partial words should not trigger keyword matches.
    """

    market = {
        "question": "New Playboi Carti Album before GTA VI?",
        "events": [],
    }

    assert not is_geopolitical_market(market)
    
