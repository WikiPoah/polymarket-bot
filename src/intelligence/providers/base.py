# File-Version: 1.0.0
"""
Base interface for intelligence providers.
"""

from abc import ABC, abstractmethod

from src.models import GeoPoliticalEvent


class IntelligenceProvider(ABC):
    """
    Contract implemented by every intelligence provider.
    """

    query_sensitive = True

    @abstractmethod
    def fetch(
        self,
        query: str | None = None,
        limit: int = 100,
        sort: str = "recent",
    ) -> list[GeoPoliticalEvent]:
        """
        Retrieve normalized geopolitical events.
        """

        raise NotImplementedError
