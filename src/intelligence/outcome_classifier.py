# File-Version: 1.1.0
"""
Rule-based outcome classifier.
"""

from src.intelligence.classifier import contains_keyword
from src.intelligence.outcomes import Outcome
from src.models import GeoPoliticalEvent


OUTCOME_KEYWORDS = {
    Outcome.LEADER_REMOVED: [
        "resign",
        "resigns",
        "resigned",
        "resignation",
        "step down",
        "removed",
        "from power",
        "leave office",
        "leaves office",
        "left office",
        "out as",
        "ousted",
        "impeached",
        "vote of no confidence",
    ],
    Outcome.GOVERNMENT_CHANGE: [
        "government formed",
        "new cabinet",
        "coalition",
    ],
    Outcome.MILITARY_ESCALATION: [
        "missile",
        "missiles",
        "airstrike",
        "bombing",
        "strike",
        "strikes",
        "shelling",
        "offensive",
        "mobilization",
    ],
    Outcome.MILITARY_DEESCALATION: [
        "ceasefire",
        "truce",
        "peace agreement",
    ],
    Outcome.SANCTIONS: [
        "sanction",
        "sanctions",
        "embargo",
        "embargoes",
        "restriction",
        "restrictions",
    ],
    Outcome.ECONOMIC_POLICY: [
        "interest rate",
        "central bank",
        "inflation",
        "gdp",
        "tariff",
        "tariffs",
    ],
    Outcome.ENERGY_DISRUPTION: [
        "oil",
        "gas",
        "pipeline",
        "pipelines",
    ],
    Outcome.SHIPPING_DISRUPTION: [
        "shipping",
        "port",
        "ports",
        "vessel",
        "vessels",
        "red sea",
    ],
    Outcome.NATURAL_DISASTER: [
        "earthquake",
        "earthquakes",
        "flood",
        "floods",
        "wildfire",
        "hurricane",
        "typhoon",
    ],
    Outcome.ELECTION_RESULT: [
        "election",
        "elections",
        "vote",
        "votes",
        "ballot",
        "ballots",
        "poll result",
    ],
}


class OutcomeClassifier:
    """
    Determines the primary outcome of an event.
    """

    def classify(
        self,
        event: GeoPoliticalEvent,
    ) -> GeoPoliticalEvent:

        text = f"{event.title} {event.summary}".lower()

        for outcome, keywords in OUTCOME_KEYWORDS.items():
            if any(contains_keyword(text, keyword) for keyword in keywords):
                event.outcome = outcome
                break

        return event
