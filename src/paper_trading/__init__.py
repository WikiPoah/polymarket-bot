"""Paper-trading records and performance evaluation."""

from src.paper_trading.history import PaperTradingRecorder
from src.paper_trading.models import PaperDecision
from src.paper_trading.performance import PerformanceMetrics, PerformanceTracker
from src.paper_trading.analytics import (
    AnalyticsReport,
    AnalyticsSummary,
    CalibrationBucket,
    PerformanceAnalytics,
    format_report,
)
from src.paper_trading.backtesting import BacktestConfig, BacktestEngine, BacktestReport
from src.paper_trading.historical import (
    HistoricalBacktestReport,
    HistoricalIntelligenceRecord,
    HistoricalIntelligenceStore,
    HistoricalMarketSnapshot,
    HistoricalMarketStore,
    HistoricalReplayEngine,
)

__all__ = [
    "PaperDecision",
    "PaperTradingRecorder",
    "PerformanceMetrics",
    "PerformanceTracker",
    "AnalyticsReport",
    "AnalyticsSummary",
    "CalibrationBucket",
    "PerformanceAnalytics",
    "format_report",
    "BacktestConfig",
    "BacktestEngine",
    "BacktestReport",
    "HistoricalBacktestReport",
    "HistoricalIntelligenceRecord",
    "HistoricalIntelligenceStore",
    "HistoricalMarketSnapshot",
    "HistoricalMarketStore",
    "HistoricalReplayEngine",
]
