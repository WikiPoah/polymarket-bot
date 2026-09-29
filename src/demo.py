# File-Version: 1.0.0
"""Deterministic offline demonstration of the production evaluation pipeline."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from src.filters import filter_geopolitical_markets
from src.intelligence.client import IntelligenceClient
from src.intelligence.market_classifier import MarketClassifier
from src.intelligence.pipeline import IntelligencePipeline
from src.intelligence.providers.base import IntelligenceProvider
from src.models import GeoPoliticalEvent
from src.monitoring import SystemStatusStore
from src.paper_trading.history import PaperTradingRecorder
from src.runner import EvaluationRunner
from src.strategy.engine import StrategyDecision


DEFAULT_FIXTURE_PATH = Path("data/demo_fixture.json")
DEFAULT_OUTPUT_DIR = Path("data/demo_run")
HISTORY_FILENAME = "paper_trading_history.json"
STATUS_FILENAME = "system_status.json"


@dataclass(frozen=True)
class DemoReport:
    """Inspectable outcome of one complete offline demo run."""

    markets_loaded: int
    geopolitical_candidates: int
    supported_markets: tuple[str, ...]
    unsupported_markets: tuple[str, ...]
    filtered_markets: tuple[str, ...]
    evidence_records: int
    relevant_evidence: int
    decisions: tuple[StrategyDecision, ...]
    history_path: Path
    status_path: Path


class FixtureMarketSource:
    """Supply raw market dictionaries through the runner's market-source interface."""

    def __init__(self, markets: list[dict[str, Any]]) -> None:
        self._markets = deepcopy(markets)

    def get_active_markets(self) -> list[dict]:
        return deepcopy(self._markets)


class FixtureIntelligenceProvider(IntelligenceProvider):
    """Normalize tracked provider-style records without using the network."""

    query_sensitive = False

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = deepcopy(records)

    def fetch(
        self,
        query: str | None = None,
        limit: int = 100,
        sort: str = "recent",
    ) -> list[GeoPoliticalEvent]:
        del query, sort
        return [self._normalize(record) for record in self._records[:limit]]

    @staticmethod
    def _normalize(record: dict[str, Any]) -> GeoPoliticalEvent:
        return GeoPoliticalEvent(
            title=str(record["title"]),
            summary=str(record["summary"]),
            category=str(record["category"]),
            subcategory=str(record["subcategory"]),
            country=record.get("country"),
            region=record.get("region"),
            continent=record.get("continent"),
            significance=float(record["significance"]),
            confidence=float(record["confidence"]),
            market_sensitivity=float(record["market_sensitivity"]),
            source_url=str(record["source_url"]),
            published_at=datetime.fromisoformat(str(record["published_at"])),
            source=str(record["source"]),
            provider="offline-fixture",
            publisher=str(record["publisher"]),
            event_cluster_id=str(record.get("event_cluster_id", "")),
        )


def _load_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("markets"), list) or not isinstance(
        payload.get("evidence"), list
    ):
        raise ValueError("Demo fixture must contain market and evidence lists.")
    return payload


def run_demo(
    fixture_path: str | Path = DEFAULT_FIXTURE_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> DemoReport:
    """Run the production pipeline against fixed local inputs and persist its output."""

    fixture = _load_fixture(Path(fixture_path))
    markets = fixture["markets"]
    evidence = fixture["evidence"]
    as_of = datetime.fromisoformat(str(fixture["as_of"]))

    def fixed_clock() -> datetime:
        return as_of

    output = Path(output_dir)
    history_path = output / HISTORY_FILENAME
    status_path = output / STATUS_FILENAME
    for generated_path in (history_path, status_path):
        if generated_path.exists():
            generated_path.unlink()

    decision_ids = (f"demo-decision-{index:03d}" for index in range(1, 100))
    recorder = PaperTradingRecorder(
        history_path,
        clock=fixed_clock,
        id_factory=decision_ids.__next__,
    )
    client = IntelligenceClient(
        [FixtureIntelligenceProvider(evidence)],
        evidence_time=as_of,
        clock=fixed_clock,
    )
    pipeline = IntelligencePipeline(client, paper_trader=recorder, as_of=as_of)
    runner = EvaluationRunner(
        FixtureMarketSource(markets),
        pipeline,
        SystemStatusStore(status_path),
        market_filter=filter_geopolitical_markets,
        clock=fixed_clock,
        recorder=recorder,
        duplicate_window_seconds=0,
        run_id_factory=lambda: "offline-demo-run",
    )
    result = runner.run_once()
    if not result.status.success:
        raise RuntimeError("Offline demo failed: " + "; ".join(result.status.errors))

    geopolitical = filter_geopolitical_markets(markets)
    classifications = [MarketClassifier().classify(market) for market in geopolitical]
    supported = tuple(
        classified.market["question"]
        for classified in classifications
        if classified.supported_proposition
    )
    unsupported = tuple(
        classified.market["question"]
        for classified in classifications
        if not classified.supported_proposition
    )
    geopolitical_ids = {market["id"] for market in geopolitical}
    filtered = tuple(
        market["question"] for market in markets if market["id"] not in geopolitical_ids
    )

    return DemoReport(
        markets_loaded=len(markets),
        geopolitical_candidates=len(geopolitical),
        supported_markets=supported,
        unsupported_markets=unsupported,
        filtered_markets=filtered,
        evidence_records=len(evidence),
        relevant_evidence=len(result.decisions),
        decisions=result.decisions,
        history_path=history_path,
        status_path=status_path,
    )


def _print_report(report: DemoReport) -> None:
    print("PolymarketBot — Offline Demo")
    print()
    print(f"Markets loaded: {report.markets_loaded}")
    print(f"Geopolitical candidates: {report.geopolitical_candidates}")
    print(f"Supported markets: {len(report.supported_markets)}")
    print(f"Evidence records normalized: {report.evidence_records}")
    print(f"Relevant evidence matched: {report.relevant_evidence}")

    for decision in report.decisions:
        opportunity = decision.opportunity
        print()
        print(f"Market: {opportunity.market['question']}")
        print(f"Evidence: {opportunity.event.event.title}")
        print("Match reasons:")
        for reason in opportunity.match_reasons:
            print(f"  - {reason}")
        print(f"Estimated YES probability: {decision.estimated_probability:.3f}")
        print(f"Market YES probability: {decision.market_probability:.3f}")
        print(f"Decision: {decision.action.value}")
        print(f"Stake: {decision.position_size:.3f}")
        explanation = next(
            (
                reason
                for reason in reversed(decision.reasons)
                if reason.startswith(("Accepted:", "Ignored:", "Risk rejected:"))
            ),
            decision.reasons[-1],
        )
        print(f"Reason: {explanation}")

    for question in report.unsupported_markets:
        print()
        print(f"Unsupported proposition: {question}")
    for question in report.filtered_markets:
        print(f"Filtered non-geopolitical market: {question}")

    print()
    print(f"History written to: {report.history_path}")
    print(f"Status written to: {report.status_path}")
    print("Dashboard command:")
    print(
        "  python -m src.dashboard "
        f"--history {report.history_path} --status {report.status_path}"
    )


def main() -> None:
    _print_report(run_demo())


if __name__ == "__main__":
    main()
