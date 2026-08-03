"""Read-only coverage checks for building a historical replay dataset.

This module only reads public data endpoints.  It is deliberately independent
from the evaluation runner and all trading/strategy components.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Callable

import requests

from src.config import INTELLIGENCE_USER_AGENT, REQUEST_TIMEOUT


GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
CLOB_HISTORY_URL = "https://clob.polymarket.com/prices-history"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
RELIEFWEB_REPORTS_URL = "https://api.reliefweb.int/v2/reports"

HttpGet = Callable[..., Any]


def _items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value:
        return None
    candidates = (value, value.replace("Z", "+00:00"))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass
class MarketCoverage:
    market_id: str | None
    question: str | None
    created_at: str | None
    closed_at: str | None
    resolution_outcome: str | None
    token_ids: dict[str, str]
    price_available: dict[str, bool]
    price_start: str | None
    price_end: str | None
    volume_available: bool
    liquidity_available: bool
    missing_fields: list[str] = field(default_factory=list)
    api_failures: list[str] = field(default_factory=list)


@dataclass
class PolymarketCoverageReport:
    requested_markets: int
    markets_returned: int
    markets_checked: int
    valid_historical_prices: int
    coverage_percentage: float
    earliest_price_timestamp: str | None
    markets: list[MarketCoverage]
    api_failures: list[str] = field(default_factory=list)


@dataclass
class SourceCoverage:
    available: bool
    records_returned: int
    valid_timestamps: int
    earliest_timestamp: str | None = None
    latest_timestamp: str | None = None
    limitations: list[str] = field(default_factory=list)
    api_failures: list[str] = field(default_factory=list)


@dataclass
class IntelligenceCoverageReport:
    gdelt: SourceCoverage
    reliefweb: SourceCoverage
    rss: SourceCoverage


@dataclass
class CoverageReport:
    generated_at: str
    period_start: str
    period_end: str
    polymarket: PolymarketCoverageReport
    intelligence: IntelligenceCoverageReport
    six_month_backtest_feasible: bool
    limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HistoricalCoverageProbe:
    """Inspect public historical data without mutating application state."""

    def __init__(self, http_get: HttpGet = requests.get, timeout: float = REQUEST_TIMEOUT):
        self.http_get = http_get
        self.timeout = timeout
        self.headers = {"User-Agent": INTELLIGENCE_USER_AGENT}

    def run(
        self,
        sample_size: int = 25,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> CoverageReport:
        if not 20 <= sample_size <= 50:
            raise ValueError("sample_size must be between 20 and 50")
        end = (end or datetime.now(timezone.utc)).astimezone(timezone.utc)
        start = (start or end - timedelta(days=183)).astimezone(timezone.utc)
        if start >= end:
            raise ValueError("start must be earlier than end")

        markets = self.probe_polymarket(sample_size)
        intelligence = self.probe_intelligence(start, end)
        feasible = markets.valid_historical_prices > 0 and (
            intelligence.gdelt.available or intelligence.reliefweb.available
        )
        limitations = [
            "Polymarket does not provide documented historical order-book depth or spread snapshots.",
            "Gamma volume and liquidity values are aggregates, not point-in-time histories.",
            "RSS feeds expose a rolling current window and cannot reconstruct six months retrospectively.",
            "Publication timestamps may approximate first availability for retrospectively retrieved intelligence.",
        ]
        return CoverageReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            period_start=start.isoformat(), period_end=end.isoformat(),
            polymarket=markets, intelligence=intelligence,
            six_month_backtest_feasible=feasible, limitations=limitations,
        )

    def probe_polymarket(self, sample_size: int = 25) -> PolymarketCoverageReport:
        if not 20 <= sample_size <= 50:
            raise ValueError("sample_size must be between 20 and 50")
        failures: list[str] = []
        try:
            response = self.http_get(
                GAMMA_MARKETS_URL,
                params={
                    "closed": "true", "limit": sample_size, "offset": 0,
                    "order": "closedTime", "ascending": "false",
                },
                headers=self.headers, timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            raw_markets = payload if isinstance(payload, list) else []
            if not isinstance(payload, list):
                failures.append("Gamma markets response was not a list")
        except (requests.RequestException, ValueError, TypeError) as error:
            failures.append(f"Gamma markets request failed: {error}")
            raw_markets = []

        markets = [self._probe_market(item) for item in raw_markets[:sample_size] if isinstance(item, dict)]
        valid = sum(
            len(item.token_ids) >= 2
            and all(item.price_available.get(outcome, False) for outcome in item.token_ids)
            for item in markets
        )
        starts = [_timestamp(item.price_start) for item in markets]
        starts = [item for item in starts if item is not None]
        return PolymarketCoverageReport(
            requested_markets=sample_size, markets_returned=len(raw_markets),
            markets_checked=len(markets), valid_historical_prices=valid,
            coverage_percentage=round(valid / len(markets) * 100, 2) if markets else 0.0,
            earliest_price_timestamp=_iso(min(starts)) if starts else None,
            markets=markets, api_failures=failures,
        )

    def _probe_market(self, market: dict[str, Any]) -> MarketCoverage:
        market_id = market.get("id") or market.get("conditionId")
        question = market.get("question")
        created = market.get("createdAt") or market.get("creationDate")
        closed = market.get("closedTime") or market.get("endDate")
        outcomes = [str(item) for item in _items(market.get("outcomes"))]
        token_values = [str(item) for item in _items(market.get("clobTokenIds"))]
        tokens = {
            outcome.upper(): token_values[index]
            for index, outcome in enumerate(outcomes)
            if index < len(token_values)
        }
        missing = []
        for name, value in (
            ("market_id", market_id), ("question", question),
            ("creation_timestamp", created), ("closing_timestamp", closed),
        ):
            if not value:
                missing.append(name)
        if not outcomes:
            missing.append("outcomes")
        for outcome in outcomes:
            if outcome.upper() not in tokens:
                missing.append(f"{outcome.lower()}_token_id")

        availability = {outcome.upper(): False for outcome in outcomes}
        times: list[datetime] = []
        api_failures: list[str] = []
        for outcome, token in tokens.items():
            if not self._valid_token_id(token):
                missing.append(f"{outcome.lower()}_invalid_token_id")
                continue
            try:
                params: dict[str, Any] = {"market": token, "fidelity": 60}
                created_time = _timestamp(created)
                closed_time = _timestamp(closed)
                if created_time is not None and closed_time is not None:
                    params.update({
                        "startTs": int(created_time.timestamp()),
                        "endTs": int((closed_time + timedelta(days=1)).timestamp()),
                    })
                else:
                    params["interval"] = "max"
                response = self.http_get(
                    CLOB_HISTORY_URL,
                    params=params,
                    headers=self.headers, timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                history = payload.get("history", []) if isinstance(payload, dict) else []
                points = [
                    _timestamp(point.get("t")) for point in history
                    if isinstance(point, dict) and point.get("p") is not None
                ]
                points = [point for point in points if point is not None]
                availability[outcome] = bool(points)
                times.extend(points)
                if not points:
                    missing.append(f"{outcome.lower()}_price_history")
            except (requests.RequestException, ValueError, TypeError) as error:
                api_failures.append(f"{outcome} price history failed: {error}")

        resolution = self._resolution(outcomes, _items(market.get("outcomePrices")))
        if resolution is None:
            missing.append("resolution_outcome")
        return MarketCoverage(
            market_id=str(market_id) if market_id is not None else None,
            question=str(question) if question is not None else None,
            created_at=str(created) if created is not None else None,
            closed_at=str(closed) if closed is not None else None,
            resolution_outcome=resolution, token_ids=tokens,
            price_available=availability,
            price_start=_iso(min(times)) if times else None,
            price_end=_iso(max(times)) if times else None,
            volume_available=market.get("volume") is not None,
            liquidity_available=market.get("liquidity") is not None,
            missing_fields=missing, api_failures=api_failures,
        )

    @staticmethod
    def _valid_token_id(value: str) -> bool:
        """CLOB asset IDs supplied by Gamma are positive decimal uint256s."""
        return value.isascii() and value.isdecimal() and int(value) > 0

    @staticmethod
    def _resolution(outcomes: list[str], prices: list[Any]) -> str | None:
        parsed: list[float] = []
        try:
            parsed = [float(value) for value in prices]
        except (TypeError, ValueError):
            return None
        if len(parsed) != len(outcomes) or not parsed:
            return None
        winner = max(range(len(parsed)), key=parsed.__getitem__)
        return outcomes[winner] if parsed[winner] >= 0.99 else None

    def probe_intelligence(self, start: datetime, end: datetime) -> IntelligenceCoverageReport:
        return IntelligenceCoverageReport(
            gdelt=self._probe_gdelt(start, end),
            reliefweb=self._probe_reliefweb(start, end),
            rss=SourceCoverage(
                available=True, records_returned=0, valid_timestamps=0,
                limitations=[
                    "Configured RSS feeds provide current rolling entries only.",
                    "They do not offer a queryable six-month historical archive.",
                    "Exact historical first-seen times require prospective local archiving.",
                ],
            ),
        )

    def _probe_gdelt(self, start: datetime, end: datetime) -> SourceCoverage:
        # Use a short window inside the requested period because the DOC API has
        # bounded query windows; a full collector should partition the period.
        window_end = min(end, start + timedelta(days=7))
        params = {
            "query": "geopolitics", "mode": "ArtList", "format": "json",
            "maxrecords": 10,
            "startdatetime": start.strftime("%Y%m%d%H%M%S"),
            "enddatetime": window_end.strftime("%Y%m%d%H%M%S"),
        }
        return self._probe_source(
            GDELT_DOC_URL, params,
            lambda payload: payload.get("articles", []) if isinstance(payload, dict) else [],
            lambda item: item.get("seendate") if isinstance(item, dict) else None,
            ["A full six-month retrieval must be split into bounded date windows."],
        )

    def _probe_reliefweb(self, start: datetime, end: datetime) -> SourceCoverage:
        params = {
            "appname": "polymarket-bot", "limit": 10,
            "sort[]": "date.created:asc",
            "filter[field]": "date.created",
            "filter[value][from]": start.isoformat(),
            "filter[value][to]": end.isoformat(),
            "fields[include][]": ["title", "date.created", "url"],
        }
        return self._probe_source(
            RELIEFWEB_REPORTS_URL, params,
            lambda payload: payload.get("data", []) if isinstance(payload, dict) else [],
            lambda item: item.get("fields", {}).get("date", {}).get("created")
            if isinstance(item, dict) else None,
            ["ReliefWeb is humanitarian-focused and is not comprehensive political news coverage."],
        )

    def _probe_source(
        self, url: str, params: dict[str, Any], records: Callable[[Any], list[Any]],
        date_value: Callable[[Any], Any], limitations: list[str],
    ) -> SourceCoverage:
        try:
            response = self.http_get(
                url, params=params, headers=self.headers, timeout=self.timeout,
            )
            response.raise_for_status()
            items = records(response.json())
            if not isinstance(items, list):
                items = []
            times = [_timestamp(date_value(item)) for item in items]
            times = [item for item in times if item is not None]
            return SourceCoverage(
                available=bool(items and times), records_returned=len(items),
                valid_timestamps=len(times), earliest_timestamp=_iso(min(times)) if times else None,
                latest_timestamp=_iso(max(times)) if times else None,
                limitations=limitations,
            )
        except (requests.RequestException, ValueError, TypeError) as error:
            return SourceCoverage(
                available=False, records_returned=0, valid_timestamps=0,
                limitations=limitations, api_failures=[str(error)],
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe public historical data coverage")
    parser.add_argument("--sample-size", type=int, default=25, choices=range(20, 51))
    parser.add_argument("--start", help="ISO-8601 period start; defaults to six months ago")
    parser.add_argument("--end", help="ISO-8601 period end; defaults to now")
    args = parser.parse_args()
    start = _timestamp(args.start) if args.start else None
    end = _timestamp(args.end) if args.end else None
    if args.start and start is None or args.end and end is None:
        parser.error("--start and --end must be valid ISO-8601 timestamps")
    report = HistoricalCoverageProbe().run(args.sample_size, start, end)
    print(json.dumps(report.to_dict(), indent=2))


if __name__ == "__main__":
    main()
