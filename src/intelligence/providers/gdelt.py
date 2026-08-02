"""
GDELT Cloud intelligence provider.

Retrieves geopolitical events from the GDELT Cloud REST API.
"""

import time

import httpx

from src.config import (
    GDELT_API_KEY,
    GDELT_API_URL,
)
from src.intelligence.exceptions import (
    IntelligenceProviderError,
)
from src.intelligence.parser import (
    parse_gdelt_event,
)
from src.intelligence.provider import (
    IntelligenceProvider,
)
from src.models import GeoPoliticalEvent


class GDELTProvider(IntelligenceProvider):
    """
    Intelligence provider for the GDELT Cloud Events API.
    """

    ENDPOINT = "/events"

    def fetch(
        self,
        limit: int = 100,
        sort: str = "recent",
    ) -> list[GeoPoliticalEvent]:
        """
        Retrieve recent geopolitical events.
        """

        if not GDELT_API_KEY:
            raise IntelligenceProviderError(
                "GDELT_API_KEY was not found."
            )

        headers = {
            "Authorization": f"Bearer {GDELT_API_KEY}",
            "Accept": "application/json",
        }

        params = {
            "limit": limit,
            "sort": sort,
        }

        url = f"{GDELT_API_URL}{self.ENDPOINT}"

        last_error: Exception | None = None

        for attempt in range(3):

            try:

                with httpx.Client(timeout=10) as client:

                    response = client.get(
                        url,
                        headers=headers,
                        params=params,
                    )

                response.raise_for_status()

                data = response.json()

                if not isinstance(data, dict):
                    raise IntelligenceProviderError(
                        "Unexpected response from GDELT."
                    )

                raw_events = data.get("data")

                if not isinstance(raw_events, list):
                    raise IntelligenceProviderError(
                        "Response does not contain an event list."
                    )

                events: list[GeoPoliticalEvent] = []

                for event in raw_events:
                    events.append(
                        parse_gdelt_event(event)
                    )

                return events

            except (
                httpx.TimeoutException,
                httpx.HTTPStatusError,
                httpx.NetworkError,
            ) as error:

                last_error = error

                if attempt < 2:
                    time.sleep(2)
                    continue

        raise IntelligenceProviderError(
            "Failed to retrieve intelligence data."
        ) from last_error