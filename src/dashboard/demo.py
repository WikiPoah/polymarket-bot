"""Generate local demo history for dashboard testing."""

import argparse
from pathlib import Path

from src.paper_trading.history import PaperTradingRecorder
from src.paper_trading.models import PaperDecision


def demo_decisions() -> list[PaperDecision]:
    """Return representative settled and open paper decisions."""

    common = dict(
        timestamp="2026-01-01T00:00:00+00:00",
        market={"question": "Xi Jinping out before 2027?"},
        market_probability=.40,
        estimated_probability=.72,
        edge=.32,
        confidence=.82,
        position_size=.08,
        evidence_confidence=.90,
        evidence_count=2,
        supporting_sources=["BBC", "GDELT"],
        event_title="Chinese leadership succession discussed",
        event_source="BBC",
        event_url="https://example.test/demo",
        event_type="LEADERSHIP",
        risk_status="ACCEPTED",
        risk_reason="",
    )
    return [
        PaperDecision(
            id="demo-win", decision="BUY YES", result="WIN",
            resolved_yes=True, profit_loss=.048, **common,
        ),
        PaperDecision(
            id="demo-loss", decision="BUY NO", result="LOSS",
            resolved_yes=True, profit_loss=-.032, **common,
        ),
        PaperDecision(
            id="demo-open", decision="BUY YES", result=None,
            resolved_yes=None, profit_loss=0.0, **common,
        ),
    ]


def create_demo_history(path: str | Path = "data/demo_paper_trading_history.json") -> Path:
    """Write demo records to a separate history file and return its path."""

    output = Path(path)
    PaperTradingRecorder(output).save(demo_decisions())
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate dashboard demo history")
    parser.add_argument(
        "--output",
        default="data/demo_paper_trading_history.json",
        help="Output JSON history path",
    )
    args = parser.parse_args()
    print(f"Wrote demo history to {create_demo_history(args.output)}")


if __name__ == "__main__":
    main()
