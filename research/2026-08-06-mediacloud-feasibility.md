<!-- File-Version: 1.0.0 -->

# Media Cloud feasibility assessment

## Decision

Recommend **integrating Media Cloud now** as a complementary historical intelligence provider, subject to pagination, indexed-time partitioning, and relevance-precision tests before full collection. Do not treat this bounded probe as a complete dataset or start replay from it.

## Scope and frozen input

- Assessment date: 2026-08-06.
- Phase: read-only feasibility assessment; no provider implementation or replay.
- Requested pilot path: `data/historical_intelligence_event_pilot_v1_7_0/event_focused_pilot_manifest.json`.
- That physical file does not exist. The directory contains `pilot_collection_plan.json`, whose frozen source is `data/historical_selection_2026-02_to_2026-08/event_focused_pilot_manifest.json`.
- The source exists and its SHA-256 matches the reference in `pilot_collection_plan.json`.
- Frozen denominator: 18 clusters, 47 markets, 9 categories.

## Connectivity and quota

- `MC_API_KEY` is configured without exposing its value.
- `GET https://search.mediacloud.org/api/auth/profile` returned HTTP 200 with the configured token.
- A deliberately invalid token returned HTTP 403 with a structured JSON `message`, confirming failures can be classified without parsing HTML or exposing credentials.
- Successful responses did not include rate-limit or quota headers.
- The live profile returned `quota: null`, so it did not disclose account-specific remaining quota.
- Media Cloud's current FAQ states a default quota of 4,000 API requests per week and says certain endpoints are limited to two requests per minute: https://www.mediacloud.org/documentation/faqs
- The official Python API client independently configures its session for two requests per minute: https://github.com/mediacloud/api-client

The probe conservatively paced search calls at least 31 seconds apart. It made 17 story-search calls for 18 clusters because one identical Russia-Ukraine query/date range was reused. There were no 429s, authentication failures, timeouts, or malformed responses.

## Timestamp safety

Media Cloud stories expose both `publish_date` and `indexed_date`. The official story guide defines:

- `publish_date`: a heuristic publication date inferred from page metadata or text; it has no time or timezone.
- `indexed_date`: the timestamp when Media Cloud captured and processed the content for insertion into its archive.

Source: https://www.mediacloud.org/documentation/story-guide

Use **`indexed_date` as `available_at`**. It is timezone-aware and represents the earliest auditable point at which Media Cloud possessed the content. Do not use `publish_date` as replay availability because it is date-only, heuristic, and cannot establish an intraday evidence boundary.

Probe timestamp results:

- 1,700/1,700 returned story assignments had `publish_date`.
- 1,700/1,700 had `indexed_date`.
- All 1,700 sampled assignments had `indexed_date` at or before the associated cluster replay end.
- Median calendar-day indexing lag was zero days for every covered cluster.
- 112/1,700 assignments (6.59%) had an indexed calendar date earlier than the heuristic publication date. This is further evidence that `publish_date` is unsuitable for ordering or availability.

Important implementation limitation: the Search API's `start` and `end` parameters constrain publication dates, while leakage safety must be based on `indexed_date`. A collector must paginate the publication-date search and then assign/filter records using `indexed_date`. Completeness by availability day cannot be inferred from a single page or publication-date filtering alone.

## Coverage pilot methodology

- Collection: Media Cloud `Global English Language Sources`, ID `9272347`.
- One event-focused Boolean query per cluster.
- Frozen pre-event intelligence start through the replay-end calendar date.
- One page of at most 100 stories per distinct query/date range.
- Ascending result order.
- No full pagination.
- A result was leakage-safe for a cluster only when `indexed_date <= replay_end`.
- GDELT comparison used the 933 records currently stored in `data/historical_intelligence_event_pilot_v1_7_0/intelligence.json`.
- Cross-provider duplicates used normalized exact URLs, with normalized exact titles as a secondary signal.

Because 17 queries returned a pagination token, their counts are lower bounds. This probe measures retrieval feasibility, not article-level relevance precision or exhaustive coverage.

## Cluster coverage

| Category | Cluster | Returned | Leakage-safe | Capped |
|---|---|---:|---:|---|
| Political | Russia-Ukraine ceasefire by June 30 | 100 | 100 | Yes |
| Political | US-Iran permanent peace deal | 100 | 100 | Yes |
| Political | US-Iran ceasefire by May 15 | 100 | 100 | Yes |
| Political | Russia-Ukraine ceasefire before GTA VI | 100 | 100 | Yes; reused request |
| Political | US strikes on Somalia | 100 | 100 | Yes |
| Diplomatic | Next US-Iran diplomatic meeting location | 100 | 100 | Yes |
| Diplomatic | US-Cuba diplomatic meeting | 100 | 100 | Yes |
| Diplomatic | Israel-Lebanon diplomatic meeting | 100 | 100 | Yes |
| Election | Colombian presidential candidate | 0 | 0 | No |
| Election | Puducherry legislative election | 100 | 100 | Yes |
| Invasion | Suspension of Israel-Lebanon offensive | 100 | 100 | Yes |
| Invasion | Halt in US-Iran offensive operations | 100 | 100 | Yes |
| Leadership | End of US military operations against Iran | 100 | 100 | Yes |
| Leadership | Strait of Hormuz blockade announcement | 100 | 100 | Yes |
| Nuclear | US-Iran nuclear deal | 100 | 100 | Yes |
| Shipping | Houthi attacks on shipping | 100 | 100 | Yes |
| Sanctions | Court-ordered tariff refunds | 100 | 100 | Yes |
| Energy | Iran ceasefire before oil reaches $120 | 100 | 100 | Yes |

Coverage was present in 17/18 clusters. The strict query containing the full Colombian candidate name returned no results.

## Category coverage

| Category | Clusters covered | Cluster denominator | Returned assignments | Unique leakage-safe stories |
|---|---:|---:|---:|---:|
| Political | 5 | 5 | 500 | 399 |
| Diplomatic | 3 | 3 | 300 | 300 |
| Election | 1 | 2 | 100 | 100 |
| Leadership | 2 | 2 | 200 | 200 |
| Invasion | 2 | 2 | 200 | 200 |
| Energy | 1 | 1 | 100 | 100 |
| Nuclear | 1 | 1 | 100 | 100 |
| Sanctions | 1 | 1 | 100 | 100 |
| Shipping | 1 | 1 | 100 | 100 |

All nine categories had some coverage. Election was the only category without complete cluster coverage.

## Comparison with current GDELT pilot data

- Media Cloud returned 1,700 cluster-story assignments.
- These represented 1,593 unique Media Cloud story IDs and 1,563 unique normalized URLs.
- Exact normalized URL overlap with current GDELT: 0/1,563 (0%).
- Exact normalized title overlap with current GDELT: 1 story (approximately 0.06%).
- Media Cloud internal cross-cluster assignment duplication: 107/1,700 (6.29%).
- Media Cloud IDs mapping to already-seen Media Cloud normalized URLs: 30/1,593 (1.88%).
- Media Cloud sampled stories covered 78 distinct `indexed_date` days.
- Seventy-one of those days were not represented in the current seven-day GDELT record set.

On exact URL identity, the probe found 1,563 additional candidate stories and 71 additional indexed days. These numbers must not be interpreted as final incremental relevant intelligence: the GDELT collection is highly incomplete, Media Cloud pages were capped, and article-level relevance was not manually validated.

## Integration proposal

### Provider and manifest interface

- Add a `MediaCloudHistoricalIntelligenceCollector` behind the existing historical collector contract; do not alter strategy or replay interfaces.
- Continue emitting `HistoricalIntelligenceItem` with `source`, URL, title, provider, query, partition provenance, `publish_date` metadata, and `available_at=indexed_date`.
- Freeze the Media Cloud collection ID, Boolean query, publication-date search range, indexed-time availability policy, page size, and pagination status in the intelligence manifest.
- Store and resume Media Cloud pagination tokens per frozen query/range.
- Deduplicate primarily by Media Cloud story ID, with normalized URL as a secondary audit identity.
- Treat query publication bounds separately from indexed-time availability partitions. Filter replay visibility exclusively by `indexed_date`.
- Preserve the existing GDELT and ReliefWeb behavior unchanged.

### Configuration

- Document `MC_API_KEY` in `.env.example` without a real value.
- Add configurable API base URL, collection IDs, two-requests-per-minute pacing, timeout, page size, logical batch budget, and bounded retry/cooldown settings.
- Never log the authorization header or token-bearing request state.

### Required tests

- Token authentication and structured 403 handling.
- Timeout, 429, `Retry-After`, bounded retry, and durable retry-queue behavior.
- Two-requests-per-minute pacing.
- Pagination-token checkpoint and resume without refetching completed pages.
- Missing/malformed `publish_date` and `indexed_date` handling.
- `available_at` exactly equals parsed `indexed_date`, never inferred publication midnight.
- Exclusion of stories indexed after a replay timestamp.
- Publication-range versus indexed-time boundary cases.
- Story-ID and normalized-URL deduplication.
- Frozen collection/query provenance and manifest-change rejection.
- Provider/day status reporting, capped-page warnings, and incomplete-pagination warnings.
- Cross-provider coexistence without changes to GDELT or ReliefWeb behavior.

## Limitations

- The probe retrieved only one page per query and 17/18 pages were capped.
- Query results were not manually labeled for relevance or precision.
- The Global English collection does not measure non-English recall.
- Exact URL comparison understates semantic duplication and syndication.
- GDELT currently covers only seven pilot days, making incremental-day and duplicate comparisons provisional.
- No full Media Cloud dataset was collected and replay was not started.
