"""
Intelligence client.

Coordinates one or more intelligence providers.
"""

from src.intelligence.providers.base import (
    IntelligenceProvider,
)
from src.intelligence.exceptions import (
    IntelligenceProviderError,
)
from src.models import GeoPoliticalEvent


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
    ) -> list[GeoPoliticalEvent]:
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

        results: list[GeoPoliticalEvent] = []

        for provider in self._providers:

            try:
                provider_results = provider.fetch(
                    query=query,
                    limit=limit,
                    sort=sort,
                )
            except IntelligenceProviderError:
                continue

            if provider_results:
                if not all(
                    isinstance(
                        event,
                        GeoPoliticalEvent,
                    )
                    for event in provider_results
                ):
                    raise TypeError(
                        "Intelligence providers must return "
                        "GeoPoliticalEvent objects."
                    )

                results.extend(provider_results)

        return results
