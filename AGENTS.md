<!-- File-Version: 1.0.0 -->

# Repository Instructions

This file is the authoritative guide for how work is performed in this repository. Tool-specific instruction files must only point here. Do not put status reports, completed-work summaries, debugging diaries, runtime output, or milestone histories in this file.

## Purpose and priorities

PolymarketBot is a geopolitical prediction-market intelligence system. It retrieves markets, identifies geopolitical markets, collects external intelligence, classifies and matches events, evaluates opportunities, and supports paper trading before any live execution.

Use this priority order:

1. Correct classification.
2. Correct relevance filtering.
3. Correct market matching.
4. Correct strategy evaluation.
5. Trading execution.

Favor precision over recall, and accuracy over execution speed. Do not turn the intelligence pipeline into a broad keyword scraper.

## Working method

- Continue from the existing architecture; do not rebuild or restart it without explicit authorization.
- Preserve working features and existing behavior outside the requested scope.
- Make the smallest coherent change that satisfies the task.
- Avoid unnecessary refactors.
- Preserve the local coding style and public interfaces unless the task requires a change.
- Read relevant code and tests before editing.
- Use focused tests while developing and the full test suite before handoff when practical.
- Keep existing tests passing. Add regression tests for behavior changes.
- Do not silently weaken validation, leakage protection, truncation detection, retry safety, or provenance tracking.
- Do not commit, tag, push, deploy, trade, or contact external parties unless explicitly requested.
- Keep commits small and logical when commits are requested.

## Per-file semantic versioning

Every human-maintained file created or modified during a task must carry its own semantic version and have that version updated in the same change.

- Use `MAJOR.MINOR.PATCH`.
- Increment `MAJOR` for incompatible file-format, contract, or public-interface changes.
- Increment `MINOR` for backward-compatible behavior or content additions.
- Increment `PATCH` for backward-compatible fixes, clarifications, or maintenance.
- New files start at `1.0.0`.
- For languages that support comments, put `File-Version: X.Y.Z` in a valid top-of-file comment.
- For Markdown, use `<!-- File-Version: X.Y.Z -->` on the first line.
- For JSON, add a top-level `file_version` field when the schema permits it. If an external or frozen schema forbids extra fields, record the version in the nearest human-maintained manifest or sidecar.
- For formats with an established version field, use that field rather than creating a duplicate.
- Do not alter generated files, collected datasets, checkpoints, caches, lockfiles, vendored dependencies, or externally frozen artifacts merely to add a version. If a task intentionally changes such a file, version its human-maintained generator, schema, or sidecar instead.
- Mention version changes in the handoff.

## Research and work records

- Put investigations, experiments, benchmarks, architectural evaluations, debugging histories, runtime observations, and completed-work records under `research/`.
- Use descriptive Markdown filenames, preferably prefixed with an ISO date when time is relevant.
- Add source paths, commands, timestamps, assumptions, and limitations needed to reproduce conclusions.
- Keep durable operating rules here in `AGENTS.md`; keep evidence and historical narrative in `research/`.
- Do not use `codex.MD`, `CLAUDE.md`, or `AGENTS.md` as a changelog.

## Architecture boundaries

The production flow is:

```text
Polymarket market
  -> MarketClassifier
  -> MarketQueryBuilder
  -> intelligence providers
  -> EventClassifier
  -> OutcomeClassifier
  -> relevance filtering
  -> scoring
  -> Matcher
  -> StrategyEngine
  -> paper trading / historical replay
```

Keep these responsibilities separate:

- Market classification converts market metadata into structured geopolitical intent.
- Event classification describes intelligence events.
- Outcome classification describes what an event implies; it must not independently establish relevance.
- Relevance filtering decides whether intelligence is evidence for a market.
- Matching connects relevant scored events to classified markets.
- Strategy evaluates matched opportunities.
- Replay exposes only information available at each historical timestamp.

For leadership markets, accept intelligence when the relevant actor matches, or when a leadership event and the relevant country both match. Do not treat a non-`OTHER` outcome as proof of relevance. Reject generic country news unless it supplies evidence for the market’s actual proposition.

## Historical backtesting rules

- Treat frozen selectors, market universes, collection manifests, and pilot manifests as immutable inputs.
- Never use resolution outcomes, future prices, replay decisions, or future intelligence to select or score replay inputs.
- Preserve source, query, provider partition, publication time, availability time, and timestamp-policy provenance.
- Make collection resumable and idempotent through durable checkpoints and record identities.
- Preserve explicit saturation and truncation detection.
- Store pilots and experiments separately from the main historical dataset.
- Do not start replay until required coverage and leakage-safety validation pass, unless the user explicitly accepts incomplete coverage.
- Treat an event cluster, not each related contract, as the independent evaluation unit.

## Provider reliability

- Respect provider authorization and rate limits; never bypass access controls.
- Honor `Retry-After` when present.
- Use bounded retries, global cooldowns, bounded request batches, and persistent retry queues.
- Prefer shared provider/day retrieval when multiple event clusters can reuse the same data.
- Preserve adaptive partitioning for capped GDELT results and pagination checkpoints for ReliefWeb.
- A failed or interrupted partition must remain resumable and must not be marked complete.

## Testing and validation

Run commands from the repository root using the project virtual environment:

```bash
.venv/bin/python -m pytest -q
```

Validation should be proportional to risk and normally include:

- Focused tests for the changed component.
- Full-suite verification before handoff.
- `git diff --check` for malformed patches.
- Read-only validation of manifests, checkpoints, or generated reports when those are in scope.

Report what ran and any untested or externally blocked behavior. Do not claim completion when required provider authorization, coverage, or validation is missing.

## Git and repository hygiene

- Preserve user changes in a dirty worktree.
- Do not discard or overwrite unrelated work.
- Do not use destructive Git commands without explicit approval.
- Keep runtime output, credentials, caches, and temporary files out of commits unless they are intentional project artifacts.
- Use milestone tags and semantic project versions only when explicitly requested.

## Deferred scope

Unless explicitly requested, do not prioritize live order execution, trading API integration, dashboards, UI, or automation ahead of intelligence quality and leakage-safe evaluation.
