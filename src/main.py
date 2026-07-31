"""
Application entry point.
"""

from src.api import PolymarketAPI
from src.filters import filter_geopolitical_markets
from src.utils import display_market


def main():
    """
    Run the application.
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

    filtered_markets = filter_geopolitical_markets(markets)

    print(
        f"Found {len(filtered_markets)} geopolitical markets.\n"
    )

    if not filtered_markets:
        print("No matching markets were found.")
        return

    for market in filtered_markets:
        display_market(market)


if __name__ == "__main__":
    main()