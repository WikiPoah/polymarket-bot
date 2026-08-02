"""
Rule-based event classifier.

This module enriches geopolitical events with structured
classification data used by the matcher.
"""

import re

from src.intelligence.classification import EventType, Topic
from src.intelligence.knowledge.actors import ACTORS
from src.intelligence.knowledge.countries import (
    COUNTRIES,
    COUNTRY_REGIONS,
)
from src.intelligence.knowledge.event_keywords import (
    EVENT_KEYWORDS,
)
from src.intelligence.knowledge.topics import (
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


LEADERSHIP_KEYWORDS = {
    "resign",
    "resignation",
    "removed",
    "dismissed",
    "ousted",
    "coup",
    "succession",
    "power struggle",
    "leadership change",
    "political crisis",
}


def contains_keyword(
    text: str,
    keyword: str,
) -> bool:
    """
    Check whether a keyword appears as a full word.
    """

    pattern = rf"\b{re.escape(keyword)}\b"

    return re.search(
        pattern,
        text,
    ) is not None


class EventClassifier:
    """
    Classifies geopolitical events using rule-based matching.
    """

    def classify(
        self,
        event: GeoPoliticalEvent,
    ) -> GeoPoliticalEvent:
        """
        Populate the event with structured metadata.
        """

        text = f"{event.title} {event.summary}".lower()

        #
        # Actors
        #

        for actor, aliases in ACTORS.items():

            if any(
                contains_keyword(
                    text,
                    alias.lower(),
                )
                for alias in aliases
            ):

                if actor not in event.actors:
                    event.actors.append(actor)

        #
        # Countries
        #

        for country, aliases in COUNTRIES.items():

            if any(
                contains_keyword(
                    text,
                    alias.lower(),
                )
                for alias in aliases
            ):

                if country not in event.countries:
                    event.countries.append(country)

        #
        # Event type
        #

        if any(
            contains_keyword(text, keyword)
            for keyword in LEADERSHIP_KEYWORDS
        ):

            event.event_type = EventType.LEADERSHIP

        else:

            for event_type, keywords in EVENT_KEYWORDS.items():

                if any(
                    contains_keyword(text, keyword)
                    for keyword in keywords
                ):

                    event.event_type = event_type
                    break

        #
        # Leadership inference
        #

        if (
            event.event_type == EventType.OTHER
            and any(
                actor in LEADERSHIP_ACTORS
                for actor in event.actors
            )
            and any(
                contains_keyword(text, keyword)
                for keyword in LEADERSHIP_KEYWORDS
            )
        ):

            event.event_type = EventType.LEADERSHIP

        #
        # Topics
        #

        for topic, keywords in TOPIC_KEYWORDS.items():

            if any(
                contains_keyword(text, keyword)
                for keyword in keywords
            ):

                if topic not in event.topics:
                    event.topics.append(topic)

        if (
            event.event_type == EventType.LEADERSHIP
            and Topic.POLITICS not in event.topics
        ):

            event.topics.append(
                Topic.POLITICS
            )

        #
        # Region
        #

        for country in event.countries:

            region = COUNTRY_REGIONS.get(country)

            if region is not None:

                event.classified_region = region
                break

        return event