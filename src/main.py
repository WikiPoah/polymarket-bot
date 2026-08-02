"""
Application entry point.
"""

from src.api import PolymarketAPI
from src.filters import filter_geopolitical_markets
from src.intelligence.client import IntelligenceClient
from src.intelligence.pipeline import IntelligencePipeline
from src.intelligence.providers.gdelt import GDELTProvider
from src.intelligence.providers.rss import RSSProvider
from src.paper_trading.history import PaperTradingRecorder


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

    intelligence_client = IntelligenceClient(
        [
            GDELTProvider(),
            RSSProvider(),
        ]
    )

    pipeline = IntelligencePipeline(
        intelligence_client,
        paper_trader=PaperTradingRecorder(),
    )

    decisions = pipeline.run(markets)

    if not decisions:
        print("No trading opportunities found.")
        return

    print(
        f"Found {len(decisions)} trading decisions.\n"
    )

    print("=" * 100)

    for decision in decisions:

        opportunity = decision.opportunity

        print(
            f"Action: {decision.action.value}"
        )

        print(
            f"Estimated Probability: {decision.estimated_probability:.1%}"
        )

        print(
            f"Market Probability: {decision.market_probability:.1%}"
        )

        print(
            f"Edge: {decision.edge:+.1%}"
        )

        print(
            f"Expected Value: {decision.expected_value:.3f}"
        )

        print(
            f"Position Size: {decision.position_size:.1%}"
        )

        print(
            f"Confidence: {decision.confidence:.0%}"
        )

        print()

        print(
            f"Event Score: {opportunity.event.score}"
        )

        print(
            f"Match Score: {opportunity.match_score}"
        )

        print()

        print(
            f"Country: {opportunity.event.event.country}"
        )

        print(
            f"Category: {opportunity.event.event.category}"
        )

        print()

        print("Event:")
        print(
            f"  {opportunity.event.event.title}"
        )

        print()

        print("Matched Market:")
        print(
            f"  {opportunity.market.get('question')}"
        )

        if decision.reasons:

            print()

            print("Strategy:")

            for reason in decision.reasons:
                print(f"  - {reason}")

        if opportunity.match_reasons:

            print()

            print("Matching:")

            for reason in opportunity.match_reasons:
                print(f"  - {reason}")

        print("=" * 100)


if __name__ == "__main__":
    main()
