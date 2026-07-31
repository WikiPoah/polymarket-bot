"""
Utility functions used throughout the application.
"""

import json


def display_market(market):
    """
    Display a market in a readable format.

    Args:
        market (dict):
            A market returned by the Polymarket API.
    """

    question = market.get("question", "Unknown market")

    volume = float(market.get("volume", 0))

    liquidity = float(market.get("liquidity", 0))

    outcomes = json.loads(market.get("outcomes", "[]"))

    prices = json.loads(market.get("outcomePrices", "[]"))

    print("=" * 60)
    print(question)
    print()

    for outcome, price in zip(outcomes, prices):
        print(f"{outcome:<5}: ${float(price):.3f}")

    print()
    print(f"Volume    : ${volume:,.2f}")
    print(f"Liquidity : ${liquidity:,.2f}")
    print("=" * 60)
    print()