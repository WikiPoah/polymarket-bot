"""
Application entry point.
"""

from src.api import PolymarketAPI
from src.filters import filter_geopolitical_markets
from src.intelligence.pipeline import IntelligencePipeline
from src.intelligence.providers.gdelt import GDELTProvider


def main() -> None:
    """
    Run the trading bot.
    """

    print("Connecting to Polymarket...\n")

    api = PolymarketAPI()

    try:
        markets = api.get_active_markets()

    except RuntimeError as error:
        print(f"Error: {error}")
        return

    print("Connected successfully.\n")

    print(f"Retrieved {len(markets)} active markets.")

    markets = filter_geopolitical_markets(markets)

    print(
        f"Found {len(markets)} geopolitical markets.\n"
    )

    if not markets:
        print("No geopolitical markets found.")
        return

    print("Retrieving intelligence...\n")

    pipeline = IntelligencePipeline(
        GDELTProvider()
    )

    opportunities = pipeline.run(markets)

    if not opportunities:
        print("No trading opportunities found.")
        return

    print(
        f"Found {len(opportunities)} trading opportunities.\n"
    )

    print("=" * 100)

    for opportunity in opportunities:

        print(
            f"Event Score: {opportunity.event.score}"
        )

        print(
            f"Match Score: {opportunity.match_score}"
        )

        print(
            f"Country: {opportunity.event.event.country}"
        )

        print(
            f"Category: {opportunity.event.event.category}"
        )

        print(
            f"Event:"
        )

        print(
            f"  {opportunity.event.event.title}"
        )

        print()

        print(
            f"Matched Market:"
        )

        print(
            f"  {opportunity.market.get('question')}"
        )

        print("=" * 100)


if __name__ == "__main__":
    main()