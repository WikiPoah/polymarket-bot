"""
Event type keyword mappings.
"""

from src.intelligence.classification import EventType


EVENT_KEYWORDS = {
    EventType.LEADERSHIP: [
        "resign",
        "resignation",
        "step down",
        "steps down",
        "ousted",
        "impeached",
        "removed from office",
        "removed as",
        "removed from power",
        "overthrown",
        "leadership challenge",
        "confidence vote",
        "vote of no confidence",
        "out before",
    ],

    EventType.MILITARY_STRIKE: [
        "airstrike",
        "missile",
        "bombing",
        "strike",
        "shelling",
        "rocket attack",
        "artillery",
    ],

    EventType.MILITARY_EXERCISE: [
        "exercise",
        "drill",
        "war game",
        "live-fire",
        "naval exercise",
    ],

    EventType.INVASION: [
        "invade",
        "invasion",
        "offensive",
        "mobilization",
    ],

    EventType.DIPLOMATIC: [
        "meeting",
        "summit",
        "talks",
        "negotiation",
        "visit",
        "agreement",
    ],

    EventType.SANCTIONS: [
        "sanction",
        "embargo",
        "restriction",
        "tariff",
    ],

    EventType.ELECTION: [
        "election",
        "vote",
        "ballot",
        "poll",
    ],

    EventType.ECONOMIC: [
        "economy",
        "inflation",
        "gdp",
        "interest rate",
        "recession",
    ],

    EventType.ENERGY: [
        "oil",
        "gas",
        "pipeline",
        "energy",
        "lng",
    ],

    EventType.SHIPPING: [
        "shipping",
        "cargo",
        "vessel",
        "port",
        "red sea",
    ],

    EventType.NUCLEAR: [
        "nuclear",
        "uranium",
        "reactor",
        "atomic",
    ],

    EventType.TERRORISM: [
        "terror",
        "terrorist",
        "suicide bombing",
    ],
}