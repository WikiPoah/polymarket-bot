"""
Functions for communicating with the Polymarket API.
"""

import time

import requests

from src.config import (
    GAMMA_API_URL,
    REQUEST_TIMEOUT,
    DEFAULT_MARKET_LIMIT,
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

    def get_active_markets(
        self,
        limit=DEFAULT_MARKET_LIMIT,
    ):
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
            "limit": limit,
        }

        last_error = None

        for attempt in range(3):

            try:

                print(
                    f"Polymarket request attempt {attempt + 1}/3..."
                )

                response = requests.get(
                    endpoint,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )

                print(
                    f"Response status: {response.status_code}"
                )

                response.raise_for_status()

                return response.json()

            except requests.exceptions.Timeout as error:

                print(
                    "Polymarket timeout."
                )

                last_error = error

            except requests.exceptions.ConnectionError as error:

                print(
                    "Polymarket connection error."
                )

                last_error = error

            except requests.exceptions.HTTPError as error:

                status_code = (
                    error.response.status_code
                    if error.response is not None
                    else "unknown"
                )

                raise RuntimeError(
                    f"HTTP error: {status_code}"
                ) from error

            except requests.exceptions.RequestException as error:

                raise RuntimeError(
                    f"Unexpected API error: {error}"
                ) from error

            if attempt < 2:
                time.sleep(2)

        raise RuntimeError(
            f"Polymarket request failed after retries: {last_error}"
        ) from last_error