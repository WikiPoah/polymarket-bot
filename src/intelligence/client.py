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
from src.intelligence.evidence import aggregate_events
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
        self._provider_status: dict[str, str] = {}
        self._provider_errors: list[str] = []

    @property
    def provider_status(self) -> dict[str, str]:
        return dict(self._provider_status)

    @property
    def provider_errors(self) -> list[str]:
        return list(self._provider_errors)

    def reset_status(self) -> None:
        self._provider_status.clear()
        self._provider_errors.clear()

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

            provider_name = type(provider).__name__

            try:
                provider_results = provider.fetch(
                    query=query,
                    limit=limit,
                    sort=sort,
                )
            except IntelligenceProviderError as error:
                self._provider_status[provider_name] = "ERROR"
                message = f"{provider_name}: {error}"
                if message not in self._provider_errors:
                    self._provider_errors.append(message)
                continue

            self._provider_status.setdefault(provider_name, "OK")

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

        return aggregate_events(results)
