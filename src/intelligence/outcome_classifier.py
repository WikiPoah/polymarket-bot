"""
Rule-based outcome classifier.
"""

from src.intelligence.outcomes import Outcome
from src.models import GeoPoliticalEvent


OUTCOME_KEYWORDS = {
    Outcome.LEADER_REMOVED: [
        "resign",
        "resignation",
        "step down",
        "removed",
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
        "airstrike",
        "bombing",
        "strike",
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
        "embargo",
        "restriction",
    ],
    Outcome.ECONOMIC_POLICY: [
        "interest rate",
        "central bank",
        "inflation",
        "gdp",
        "tariff",
    ],
    Outcome.ENERGY_DISRUPTION: [
        "oil",
        "gas",
        "pipeline",
    ],
    Outcome.SHIPPING_DISRUPTION: [
        "shipping",
        "port",
        "vessel",
        "red sea",
    ],
    Outcome.NATURAL_DISASTER: [
        "earthquake",
        "flood",
        "wildfire",
        "hurricane",
        "typhoon",
    ],
    Outcome.ELECTION_RESULT: [
        "election",
        "vote",
        "ballot",
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
            if any(keyword in text for keyword in keywords):
                event.outcome = outcome
                break

        return event