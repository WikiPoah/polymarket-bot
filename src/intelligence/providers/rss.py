"""
Placeholder RSS intelligence provider.
"""

from src.intelligence.providers.base import (
    IntelligenceProvider,
)
from src.models import GeoPoliticalEvent


class RSSProvider(IntelligenceProvider):
    """
    Future provider for RSS-based intelligence sources.
    """

    def fetch(
        self,
        query: str | None = None,
        limit: int = 100,
        sort: str = "recent",
    ) -> list[GeoPoliticalEvent]:
        """
        RSS ingestion is not configured yet.
        """

        raise NotImplementedError(
            "RSSProvider is not implemented yet."
        )
