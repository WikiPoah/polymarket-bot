"""
Country aliases and region mappings.
"""

from src.intelligence.classification import Region


COUNTRIES = {
    "China": [
        "china",
        "prc",
        "people's republic of china",
    ],
    "Taiwan": [
        "taiwan",
        "republic of china",
    ],
    "Japan": [
        "japan",
    ],
    "South Korea": [
        "south korea",
        "republic of korea",
        "rok",
    ],
    "North Korea": [
        "north korea",
        "dprk",
        "democratic people's republic of korea",
    ],
    "Russia": [
        "russia",
        "russian federation",
    ],
    "Ukraine": [
        "ukraine",
    ],
    "Iran": [
        "iran",
        "islamic republic of iran",
    ],
    "Israel": [
        "israel",
    ],
    "Saudi Arabia": [
        "saudi arabia",
    ],
    "Qatar": [
        "qatar",
    ],
    "Iraq": [
        "iraq",
    ],
    "Syria": [
        "syria",
    ],
    "Yemen": [
        "yemen",
    ],
    "India": [
        "india",
    ],
    "Pakistan": [
        "pakistan",
    ],
    "United States": [
        "united states",
        "usa",
        "u.s.",
        "us",
        "america",
    ],
    "United Kingdom": [
        "united kingdom",
        "uk",
        "britain",
        "great britain",
        "england",
    ],
    "France": [
        "france",
    ],
    "Germany": [
        "germany",
    ],
}


COUNTRY_REGIONS = {
    "China": Region.EAST_ASIA,
    "Taiwan": Region.EAST_ASIA,
    "Japan": Region.EAST_ASIA,
    "South Korea": Region.EAST_ASIA,
    "North Korea": Region.EAST_ASIA,

    "Russia": Region.EUROPE,
    "Ukraine": Region.EUROPE,
    "United Kingdom": Region.EUROPE,
    "France": Region.EUROPE,
    "Germany": Region.EUROPE,

    "Iran": Region.MIDDLE_EAST,
    "Israel": Region.MIDDLE_EAST,
    "Saudi Arabia": Region.MIDDLE_EAST,
    "Qatar": Region.MIDDLE_EAST,
    "Iraq": Region.MIDDLE_EAST,
    "Syria": Region.MIDDLE_EAST,
    "Yemen": Region.MIDDLE_EAST,

    "India": Region.SOUTH_ASIA,
    "Pakistan": Region.SOUTH_ASIA,

    "United States": Region.NORTH_AMERICA,
}