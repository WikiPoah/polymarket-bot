# File-Version: 1.2.2
"""
Application configuration constants.

This module stores configuration values that may change over time.
Keeping them in one place makes the application easier to maintain.
"""

import os

from dotenv import load_dotenv

# Load environment variables from the .env file.
load_dotenv()

# Base URL for the public Polymarket Gamma API
GAMMA_API_URL = "https://gamma-api.polymarket.com"

# Maximum time (in seconds) to wait for API responses
REQUEST_TIMEOUT = 30

# Default number of highest-volume active markets to scan per evaluation.
DEFAULT_MARKET_LIMIT = 100

# User-Agent used when requesting intelligence providers.
#
# Some providers reject requests that do not include a User-Agent.
INTELLIGENCE_USER_AGENT = "PolymarketBot research client"

# GDELT Cloud API configuration
GDELT_API_URL = "https://gdeltcloud.com/api/v2"
GDELT_API_KEY = os.getenv("GDELT_API_KEY")

# RSS intelligence feed configuration. Each feed is converted into
# GeoPoliticalEvent objects before entering the shared pipeline.
RSS_FEEDS = [
    {
        "name": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
    },
    {
        "name": "UN News",
        "url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
    },
]

RELIEFWEB_API_URL = "https://api.reliefweb.int/v2/reports"
RELIEFWEB_APPNAME = os.getenv("RELIEFWEB_APPNAME", "polymarket-bot")

# Media Cloud historical search configuration. MC_API_KEY remains a temporary
# compatibility fallback for local environments configured during feasibility.
MEDIA_CLOUD_API_URL = "https://search.mediacloud.org/api/search/story-list"
MEDIA_CLOUD_API_KEY = os.getenv("MEDIA_CLOUD_API_KEY") or os.getenv("MC_API_KEY")
MEDIA_CLOUD_COLLECTION_IDS = tuple(
    int(value.strip())
    for value in os.getenv("MEDIA_CLOUD_COLLECTION_IDS", "9272347").split(",")
    if value.strip()
)

# Configurable source reliability values used when combining evidence.
# The scorer consumes the resulting event confidence, not these values.
SOURCE_RELIABILITY = {
    "GDELT": 0.90,
    "BBC World": 0.80,
    "UN News": 0.85,
    "ReliefWeb": 0.85,
    "Media Cloud": 0.85,
    "RSS": 0.70,
    "default": 0.50,
}

# Keywords used to identify geopolitical markets.
#
# The filtering system searches market questions and event titles
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
