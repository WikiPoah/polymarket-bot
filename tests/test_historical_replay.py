# File-Version: 1.1.0
"""Tests for timestamped market collection and true historical replay."""

import json

import pytest

from src.paper_trading.historical import (
    HistoricalIntelligenceRecord,
    HistoricalIntelligenceStore,
    HistoricalIntelligenceProvider,
    HistoricalMarketSnapshot,
    HistoricalMarketStore,
    HistoricalReplayEngine,
)
from src.persistence import PersistenceCorruptionError


def intelligence(**changes):
    values = dict(
        title="Xi Jinping resigns after leadership challenge",
        summary="China begins a leadership transition.",
        source="BBC World",
        source_url="https://example.test/xi-resigns",
        published_at="2026-01-01T08:00:00+00:00",
        available_at="2026-01-01T09:00:00+00:00",
        category="POLITICAL",
        country="China",
        significance=.9,
        confidence=.9,
        market_sensitivity=.9,
    )
    values.update(changes)
    return HistoricalIntelligenceRecord(**values)


def snapshot(**changes):
    values = dict(
        market_id="xi-2027",
        question="Xi Jinping out before 2027?",
        observed_at="2026-01-01T12:00:00+00:00",
        yes_price=.4,
        resolved_yes=True,
        resolved_at="2026-01-03T00:00:00+00:00",
        liquidity=10000.0,
        volume=50000.0,
        category="LEADERSHIP",
    )
    values.update(changes)
    return HistoricalMarketSnapshot(**values)


def test_historical_market_store_rejects_invalid_records(tmp_path):
    path = tmp_path / "markets.json"
    path.write_text(json.dumps({
        "version": 1,
        "records": [
            snapshot().__dict__,
            {"market_id": "bad", "question": "", "observed_at": "invalid", "yes_price": 2},
        ],
    }), encoding="utf-8")
    store = HistoricalMarketStore(path)

    with pytest.raises(PersistenceCorruptionError, match="record 1 is invalid"):
        store.load()

    assert store.invalid_records == 1


def test_historical_market_capture_preserves_malformed_state(tmp_path):
    from datetime import datetime, timezone

    path = tmp_path / "markets.json"
    original = b'{"records": [broken'
    path.write_bytes(original)
    store = HistoricalMarketStore(path)

    with pytest.raises(PersistenceCorruptionError, match="historical market file"):
        store.capture_market({
            "id": "market-1", "question": "Will an event happen?",
            "outcomes": '["Yes", "No"]', "outcomePrices": '["0.35", "0.65"]',
        }, datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert path.read_bytes() == original


def test_historical_intelligence_capture_preserves_malformed_state(tmp_path):
    path = tmp_path / "intelligence.json"
    original = b'{"records": [broken'
    path.write_bytes(original)
    store = HistoricalIntelligenceStore(path)

    with pytest.raises(PersistenceCorruptionError, match="historical intelligence file"):
        store.capture_events([intelligence().to_event()])

    assert path.read_bytes() == original


def test_market_capture_persists_price_and_market_metadata(tmp_path):
    store = HistoricalMarketStore(tmp_path / "markets.json")
    from datetime import datetime, timezone
    store.capture_market({
        "id": "market-1", "question": "Will an event happen?",
        "outcomes": '["Yes", "No"]', "outcomePrices": '["0.35", "0.65"]',
        "liquidity": "2500", "volume": "9000", "category": "MILITARY",
    }, datetime(2026, 1, 1, tzinfo=timezone.utc))

    loaded = store.load()
    assert loaded[0].yes_price == .35
    assert loaded[0].liquidity == 2500.0
    assert loaded[0].volume == 9000.0


def test_historical_provider_excludes_future_information():
    from datetime import datetime, timezone
    records = [
        intelligence(),
        intelligence(
            title="Future report", source_url="future",
            available_at="2026-01-02T00:00:00+00:00",
        ),
    ]
    provider = HistoricalIntelligenceProvider(
        records, datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
    )

    events = provider.fetch()

    assert [event.title for event in events] == [records[0].title]


def test_replay_is_chronological_and_does_not_settle_early():
    engine = HistoricalReplayEngine([intelligence()])
    states = []

    def factory(as_of, recorder):
        states.append([item.result for item in recorder.load()])
        return engine._pipeline(as_of, recorder)

    engine.pipeline_factory = factory
    report = engine.replay([
        snapshot(
            market_id="later", observed_at="2026-01-02T00:00:00+00:00",
            resolved_at="2026-01-04T00:00:00+00:00",
        ),
        snapshot(market_id="earlier"),
    ])

    assert report.markets_analyzed == 2
    assert report.opportunities_found == 2
    assert states[0] == []
    assert states[1] == [None]
    assert [item.market["id"] for item in report.decisions] == ["earlier", "later"]


def test_replay_resolves_outcomes_and_calculates_performance():
    report = HistoricalReplayEngine([intelligence()]).replay([
        snapshot(),
        snapshot(
            market_id="xi-loss", observed_at="2026-01-02T00:00:00+00:00",
            resolved_yes=False, resolved_at="2026-01-04T00:00:00+00:00",
        ),
    ])

    summary = report.analytics.summary
    assert report.simulated_trades == 2
    assert summary.wins == 1
    assert summary.losses == 1
    assert summary.win_rate == .5
    assert summary.profit_loss == pytest.approx(.05)
    assert report.roi == pytest.approx(.25)
    assert report.maximum_drawdown == pytest.approx(.1)
    assert summary.average_edge > 0
    assert report.analytics.calibration
    assert report.performance_by_market_category["LEADERSHIP"].executed_trades == 2


def test_replay_empty_dataset_and_already_resolved_snapshot():
    engine = HistoricalReplayEngine([intelligence()])
    empty = engine.replay([])
    invalid = engine.replay([snapshot(resolved_at="2025-12-31T00:00:00+00:00")])

    assert empty.markets_analyzed == 0
    assert empty.simulated_trades == 0
    assert empty.roi == 0.0
    assert invalid.markets_analyzed == 0
    assert invalid.invalid_records == 1
