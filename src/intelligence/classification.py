from enum import Enum, auto


class EventType(Enum):
    """High-level category describing the type of geopolitical event."""

    LEADERSHIP = auto()
    MILITARY_STRIKE = auto()
    MILITARY_EXERCISE = auto()
    INVASION = auto()
    DIPLOMATIC = auto()
    SANCTIONS = auto()
    ELECTION = auto()
    ECONOMIC = auto()
    ENERGY = auto()
    SHIPPING = auto()
    NUCLEAR = auto()
    TERRORISM = auto()
    NATURAL_DISASTER = auto()
    OTHER = auto()


class Region(Enum):
    """Broad geographic region associated with an event or market."""

    EAST_ASIA = auto()
    SOUTH_ASIA = auto()
    CENTRAL_ASIA = auto()
    EUROPE = auto()
    MIDDLE_EAST = auto()
    AFRICA = auto()
    NORTH_AMERICA = auto()
    SOUTH_AMERICA = auto()
    OCEANIA = auto()
    GLOBAL = auto()
    UNKNOWN = auto()


class Topic(Enum):
    """Topics used to compare events and prediction markets."""

    MILITARY = auto()
    DIPLOMACY = auto()
    ENERGY = auto()
    SHIPPING = auto()
    POLITICS = auto()
    ECONOMY = auto()
    NUCLEAR = auto()
    TRADE = auto()
    CYBER = auto()
    HUMANITARIAN = auto()
    OTHER = auto()