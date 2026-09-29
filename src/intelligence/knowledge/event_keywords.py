# File-Version: 1.0.0
"""
Event type keyword mappings.
"""

from src.intelligence.classification import EventType


EVENT_KEYWORDS = {
    EventType.LEADERSHIP: [
        "resign",
        "resigns",
        "resigned",
        "resignation",
        "step down",
        "steps down",
        "ousted",
        "impeached",
        "removed",
        "removed from office",
        "removed as",
        "removed from power",
        "from power",
        "overthrown",
        "leave office",
        "leaves office",
        "left office",
        "out as",
        "leadership challenge",
        "confidence vote",
        "vote of no confidence",
        "out before",
    ],

    EventType.MILITARY_STRIKE: [
        "airstrike",
        "airstrikes",
        "air strike",
        "air strikes",
        "missile strike",
        "missile strikes",
        "bombing",
        "shelling",
        "rocket attack",
        "artillery",
    ],

    EventType.MILITARY_EXERCISE: [
        "exercise",
        "exercises",
        "drill",
        "drills",
        "war game",
        "live-fire",
        "naval exercise",
    ],

    EventType.INVASION: [
        "invade",
        "invades",
        "invaded",
        "invasion",
        "invasions",
        "offensive",
        "mobilization",
    ],

    EventType.DIPLOMATIC: [
        "meeting",
        "meetings",
        "summit",
        "talks",
        "negotiation",
        "visit",
        "visits",
        "agreement",
        "agreements",
        "deal",
        "deals",
    ],

    EventType.SANCTIONS: [
        "sanction",
        "sanctions",
        "embargo",
        "embargoes",
        "restriction",
        "restrictions",
        "tariff",
        "tariffs",
    ],

    EventType.ELECTION: [
        "election",
        "elections",
        "vote",
        "votes",
        "ballot",
        "ballots",
        "poll",
        "polls",
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
