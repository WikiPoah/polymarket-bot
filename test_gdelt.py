"""
Temporary script for testing the GDELT provider.

This script fetches recent geopolitical events from GDELT,
scores them and prints a summary.
"""

from src.intelligence.providers.gdelt import GDELTProvider
from src.intelligence.scorer import score_events


def main() -> None:
    """
    Fetch, score and display geopolitical events.
    """

    provider = GDELTProvider()

    events = provider.fetch(limit=100)

    print(f"Retrieved {len(events)} events.\n")

    scored_events = score_events(events)

    for scored_event in scored_events:
        event = scored_event.event

        print(f"Score: {scored_event.score}")
        print(f"Title: {event.title}")
        print(f"Category: {event.category}")

        if event.country:
            print(f"Country: {event.country}")

        print(f"Published: {event.published_at}")
        print(f"URL: {event.source_url}")
        print("-" * 80)


if __name__ == "__main__":
    main()