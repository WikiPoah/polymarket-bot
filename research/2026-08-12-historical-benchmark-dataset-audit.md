<!-- File-Version: 1.2.0 -->
# Historical benchmark dataset audit

Generated on 2026-08-12 in `Europe/Berlin` from the repository datasets. This
record distinguishes verified dataset facts from benchmark limitations; it is
not a model-performance conclusion.

## Commands

```bash
.venv/bin/python -m src.evaluation.coverage \
  --dataset-dir data/historical_selection_2026-02_to_2026-08

.venv/bin/python -m src.evaluation \
  --dataset-dir data/historical_selection_2026-02_to_2026-08 \
  --generate-only

.venv/bin/python -m src.evaluation \
  --dataset-dir data/historical_selection_2026-02_to_2026-08 \
  --observations-input data/historical_selection_2026-02_to_2026-08/forecast_observations.json \
  --bootstrap-samples 1000
```

## The 912 legacy exclusions

The legacy `data/historical_dataset/markets.json` contains 1,114 collected
contracts. Its replay adapter accepts 202 Yes/No contracts and excludes 912.
All 912 exclusions are `non_binary_yes_no_contract`; they are not missing CLOB
histories:

- 479 Over/Under contracts;
- 287 Up/Down contracts;
- 23 Odd/Even contracts;
- 123 contracts with named competitors or other non-Yes/No outcomes.

Those contracts have outcome-specific histories, but no semantically valid YES
token. Treating one named outcome as YES would silently change the benchmark
question. The prior aggregate message "missing usable YES-price histories" was
therefore imprecise. Replay now records a reason for every excluded market.

## Frozen-universe and price alignment

`data/historical_selection_2026-02_to_2026-08` is the correct frozen
geopolitical universe:

- 139 selected and collected markets;
- 139 matching market identifiers;
- 139 Yes/No contracts with a YES token and usable pre-close history;
- 139 markets passing the default requirement of at least two observations and
  10% lifetime span;
- 89,357 leakage-safe pre-resolution YES-price snapshots;
- no extra collected contracts outside the frozen universe.

The coverage report records observations, earliest/latest timestamps, lifetime
span, largest gap, token identity, and exclusion reason per market.

## Intelligence coverage blocker

The frozen intelligence manifest is incomplete. At audit time its 362
partitions were:

- 16 complete;
- 52 failed;
- 293 pending;
- 1 still marked collecting.

The read-only status command normalizes stale/failed states into remaining work:
GDELT has 16/181 complete partitions and 165 pending; ReliefWeb has 0/181
complete, 129 pending, and 52 failed. GDELT estimates at least 165 logical
requests and about 103 minutes at required pacing. ReliefWeb returns HTTP 403
for the configured unapproved `polymarket-bot` app name. These are external
collection constraints, not replay exclusions.

The collected archive contains 2,604 intelligence records, all delivered by
GDELT. ReliefWeb and Media Cloud do not yet contribute completed aligned
partitions. Media Cloud must continue to use `indexed_date` as canonical
`available_at`; `publish_date` is not leakage-safe availability evidence.

Consequently, the current aligned forecast file is a diagnostic pilot, not a
frozen benchmark suitable for model selection.

## Causal event representation

Historical articles are now assigned deterministic event-cluster identities in
`available_at` order. Matching uses event type, actor/country overlap,
normalized-title similarity, and a bounded time gap. A later article can add a
publisher confirmation but cannot alter an earlier assignment or earlier
confirmation count. Provider transport and original publisher are distinct:
the same publisher arriving through GDELT and RSS counts once.

## Diagnostic observation result

The current aligned pilot generated 1,755 observations. Its composition remains
unsuitable for estimator redesign:

- provider: 100% GDELT;
- category: 89.0% POLITICAL;
- strategy confidence: 94.9% LOW;
- chronological cluster split: 262 train, 1 calibration, 257 test, and 1,235
  purged boundary-crossing observations.

On the retained 257-observation test slice, the unchanged heuristic had Brier
score 0.24162 versus market 0.21913 and log loss 0.67742 versus market 0.61704.
These numbers are diagnostic only because provider coverage is incomplete and
the calibration partition is unusably small.

## Time-to-resolution finding

The previous legacy benchmark's short horizon was not caused by absent market
price history. The aligned dataset contains broad market histories. Forecasts
only occur when collected intelligence becomes available, so gaps and temporal
concentration in the incomplete intelligence partitions directly determine the
observed horizons. Completing the frozen intelligence manifest must precede any
claim about horizon diversity.

## Required next gate

Resume the existing immutable intelligence manifest until all required
partitions are complete or carry an explicit, evidenced terminal exclusion.
Then regenerate coverage, causal clusters, observations, composition, and the
split. Do not tune `ProbabilityEstimator` until provider coverage passes and
train/calibration/test partitions contain useful independent cluster counts.
The evaluation output now includes a machine-readable `readiness` gate and
`ready_to_freeze`; the current dataset returns `false`.

## Intelligence completion continuation

ReliefWeb is now intentionally excluded in collection status with the explicit
reason that its HTTP 403 requires an externally approved identifying app name.
The partition plan remains immutable, completed data is untouched, and a later
approved collection can use a new aligned provider manifest. Readiness ignores
only fully documented provider exclusions; unexpected incomplete partitions
remain blockers.

A separate Media Cloud manifest was frozen at
`data/historical_intelligence_mediacloud_aligned/intelligence_manifest.json`.
It covers exactly `2026-02-01T00:00:00Z` through `2026-08-01T00:00:00Z` and
records frozen-universe SHA-256
`e1dac5556de3090c3f79eb0cf60cd21a2afbdfea1694947cbc6b2f8f1a0a405d`.
It contains only Media Cloud partitions and retains
`mediacloud.indexed_date` as its availability policy.

Collection attempts on 2026-08-12 confirmed:

- GDELT remains service-rate-limited. A bounded resume stopped safely after
  persistent HTTP 429 responses, leaving adaptive retry state durable.
- Media Cloud collection is authorized and progressing under its 30-second
  pacing with no failures in the observed initial partitions.

Evaluation can accept multiple raw intelligence archives and manifests without
copying or modifying them. Its merge layer annotates normalized story identity
and cross-provider duplicates while retaining both provider records. Causal
clustering now assigns conservative reporting-group identities, so identical or
lightly altered syndicated coverage cannot increase independent confirmation.

The fixed 60/20/20 timestamp boundaries caused the earlier 1,235-observation
purge because long-lived related-contract clusters crossed those arbitrary
dates. Optimized chronological boundaries preserve whole market clusters and,
on the same partial 1,755 observations, yield 1,311 train, 90 calibration, 161
test, and 193 purged. This fixes split viability without allowing any market
cluster into more than one partition. Metrics remain diagnostic until provider
collection completes.
