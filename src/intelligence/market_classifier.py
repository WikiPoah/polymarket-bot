# File-Version: 1.0.0
"""
Market classifier.

Converts raw Polymarket markets into structured
ClassifiedMarket objects.
"""

from src.intelligence.classification import EventType, Topic
from src.intelligence.classifier import contains_keyword
from src.intelligence.knowledge import (
    ACTORS,
    COUNTRIES,
    COUNTRY_REGIONS,
    EVENT_KEYWORDS,
    TOPIC_KEYWORDS,
)
from src.intelligence.outcomes import Outcome
from src.models import ClassifiedMarket


ACTOR_COUNTRIES = {
    "Xi Jinping": "China",
    "CCP": "China",
    "Donald Trump": "United States",
    "Vladimir Putin": "Russia",
    "Volodymyr Zelenskyy": "Ukraine",
    "Benjamin Netanyahu": "Israel",
    "Ayatollah Khamenei": "Iran",
}


NEGATION_EXCEPTIONS = (
    "if not",
    "whether or not",
    "not later than",
    "no later than",
    "vote of no confidence",
)


def _has_unsupported_negation(question: str) -> bool:
    """Detect explicit proposition negation while preserving narrow exceptions."""

    remaining = question
    for phrase in NEGATION_EXCEPTIONS:
        remaining = remaining.replace(phrase, " ")
    return any(
        contains_keyword(remaining, term)
        for term in ("not", "never", "no", "without")
    )


class MarketClassifier:
    """
    Classifies Polymarket markets using the same
    knowledge base as event classification.
    """

    def classify(
        self,
        market: dict,
    ) -> ClassifiedMarket:
        """
        Classify a Polymarket market.
        """

        classified = ClassifiedMarket(
            market=market,
        )

        question = str(market.get("question") or "").lower()

        #
        # Event type
        #

        for event_type, keywords in EVENT_KEYWORDS.items():

            if any(
                contains_keyword(question, keyword)
                for keyword in keywords
            ):

                classified.event_type = event_type
                break

        #
        # Topics
        #

        for topic, keywords in TOPIC_KEYWORDS.items():

            if any(
                contains_keyword(question, keyword)
                for keyword in keywords
            ):

                if topic not in classified.topics:
                    classified.topics.append(topic)

        #
        # Actors
        #

        for actor, aliases in ACTORS.items():

            if any(
                contains_keyword(question, alias.lower())
                for alias in aliases
            ):

                if actor not in classified.actors:
                    classified.actors.append(actor)

        #
        # Countries
        #

        for country, aliases in COUNTRIES.items():

            if any(
                contains_keyword(question, alias.lower())
                for alias in aliases
            ):

                if country not in classified.countries:
                    classified.countries.append(country)

        #
        # Infer country from actor
        #

        for actor in classified.actors:

            country = ACTOR_COUNTRIES.get(actor)

            if (
                country is not None
                and country not in classified.countries
            ):

                classified.countries.append(country)

        #
        # If a leadership actor is detected,
        # ensure politics topic exists.
        #

        if (
            classified.event_type == EventType.LEADERSHIP
            and Topic.POLITICS not in classified.topics
        ):

            classified.topics.append(
                Topic.POLITICS
            )

        #
        # Expected outcome
        #

        if classified.event_type == EventType.LEADERSHIP:

            classified.expected_outcome = (
                Outcome.LEADER_REMOVED
            )

        elif classified.event_type == EventType.MILITARY_STRIKE:

            classified.expected_outcome = (
                Outcome.MILITARY_ESCALATION
            )

        elif classified.event_type == EventType.SANCTIONS:

            classified.expected_outcome = (
                Outcome.SANCTIONS
            )

        elif classified.event_type == EventType.ENERGY:

            classified.expected_outcome = (
                Outcome.ENERGY_DISRUPTION
            )

        elif classified.event_type == EventType.SHIPPING:

            classified.expected_outcome = (
                Outcome.SHIPPING_DISRUPTION
            )

        elif classified.event_type == EventType.ECONOMIC:

            classified.expected_outcome = (
                Outcome.ECONOMIC_POLICY
            )

        elif classified.event_type == EventType.ELECTION:

            classified.expected_outcome = (
                Outcome.ELECTION_RESULT
            )

        #
        # Region
        #

        for country in classified.countries:

            region = COUNTRY_REGIONS.get(country)

            if region is not None:

                classified.classified_region = region
                break

        if _has_unsupported_negation(question):
            classified.unsupported_reason = (
                "Unsupported or ambiguous proposition: explicit negation."
            )
        elif classified.event_type == EventType.OTHER:
            classified.unsupported_reason = (
                "Unsupported proposition: no recognized geopolitical event intent."
            )
        else:
            classified.supported_proposition = True
            classified.unsupported_reason = ""

        return classified
