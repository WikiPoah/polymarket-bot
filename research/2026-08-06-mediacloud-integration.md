<!-- File-Version: 1.0.1 -->

# Media Cloud historical provider integration

## Decision record

Media Cloud is integrated as an explicit, complementary provider in the historical intelligence pipeline. It is opt-in through `--include-media-cloud`, so existing frozen GDELT/ReliefWeb manifests and collection behavior remain unchanged.

The canonical credential is `MEDIA_CLOUD_API_KEY`. `MC_API_KEY` remains a compatibility fallback for the locally configured feasibility credential; neither value is logged or stored in checkpoints or manifests. The default collection is Media Cloud's Global English collection (`9272347`) and can be overridden with `MEDIA_CLOUD_COLLECTION_IDS`.

## Leakage-safe timestamp policy

The frozen policy identifier is `mediacloud.indexed_date`. A valid record must have a timezone-aware `indexed_date`, and that value becomes both `available_at` and the internal `published_at` field used by the existing replay DTO. This deliberately prevents Media Cloud's heuristic, date-only `publish_date` from influencing replay visibility. The original `publish_date` is retained only in metadata.

Records whose `indexed_date` is at or after the requested collection end are excluded. The shared pilot status validator also requires Media Cloud story identity, normalized URL, collection partition, timestamp policy, and equality between `indexed_date` and `available_at`.

## Collection behavior

- Authentication uses the `Authorization: Token` header.
- Requests are paced at 30 seconds by default, matching the two-requests-per-minute constraint.
- Network failures and HTTP 429 responses receive one bounded retry; `Retry-After` is honored.
- HTTP 401 and 403 failures are classified without repeated authentication attempts.
- Pagination tokens, per-partition record counts, completed windows, and persistent retry queues are stored in the existing checkpoint format.
- Story identity is `mediacloud:<story_id>`. Normalized URL is retained as a secondary audit deduplication key.
- Every emitted record retains provider, story ID, normalized URL, frozen query, collection IDs, root and active partitions, timestamp policy, indexed date, and publication-date metadata.

## Manifest and operating boundary

Media Cloud uses the existing frozen historical intelligence manifest fields: provider, query, daily partition, and availability timestamp policy. Because the current event-pilot collection manifest is already frozen to its existing providers, a Media Cloud pilot must use a separate pilot-specific output directory and newly frozen collection manifest derived from the unchanged event-focused pilot input.

No live or full historical collection was started during implementation. Before a pilot run, freeze the exact Media Cloud query and collection ID set in that separate manifest. ReliefWeb authorization remains independent of Media Cloud readiness.

## Validation

Focused tests cover successful and failed authentication, bounded 429 retry with `Retry-After`, pagination checkpoint resume, two-requests-per-minute pacing, indexed-time safety, post-window exclusion, story-ID deduplication, normalized-URL audit provenance, manifest policy, and shared pilot provenance validation.
