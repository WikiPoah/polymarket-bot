"""
Intelligence client.

Coordinates one or more intelligence providers.
"""

from typing import Any

from .provider import IntelligenceProvider


class IntelligenceClient:
    """
    Coordinates one or more intelligence providers.
    """

    def __init__(
        self,
        providers: list[IntelligenceProvider],
    ) -> None:
        """
        Initialise the intelligence client.

        Args:
            providers:
                Intelligence providers to query.
        """
        self._providers = providers

    def fetch(
        self,
        query: str | None = None,
        limit: int = 100,
        sort: str = "recent",
    ) -> list[Any]:
        """
        Retrieve data from every configured provider.

        Args:
            query:
                Optional search query.

            limit:
                Maximum number of records to retrieve.

            sort:
                Ordering applied by each provider.

        Returns:
            A combined list containing the results from all providers.
        """

        results: list[Any] = []

        for provider in self._providers:

            provider_results = provider.fetch(
                query=query,
                limit=limit,
                sort=sort,
            )

            if provider_results:
                results.extend(provider_results)

        return results