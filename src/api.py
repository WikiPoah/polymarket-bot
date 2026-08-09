# File-Version: 1.1.0
"""
Functions for communicating with the Polymarket API.
"""

import time

import requests

from src.config import (
    DEFAULT_MARKET_LIMIT,
    GAMMA_API_URL,
    REQUEST_TIMEOUT,
)


MARKET_PAGE_SIZE = 100
MAX_MARKET_PAGES = 1000


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
        limit: int = DEFAULT_MARKET_LIMIT,
    ) -> list[dict]:
        """
        Retrieve active markets from Polymarket.

        Args:
            limit:
                Maximum number of highest-volume active markets to retrieve.

        Returns:
            list:
                A list of market dictionaries.

        Raises:
            RuntimeError:
                If the request cannot be completed.
        """

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit <= 0
        ):
            raise ValueError("limit must be a positive integer")

        endpoint = f"{self.base_url}/markets/keyset"
        markets: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        for _page_number in range(MAX_MARKET_PAGES):
            page_limit = MARKET_PAGE_SIZE
            page_limit = min(page_limit, limit - len(markets))

            params: dict[str, str | int] = {
                "active": "true",
                "closed": "false",
                "limit": page_limit,
                "order": "volume24hr",
                "ascending": "false",
            }
            if cursor is not None:
                params["after_cursor"] = cursor

            payload = self._get_page(endpoint, params)
            page = payload.get("markets")
            next_cursor = payload.get("next_cursor")

            if not isinstance(page, list) or not all(
                isinstance(market, dict) for market in page
            ):
                raise RuntimeError(
                    "Unexpected Polymarket response: markets must be a list of objects"
                )

            markets.extend(page)
            if len(markets) >= limit:
                return markets[:limit]

            if next_cursor is None:
                return markets
            if not isinstance(next_cursor, str) or not next_cursor:
                raise RuntimeError(
                    "Unexpected Polymarket response: next_cursor must be a string"
                )
            if next_cursor in seen_cursors:
                raise RuntimeError("Polymarket pagination returned a repeated cursor")

            seen_cursors.add(next_cursor)
            cursor = next_cursor

        raise RuntimeError(
            f"Polymarket pagination exceeded {MAX_MARKET_PAGES} pages"
        )

    @staticmethod
    def _get_page(
        endpoint: str,
        params: dict[str, str | int],
    ) -> dict:
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                response = requests.get(
                    endpoint,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError(
                        "Unexpected Polymarket response: expected an object"
                    )
                return payload
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as error:
                last_error = error
            except requests.exceptions.HTTPError as error:
                status_code = (
                    error.response.status_code
                    if error.response is not None
                    else "unknown"
                )
                raise RuntimeError(f"HTTP error: {status_code}") from error
            except requests.exceptions.RequestException as error:
                raise RuntimeError(f"Unexpected API error: {error}") from error
            except ValueError as error:
                raise RuntimeError("Polymarket returned invalid JSON") from error

            if attempt < 2:
                time.sleep(2)

        raise RuntimeError(
            f"Polymarket request failed after retries: {last_error}"
        ) from last_error
