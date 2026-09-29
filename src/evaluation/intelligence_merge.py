# File-Version: 1.0.0
"""Deterministically normalize intelligence archives for aligned evaluation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
import hashlib

from src.historical_dataset import HistoricalIntelligenceItem, _normalized_story_url


@dataclass(frozen=True)
class IntelligenceMergeReport:
    input_records: int
    output_records: int
    exact_duplicates_removed: int
    cross_provider_duplicate_groups: int
    cross_provider_duplicate_records: int
    unique_publishers: int


def merge_intelligence_records(
    archives: list[list[HistoricalIntelligenceItem]],
) -> tuple[list[HistoricalIntelligenceItem], IntelligenceMergeReport]:
    """Preserve provider records while annotating shared underlying articles."""
    unique: dict[tuple[str, str], HistoricalIntelligenceItem] = {}
    input_records = 0
    for records in archives:
        for record in records:
            input_records += 1
            unique.setdefault((record.source, record.record_id), record)

    by_story: dict[str, list[HistoricalIntelligenceItem]] = defaultdict(list)
    for record in unique.values():
        normalized_url = _normalized_story_url(record.source_url)
        identity = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
        by_story[identity].append(record)

    merged: list[HistoricalIntelligenceItem] = []
    cross_groups = cross_records = 0
    for identity in sorted(by_story):
        records = by_story[identity]
        providers = {item.source for item in records}
        is_cross_provider = len(providers) > 1
        if is_cross_provider:
            cross_groups += 1
            cross_records += len(records)
        for record in sorted(records, key=lambda item: (item.source, item.record_id)):
            metadata = dict(record.metadata)
            metadata.update({
                "normalized_story_identity": identity,
                "cross_provider_duplicate": is_cross_provider,
                "cross_provider_providers": sorted(providers),
            })
            merged.append(replace(record, metadata=metadata))

    publishers = {
        item.source_domain or _normalized_story_url(item.source_url).split("/", 1)[0]
        for item in merged
    }
    return merged, IntelligenceMergeReport(
        input_records=input_records,
        output_records=len(merged),
        exact_duplicates_removed=input_records - len(unique),
        cross_provider_duplicate_groups=cross_groups,
        cross_provider_duplicate_records=cross_records,
        unique_publishers=len(publishers),
    )
