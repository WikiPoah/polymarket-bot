<!-- File-Version: 1.0.0 -->

# Legacy Codex Handoff Record

This file preserves the historical substance formerly stored in `codex.MD`. It is a record of earlier work, not current operating instructions. Current rules are in [`../AGENTS.md`](../AGENTS.md).

## Earlier project state

The project was established as a geopolitical Polymarket intelligence system with a precision-first pipeline. At the time of the original handoff, the implemented components included:

- Gamma market retrieval with retries, timeouts, and error handling.
- Geopolitical market filtering.
- Market and intelligence-event classification.
- Actor, country, event-keyword, and topic knowledge bases.
- GDELT retrieval and parsing.
- Market-specific query construction.
- Outcome classification, relevance filtering, scoring, matching, and strategy evaluation.

The recorded pipeline was:

```text
Polymarket market
  -> MarketClassifier
  -> MarketQueryBuilder
  -> GDELT provider
  -> EventClassifier
  -> OutcomeClassifier
  -> relevance filtering
  -> scoring
  -> Matcher
  -> StrategyEngine
```

## Historical debugging record

The active example was a market asking whether Xi Jinping would leave power. The query had been refined from a generic China politics query to terms covering removal, resignation, succession, and related leadership-change language.

The investigation found that unrelated China reporting was surviving relevance filtering because a classified outcome other than `OTHER` was being treated as relevance evidence. For example, generic country news could receive an overly broad outcome and then pass filtering despite providing no evidence of leadership change.

The resulting design conclusion was:

- Outcome classification describes an event but does not establish relevance.
- Leadership-market intelligence should require an actor match, or a leadership-event plus country match.
- Generic economic, weather, diplomatic, and policy stories should be rejected unless they provide evidence for the proposition being traded.

The historical follow-up list called for improving `src/intelligence/pipeline.py`, reviewing overly broad outcome classification if needed, increasing GDELT precision, and reviewing matching only after intelligence relevance was reliable.

## Superseded operational details

The old handoff recorded a 30-test suite, early repository structure, example runtime counts, and a manual milestone Git workflow. Those observations are retained only as history; they are not assertions about the current repository state.

Git history contains the complete original 716-line handoff if verbatim reconstruction is ever required.
