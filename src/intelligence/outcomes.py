"""
Outcome classifications.

Represents the real-world consequence of an event.
"""

from enum import Enum, auto


class Outcome(Enum):
    LEADER_REMOVED = auto()
    GOVERNMENT_CHANGE = auto()
    MILITARY_ESCALATION = auto()
    MILITARY_DEESCALATION = auto()
    SANCTIONS = auto()
    CEASEFIRE = auto()
    ECONOMIC_POLICY = auto()
    ENERGY_DISRUPTION = auto()
    SHIPPING_DISRUPTION = auto()
    NATURAL_DISASTER = auto()
    ELECTION_RESULT = auto()
    OTHER = auto()