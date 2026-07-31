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
        providers: list[IntelligenceProvider]
    ) -> None:
        """
        Initialise the intelligence client.

        Args:
            providers:
                Intelligence providers to query.
        """
        self._providers = providers

    def fetch(self) -> list[Any]:
        """
        Retrieve data from every configured provider.

        Returns:
            A combined list containing the results from all providers.
        """

        results: list[Any] = []

        for provider in self._providers:
            provider_results = provider.fetch()

            if provider_results:
                results.extend(provider_results)

        return results