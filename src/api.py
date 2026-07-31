"""
Functions for communicating with the Polymarket API.
"""

import requests

from src.config import (
    GAMMA_API_URL,
    REQUEST_TIMEOUT,
    DEFAULT_MARKET_LIMIT
)


class PolymarketAPI:
    """
    Client for interacting with the public Polymarket Gamma API.
    """

    def __init__(self):
        """
        Initialise the API client.
        """

        self.base_url = GAMMA_API_URL

    def get_active_markets(self, limit=DEFAULT_MARKET_LIMIT):
        """
        Retrieve active markets from Polymarket.

        Args:
            limit (int):
                Maximum number of markets to retrieve.

        Returns:
            list:
                A list of market dictionaries.

        Raises:
            RuntimeError:
                If the request cannot be completed.
        """

        endpoint = f"{self.base_url}/markets"

        params = {
            "active": "true",
            "closed": "false",
            "limit": limit
        }

        try:
            response = requests.get(
                endpoint,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            response.raise_for_status()

            return response.json()

        except requests.exceptions.Timeout as error:
            raise RuntimeError(
                "The request to the Polymarket API timed out."
            ) from error

        except requests.exceptions.ConnectionError as error:
            raise RuntimeError(
                "Unable to connect to the Polymarket API."
            ) from error

        except requests.exceptions.HTTPError as error:
            raise RuntimeError(
                f"HTTP error: {error.response.status_code}"
            ) from error

        except requests.exceptions.RequestException as error:
            raise RuntimeError(
                "An unexpected API error occurred."
            ) from error