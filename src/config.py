"""
Application configuration constants.

This module stores configuration values that may change over time.
Keeping them in one place makes the application easier to maintain.
"""

# Base URL for the public Polymarket Gamma API
GAMMA_API_URL = "https://gamma-api.polymarket.com"

# Maximum time (in seconds) to wait for an API response
REQUEST_TIMEOUT = 10

# Default number of markets to request
DEFAULT_MARKET_LIMIT = 25