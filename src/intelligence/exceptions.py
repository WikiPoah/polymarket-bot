"""
Custom exceptions for the intelligence package.
"""


class IntelligenceError(Exception):
    """
    Base exception for all intelligence-related errors.
    """


class IntelligenceProviderError(IntelligenceError):
    """
    Raised when an intelligence provider fails to retrieve data.
    """


class IntelligenceParsingError(IntelligenceError):
    """
    Raised when intelligence data cannot be parsed into the
    application's internal models.
    """