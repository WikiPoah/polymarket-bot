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

# Keywords used to identify geopolitical markets.
#
# The filtering system searches market questions and descriptions
# for these terms. The list is intentionally grouped by category
# to make future maintenance easier.
GEOPOLITICAL_KEYWORDS = [

    # Middle East
    "iran",
    "israel",
    "palestine",
    "gaza",
    "west bank",
    "lebanon",
    "syria",
    "jordan",
    "iraq",
    "yemen",
    "saudi arabia",
    "uae",
    "united arab emirates",
    "qatar",
    "oman",
    "turkey",

    # Eastern Europe
    "russia",
    "ukraine",
    "belarus",

    # East Asia
    "china",
    "taiwan",
    "taiwan strait",
    "north korea",
    "south korea",
    "japan",

    # Strategic regions
    "middle east",
    "persian gulf",
    "gulf of oman",
    "red sea",
    "strait of hormuz",
    "bab el-mandeb",
    "south china sea",
    "east china sea",
    "black sea",

    # Organisations
    "hamas",
    "hezbollah",
    "houthi",
    "houthis",
    "irgc",
    "islamic revolutionary guard corps",
    "isis",
    "isil",
    "daesh",
    "al qaeda",
    "taliban",
    "nato",
    "idf",
    "pla",
    "wagner",

    # Energy
    "oil",
    "crude",
    "brent",
    "wti",
    "opec",
    "opec+",
    "lng",
    "natural gas",

    # High-profile leaders
    "xi jinping",
    "putin",
    "vladimir putin",
    "zelensky",
    "volodymyr zelensky",
    "netanyahu",
    "benjamin netanyahu",
    "khamenei",
    "ali khamenei",
    "trump",
    "donald trump",
    "kim jong un",
]