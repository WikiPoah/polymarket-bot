"""
Placeholder News API intelligence provider.
"""

from src.intelligence.providers.base import (
    IntelligenceProvider,
)
from src.models import GeoPoliticalEvent


class NewsAPIProvider(IntelligenceProvider):
    """
    Future provider for News API intelligence sources.
    """

    def fetch(
        self,
        query: str | None = None,
        limit: int = 100,
        sort: str = "recent",
    ) -> list[GeoPoliticalEvent]:
        """
        News API ingestion is not configured yet.
        """

        raise NotImplementedError(
            "NewsAPIProvider is not implemented yet."
        )
