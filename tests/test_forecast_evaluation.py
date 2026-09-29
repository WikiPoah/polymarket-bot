# File-Version: 1.11.0
"""Tests for leakage-safe forecast observations and market-baseline evaluation."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from src.evaluation.metrics import ForecastEvaluator
from src.evaluation.__main__ import _load_sufficient_price_coverage
from src.evaluation.intelligence_merge import merge_intelligence_records
from src.evaluation.clustering import CausalEventClusterer
from src.evaluation.coverage import audit_price_coverage
from src.evaluation.composition import analyze_composition
from src.evaluation.models import ForecastObservation
from src.evaluation.readiness import assess_benchmark_readiness
from src.evaluation.observations import ForecastObservationGenerator
from src.evaluation.split import (
    chronological_cluster_split,
    optimized_chronological_cluster_split,
)
from src.paper_trading.historical import (
    HistoricalIntelligenceRecord,
    HistoricalMarketSnapshot,
)
from src.historical_dataset import (
    HistoricalIntelligenceItem,
    HistoricalMarketMetadata,
    HistoricalMarketRecord,
    PriceCandle,
)


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def intelligence(**changes):
    values = dict(
        title="Xi Jinping resigns after leadership challenge",
        summary="China begins a leadership transition.",
        source="BBC World",
        source_url="https://example.test/xi-resigns",
        published_at=(START + timedelta(hours=8)).isoformat(),
        available_at=(START + timedelta(hours=9)).isoformat(),
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
        observed_at=(START + timedelta(hours=10)).isoformat(),
        yes_price=.4,
        resolved_yes=True,
        resolved_at=(START + timedelta(days=2)).isoformat(),
        liquidity=1000.0,
        volume=5000.0,
        category="LEADERSHIP",
    )
    values.update(changes)
    return HistoricalMarketSnapshot(**values)


def observation(**changes):
    values = dict(
        observation_id="observation",
        market_id="market",
        event_cluster_id="cluster",
        evidence_state_id="evidence",
        forecast_timestamp=START.isoformat(),
        evidence_available_at=START.isoformat(),
        evidence_published_at=START.isoformat(),
        market_probability=.6,
        bot_probability=.8,
        resolved_yes=True,
        resolved_at=(START + timedelta(days=30)).isoformat(),
        evaluation_time_to_resolution_seconds=30 * 86400,
        category="LEADERSHIP",
        event_type="LEADERSHIP",
        expected_outcome="LEADER_REMOVED",
        match_score=100,
        event_score=90,
        relevance_confidence=1.0,
        evidence_confidence=.8,
        evidence_recency_seconds=0.0,
        source="BBC World",
        supporting_sources=("BBC World",),
        independent_confirmation_count=1,
        independently_confirmed=False,
        liquidity=1000.0,
        volume=5000.0,
        is_new_evidence=True,
        event_title="Event",
        event_url="https://example.test/event",
        match_reasons=("Actor",),
        provenance={"strategy_confidence": .8},
    )
    values.update(changes)
    return ForecastObservation(**values)


def test_generator_excludes_future_evidence_and_uses_available_at():
    records = [
        intelligence(),
        intelligence(
            title="Future confirmation",
            source="GDELT",
            source_url="https://example.test/future",
            available_at=(START + timedelta(hours=11)).isoformat(),
        ),
    ]

    observations = ForecastObservationGenerator().generate([snapshot()], records)

    assert len(observations) == 1
    assert observations[0].source == "BBC World"
    assert observations[0].evidence_available_at == (START + timedelta(hours=9)).isoformat()
    assert observations[0].evidence_recency_seconds == 3600


def test_generator_deduplicates_evidence_state_and_emits_new_confirmation():
    matching_confirmation = intelligence(
        title="Xi Jinping may resign as political leadership challenge grows",
        source="GDELT",
        publisher="reuters.com",
        available_at=(START + timedelta(hours=12)).isoformat(),
    )
    snapshots = [
        snapshot(),
        snapshot(observed_at=(START + timedelta(hours=13)).isoformat(), yes_price=.45),
        snapshot(observed_at=(START + timedelta(hours=14)).isoformat(), yes_price=.5),
    ]

    first = ForecastObservationGenerator().generate(
        snapshots, [intelligence(publisher="bbc.com"), matching_confirmation],
        {"xi-2027": "leadership-cluster"},
    )
    second = ForecastObservationGenerator().generate(
        snapshots, [intelligence(publisher="bbc.com"), matching_confirmation],
        {"xi-2027": "leadership-cluster"},
    )

    assert first == second
    assert len(first) == 2
    assert first[0].market_probability == .4
    assert first[1].market_probability == .45
    assert first[1].independently_confirmed is True
    assert first[1].independent_confirmation_count == 2
    assert all(item.event_cluster_id == "leadership-cluster" for item in first)
    assert len({item.observation_id for item in first}) == 2


def test_causal_clustering_merges_related_titles_and_counts_publishers():
    records = [
        intelligence(
            title="Russia launches missile strike against Ukraine",
            source="GDELT", provider="GDELT", publisher="reuters.com", record_id="one",
        ),
        intelligence(
            title="Russia launches missile strikes on Ukraine",
            source="RSS", provider="RSS", publisher="reuters.com", record_id="two",
            available_at=(START + timedelta(hours=10)).isoformat(),
        ),
        intelligence(
            title="Russia missile strike hits Ukraine",
            source="GDELT", provider="GDELT", publisher="bbc.com", record_id="three",
            available_at=(START + timedelta(hours=11)).isoformat(),
        ),
    ]

    assignments = CausalEventClusterer(minimum_title_similarity=.3).cluster(records)

    assert len({item.event_cluster_id for item in assignments}) == 1
    assert [item.independent_confirmation_count for item in assignments] == [1, 1, 1]
    assert len({item.confirmation_group_id for item in assignments}) == 1
    assert assignments[0].event_cluster_id == CausalEventClusterer(
        minimum_title_similarity=.3,
    ).cluster(records)[0].event_cluster_id


def test_causal_clustering_does_not_use_future_confirmation():
    records = [
        intelligence(provider="GDELT", publisher="reuters.com", record_id="one"),
        intelligence(
            provider="RSS", publisher="bbc.com", record_id="two",
            available_at=(START + timedelta(hours=12)).isoformat(),
        ),
    ]

    assignments = CausalEventClusterer(minimum_title_similarity=.1).cluster(records)

    assert assignments[0].independent_confirmation_count == 1
    assert assignments[1].independent_confirmation_count == 1


def test_distinct_reporting_can_add_causal_confirmation():
    records = [
        intelligence(
            title="Xi Jinping resigns after leadership challenge",
            provider="GDELT", publisher="reuters.com", record_id="one",
        ),
        intelligence(
            title="Leadership succession talks begin as Jinping prepares to leave office",
            provider="Media Cloud", publisher="bbc.com", record_id="two",
            available_at=(START + timedelta(hours=12)).isoformat(),
        ),
    ]

    assignments = CausalEventClusterer(minimum_title_similarity=.1).cluster(records)

    assert len({item.event_cluster_id for item in assignments}) == 1
    assert assignments[0].independent_confirmation_count == 1
    assert assignments[1].independent_confirmation_count == 2


def test_intelligence_merge_marks_cross_provider_story_without_dropping_provenance():
    records = [[HistoricalIntelligenceItem(
        record_id="gdelt", title="Shared story", source="GDELT",
        source_url="https://www.reuters.com/world/story?tracking=1",
        published_at=START.isoformat(), available_at=START.isoformat(),
        source_domain="reuters.com",
    )], [HistoricalIntelligenceItem(
        record_id="media-cloud", title="Shared story", source="Media Cloud",
        source_url="https://reuters.com/world/story?other=2",
        published_at=START.isoformat(), available_at=START.isoformat(),
        source_domain="reuters.com",
    )]]

    merged, report = merge_intelligence_records(records)

    assert len(merged) == 2
    assert {item.source for item in merged} == {"GDELT", "Media Cloud"}
    assert report.cross_provider_duplicate_groups == 1
    assert report.cross_provider_duplicate_records == 2
    assert len({item.metadata["normalized_story_identity"] for item in merged}) == 1


def test_price_coverage_reports_alignment_history_and_exclusion_reason():
    frozen = [HistoricalMarketMetadata(
        market_id="market", condition_id="condition", question="Will it happen?",
        created_at=START.isoformat(),
        scheduled_end_at=(START + timedelta(days=10)).isoformat(),
        actual_close_at=(START + timedelta(days=10)).isoformat(),
        resolution_status="resolved", category="DIPLOMATIC", outcomes=("Yes", "No"),
        token_ids=("yes-token", "no-token"), outcome_prices=("1", "0"),
    )]
    collected = [HistoricalMarketRecord(
        market_id="market", condition_id="condition", question="Will it happen?",
        created_at=START.isoformat(), closed_at=(START + timedelta(days=10)).isoformat(),
        outcomes=("Yes", "No"), token_ids={"YES": "yes-token", "NO": "no-token"},
        resolution_outcome="YES", price_history={
            "YES": (
                PriceCandle((START + timedelta(days=1)).isoformat(), .4),
                PriceCandle((START + timedelta(days=9)).isoformat(), .8),
            ),
            "NO": (),
        },
    )]

    report = audit_price_coverage(frozen, collected)

    assert report.aligned_markets == 1
    assert report.markets_with_sufficient_history == 1
    assert report.usable_history_percentage == 100.0
    assert report.sufficient_history_percentage == 100.0
    assert report.records[0].observation_count == 2
    assert report.records[0].lifetime_coverage == pytest.approx(.8)

    sparse = audit_price_coverage(frozen, [replace(
        collected[0],
        price_history={"YES": (collected[0].price_history["YES"][0],), "NO": ()},
    )])
    assert sparse.usable_history_percentage == 100.0
    assert sparse.sufficient_history_percentage == 0.0

    missing = audit_price_coverage(frozen, [])
    assert missing.excluded_counts_by_reason == {"missing_collected_market": 1}


def test_readiness_coverage_uses_only_histories_that_pass_quality_thresholds(tmp_path):
    report_path = tmp_path / "price_coverage_report.json"
    report_path.write_text(json.dumps({
        "usable_history_percentage": 100.0,
        "sufficient_history_percentage": 40.0,
    }), encoding="utf-8")

    assert _load_sufficient_price_coverage(tmp_path) == 40.0

    report_path.write_text(json.dumps({
        "usable_history_percentage": 100.0,
    }), encoding="utf-8")

    assert _load_sufficient_price_coverage(tmp_path) is None


def test_resolution_label_does_not_change_generated_forecast():
    yes = ForecastObservationGenerator().generate([snapshot(resolved_yes=True)], [intelligence()])
    no = ForecastObservationGenerator().generate([snapshot(resolved_yes=False)], [intelligence()])

    assert yes[0].bot_probability == no[0].bot_probability
    assert yes[0].market_probability == no[0].market_probability
    assert yes[0].evidence_state_id == no[0].evidence_state_id
    assert yes[0].resolved_yes is True
    assert no[0].resolved_yes is False


def test_market_baseline_uses_snapshot_price_not_strategy_fallback():
    military = intelligence(
        title="Russia launches invasion of Ukraine",
        summary="Russian forces begin an invasion of Ukraine.",
        country="Ukraine",
    )
    market = snapshot(
        market_id="invasion",
        question="Will Russia invade Ukraine before July?",
        yes_price=.27,
        category="INVASION",
    )

    result = ForecastObservationGenerator().generate([market], [military])

    assert result
    assert result[0].market_probability == .27


def test_observation_rejects_future_market_resolution():
    with pytest.raises(ValueError, match="precede resolution"):
        ForecastObservationGenerator().generate([
            snapshot(resolved_at=(START + timedelta(hours=9)).isoformat()),
        ], [intelligence()])


def test_observation_model_rejects_future_evidence_and_invalid_probabilities():
    with pytest.raises(ValueError, match="future evidence"):
        observation(
            evidence_available_at=(START + timedelta(hours=1)).isoformat(),
        )
    with pytest.raises(ValueError, match="finite fractions"):
        observation(bot_probability=1.1)


def test_evaluator_compares_brier_log_loss_and_market_baseline():
    values = [
        observation(observation_id="yes", bot_probability=.8, market_probability=.6),
        observation(
            observation_id="no", market_id="market-2", event_cluster_id="cluster-2",
            bot_probability=.2, market_probability=.4, resolved_yes=False,
        ),
    ]

    report = ForecastEvaluator().evaluate(values, bootstrap_samples=100, bootstrap_seed=7)

    assert report.overall.bot_brier_score == pytest.approx(.04)
    assert report.overall.market_brier_score == pytest.approx(.16)
    assert report.overall.brier_improvement == pytest.approx(.12)
    assert report.overall.bot_log_loss < report.overall.market_log_loss
    assert report.overall.log_loss_improvement > 0
    assert report.overall.calibration_error == pytest.approx(.2)
    assert report.overall.sample_count == 2
    assert report.overall.unique_market_count == 2
    assert report.overall.unique_event_cluster_count == 2
    assert report.brier_improvement_interval is not None


def test_evaluator_breakdowns_and_time_to_resolution_buckets():
    values = [
        observation(evaluation_time_to_resolution_seconds=3600),
        observation(
            observation_id="confirmed", market_id="m2", event_cluster_id="c2",
            independently_confirmed=True, independent_confirmation_count=2,
            supporting_sources=("BBC World", "GDELT"),
            evaluation_time_to_resolution_seconds=10 * 86400,
            provenance={"strategy_confidence": .5},
        ),
    ]

    report = ForecastEvaluator().evaluate(values, bootstrap_samples=0)

    assert set(report.breakdowns["time_to_resolution"]) == {"0-1_DAY", "7-30_DAYS"}
    assert set(report.breakdowns["confirmation"]) == {
        "INDEPENDENTLY_CONFIRMED", "SINGLE_SOURCE",
    }
    assert set(report.breakdowns["confidence"]) == {"HIGH", "LOW"}
    assert report.breakdowns["source"]["GDELT"].sample_count == 1


def test_composition_reports_required_dimensions_and_near_close_warning():
    report = analyze_composition([observation(
        evaluation_time_to_resolution_seconds=1800,
        provenance={
            "strategy_confidence": .5,
            "event_provider": "GDELT",
            "event_publisher": "reuters.com",
            "evidence_event_cluster_id": "news-cluster",
        },
    )])

    assert report.distributions["provider"] == {"GDELT": 1}
    assert report.distributions["publisher"] == {"reuters.com": 1}
    assert report.distributions["event_cluster"] == {"news-cluster": 1}
    assert report.distributions["time_to_resolution"] == {"<1_HOUR": 1}
    assert any("under one day" in warning for warning in report.warnings)


def test_readiness_rejects_incomplete_provider_and_unusable_split(tmp_path):
    manifest = tmp_path / "intelligence_manifest.json"
    manifest.write_text(json.dumps({
        "partitions": [
            {"partition_id": "gdelt:one", "provider": "GDELT"},
            {"partition_id": "gdelt:two", "provider": "GDELT"},
        ],
        "collection_status": {
            "gdelt:one": {"status": "complete"},
            "gdelt:two": {"status": "pending"},
        },
    }), encoding="utf-8")

    readiness = assess_benchmark_readiness(
        manifest, calibration_observations=1, test_observations=200,
    )

    assert readiness.ready_to_freeze is False
    assert readiness.provider_coverage[0].incomplete_partitions == 1
    assert any("calibration split" in blocker for blocker in readiness.blockers)


def test_readiness_accepts_complete_manifest_and_usable_split(tmp_path):
    manifest = tmp_path / "intelligence_manifest.json"
    manifest.write_text(json.dumps({
        "partitions": [{"partition_id": "gdelt:one", "provider": "GDELT"}],
        "collection_status": {"gdelt:one": {"status": "complete"}},
    }), encoding="utf-8")

    readiness = assess_benchmark_readiness(
        manifest, calibration_observations=30, test_observations=100,
        market_price_coverage_percentage=100,
        observation_count=500, event_cluster_count=30, category_count=3,
    )

    assert readiness.ready_to_freeze is True


def test_readiness_cannot_be_true_while_any_manifest_blocker_remains(tmp_path):
    manifest = tmp_path / "intelligence_manifest.json"
    manifest.write_text(json.dumps({
        "partitions": [{"partition_id": "gdelt:one", "provider": "GDELT"}],
        "collection_status": {"gdelt:one": {"status": "complete"}},
    }), encoding="utf-8")

    readiness = assess_benchmark_readiness(
        [manifest, tmp_path / "missing-manifest.json"],
        calibration_observations=30,
        test_observations=100,
        market_price_coverage_percentage=100,
        observation_count=500,
        event_cluster_count=30,
        category_count=3,
    )

    assert readiness.blockers
    assert readiness.ready_to_freeze is False


def test_readiness_allows_documented_provider_exclusion(tmp_path):
    manifest = tmp_path / "intelligence_manifest.json"
    manifest.write_text(json.dumps({
        "partitions": [
            {"partition_id": "gdelt:one", "provider": "GDELT"},
            {"partition_id": "relief:one", "provider": "ReliefWeb"},
        ],
        "collection_status": {
            "gdelt:one": {"status": "complete"},
            "relief:one": {"status": "excluded"},
        },
        "provider_exclusions": {
            "ReliefWeb": {"reason": "HTTP 403; external approval required"},
        },
    }), encoding="utf-8")

    readiness = assess_benchmark_readiness(
        manifest, calibration_observations=30, test_observations=100,
        market_price_coverage_percentage=100,
        observation_count=500, event_cluster_count=30, category_count=3,
    )

    assert readiness.ready_to_freeze is True
    reliefweb = next(
        item for item in readiness.provider_coverage if item.provider == "ReliefWeb"
    )
    assert reliefweb.intentionally_excluded is True
    assert not any("ReliefWeb has" in blocker for blocker in readiness.blockers)


def test_chronological_split_keeps_event_clusters_together():
    values = []
    for index in range(5):
        cluster = f"cluster-{index}"
        for duplicate in range(2):
            values.append(observation(
                observation_id=f"{cluster}-{duplicate}",
                market_id=f"market-{index}-{duplicate}",
                event_cluster_id=cluster,
                forecast_timestamp=(START + timedelta(days=index, hours=duplicate)).isoformat(),
            ))

    split = chronological_cluster_split(values)
    partitions = [split.train, split.calibration, split.test]
    cluster_sets = [{item.event_cluster_id for item in partition} for partition in partitions]

    assert all(partitions)
    assert cluster_sets[0].isdisjoint(cluster_sets[1])
    assert cluster_sets[0].isdisjoint(cluster_sets[2])
    assert cluster_sets[1].isdisjoint(cluster_sets[2])
    assert max(item.forecast_timestamp for item in split.train) < min(
        item.forecast_timestamp for item in split.test
    )
    assert not split.excluded_boundary_clusters


def test_chronological_split_purges_clusters_crossing_boundaries():
    values = [
        observation(
            observation_id=f"regular-{index}", event_cluster_id=f"cluster-{index}",
            forecast_timestamp=(START + timedelta(days=index)).isoformat(),
        )
        for index in range(10)
    ]
    values.extend([
        observation(
            observation_id="crossing-start", event_cluster_id="crossing",
            forecast_timestamp=(START + timedelta(days=1)).isoformat(),
        ),
        observation(
            observation_id="crossing-end", event_cluster_id="crossing",
            forecast_timestamp=(START + timedelta(days=9)).isoformat(),
        ),
    ])

    split = chronological_cluster_split(values)

    assert {item.event_cluster_id for item in split.excluded_boundary_clusters} == {"crossing"}
    retained = split.train + split.calibration + split.test
    assert all(item.event_cluster_id != "crossing" for item in retained)


def test_optimized_split_finds_viable_cluster_safe_boundaries():
    values = []
    for index in range(12):
        values.extend(observation(
            observation_id=f"{index}-{duplicate}",
            event_cluster_id=f"cluster-{index}",
            forecast_timestamp=(START + timedelta(days=index, minutes=duplicate)).isoformat(),
        ) for duplicate in range(10))

    split = optimized_chronological_cluster_split(
        values, minimum_calibration_observations=20, minimum_test_observations=20,
    )

    assert len(split.calibration) >= 20
    assert len(split.test) >= 20
    partitions = (split.train, split.calibration, split.test)
    cluster_sets = [{item.event_cluster_id for item in part} for part in partitions]
    assert cluster_sets[0].isdisjoint(cluster_sets[1])
    assert cluster_sets[0].isdisjoint(cluster_sets[2])
    assert cluster_sets[1].isdisjoint(cluster_sets[2])


@pytest.mark.parametrize(("train", "calibration"), [
    (0, .2), (1, .2), (.8, .2), (.6, -.1),
])
def test_chronological_split_rejects_invalid_fractions(train, calibration):
    with pytest.raises(ValueError):
        chronological_cluster_split([], train, calibration)
