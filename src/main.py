"""Application entry point for one-shot or continuous paper evaluation."""

import argparse

from src.api import PolymarketAPI
from src.filters import filter_geopolitical_markets
from src.intelligence.client import IntelligenceClient
from src.intelligence.pipeline import IntelligencePipeline
from src.intelligence.providers.gdelt import GDELTProvider
from src.intelligence.providers.rss import RSSProvider
from src.paper_trading.history import PaperTradingRecorder
from src.monitoring import SystemStatusStore
from src.runner import EvaluationResult, EvaluationRunner


def _build_runner(history: str, status: str) -> EvaluationRunner:
    recorder = PaperTradingRecorder(history)
    intelligence_client = IntelligenceClient(
        [
            GDELTProvider(),
            RSSProvider(),
        ]
    )

    pipeline = IntelligencePipeline(
        intelligence_client,
        paper_trader=recorder,
    )
    return EvaluationRunner(
        market_source=PolymarketAPI(),
        pipeline=pipeline,
        status_store=SystemStatusStore(status),
        market_filter=filter_geopolitical_markets,
    )


def _print_result(result: EvaluationResult) -> None:
    status = result.status
    if not status.success:
        print("Evaluation failed:")
        for error in status.errors:
            print(f"  - {error}")
        return

    print(f"Analysed {status.markets_analyzed} geopolitical markets.")
    print(f"Generated {status.decisions_generated} trading decisions.")
    if status.errors:
        print("Provider warnings:")
        for error in status.errors:
            print(f"  - {error}")
    if not result.decisions:
        print("No trading opportunities found.")
        return

    print("=" * 100)

    for decision in result.decisions:

        opportunity = decision.opportunity

        print(
            f"Action: {decision.action.value}"
        )

        print(
            f"Estimated Probability: {decision.estimated_probability:.1%}"
        )

        print(
            f"Market Probability: {decision.market_probability:.1%}"
        )

        print(
            f"Edge: {decision.edge:+.1%}"
        )

        print(
            f"Expected Value: {decision.expected_value:.3f}"
        )

        print(
            f"Position Size: {decision.position_size:.1%}"
        )

        print(
            f"Confidence: {decision.confidence:.0%}"
        )

        print()

        print(
            f"Event Score: {opportunity.event.score}"
        )

        print(
            f"Match Score: {opportunity.match_score}"
        )

        print()

        print(
            f"Country: {opportunity.event.event.country}"
        )

        print(
            f"Category: {opportunity.event.event.category}"
        )

        print()

        print("Event:")
        print(
            f"  {opportunity.event.event.title}"
        )

        print()

        print("Matched Market:")
        print(
            f"  {opportunity.market.get('question')}"
        )

        if decision.reasons:

            print()

            print("Strategy:")

            for reason in decision.reasons:
                print(f"  - {reason}")

        if opportunity.match_reasons:

            print()

            print("Matching:")

            for reason in opportunity.match_reasons:
                print(f"  - {reason}")

        print("=" * 100)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run paper-trading evaluation")
    parser.add_argument(
        "--interval",
        type=float,
        help="Continuously evaluate at this interval in seconds",
    )
    parser.add_argument("--history", default="data/paper_trading_history.json")
    parser.add_argument("--status", default="data/system_status.json")
    args = parser.parse_args()

    runner = _build_runner(args.history, args.status)
    if args.interval is None:
        print("Running Polymarket evaluation...\n")
        _print_result(runner.run_once())
        return

    print(f"Running continuously every {args.interval:g} seconds. Press Ctrl+C to stop.")
    try:
        runner.run_forever(args.interval, on_result=_print_result)
    except KeyboardInterrupt:
        print("Evaluation runner stopped.")


if __name__ == "__main__":
    main()
