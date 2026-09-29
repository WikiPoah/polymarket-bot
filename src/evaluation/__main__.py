# File-Version: 1.6.1
"""Command-line benchmark for historical bot-versus-market forecasts."""

import argparse
from collections import Counter
from dataclasses import asdict
import json
import math
from pathlib import Path

from src.evaluation.metrics import ForecastEvaluator
from src.evaluation.intelligence_merge import merge_intelligence_records
from src.evaluation.composition import analyze_composition
from src.evaluation.models import ForecastObservation
from src.evaluation.observations import ForecastObservationGenerator
from src.evaluation.readiness import assess_benchmark_readiness
from src.evaluation.split import optimized_chronological_cluster_split
from src.historical_dataset import (
    HistoricalDatasetReplayAdapter,
    HistoricalIntelligenceDatasetStore,
    HistoricalMarketDatasetStore,
    HistoricalMarketUniverseStore,
    analyze_market_universe,
)


def _cluster_mapping(universe_path: Path) -> dict[str, str]:
    if not universe_path.exists():
        return {}
    records = HistoricalMarketUniverseStore(universe_path).load()
    report = analyze_market_universe(records, largest_limit=max(1, len(records)))
    return {
        market_id: cluster.cluster_id
        for cluster in report.largest_clusters
        for market_id in cluster.market_ids
    }


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def _load_sufficient_price_coverage(dataset: Path) -> float | None:
    """Load the strict frozen-universe price-coverage metric, failing closed."""

    try:
        payload = json.loads(
            (dataset / "price_coverage_report.json").read_text(encoding="utf-8")
        )
        value = payload["sufficient_history_percentage"]
        percentage = float(value)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(percentage) or not 0.0 <= percentage <= 100.0:
        return None
    return percentage


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate historical bot forecasts against Polymarket probabilities",
    )
    parser.add_argument("--dataset-dir", default="data/historical_dataset")
    parser.add_argument(
        "--universe",
        help="selected_markets.json used to preserve related-contract event clusters",
    )
    parser.add_argument("--observations-output")
    parser.add_argument("--observations-input")
    parser.add_argument("--intelligence-input", action="append")
    parser.add_argument("--intelligence-manifest", action="append")
    parser.add_argument("--report-output")
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    args = parser.parse_args()

    dataset = Path(args.dataset_dir)
    universe_path = Path(args.universe) if args.universe else dataset / "selected_markets.json"
    converted = None
    if args.observations_input:
        payload = json.loads(Path(args.observations_input).read_text(encoding="utf-8"))
        observations = [ForecastObservation.from_dict(item) for item in payload["records"]]
    else:
        market_store = HistoricalMarketDatasetStore(dataset / "markets.json")
        intelligence_paths = [Path(value) for value in args.intelligence_input] \
            if args.intelligence_input else [dataset / "intelligence.json"]
        intelligence_archives = [
            HistoricalIntelligenceDatasetStore(path).load() for path in intelligence_paths
        ]
        merged_intelligence, merge_report = merge_intelligence_records(
            intelligence_archives,
        )
        converted = HistoricalDatasetReplayAdapter().convert(
            market_store.load(), merged_intelligence,
        )
        cluster_mapping = _cluster_mapping(universe_path)
        observations = ForecastObservationGenerator().generate(
            converted.snapshots,
            converted.intelligence,
            cluster_mapping,
        )
    split = optimized_chronological_cluster_split(observations)
    report = None if args.generate_only else ForecastEvaluator().evaluate(
        split.test, bootstrap_samples=args.bootstrap_samples,
    )
    composition = analyze_composition(observations)
    price_coverage = _load_sufficient_price_coverage(dataset)
    manifest_paths = [Path(value) for value in args.intelligence_manifest] \
        if args.intelligence_manifest else [dataset / "intelligence_manifest.json"]
    readiness = assess_benchmark_readiness(
        manifest_paths,
        calibration_observations=len(split.calibration),
        test_observations=len(split.test),
        market_price_coverage_percentage=price_coverage,
        observation_count=len(observations),
        event_cluster_count=len({
            str(item.provenance.get("evidence_event_cluster_id"))
            for item in observations
            if item.provenance.get("evidence_event_cluster_id")
        }),
        category_count=len(composition.distributions["category"]),
    )

    observations_path = Path(
        args.observations_output or dataset / "forecast_observations.json"
    )
    report_path = Path(args.report_output or dataset / "forecast_evaluation.json")
    fallback_count = sum(
        item.provenance.get("event_cluster_policy") == "market_id_fallback"
        for item in observations
    )
    warnings = []
    if fallback_count:
        warnings.append(
            f"{fallback_count} observations lack selected-universe cluster provenance; "
            "unique event-cluster counts may overstate independence."
        )
    if not any(item.independently_confirmed for item in observations):
        warnings.append("No observations contain cross-provider confirmation.")
    if converted is not None and converted.skipped_markets:
        warnings.append(
            f"{converted.skipped_markets} markets were excluded: "
            f"{dict(sorted(Counter(converted.market_exclusions.values()).items()))}."
        )
    warnings.extend(composition.warnings)
    warnings.extend(readiness.blockers)
    _write(observations_path, {
        "version": 1,
        "records": [item.to_dict() for item in observations],
        "split": {
            "train": [item.observation_id for item in split.train],
            "calibration": [item.observation_id for item in split.calibration],
            "test": [item.observation_id for item in split.test],
            "excluded_boundary_clusters": [
                item.observation_id for item in split.excluded_boundary_clusters
            ],
        },
        "skipped_markets": converted.skipped_markets if converted else 0,
        "skipped_intelligence": converted.skipped_intelligence if converted else 0,
        "market_exclusions": converted.market_exclusions if converted else {},
        "intelligence_merge": (
            asdict(merge_report) if converted is not None else None
        ),
        "composition": composition.to_dict(),
        "readiness": readiness.to_dict(),
        "warnings": warnings,
    })
    if report is not None:
        _write(report_path, {
            "version": 1,
            "dataset_dir": str(dataset),
            "universe": str(universe_path),
            "warnings": warnings,
            "composition": composition.to_dict(),
            "readiness": readiness.to_dict(),
            "split_counts": {
                "train": len(split.train),
                "calibration": len(split.calibration),
                "test": len(split.test),
                "excluded_boundary_clusters": len(split.excluded_boundary_clusters),
            },
            "report": report.to_dict(),
        })
    print(json.dumps({
        "observations": len(observations),
        "split_counts": {
            "train": len(split.train),
            "calibration": len(split.calibration),
            "test": len(split.test),
            "excluded_boundary_clusters": len(split.excluded_boundary_clusters),
        },
        "test_metrics": asdict(report.overall) if report is not None else None,
        "ready_to_freeze": readiness.ready_to_freeze,
        "observations_output": str(observations_path),
        "report_output": str(report_path),
        "warnings": warnings,
    }, indent=2))


if __name__ == "__main__":
    main()
