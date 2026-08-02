"""
Market classifier.

Converts raw Polymarket markets into structured
ClassifiedMarket objects.
"""

from src.intelligence.classification import EventType, Topic
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


LEADERSHIP_ACTORS = set(ACTOR_COUNTRIES.keys())


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

        question = market.get(
            "question",
            "",
        ).lower()

        #
        # Event type
        #

        for event_type, keywords in EVENT_KEYWORDS.items():
            if any(keyword in question for keyword in keywords):
                classified.event_type = event_type
                break

        #
        # Topics
        #

        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(keyword in question for keyword in keywords):
                classified.topics.append(topic)

        #
        # Actors
        #

        for actor, aliases in ACTORS.items():
            if any(alias in question for alias in aliases):
                classified.actors.append(actor)

        #
        # Leadership inference
        #

        if (
            classified.event_type == EventType.OTHER
            and any(
                actor in LEADERSHIP_ACTORS
                for actor in classified.actors
            )
        ):
            classified.event_type = EventType.LEADERSHIP

        if (
            classified.event_type == EventType.LEADERSHIP
            and Topic.POLITICS not in classified.topics
        ):
            classified.topics.append(Topic.POLITICS)

        #
        # Countries
        #

        for country, aliases in COUNTRIES.items():
            if any(alias in question for alias in aliases):
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
        # Expected outcome
        #

        if classified.event_type == EventType.LEADERSHIP:
            classified.expected_outcome = Outcome.LEADER_REMOVED

        elif classified.event_type == EventType.MILITARY_STRIKE:
            classified.expected_outcome = (
                Outcome.MILITARY_ESCALATION
            )

        elif classified.event_type == EventType.SANCTIONS:
            classified.expected_outcome = Outcome.SANCTIONS

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

        return classified