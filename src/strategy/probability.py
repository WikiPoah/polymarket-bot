"""
Probability estimation.

This module estimates the probability that a trading opportunity will
resolve in the expected direction based on the available intelligence.
"""

from datetime import datetime, timezone

from src.models import TradingOpportunity


class ProbabilityEstimator:
    """
    Estimates the probability of a trading opportunity succeeding.
    """

    def estimate(self, opportunity: TradingOpportunity) -> float:
        """
        Estimate the probability of success.

        Returns a value between 0.0 and 1.0.
        """

        event = opportunity.event.event

        score = 0.50

        #
        # Intelligence confidence
        #

        if event.confidence is not None:
            score += (event.confidence - 0.5) * 0.20

        #
        # Event significance
        #

        if event.significance is not None:
            score += (event.significance - 0.5) * 0.15

        #
        # Market sensitivity
        #

        if event.market_sensitivity is not None:
            score += (event.market_sensitivity - 0.5) * 0.10

        score += (
            event.evidence_confidence - 0.5
        ) * 0.15

        #
        # Match quality
        #

        score += min(opportunity.match_score / 100, 1.0) * 0.15

        #
        # Matching evidence
        #

        score += min(len(opportunity.match_reasons), 5) * 0.02

        #
        # Event importance
        #

        score += min(opportunity.event.score / 100, 1.0) * 0.10

        #
        # Event recency
        #

        now = datetime.now(timezone.utc)

        published = event.published_at

        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)

        age_days = (now - published).days

        if age_days <= 1:
            score += 0.05
        elif age_days <= 7:
            score += 0.03
        elif age_days <= 30:
            score += 0.01

        return max(0.0, min(score, 1.0))
