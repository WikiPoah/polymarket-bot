"""
Topic keyword mappings.
"""

from src.intelligence.classification import Topic


TOPIC_KEYWORDS = {
    Topic.MILITARY: [
        "military",
        "army",
        "navy",
        "air force",
        "missile",
        "drill",
        "troops",
        "soldiers",
        "war",
        "defence",
        "defense",
        "battle",
    ],
    Topic.DIPLOMACY: [
        "meeting",
        "summit",
        "negotiation",
        "agreement",
        "treaty",
        "delegation",
        "minister",
        "foreign minister",
    ],
    Topic.ENERGY: [
        "oil",
        "gas",
        "pipeline",
        "energy",
        "lng",
        "crude",
        "electricity",
    ],
    Topic.SHIPPING: [
        "shipping",
        "cargo",
        "vessel",
        "port",
        "container",
        "red sea",
        "shipping lane",
    ],
    Topic.POLITICS: [
        "government",
        "minister",
        "president",
        "parliament",
        "prime minister",
        "cabinet",
    ],
    Topic.ECONOMY: [
        "economy",
        "inflation",
        "gdp",
        "interest rate",
        "recession",
        "trade",
        "tariff",
    ],
    Topic.NUCLEAR: [
        "nuclear",
        "uranium",
        "reactor",
        "atomic",
        "enrichment",
    ],
}