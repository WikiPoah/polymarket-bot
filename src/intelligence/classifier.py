"""
Rule-based event classifier.

This module enriches geopolitical events with structured
classification data used by the matcher.
"""

from src.intelligence.classification import EventType, Topic
from src.intelligence.knowledge import (
    ACTORS,
    COUNTRIES,
    COUNTRY_REGIONS,
    EVENT_KEYWORDS,
    TOPIC_KEYWORDS,
)
from src.models import GeoPoliticalEvent


LEADERSHIP_ACTORS = {
    "Xi Jinping",
    "Donald Trump",
    "Vladimir Putin",
    "Volodymyr Zelenskyy",
    "Benjamin Netanyahu",
    "Ayatollah Khamenei",
}


class EventClassifier:
    """
    Classifies geopolitical events using simple rule-based matching.
    """

    def classify(
        self,
        event: GeoPoliticalEvent,
    ) -> GeoPoliticalEvent:
        """
        Populate the event with structured metadata.
        """

        text = f"{event.title} {event.summary}".lower()

        # Event type

        for event_type, keywords in EVENT_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                event.event_type = event_type
                break

        # Topics

        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                event.topics.append(topic)

        # Actors

        for actor, aliases in ACTORS.items():
            if any(alias in text for alias in aliases):
                event.actors.append(actor)

        # Leadership inference

        if (
            event.event_type == EventType.OTHER
            and any(
                actor in LEADERSHIP_ACTORS
                for actor in event.actors
            )
        ):
            event.event_type = EventType.LEADERSHIP

        if (
            event.event_type == EventType.LEADERSHIP
            and Topic.POLITICS not in event.topics
        ):
            event.topics.append(Topic.POLITICS)

        # Countries

        for country, aliases in COUNTRIES.items():
            if any(alias in text for alias in aliases):
                event.countries.append(country)

        # Region

        for country in event.countries:
            region = COUNTRY_REGIONS.get(country)

            if region is not None:
                event.classified_region = region
                break

        return event