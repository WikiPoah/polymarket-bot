"""
Application entry point.
"""

from src.api import PolymarketAPI
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

    print(f"Retrieved {len(markets)} active markets.\n")

    for market in markets:
        display_market(market)


if __name__ == "__main__":
    main()