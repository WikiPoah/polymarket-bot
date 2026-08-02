"""
Base interface for intelligence providers.

All intelligence providers should inherit from IntelligenceProvider
and implement the fetch() method.
"""

from abc import ABC, abstractmethod
from typing import Any


class IntelligenceProvider(ABC):
    """
    Abstract base class for all intelligence providers.
    """

    @abstractmethod
    def fetch(
        self,
        query: str | None = None,
        limit: int = 100,
        sort: str = "recent",
    ) -> list[Any]:
        """
        Retrieve intelligence data.

        Args:
            query:
                Optional search query. Providers may ignore this if
                searching is not supported.

            limit:
                Maximum number of records to retrieve.

            sort:
                Ordering applied by the provider.

        Returns:
            A list containing provider-specific data.
        """
        raise NotImplementedError