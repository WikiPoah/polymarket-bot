# File-Version: 1.2.0
"""
Intelligence client.

Coordinates one or more intelligence providers.
"""

from copy import deepcopy
from datetime import datetime, timezone

from src.intelligence.providers.base import (
    IntelligenceProvider,
)
from src.intelligence.exceptions import (
    IntelligenceProviderError,
)
from src.intelligence.evidence import aggregate_events
from src.models import GeoPoliticalEvent
from typing import Callable


class IntelligenceClient:
    """
    Coordinates one or more intelligence providers.
    """

    def __init__(
        self,
        providers: list[IntelligenceProvider],
        evidence_time: datetime | None = None,
        event_sink: Callable[[list[GeoPoliticalEvent]], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """
        Initialise the intelligence client.

        Args:
            providers:
                Intelligence providers to query.
        """
        self._providers = providers
        self._evidence_time = evidence_time
        self._event_sink = event_sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._provider_status: dict[str, str] = {}
        self._provider_errors: list[str] = []
        self._provider_cache: dict[
            tuple[int, str | None, int, str],
            list[GeoPoliticalEvent],
        ] = {}
        self._provider_details: dict[str, dict] = {
            type(provider).__name__: self._empty_provider_details()
            for provider in providers
        }

    @property
    def provider_status(self) -> dict[str, str]:
        return dict(self._provider_status)

    @property
    def provider_errors(self) -> list[str]:
        return list(self._provider_errors)

    @property
    def provider_details(self) -> dict[str, dict]:
        return {name: dict(details) for name, details in self._provider_details.items()}

    def reset_status(self) -> None:
        self._provider_status.clear()
        self._provider_errors.clear()
        self._provider_cache.clear()
        for details in self._provider_details.values():
            details["status"] = "UNKNOWN"
            details["error"] = ""

    @staticmethod
    def _empty_provider_details() -> dict:
        return {
            "status": "UNKNOWN",
            "last_successful_run": None,
            "last_data_received": None,
            "event_age_seconds": None,
            "error": "",
        }

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
        fresh_results: list[GeoPoliticalEvent] = []

        for provider in self._providers:

            provider_name = type(provider).__name__
            effective_query = (
                query
                if getattr(provider, "query_sensitive", True)
                else None
            )
            cache_key = (id(provider), effective_query, limit, sort)

            if cache_key in self._provider_cache:
                results.extend(deepcopy(self._provider_cache[cache_key]))
                continue

            try:
                provider_results = provider.fetch(
                    query=query,
                    limit=limit,
                    sort=sort,
                )
            except IntelligenceProviderError as error:
                self._provider_status[provider_name] = "ERROR"
                message = f"{provider_name}: {error}"
                details = self._provider_details.setdefault(
                    provider_name, self._empty_provider_details()
                )
                details.update(status="ERROR", error=str(error))
                if message not in self._provider_errors:
                    self._provider_errors.append(message)
                continue

            if not all(
                isinstance(event, GeoPoliticalEvent)
                for event in provider_results
            ):
                raise TypeError(
                    "Intelligence providers must return GeoPoliticalEvent objects."
                )

            self._provider_status.setdefault(provider_name, "OK")
            now = self._clock()
            for event in provider_results:
                if event.available_at is None:
                    event.available_at = now
            self._provider_cache[cache_key] = deepcopy(provider_results)
            details = self._provider_details.setdefault(
                provider_name, self._empty_provider_details()
            )
            details["last_successful_run"] = now.isoformat()
            if self._provider_status[provider_name] != "ERROR":
                details.update(status="OK", error="")

            if provider_results:
                results.extend(provider_results)
                fresh_results.extend(provider_results)
                timestamps = [
                    event.published_at
                    for event in provider_results
                    if isinstance(event.published_at, datetime)
                ]
                if timestamps:
                    normalized = [
                        value.replace(tzinfo=timezone.utc)
                        if value.tzinfo is None else value.astimezone(timezone.utc)
                        for value in timestamps
                    ]
                    latest = max(normalized)
                    details["last_data_received"] = latest.isoformat()
                    details["event_age_seconds"] = max(
                        0.0, (now - latest).total_seconds()
                    )

        if self._event_sink is not None and fresh_results:
            # Archive independent provider reports before evidence aggregation.
            self._event_sink(fresh_results)
        aggregated = aggregate_events(results, now=self._evidence_time)
        return aggregated
