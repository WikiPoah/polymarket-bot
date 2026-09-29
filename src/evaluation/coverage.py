# File-Version: 1.2.0
"""Audit frozen-universe alignment and historical YES-price coverage."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path

from src.coverage_probe import _timestamp
from src.historical_dataset import (
    HistoricalMarketDatasetStore,
    HistoricalMarketMetadata,
    HistoricalMarketRecord,
    HistoricalMarketUniverseStore,
)


@dataclass(frozen=True)
class MarketCoverage:
    market_id: str
    condition_id: str | None
    question: str
    included: bool
    reason: str | None
    observation_count: int
    earliest_price_at: str | None
    latest_price_at: str | None
    lifetime_coverage: float
    largest_gap_seconds: float | None
    outcomes: tuple[str, ...]
    yes_token_id: str | None


@dataclass(frozen=True)
class CoverageReport:
    selected_markets: int
    collected_markets: int
    aligned_markets: int
    markets_with_any_usable_history: int
    markets_with_sufficient_history: int
    markets_with_no_history: int
    usable_history_percentage: float
    sufficient_history_percentage: float
    excluded_counts_by_reason: dict[str, int]
    unselected_collected_markets: int
    records: tuple[MarketCoverage, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def audit_price_coverage(
    selected: list[HistoricalMarketMetadata],
    collected: list[HistoricalMarketRecord],
    *,
    minimum_observations: int = 2,
    minimum_lifetime_coverage: float = 0.1,
) -> CoverageReport:
    """Return an auditable reason for every market in the frozen universe."""
    by_id = {market.market_id: market for market in collected}
    rows: list[MarketCoverage] = []
    reasons: Counter[str] = Counter()
    any_history = sufficient = 0

    for frozen in sorted(selected, key=lambda item: item.market_id):
        market = by_id.get(frozen.market_id)
        reason: str | None = None
        candles = ()
        normalized_outcomes = {item.strip().upper() for item in frozen.outcomes}
        if market is None:
            reason = "missing_collected_market"
        elif market.condition_id != frozen.condition_id:
            reason = "condition_id_mismatch"
        elif normalized_outcomes != {"YES", "NO"}:
            reason = "non_binary_yes_no_contract"
        elif "YES" not in market.token_ids:
            reason = "missing_yes_token"
        else:
            candles = market.price_history.get("YES", ())
            if not candles:
                reason = "missing_yes_price_history"

        created = _timestamp(market.created_at) if market else None
        closed = _timestamp(market.closed_at) if market else None
        timestamps = sorted(
            timestamp for candle in candles
            if (timestamp := _timestamp(candle.timestamp)) is not None
            and (created is None or timestamp >= created)
            and (closed is None or timestamp < closed)
        )
        if candles and not timestamps and reason is None:
            reason = "no_prices_during_market_lifetime"

        count = len(timestamps)
        if count:
            any_history += 1
        lifetime = (closed - created).total_seconds() if created and closed else 0.0
        covered = (timestamps[-1] - timestamps[0]).total_seconds() if count > 1 else 0.0
        coverage = min(1.0, max(0.0, covered / lifetime)) if lifetime > 0 else 0.0
        gaps = [
            (right - left).total_seconds()
            for left, right in zip(timestamps, timestamps[1:])
        ]
        if reason is None and count < minimum_observations:
            reason = "sparse_yes_price_history"
        elif reason is None and coverage < minimum_lifetime_coverage:
            reason = "insufficient_lifetime_coverage"
        if reason is None:
            sufficient += 1
        else:
            reasons[reason] += 1

        rows.append(MarketCoverage(
            market_id=frozen.market_id,
            condition_id=frozen.condition_id,
            question=frozen.question,
            included=reason is None,
            reason=reason,
            observation_count=count,
            earliest_price_at=_iso(timestamps[0]) if timestamps else None,
            latest_price_at=_iso(timestamps[-1]) if timestamps else None,
            lifetime_coverage=coverage,
            largest_gap_seconds=max(gaps) if gaps else None,
            outcomes=frozen.outcomes,
            yes_token_id=market.token_ids.get("YES") if market else None,
        ))

    selected_ids = {item.market_id for item in selected}
    return CoverageReport(
        selected_markets=len(selected),
        collected_markets=len(collected),
        aligned_markets=sum(item.market_id in by_id for item in selected),
        markets_with_any_usable_history=any_history,
        markets_with_sufficient_history=sufficient,
        markets_with_no_history=len(selected) - any_history,
        usable_history_percentage=(any_history / len(selected) * 100 if selected else 0.0),
        sufficient_history_percentage=(
            sufficient / len(selected) * 100 if selected else 0.0
        ),
        excluded_counts_by_reason=dict(sorted(reasons.items())),
        unselected_collected_markets=sum(item.market_id not in selected_ids for item in collected),
        records=tuple(rows),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", default="data/historical_dataset")
    parser.add_argument("--universe")
    parser.add_argument("--output")
    parser.add_argument("--minimum-observations", type=int, default=2)
    parser.add_argument("--minimum-lifetime-coverage", type=float, default=0.1)
    args = parser.parse_args()
    dataset = Path(args.dataset_dir)
    universe_path = Path(args.universe) if args.universe else dataset / "selected_markets.json"
    report = audit_price_coverage(
        HistoricalMarketUniverseStore(universe_path).load(),
        HistoricalMarketDatasetStore(dataset / "markets.json").load(),
        minimum_observations=args.minimum_observations,
        minimum_lifetime_coverage=args.minimum_lifetime_coverage,
    )
    payload = report.to_dict()
    output = Path(args.output) if args.output else dataset / "price_coverage_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(json.dumps({"version": 1, **payload}, indent=2), encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({key: value for key, value in payload.items() if key != "records"}, indent=2))


if __name__ == "__main__":
    main()
