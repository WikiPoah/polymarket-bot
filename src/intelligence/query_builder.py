"""
Market query builder.

Creates intelligence search queries from classified markets.
"""

from src.intelligence.classification import EventType
from src.models import ClassifiedMarket


class MarketQueryBuilder:
    """
    Builds search queries using structured market information.
    """

    EVENT_TERMS = {
        EventType.LEADERSHIP: [
            "removed",
            "resignation",
            "steps down",
            "ousted",
            "succession",
        ],

        EventType.MILITARY_STRIKE: [
            "strike",
            "attack",
            "escalation",
        ],

        EventType.SANCTIONS: [
            "sanctions",
            "restrictions",
        ],

        EventType.ELECTION: [
            "election",
            "vote",
            "poll",
        ],
    }

    def build(
        self,
        market: ClassifiedMarket,
    ) -> str:
        """
        Create a focused intelligence query from a market.
        """

        terms: list[str] = []

        #
        # Actors are highest signal.
        #

        terms.extend(
            market.actors[:2]
        )

        #
        # Countries.
        #

        terms.extend(
            market.countries[:2]
        )

        #
        # Event intent.
        #

        terms.extend(
            self.EVENT_TERMS.get(
                market.event_type,
                [],
            )
        )

        #
        # Only add topics if query is empty.
        # Broad topics reduce relevance.
        #

        if not terms:

            for topic in market.topics:
                terms.append(
                    topic.name.replace("_", " ")
                )

        #
        # Fallback to market question.
        #

        if not terms:

            terms.append(
                market.market.get(
                    "question",
                    "",
                )
            )

        return " ".join(
            dict.fromkeys(terms)
        )