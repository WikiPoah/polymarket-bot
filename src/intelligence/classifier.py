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
}


LOCATION_ALIASES = {
    "Beijing": "China",
    "Moscow": "Russia",
    "Kyiv": "Ukraine",
    "Tehran": "Iran",
    "Jerusalem": "Israel",
    "Taipei": "Taiwan",
    "Gaza": None,
    "West Bank": None,
    "Red Sea": None,
}


DATE_PATTERNS = (
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+\d{1,2}(?:,\s+\d{4})?\b",
)


SIGNIFICANCE_BY_TYPE = {
    EventType.INVASION: 0.95,
    EventType.MILITARY_STRIKE: 0.85,
    EventType.NUCLEAR: 0.85,
    EventType.TERRORISM: 0.80,
    EventType.LEADERSHIP: 0.80,
    EventType.SANCTIONS: 0.70,
    EventType.MILITARY_EXERCISE: 0.65,
    EventType.SHIPPING: 0.65,
    EventType.ENERGY: 0.60,
    EventType.ELECTION: 0.60,
    EventType.DIPLOMATIC: 0.50,
    EventType.ECONOMIC: 0.50,
    EventType.OTHER: 0.30,
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

        if event.country:
            if event.country not in event.countries:
                event.countries.append(event.country)
            if event.country not in event.locations:
                event.locations.append(event.country)

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

                if country not in event.locations:
                    event.locations.append(country)

        for location, country in LOCATION_ALIASES.items():
            if contains_keyword(text, location.lower()):
                if location not in event.locations:
                    event.locations.append(location)
                if country and country not in event.countries:
                    event.countries.append(country)

        for pattern in DATE_PATTERNS:
            for match in re.findall(pattern, text, flags=re.IGNORECASE):
                value = match.strip()
                if value not in event.mentioned_dates:
                    event.mentioned_dates.append(value)

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

        if event.significance is None:
            significance = SIGNIFICANCE_BY_TYPE.get(event.event_type, 0.30)
            if event.actors and event.countries:
                significance += 0.05
            if event.evidence_count > 1:
                significance += min(0.10, 0.03 * (event.evidence_count - 1))
            event.significance = min(1.0, significance)

        return event
